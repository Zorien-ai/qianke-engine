"""C 端商品浏览与模拟订单 HTTP API。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.c_end import store

router = APIRouter(prefix="/api/c", tags=["c-end"])


def _buyer() -> tuple[str, dict]:
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号不可用")
    return f"buyer_{account['id']}", account


class ItemIn(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=40)
    quantity: int = Field(..., ge=1, le=99)


class PrepareOrderIn(BaseModel):
    items: list[ItemIn] = Field(..., min_length=1, max_length=20)


class ConfirmOrderIn(BaseModel):
    confirmation_token: str = Field(..., min_length=8, max_length=200)
    request_id: str | None = Field(default=None, max_length=128)


def _http_error(exc: store.CStoreError) -> HTTPException:
    status = 409 if exc.code in {
        "INSUFFICIENT_STOCK",
        "ORDER_CHANGED",
        "ORDER_NOT_DRAFT",
        "INVALID_CONFIRMATION",
        "ORDER_FORBIDDEN",
        "IDEMPOTENCY_CONFLICT",
    } else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


@router.get("/products")
def list_products(category: str | None = None, keyword: str | None = None, limit: int = 20) -> dict:
    return {"products": store.list_products(category=category, keyword=keyword, limit=limit)}


@router.post("/orders/prepare")
def prepare_order(req: PrepareOrderIn) -> dict:
    buyer_id, _ = _buyer()
    items = [item.model_dump() for item in req.items]
    try:
        return store.prepare_order(buyer_id, items)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.post("/orders/{draft_id}/confirm")
def confirm_order(draft_id: str, req: ConfirmOrderIn) -> dict:
    buyer_id, _ = _buyer()
    request_id = (req.request_id or "").strip() or f"req_c_{uuid.uuid4().hex[:16]}"
    try:
        return store.confirm_order(
            buyer_id,
            draft_id,
            req.confirmation_token,
            request_id=request_id,
        )
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/orders/{order_id}")
def get_order(order_id: str) -> dict:
    buyer_id, _ = _buyer()
    order = store.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order["buyer_id"] != buyer_id:
        raise HTTPException(status_code=403, detail="不能查看其他用户的订单")
    return order


def register_c_end(app) -> None:
    app.include_router(router)
