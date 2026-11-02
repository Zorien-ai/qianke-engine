"""B 端商家工作台 API（商家租户作用域）。

与 /api/c/admin/* 的区别：
- 不要求系统管理员，而是要求当前账号已绑定商家；
- 所有订单/商品/售后操作都必须落在该 merchant_id 内。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.c_end import store
from rag_demo.merchant import MerchantError, get_merchant_repository, get_merchant_write_repository

router = APIRouter(prefix="/api/b/workbench", tags=["b-workbench"])

DEFAULT_MERCHANT_ID = "m_gear_002"
MERCHANT_NAMES = {"m_gear_002": "山野户外旗舰店"}


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
        "counts": {"products": len(products), "orders": len(orders)},
        "backend": repo.backend,
    }


@router.get("/products")
def workbench_products(limit: int = 100) -> dict[str, Any]:
    account = _account()
    merchant_id = _membership(account)["merchant_id"]
    repo = get_merchant_repository()
    products = repo.list_products(merchant_id, limit=limit)
    items = []
    for product in products:
        skus = repo.list_product_skus(product.product_id, merchant_id=merchant_id)
        items.append({
            **product.to_dict(),
            "skus": [
                {
                    "sku": sku.sku,
                    "spec": sku.spec,
                    "price": str(sku.price),
                    "status": sku.status,
                }
                for sku in skus
            ],
        })
    return {"merchant_id": merchant_id, "products": items}


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
    merchant_id = _membership(account)["merchant_id"]
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
    merchant_id = _membership(account)["merchant_id"]
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
    merchant_id = _membership(account)["merchant_id"]
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
