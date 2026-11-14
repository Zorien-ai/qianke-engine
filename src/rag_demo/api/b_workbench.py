"""B 端商家工作台 API（商家租户作用域）。

与 /api/c/admin/* 的区别：
- 不要求系统管理员，而是要求当前账号已绑定商家；
- 所有订单/商品/售后操作都必须落在该 merchant_id 内。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from rag_demo import auth, product_media as media
from rag_demo.c_end import alerts as alert_notifier
from rag_demo.c_end import store
from rag_demo.merchant import MerchantError, get_merchant_repository, get_merchant_write_repository

router = APIRouter(prefix="/api/b/workbench", tags=["b-workbench"])

DEFAULT_MERCHANT_ID = "m_gear_002"
MERCHANT_NAMES = {"m_gear_002": "山野户外旗舰店", "m_tea_001": "山雾茶业"}
BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _business_day_utc_range(date_from: str | None, date_to: str | None) -> tuple[str | None, str | None]:
    """把商家营业日（Asia/Shanghai）转成 UTC 左闭右开区间。"""
    start = None
    end = None
    try:
        if date_from:
            start_dt = datetime.combine(date.fromisoformat(date_from), time.min, tzinfo=BUSINESS_TIMEZONE)
            start = start_dt.astimezone(timezone.utc).isoformat()
        if date_to:
            end_day = date.fromisoformat(date_to) + timedelta(days=1)
            end_dt = datetime.combine(end_day, time.min, tzinfo=BUSINESS_TIMEZONE)
            end = end_dt.astimezone(timezone.utc).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc
    if start and end and start >= end:
        raise HTTPException(status_code=400, detail="date_from 不能晚于 date_to")
    return start, end

ROLE_PERMISSIONS = {
    "owner": {
        "view_orders", "view_products", "view_after_sales", "view_superagent",
        "operate_orders", "resolve_after_sale", "receive_return",
        "approve_superagent", "manage_members", "operate_inventory",
    },
    "admin": {
        "view_orders", "view_products", "view_after_sales", "view_superagent",
        "operate_orders", "resolve_after_sale", "receive_return",
        "approve_superagent", "operate_inventory",
    },
    "staff": {
        "view_orders", "view_products", "view_after_sales", "view_superagent",
    },
}


class WorkbenchOrderStatusIn(BaseModel):
    status: str = Field(..., pattern="^(PAID|SHIPPED|COMPLETED|CANCELLED)$")
    tracking_no: str | None = Field(default=None, max_length=64)
    carrier: str | None = Field(default=None, max_length=64)


class WorkbenchAfterSaleResolveIn(BaseModel):
    approved: bool


class WorkbenchAfterSaleReceiveIn(BaseModel):
    accepted: bool


class InventoryAdjustItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., min_length=1, max_length=80)
    sku: str = Field(..., min_length=1, max_length=80)
    target_available: int = Field(..., ge=0)


class InventoryPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str | None = Field(default=None, max_length=80)
    reason_code: str = Field(default="MANUAL_RECONCILIATION", max_length=64)
    reason: str = Field(default="批量可售量调整", max_length=300)
    items: list[InventoryAdjustItemIn] = Field(..., min_length=1, max_length=50)


class InventoryBatchItemIn(InventoryAdjustItemIn):
    warehouse_id: str = Field(..., min_length=1, max_length=80)
    expected_available: int = Field(..., ge=0)
    expected_reserved: int = Field(..., ge=0)


class InventoryBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: str = Field(..., min_length=1, max_length=80)
    reason_code: str = Field(default="MANUAL_RECONCILIATION", max_length=64)
    reason: str = Field(default="批量可售量调整", max_length=300)
    items: list[InventoryBatchItemIn] = Field(..., min_length=1, max_length=50)


def _account() -> dict[str, Any]:
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号不可用")
    return account


def _membership(account: dict[str, Any]) -> dict[str, Any]:
    """账号 → 商家。演示环境首次访问允许系统管理员自动绑定默认商家。"""
    row = store.get_merchant_member(account["id"])
    if row is not None:
        return row
    if account.get("is_system_admin"):
        return store.bind_merchant_member(account["id"], DEFAULT_MERCHANT_ID)
    raise HTTPException(status_code=403, detail="当前账号未绑定商家，无法进入商家工作台")


def permissions_for(role: str) -> set[str]:
    return set(ROLE_PERMISSIONS.get(str(role or "").lower(), set()))


def _require_permission(account: dict[str, Any], permission: str) -> dict[str, Any]:
    member = _membership(account)
    if permission not in permissions_for(member["role"]):
        raise HTTPException(status_code=403, detail=f"当前角色 {member['role']} 没有 {permission} 权限")
    return member


def _merchant_error(exc: MerchantError) -> HTTPException:
    code = getattr(exc, "code", "MERCHANT_ERROR")
    status = 404 if code in {"MERCHANT_NOT_FOUND"} else 409 if code in {
        "MERCHANT_CONFLICT",
        "MERCHANT_INVALID",
        "MERCHANT_UNAVAILABLE",
    } else 400
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


def _ticket_for_merchant(ticket_id: str, merchant_id: str) -> dict[str, Any]:
    ticket = store.get_after_sale(ticket_id)
    order = store.get_order(ticket["order_id"])
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    merchant_order = get_merchant_repository().get_order(
        order["order_id"], merchant_id=merchant_id
    )
    if merchant_order is None:
        raise HTTPException(status_code=404, detail="售后工单不属于当前商家")
    return ticket


@router.get("/me")
def workbench_me() -> dict[str, Any]:
    account = _account()
    member = _membership(account)
    merchant_id = member["merchant_id"]
    repo = get_merchant_repository()
    products = repo.list_products(merchant_id, limit=200)
    orders = repo.list_orders(merchant_id, limit=500)
    return {
        "account": {
            "id": account.get("id"),
            "username": account.get("username"),
            "display_name": account.get("display_name"),
        },
        "merchant": {
            "merchant_id": merchant_id,
            "name": MERCHANT_NAMES.get(merchant_id, merchant_id),
            "role": member["role"],
        },
        "permissions": sorted(permissions_for(member["role"])),
        "counts": {"products": len(products), "orders": len(orders)},
        "backend": repo.backend,
    }


@router.get("/products")
def workbench_products(limit: int = 100) -> dict[str, Any]:
    account = _account()
    merchant_id = _membership(account)["merchant_id"]
    return _products_snapshot(merchant_id, limit=limit)


MAX_PRODUCT_IMAGES = 8
_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or ""))[:100]


def _save_product_image(raw: bytes, merchant_id: str, product_id: str, *, unique: bool = True) -> dict[str, str]:
    """校验并保存主图 + 360px 缩略图，返回 url / thumb_url。"""
    with Image.open(io.BytesIO(raw)) as probe:
        probe.verify()
    with Image.open(io.BytesIO(raw)) as source:
        image = source.convert("RGB")
        image.thumbnail((1200, 1200))
        base = _safe_name(product_id)
        if unique:
            base = f"{base}-{uuid.uuid4().hex[:10]}"
        main_buffer = io.BytesIO()
        thumb_buffer = io.BytesIO()
        image.save(main_buffer, "WEBP", quality=86, method=6)
        thumb = image.copy()
        thumb.thumbnail((360, 360))
        thumb.save(thumb_buffer, "WEBP", quality=78, method=6)
    return media.save_product_image_bytes(
        main_buffer.getvalue(),
        thumb_buffer.getvalue(),
        merchant_id=merchant_id,
        product_id=product_id,
        base_name=base,
    )


def _current_product(repo: Any, merchant_id: str, product_id: str) -> Any:
    for product in repo.list_products(merchant_id, limit=500):
        if product.product_id == product_id:
            return product
    return None


def _current_images(product: Any) -> list[dict[str, str]]:
    if product is None:
        return []
    images = [dict(item) for item in (product.images or ()) if item.get("url")]
    if not images and product.image_url:
        images = [{"url": product.image_url, "thumb_url": product.image_url}]
    return images


async def _read_valid_upload(file: UploadFile) -> bytes:
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="只支持 PNG / JPEG / WebP")
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="图片不能超过 2MB")
    return raw


@router.post("/products/{product_id}/image")
async def upload_product_image(product_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """兼容旧接口：上传单张主图（同时生成缩略图）。"""
    account = _account()
    member = _require_permission(account, "operate_inventory")
    merchant_id = member["merchant_id"]
    product_id = str(product_id or "").strip()
    if not product_id:
        raise HTTPException(status_code=400, detail="product_id 不能为空")
    raw = await _read_valid_upload(file)
    repo = get_merchant_write_repository()
    if _current_product(repo, merchant_id, product_id) is None:
        raise HTTPException(status_code=404, detail="商品不存在或不属于当前商家")
    try:
        image = _save_product_image(raw, merchant_id, product_id, unique=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="图片无法解析") from exc
    if not repo.set_product_images(merchant_id, product_id, [image]):
        raise HTTPException(status_code=404, detail="商品不存在或不属于当前商家")
    media.record_image_audit(
        merchant_id=merchant_id, product_id=product_id,
        action="REPLACE", image_url=image["url"], actor_id=account.get("id"),
    )
    return {"product_id": product_id, "image_url": image["url"], "images": [image]}


@router.post("/products/{product_id}/images")
async def upload_product_images(product_id: str, files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """B 端追加商品图片，最多 8 张；首图作为封面。"""
    account = _account()
    member = _require_permission(account, "operate_inventory")
    merchant_id = member["merchant_id"]
    product_id = str(product_id or "").strip()
    if not product_id:
        raise HTTPException(status_code=400, detail="product_id 不能为空")
    repo = get_merchant_write_repository()
    product = _current_product(repo, merchant_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在或不属于当前商家")
    current = _current_images(product)
    if len(current) + len(files) > MAX_PRODUCT_IMAGES:
        raise HTTPException(status_code=400, detail=f"每个商品最多 {MAX_PRODUCT_IMAGES} 张图片")
    added: list[dict[str, str]] = []
    for upload in files:
        raw = await _read_valid_upload(upload)
        try:
            added.append(_save_product_image(raw, merchant_id, product_id, unique=True))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="图片无法解析") from exc
    merged = current + added
    if not repo.set_product_images(merchant_id, product_id, merged):
        raise HTTPException(status_code=404, detail="商品不存在或不属于当前商家")
    for image in added:
        media.record_image_audit(
            merchant_id=merchant_id, product_id=product_id,
            action="UPLOAD", image_url=image["url"], actor_id=account.get("id"),
        )
    return {"product_id": product_id, "image_url": merged[0]["url"] if merged else "", "images": merged}


@router.delete("/products/{product_id}/images")
def delete_product_image(product_id: str, url: str) -> dict[str, Any]:
    """B 端删除一张商品图；首图删除后自动顺延下一张为封面。"""
    account = _account()
    member = _require_permission(account, "operate_inventory")
    merchant_id = member["merchant_id"]
    product_id = str(product_id or "").strip()
    repo = get_merchant_write_repository()
    product = _current_product(repo, merchant_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="商品不存在或不属于当前商家")
    current = _current_images(product)
    target = str(url or "").split("?", 1)[0]
    removed = [item for item in current if item.get("url", "").split("?", 1)[0] == target]
    remaining = [item for item in current if item not in removed]
    if not removed:
        raise HTTPException(status_code=404, detail="图片不存在")
    if not repo.set_product_images(merchant_id, product_id, remaining):
        raise HTTPException(status_code=404, detail="商品不存在或不属于当前商家")
    for image in removed:
        media.delete_image_objects(image)
    media.record_image_audit(
        merchant_id=merchant_id, product_id=product_id,
        action="DELETE", image_url=url, actor_id=account.get("id"),
    )
    return {
        "product_id": product_id,
        "image_url": remaining[0]["url"] if remaining else "",
        "images": remaining,
    }


@router.get("/products/{product_id}/image-audit")
def product_image_audit(product_id: str, limit: int = 20) -> dict[str, Any]:
    account = _account()
    member = _membership(account)
    return {
        "merchant_id": member["merchant_id"],
        "product_id": product_id,
        "events": media.list_image_audit(member["merchant_id"], product_id, limit=limit),
    }


@router.get("/inventory/capabilities")
def workbench_inventory_capabilities() -> dict[str, Any]:
    account = _account()
    member = _require_permission(account, "operate_inventory")
    return {
        "merchant_id": member["merchant_id"],
        "mode": "SET_AVAILABLE",
        "max_items": 50,
        "physical_count_supported": False,
        "simulation_mode": "SIMULATED",
    }


@router.post("/inventory/preview")
def workbench_inventory_preview(req: InventoryPreviewIn) -> dict[str, Any]:
    account = _account()
    member = _require_permission(account, "operate_inventory")
    merchant_id = member["merchant_id"]
    repo = get_merchant_repository()
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for item in req.items:
        if item.sku in seen:
            raise HTTPException(status_code=422, detail="同一批次不能重复 SKU")
        seen.add(item.sku)
        inventory = repo.get_inventory(item.sku, merchant_id=merchant_id)
        if inventory is None or not inventory.warehouses:
            items.append({
                "item_id": item.item_id, "sku": item.sku, "status": "INVALID",
                "error": {"code": "NOT_FOUND", "message": "找不到当前商家的库存记录"},
            })
            continue
        warehouses = inventory.warehouses
        selected = next((w for w in warehouses if w.warehouse_id == req.warehouse_id), None) if req.warehouse_id else warehouses[0]
        if selected is None:
            items.append({
                "item_id": item.item_id, "sku": item.sku, "status": "INVALID",
                "error": {"code": "NOT_FOUND", "message": "指定仓库下没有该 SKU"},
            })
            continue
        before = selected.available_qty
        target = int(item.target_available)
        items.append({
            "item_id": item.item_id,
            "sku": item.sku,
            "warehouse_id": selected.warehouse_id,
            "expected_available": before,
            "expected_reserved": selected.reserved_qty,
            "before": {"available_qty": before, "reserved_qty": selected.reserved_qty, "safety_stock": selected.safety_stock},
            "after": {"available_qty": target, "reserved_qty": selected.reserved_qty, "safety_stock": selected.safety_stock},
            "delta_available": target - before,
            "status": "READY" if target != before else "UNCHANGED",
        })
    return {
        "merchant_id": merchant_id,
        "mode": "SET_AVAILABLE",
        "simulation_mode": "SIMULATED",
        "max_items": 50,
        "warehouse_id": req.warehouse_id,
        "valid_count": sum(1 for item in items if item["status"] == "READY"),
        "invalid_count": sum(1 for item in items if item["status"] == "INVALID"),
        "items": items,
    }


@router.post("/inventory/batch")
def workbench_inventory_batch(req: InventoryBatchIn) -> dict[str, Any]:
    account = _account()
    member = _require_permission(account, "operate_inventory")
    merchant_id = member["merchant_id"]
    repo = get_merchant_repository()
    seen: set[str] = set()
    for item in req.items:
        if item.sku in seen:
            raise HTTPException(status_code=422, detail="同一批次不能重复 SKU")
        seen.add(item.sku)
    batch_id = f"adjbatch_{uuid.uuid4().hex}"
    actor_id = str(account["id"])
    results: list[dict[str, Any]] = []
    for item in req.items:
        payload = {
            "warehouse_id": item.warehouse_id,
            "sku": item.sku,
            "target_available": item.target_available,
            "expected_available": item.expected_available,
            "expected_reserved": item.expected_reserved,
            "reason_code": req.reason_code,
            "reason": req.reason,
        }
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        row = repo.adjust_inventory_available(
            merchant_id,
            batch_id=batch_id,
            item_id=item.item_id,
            actor_id=actor_id,
            client_request_id=req.client_request_id,
            warehouse_id=item.warehouse_id,
            sku=item.sku,
            target_available=item.target_available,
            expected_available=item.expected_available,
            expected_reserved=item.expected_reserved,
            payload_hash=payload_hash,
            reason_code=req.reason_code,
            reason=req.reason,
        )
        results.append({
            "item_id": row["item_id"],
            "sku": row["sku"],
            "warehouse_id": row["warehouse_id"],
            "status": row["status"],
            "before_available": row["before_available"],
            "after_available": row["after_available"],
            "reserved_qty": row["reserved_qty"],
            "target_available": row["target_available"],
            "error_code": row["error_code"],
            "audit_event_id": row["event_id"],
        })
    succeeded = sum(1 for row in results if row["status"] == "SUCCEEDED")
    unchanged = sum(1 for row in results if row["status"] == "UNCHANGED")
    failed = sum(1 for row in results if row["status"] == "FAILED")
    if failed == 0 and (succeeded or unchanged):
        status = "SUCCEEDED"
    elif succeeded or unchanged:
        status = "PARTIAL_SUCCESS"
    else:
        status = "FAILED"
    return {
        "merchant_id": merchant_id,
        "batch_id": batch_id,
        "client_request_id": req.client_request_id,
        "mode": "SET_AVAILABLE",
        "simulation_mode": "SIMULATED",
        "status": status,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "unchanged": unchanged,
        "items": results,
    }


@router.get("/inventory/alerts")
def workbench_inventory_alerts(status: str | None = "PENDING", limit: int = 100) -> dict[str, Any]:
    account = _account()
    merchant_id = _membership(account)["merchant_id"]
    alerts = store.list_inventory_alerts(merchant_id, status=status or None, limit=limit)
    return {
        "merchant_id": merchant_id,
        "status": (status or "").upper() or None,
        "alerts": alerts,
    }


@router.post("/inventory/alerts/scan")
def workbench_inventory_scan() -> dict[str, Any]:
    account = _account()
    member = _require_permission(account, "operate_inventory")
    merchant_id = member["merchant_id"]
    snapshot = _products_snapshot(merchant_id)
    low_items = []
    for product in snapshot["products"]:
        for sku in product["skus"]:
            if not sku.get("low_stock"):
                continue
            low_items.append({
                "product_id": product["product_id"],
                "product_title": product.get("title") or product.get("name") or product["product_id"],
                "sku": sku["sku"],
                "spec": sku.get("spec") or "",
                "available_qty": sku.get("available_qty") or 0,
                "safety_stock": sku.get("safety_stock") or 0,
                "reorder_qty": sku.get("reorder_qty") or 0,
            })
    result = store.sync_inventory_alerts(merchant_id, low_items)
    alerts = store.list_inventory_alerts(merchant_id, status="PENDING", limit=100)
    return {
        "merchant_id": merchant_id,
        **result,
        "alerts": alerts,
        "dispatch": {
            "configured": False,
            "channel": "IN_APP",
            "note": "当前只写入站内待发送队列；企业微信/邮件渠道未配置。",
        },
    }


@router.post("/inventory/alerts/{alert_id}/ack")
def workbench_inventory_alert_ack(alert_id: str) -> dict[str, Any]:
    account = _account()
    member = _require_permission(account, "operate_inventory")
    alert = store.ack_inventory_alert(member["merchant_id"], alert_id, int(account["id"]))
    if alert is None:
        raise HTTPException(status_code=404, detail="告警不存在、已被处理或不属于当前商家")
    return {"merchant_id": member["merchant_id"], "alert": alert}


@router.post("/inventory/alerts/dispatch")
def workbench_inventory_dispatch() -> dict[str, Any]:
    account = _account()
    member = _require_permission(account, "operate_inventory")
    merchant_id = member["merchant_id"]
    alerts = store.list_inventory_alerts(merchant_id, status="PENDING", limit=100)
    if not alerts:
        return {"merchant_id": merchant_id, "sent": False, "reason": "NO_ALERTS", "dispatched": 0}
    result = alert_notifier.deliver_inventory_alerts_wecom(alerts)
    dispatched = 0
    if result.get("sent"):
        dispatched = store.mark_inventory_alerts_sent(
            merchant_id, [str(item["alert_id"]) for item in alerts]
        )
    remaining = len(store.list_inventory_alerts(merchant_id, status="PENDING", limit=100))
    return {
        "merchant_id": merchant_id,
        **result,
        "dispatched": dispatched,
        "remaining": remaining,
    }


def _products_snapshot(merchant_id: str, *, limit: int = 100) -> dict[str, Any]:
    repo = get_merchant_repository()
    products = repo.list_products(merchant_id, limit=limit)
    items = []
    for product in products:
        skus = repo.list_product_skus(product.product_id, merchant_id=merchant_id)
        sku_items = []
        available_total = 0
        reserved_total = 0
        safety_total = 0
        reorder_total = 0
        low_stock_skus = 0
        for sku in skus:
            inventory = None
            try:
                inventory = repo.get_inventory(sku.sku, merchant_id=merchant_id)
            except MerchantError:
                inventory = None
            item = {
                "sku": sku.sku,
                "spec": sku.spec,
                "price": str(sku.price),
                "status": sku.status,
            }
            if inventory is not None:
                low = inventory.safety_stock > 0 and inventory.available_qty <= inventory.safety_stock
                reorder_qty = max(0, inventory.safety_stock - inventory.available_qty)
                item.update({
                    "available_qty": inventory.available_qty,
                    "reserved_qty": inventory.reserved_qty,
                    "safety_stock": inventory.safety_stock,
                    "in_stock": inventory.in_stock,
                    "warehouse_count": len(inventory.warehouses),
                    "low_stock": low,
                    "reorder_qty": reorder_qty,
                })
                available_total += inventory.available_qty
                reserved_total += inventory.reserved_qty
                safety_total += inventory.safety_stock
                reorder_total += reorder_qty
                if low:
                    low_stock_skus += 1
            sku_items.append(item)
        items.append({
            **product.to_dict(),
            "stock": available_total,
            "available_qty": available_total,
            "reserved_qty": reserved_total,
            "safety_stock": safety_total,
            "low_stock": low_stock_skus > 0,
            "low_stock_skus": low_stock_skus,
            "reorder_qty": reorder_total,
            "skus": sku_items,
        })
    low_stock_products = sum(1 for item in items if item["low_stock"])
    low_stock_skus = sum(int(item["low_stock_skus"]) for item in items)
    suggested_reorder = sum(int(item["reorder_qty"]) for item in items)
    return {
        "merchant_id": merchant_id,
        "summary": {
            "total_products": len(items),
            "low_stock_products": low_stock_products,
            "low_stock_skus": low_stock_skus,
            "suggested_reorder_qty": suggested_reorder,
        },
        "products": items,
    }

@router.get("/chat-profiles")
def workbench_chat_profiles(limit: int = 100) -> dict[str, Any]:
    """B 端：只读当前商家的会话用户画像摘要。"""
    account = _account()
    merchant_id = _membership(account)["merchant_id"]
    profiles = store.list_chat_user_profiles(merchant_id, limit=limit)
    return {"merchant_id": merchant_id, "profiles": profiles, "count": len(profiles)}


@router.get("/chat-profiles/{buyer_id}")
def workbench_chat_profile(buyer_id: str) -> dict[str, Any]:
    account = _account()
    merchant_id = _membership(account)["merchant_id"]
    profile = store.get_chat_user_profile(merchant_id, buyer_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="画像不存在或不属于当前商家")
    return {"merchant_id": merchant_id, "profile": profile}


@router.get("/orders")
def workbench_orders(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    account = _account()
    merchant_id = _require_permission(account, "view_orders")["merchant_id"]
    repo = get_merchant_repository()
    bounded_limit = max(1, min(int(limit or 20), 100))
    safe_offset = min(max(0, int(offset or 0)), 10000)
    start, end = _business_day_utc_range(date_from, date_to)
    query = (q or "").strip()[:80] or None
    total = repo.count_orders(
        merchant_id,
        status=status,
        q=query,
        created_from=start,
        created_to=end,
    )
    orders = repo.search_orders(
        merchant_id,
        status=status,
        q=query,
        created_from=start,
        created_to=end,
        limit=bounded_limit,
        offset=safe_offset,
    )
    return {
        "merchant_id": merchant_id,
        "orders": [order.to_dict() for order in orders],
        "total": total,
        "limit": bounded_limit,
        "offset": safe_offset,
    }


@router.patch("/orders/{order_id}/status")
def workbench_update_order(order_id: str, req: WorkbenchOrderStatusIn) -> dict[str, Any]:
    account = _account()
    merchant_id = _require_permission(account, "operate_orders")["merchant_id"]
    repo = get_merchant_write_repository()
    try:
        order = repo.update_order_status(
            merchant_id,
            order_id,
            req.status,
            tracking_no=req.tracking_no,
            carrier=req.carrier,
        )
    except MerchantError as exc:
        raise _merchant_error(exc) from exc
    return {"order": order.to_dict()}


@router.get("/after-sales")
def workbench_after_sales(status: str | None = None, limit: int = 100) -> dict[str, Any]:
    account = _account()
    merchant_id = _membership(account)["merchant_id"]
    repo = get_merchant_repository()
    tickets = store.list_after_sales(limit=min(max(int(limit), 1), 200))
    scoped = []
    for ticket in tickets:
        if status and ticket["status"] != status.upper():
            continue
        order = store.get_order(ticket["order_id"])
        if order is None:
            continue
        if repo.get_order(order["order_id"], merchant_id=merchant_id) is None:
            continue
        scoped.append(ticket)
    return {"merchant_id": merchant_id, "tickets": scoped}


@router.patch("/after-sales/{ticket_id}")
def workbench_resolve_after_sale(ticket_id: str, req: WorkbenchAfterSaleResolveIn) -> dict[str, Any]:
    account = _account()
    merchant_id = _require_permission(account, "resolve_after_sale")["merchant_id"]
    _ticket_for_merchant(ticket_id, merchant_id)
    try:
        return store.resolve_after_sale(ticket_id, approved=req.approved)
    except store.CStoreError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/after-sales/{ticket_id}/receive")
def workbench_receive_after_sale(ticket_id: str, req: WorkbenchAfterSaleReceiveIn) -> dict[str, Any]:
    account = _account()
    merchant_id = _require_permission(account, "receive_return")["merchant_id"]
    _ticket_for_merchant(ticket_id, merchant_id)
    try:
        return store.receive_after_sale(ticket_id, accepted=req.accepted)
    except store.CStoreError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


def register_b_workbench(app) -> None:
    from rag_demo.api.tenants import router as tenants_router

    app.include_router(router)
    app.include_router(tenants_router)

