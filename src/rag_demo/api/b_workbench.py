"""B 端商家工作台 API（商家租户作用域）。

与 /api/c/admin/* 的区别：
- 不要求系统管理员，而是要求当前账号已绑定商家；
- 所有订单/商品/售后操作都必须落在该 merchant_id 内。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from rag_demo import auth, config, product_media as media
from rag_demo.b_end import insights as b_insights
from rag_demo.b_end import user_pool as b_user_pool
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
        "view_profiles", "manage_profiles",
    },
    "admin": {
        "view_orders", "view_products", "view_after_sales", "view_superagent",
        "operate_orders", "resolve_after_sale", "receive_return",
        "approve_superagent", "operate_inventory",
        "view_profiles", "manage_profiles",
    },
    "staff": {
        "view_orders", "view_products", "view_after_sales", "view_superagent",
        "view_profiles",
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


class OrderSimulationActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: str = Field(..., min_length=1, max_length=80)
    action: str = Field(..., pattern="^(SIMULATE_PAYMENT|SIMULATE_COMPLETION)$")
    expected_status: str = Field(..., min_length=1, max_length=32)
    expected_amount: str = Field(..., min_length=1, max_length=64)
    expected_currency: str = Field(default="CNY", min_length=1, max_length=8)
    reason: str = Field(..., min_length=1, max_length=300)


class InventoryAdjustItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(..., min_length=1, max_length=80)
    sku: str = Field(..., min_length=1, max_length=80)
    target_available: int = Field(..., ge=0)


class InventoryPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(..., min_length=1, max_length=80)
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


class ProfileQueryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=500)
    source: str = Field(default="all", pattern="^(qianke|imported|all)$")


PROFILE_SOURCES = {
    "qianke": "千客用户",
    "imported": "导入用户",
    "all": "全部用户",
}


def _profile_scope(account: dict[str, Any], permission: str) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    """权限 + 商户 + 商户数据集 + 数据空间状态，一次算清。"""
    member = _require_permission(account, permission)
    merchant_id = str(member["merchant_id"])
    try:
        dataset = config.merchant_dataset_name(merchant_id)
        dbname = config.merchant_db_name(merchant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "PROFILE_MERCHANT_INVALID", "message": str(exc)},
        ) from exc
    if dataset not in config.DATASETS:
        # 启动时注册过；这里兜底覆盖「服务启动后新建的商户」。
        config.register_dataset(dataset, dbname)
    status = b_insights.dataset_status(dataset)
    return member, merchant_id, dataset, status


def _require_import_ready(status: dict[str, Any]) -> None:
    if status.get("ready"):
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": "PROFILE_DB_NOT_READY",
            "message": "导入用户数据空间还没有构建，请先到「数据接入」导入 CSV 或载入示例数据",
            "next_action": "IMPORT",
        },
    )


def _profile_source(source: str) -> str:
    value = str(source or "all").strip().lower()
    if value not in PROFILE_SOURCES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "PROFILE_SOURCE_INVALID",
                "message": "数据范围只能是 qianke / imported / all",
            },
        )
    return value


def _merchant_sample_files() -> list[tuple[str, bytes]]:
    """B 端演示画像：仓库自带的小样本，避免把平台 8110 条 demo 画像灌给商户。"""
    base = Path(config.BASE_DIR) / "data" / "samples"
    pairs = (
        ("merchant_users.csv", base / "merchant_users.csv"),
        ("merchant_rules.md", base / "merchant_rules.md"),
    )
    files: list[tuple[str, bytes]] = []
    for name, path in pairs:
        if not path.is_file():
            raise HTTPException(
                status_code=500,
                detail=f"示例数据文件缺失：{path}",
            )
        files.append((name, path.read_bytes()))
    return files


def _can_see_sql(member: dict[str, Any]) -> bool:
    return str(member.get("role") or "").lower() in {"owner", "admin"}


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


@router.get("/reports/completion")
def workbench_completion_report(date_from: str, date_to: str) -> dict[str, Any]:
    account = _account()
    member = _require_permission(account, "view_orders")
    if member["role"] not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="只有店主/管理员可以查看经营报告")
    merchant_id = member["merchant_id"]
    start, end = _business_day_utc_range(date_from, date_to)
    repo = get_merchant_repository()
    orders = repo.list_orders_for_completion_report(merchant_id, start_at=start, end_at=end)

    def money(value: Any) -> Decimal:
        try:
            return Decimal(str(value or "0"))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)

    def parsed_at(value: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def in_range(value: str) -> bool:
        return bool(value) and start_dt <= parsed_at(value) < end_dt

    def local_day(value: str) -> str:
        return parsed_at(value).astimezone(BUSINESS_TIMEZONE).date().isoformat()

    completed_gmv = Decimal("0")
    completed_count = 0
    refund_amount = Decimal("0")
    refund_orders = 0
    cohort_refund = Decimal("0")
    currencies: dict[str, dict[str, Any]] = {}
    daily: dict[str, dict[str, Any]] = {}

    def bucket(code: str) -> dict[str, Any]:
        return currencies.setdefault(code, {
            "currency": code,
            "completed_orders": 0,
            "completed_gmv": Decimal("0"),
            "refund_amount": Decimal("0"),
            "refund_orders": 0,
            "net_amount": Decimal("0"),
        })

    def day_row(day: str) -> dict[str, Any]:
        return daily.setdefault(day, {
            "date": day,
            "completed_orders": 0,
            "completed_gmv": Decimal("0"),
            "refund_amount": Decimal("0"),
            "refund_orders": 0,
            "net_amount": Decimal("0"),
        })

    for order in orders:
        code = str(order.currency or "CNY").upper()
        total = money(order.total_amount)
        refund = money(order.refund_amount)
        completed_at = str(order.completed_at or "")
        refunded_at = str(order.refunded_at or "")
        completed_in_range = in_range(completed_at)
        refund_in_range = in_range(refunded_at)
        if completed_in_range:
            completed_count += 1
            completed_gmv += total
            cohort_refund += refund
            c = bucket(code)
            c["completed_orders"] += 1
            c["completed_gmv"] += total
            d = day_row(local_day(completed_at))
            d["completed_orders"] += 1
            d["completed_gmv"] += total
        if refund_in_range:
            refund_orders += 1
            refund_amount += refund
            c = bucket(code)
            c["refund_orders"] += 1
            c["refund_amount"] += refund
            d = day_row(local_day(refunded_at))
            d["refund_orders"] += 1
            d["refund_amount"] += refund

    def text(value: Decimal) -> str:
        return format(value.quantize(Decimal("0.01")), "f")

    for c in currencies.values():
        c["completed_gmv"] = text(c["completed_gmv"])
        c["refund_amount"] = text(c["refund_amount"])
        c["net_amount"] = text(money(c["completed_gmv"]) - money(c["refund_amount"]))
    for d in daily.values():
        d["completed_gmv"] = text(d["completed_gmv"])
        d["refund_amount"] = text(d["refund_amount"])
        d["net_amount"] = text(money(d["completed_gmv"]) - money(d["refund_amount"]))
    currency_values = sorted(currencies)
    return {
        "merchant_id": merchant_id,
        "period": {"date_from": date_from, "date_to": date_to, "timezone": "Asia/Shanghai"},
        "simulation_mode": "SIMULATED",
        "currency": currency_values[0] if len(currency_values) == 1 else ("MIXED" if currency_values else "CNY"),
        "currencies": [currencies[code] for code in currency_values],
        "completed_orders": completed_count,
        "completed_gmv": text(completed_gmv),
        "refund_orders": refund_orders,
        "refund_amount": text(refund_amount),
        "net_amount": text(completed_gmv - refund_amount),
        "cohort_refund_amount": text(cohort_refund),
        "cohort_net_amount": text(completed_gmv - cohort_refund),
        "daily": [daily[key] for key in sorted(daily)],
        "note": "完成口径按 completed_at；退款按 refunded_at 发生期冲减；金额为模拟交易，不是真实收款。",
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
        "writes_inventory": True,
        "transaction_mode": "INVENTORY_WRITE",
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
        selected = next((w for w in warehouses if w.warehouse_id == req.warehouse_id), None)
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
        "transaction_mode": "INVENTORY_WRITE",
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
                    "warehouses": [
                        {
                            "warehouse_id": warehouse.warehouse_id,
                            "available_qty": warehouse.available_qty,
                            "reserved_qty": warehouse.reserved_qty,
                        }
                        for warehouse in inventory.warehouses
                    ],
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


# ==================== 画像查询：千客用户 / 导入用户 / 全部用户 ====================

@router.get("/profile-sources")
def workbench_profile_sources() -> dict[str, Any]:
    """两池状态：千客用户池 + 导入用户数据空间；前端据此决定空态与按钮。"""
    account = _account()
    member, merchant_id, dataset, status = _profile_scope(account, "view_profiles")
    can_manage = "manage_profiles" in permissions_for(member["role"])
    return {
        "merchant_id": merchant_id,
        "qianke": b_user_pool.pool_summary(merchant_id),
        "imported": {
            **status,
            "can_manage": can_manage,
        },
        "scopes": [
            {"value": key, "label": label} for key, label in PROFILE_SOURCES.items()
        ],
        "can_manage": can_manage,
    }


@router.get("/profiles")
def workbench_profiles(
    source: str = "all",
    query: str = "",
    page: int = 1,
    size: int = 12,
) -> dict[str, Any]:
    """画像卡牌/搜索。imported 未构建时返回 409；all 返回两分组。"""
    account = _account()
    _member, merchant_id, dataset, status = _profile_scope(account, "view_profiles")
    scope = _profile_source(source)
    question = str(query or "").strip()
    page = max(1, int(page or 1))
    size = min(50, max(1, int(size or 12)))

    def single_scope(target: str) -> dict[str, Any]:
        if target == "imported":
            _require_import_ready(status)
            payload = (
                b_insights.imported_profile_search(dataset, question, limit=size)
                if question
                else b_insights.imported_profile_page(dataset, page=page, size=size)
            )
        else:
            payload = (
                b_insights.qianke_profile_search(merchant_id, question, limit=size)
                if question
                else b_insights.qianke_profile_page(merchant_id, page=page, size=size)
            )
        return {"merchant_id": merchant_id, "ready": True, **payload}

    if scope != "all":
        return single_scope(scope)

    imported_ready = bool(status.get("ready"))
    if imported_ready:
        imported_payload = (
            b_insights.imported_profile_search(dataset, question, limit=size)
            if question
            else b_insights.imported_profile_page(dataset, page=page, size=size)
        )
    else:
        imported_payload = {
            "source": "imported",
            "page": page,
            "size": size,
            "total": 0,
            "total_pages": 0,
            "items": [],
            "mode": "search" if question else "list",
        }
    qianke_payload = (
        b_insights.qianke_profile_search(merchant_id, question, limit=size)
        if question
        else b_insights.qianke_profile_page(merchant_id, page=page, size=size)
    )
    return {
        "merchant_id": merchant_id,
        "source": "all",
        "ready": imported_ready or bool(qianke_payload.get("total")),
        "groups": {
            "qianke": {"ready": True, **qianke_payload},
            "imported": {"ready": imported_ready, **imported_payload},
        },
    }


@router.post("/profile-query")
def workbench_profile_query(req: ProfileQueryIn) -> dict[str, Any]:
    """问小千：按数据范围路由到导入画像 / 千客用户 / 两池合并。"""
    account = _account()
    member, merchant_id, dataset, status = _profile_scope(account, "view_profiles")
    scope = _profile_source(req.source)
    if scope == "imported":
        _require_import_ready(status)
    try:
        result = b_insights.answer(
            scope=scope,
            question=req.question,
            merchant_id=merchant_id,
            account=account,
            dataset=dataset,
            imported_ready=bool(status.get("ready")),
            imported_total=int(status.get("profiles") or 0),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "PROFILE_QUERY_INVALID", "message": str(exc)},
        ) from exc
    # 内部字段不出网：trace 只进日志/评测；SQL 原文仅 owner/admin 可见。
    for internal in ("trace", "usage", "guard", "persona_guard"):
        result.pop(internal, None)
    if not _can_see_sql(member):
        result.pop("sql", None)
    return {
        "merchant_id": merchant_id,
        "source": scope,
        "dataset": dataset if status.get("ready") else None,
        **result,
    }


@router.post("/profile-pool/refresh")
def workbench_profile_pool_refresh() -> dict[str, Any]:
    """重建当前商户的千客用户池（会话 + 交易并集）。"""
    account = _account()
    _member, merchant_id, _dataset, _status = _profile_scope(account, "manage_profiles")
    try:
        return b_user_pool.refresh_merchant_pool(merchant_id)
    except Exception as exc:  # noqa: BLE001 - 让前端看到可读失败，而不是裸栈
        raise HTTPException(
            status_code=502,
            detail={"code": "PROFILE_POOL_REFRESH_FAILED", "message": f"用户池刷新失败：{exc}"},
        ) from exc


@router.post("/profile-import/sample")
def workbench_profile_import_sample() -> dict[str, Any]:
    """把仓库自带的商户演示画像落盘成上传批次；构建仍走 /api/wizard/build。"""
    account = _account()
    _member, _merchant_id, dataset, _status = _profile_scope(account, "manage_profiles")
    from rag_demo.mvp import uploads

    try:
        upload_id, rejected = uploads.save(None, _merchant_sample_files())
    except uploads.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth.bind_upload(upload_id, account)
    from rag_demo.mvp import app as wizard_app

    state = wizard_app._state_payload(upload_id)
    state["rejected"] = rejected
    return {"upload_id": upload_id, "dataset": dataset, "state": state}


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


@router.post("/orders/{order_id}/simulation-actions")
def workbench_order_simulation_action(order_id: str, req: OrderSimulationActionIn) -> dict[str, Any]:
    account = _account()
    member = _require_permission(account, "operate_orders")
    repo = get_merchant_write_repository()
    try:
        action = repo.apply_order_simulation_action(
            member["merchant_id"],
            order_id=order_id,
            actor_id=str(account["id"]),
            client_request_id=req.client_request_id,
            action=req.action,
            expected_status=req.expected_status,
            expected_amount=req.expected_amount,
            expected_currency=req.expected_currency,
            reason=req.reason,
        )
    except MerchantError as exc:
        raise _merchant_error(exc) from exc
    return {"merchant_id": member["merchant_id"], "action": action}


@router.get("/orders/{order_id}/simulation-actions/{client_request_id}")
def workbench_order_simulation_action_lookup(order_id: str, client_request_id: str) -> dict[str, Any]:
    account = _account()
    member = _require_permission(account, "view_orders")
    repo = get_merchant_repository()
    action = repo.get_order_simulation_action(
        member["merchant_id"],
        order_id=order_id,
        actor_id=str(account["id"]),
        client_request_id=client_request_id,
    )
    if action is None:
        raise HTTPException(status_code=404, detail="模拟动作不存在或不属于当前账号")
    return {"merchant_id": member["merchant_id"], "action": action}


@router.patch("/orders/{order_id}/status")
def workbench_update_order(order_id: str, req: WorkbenchOrderStatusIn) -> dict[str, Any]:
    account = _account()
    merchant_id = _require_permission(account, "operate_orders")["merchant_id"]
    if req.status in {"PAID", "COMPLETED"}:
        raise HTTPException(
            status_code=409,
            detail="PAID/COMPLETED 必须走 /orders/{id}/simulation-actions 独立模拟动作接口",
        )
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
    tickets = store.list_after_sales(
        merchant_id=merchant_id,
        limit=min(max(int(limit), 1), 200),
    )
    scoped = [
        ticket
        for ticket in tickets
        if not status or ticket["status"] == status.upper()
    ]
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

