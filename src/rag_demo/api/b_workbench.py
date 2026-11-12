"""B 端商家工作台 API（商家租户作用域）。

与 /api/c/admin/* 的区别：
- 不要求系统管理员，而是要求当前账号已绑定商家；
- 所有订单/商品/售后操作都必须落在该 merchant_id 内。
"""
from __future__ import annotations

import io
import re
import time
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel, Field

from rag_demo import auth, product_media as media
from rag_demo.c_end import alerts as alert_notifier
from rag_demo.c_end import store
from rag_demo.merchant import MerchantError, get_merchant_repository, get_merchant_write_repository

router = APIRouter(prefix="/api/b/workbench", tags=["b-workbench"])

DEFAULT_MERCHANT_ID = "m_gear_002"
MERCHANT_NAMES = {"m_gear_002": "山野户外旗舰店", "m_tea_001": "山雾茶业"}

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


@router.post("/products/{product_id}/image")
async def upload_product_image(product_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """B 端上传商品主图：校验图片 → 转 WebP → 落本地 → 写 image_url。"""
    account = _account()
    member = _require_permission(account, "operate_inventory")
    merchant_id = member["merchant_id"]
    product_id = str(product_id or "").strip()
    if not product_id:
        raise HTTPException(status_code=400, detail="product_id 不能为空")
    if file.content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=400, detail="只支持 PNG / JPEG / WebP")
    raw = await file.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="图片不能超过 2MB")
    repo = get_merchant_write_repository()
    owned = {item.product_id for item in repo.list_products(merchant_id, limit=500)}
    if product_id not in owned:
        raise HTTPException(status_code=404, detail="商品不存在或不属于当前商家")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGB")
            image.thumbnail((1200, 1200))
            safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", product_id)[:100]
            folder = media.PRODUCT_UPLOAD_ROOT / re.sub(r"[^A-Za-z0-9_.-]", "_", merchant_id)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{safe_id}.webp"
            image.save(target, "WEBP", quality=86, method=6)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="图片无法解析") from exc

    image_url = f"/uploads/products/{folder.name}/{safe_id}.webp?v={int(time.time())}"
    if not repo.set_product_image(merchant_id, product_id, image_url):
        raise HTTPException(status_code=404, detail="商品不存在或不属于当前商家")
    return {"product_id": product_id, "image_url": image_url}


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
def workbench_orders(status: str | None = None, limit: int = 100) -> dict[str, Any]:
    account = _account()
    merchant_id = _membership(account)["merchant_id"]
    repo = get_merchant_repository()
    orders = repo.list_orders(merchant_id, status=status, limit=limit)
    return {"merchant_id": merchant_id, "orders": [order.to_dict() for order in orders]}


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

