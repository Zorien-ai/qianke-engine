"""C 端商品浏览与模拟订单 HTTP API。"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.agent.checkpoint import get_checkpointer
from rag_demo.c_end import agent as c_agent
from rag_demo.c_end import companion_agent, idempotency, persona as c_persona, social, store, store_agent
from rag_demo.merchant import MerchantError, get_merchant_repository, get_merchant_write_repository

router = APIRouter(prefix="/api/c", tags=["c-end"])
_THREAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_AVATAR_KIND_RE = re.compile(r"^(companion|user)$")


def _buyer() -> tuple[str, dict]:
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号不可用")
    return f"buyer_{account['id']}", account


def _require_admin() -> dict:
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if not account.get("is_system_admin"):
        raise HTTPException(status_code=403, detail="只有平台管理员可以查看 C 端审计")
    return account



class ItemIn(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=40)
    quantity: int = Field(..., ge=1, le=99)


class PrepareOrderIn(BaseModel):
    items: list[ItemIn] = Field(..., min_length=1, max_length=20)


class ConfirmOrderIn(BaseModel):
    confirmation_token: str = Field(..., min_length=8, max_length=200)
    request_id: str | None = Field(default=None, max_length=128)


class CancelOrderIn(BaseModel):
    request_id: str | None = Field(default=None, max_length=128)


class AfterSaleIn(BaseModel):
    type: str = Field(..., pattern="^(REFUND_ONLY|RETURN_REFUND)$")
    reason: str = Field(..., min_length=1, max_length=500)


class AfterSaleResolveIn(BaseModel):
    approved: bool


class CAgentRunIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    thread_id: str | None = Field(default=None, max_length=128)
    client_message_id: str | None = Field(default=None, max_length=128)


class CAgentResumeIn(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=128)
    approved: bool


class CompanionPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=12)
    user_nickname: str | None = Field(default=None, max_length=12)
    species: str | None = Field(default=None, max_length=60)
    persona: str | None = Field(default=None, max_length=60)
    appearance: str | None = Field(default=None, max_length=60)


class SendMessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)
    client_message_id: str | None = Field(default=None, max_length=128)


class MerchantOrderStatusIn(BaseModel):
    status: str = Field(..., pattern="^(PAID|SHIPPED|COMPLETED|CANCELLED)$")
    tracking_no: str | None = Field(default=None, max_length=64)
    carrier: str | None = Field(default=None, max_length=64)


class AppMessageIn(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(..., pattern="^(user|companion|assistant|system)$")
    content: str = Field(..., min_length=1, max_length=2000)
    metadata: dict = Field(default_factory=dict)


def _last_ai_text(messages: list) -> str:
    for msg in reversed(messages or []):
        if getattr(msg, "content", None) and getattr(msg, "type", "") == "ai":
            return str(msg.content)
    return ""


def _http_error(exc: store.CStoreError) -> HTTPException:
    if exc.code == "AVATAR_TOO_LARGE":
        status = 413
    elif exc.code in {"AVATAR_NOT_FOUND", "AFTER_SALE_NOT_FOUND", "ORDER_NOT_FOUND"}:
        status = 404
    elif exc.code in {"AFTER_SALE_FORBIDDEN", "ORDER_FORBIDDEN"}:
        status = 403
    else:
        status = 409 if exc.code in {
            "INSUFFICIENT_STOCK",
            "ORDER_CHANGED",
            "ORDER_NOT_DRAFT",
            "INVALID_CONFIRMATION",
            "ORDER_FORBIDDEN",
            "IDEMPOTENCY_CONFLICT",
            "QUOTE_FORBIDDEN",
            "QUOTE_NOT_PENDING",
            "ORDER_NOT_CANCELLABLE",
            "MERCHANT_ORDER_NOT_FOUND",
            "MERCHANT_CONFLICT",
            "MERCHANT_EXPIRED",
            "AFTER_SALE_NOT_ALLOWED",
            "AFTER_SALE_EXISTS",
        } else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


@router.get("/products")
def list_products(category: str | None = None, keyword: str | None = None, limit: int = 20) -> dict:
    return {"products": store.list_products(category=category, keyword=keyword, limit=limit)}


@router.get("/companion")
def get_companion() -> dict:
    buyer_id, _ = _buyer()
    return store.get_companion(buyer_id)


@router.patch("/companion")
def update_companion(req: CompanionPatchIn) -> dict:
    buyer_id, _ = _buyer()
    try:
        return store.update_companion(
            buyer_id,
            name=req.name,
            user_nickname=req.user_nickname,
            species=req.species,
            persona=req.persona,
            appearance=req.appearance,
        )
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


def _avatar_kind(kind: str) -> str:
    if not _AVATAR_KIND_RE.fullmatch(str(kind or "")):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_AVATAR_KIND", "message": "头像类型只支持 companion / user"},
        )
    return kind


@router.post("/companion/avatar/{kind}")
async def upload_companion_avatar(kind: str, file: UploadFile = File(...)) -> dict:
    """上传买家/伙伴头像；只接受 PNG / JPEG / WebP 且 ≤ 1MB。

    文件由服务端重命名并写到受控目录，DB 只存相对路径；用户不能控制文件名/路径。
    """
    buyer_id, _ = _buyer()
    _avatar_kind(kind)
    content_type = file.content_type or ""
    try:
        # 多读 1 字节用于判断超限；真正的大小上限在 store 层还有一次校验。
        data = await file.read(store.AVATAR_MAX_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 - 上传流读取失败按 400 处理
        raise HTTPException(
            status_code=400,
            detail={"code": "AVATAR_READ_FAILED", "message": "头像读取失败，请重试"},
        ) from exc
    finally:
        await file.close()
    if len(data) > store.AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "AVATAR_TOO_LARGE", "message": "头像不能超过 1MB"},
        )
    try:
        return store.save_companion_avatar(buyer_id, kind, data, content_type)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/companion/avatar/{kind}")
def get_companion_avatar(kind: str) -> Response:
    """读取当前登录账号自己的头像；未登录 401，未设置 404，不暴露他人文件。"""
    buyer_id, _ = _buyer()
    _avatar_kind(kind)
    try:
        found = store.get_companion_avatar(buyer_id, kind)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc
    if found is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "AVATAR_NOT_FOUND", "message": "还没有设置这个头像"},
        )
    data, media_type = found
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.delete("/companion/avatar/{kind}")
def delete_companion_avatar(kind: str) -> dict:
    """恢复默认头像（前端回退首字）。"""
    buyer_id, _ = _buyer()
    _avatar_kind(kind)
    try:
        return store.clear_companion_avatar(buyer_id, kind)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/merchant/products")
def merchant_products(keyword: str | None = None, limit: int = 20) -> dict:
    """真实商家商品查询（只读）。"""
    _buyer()
    try:
        repo = get_merchant_repository()
        products = repo.list_products(store_agent.STORE_MERCHANT_ID, keyword=keyword, limit=limit)
        payload = []
        for product in products:
            skus = repo.list_product_skus(product.product_id, merchant_id=store_agent.STORE_MERCHANT_ID)
            item = product.to_dict()
            if skus:
                inventory = repo.get_inventory(skus[0].sku, merchant_id=store_agent.STORE_MERCHANT_ID)
                item.update({
                    "sku": skus[0].sku,
                    "price": float(skus[0].price),
                    "stock": inventory.available_qty if inventory else 0,
                })
            payload.append(item)
        return {"source": "merchant_v1", "products": payload}
    except MerchantError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/merchant/inventory/{sku}")
def merchant_inventory(sku: str) -> dict:
    """真实商家 SKU 库存查询（只读）。"""
    _buyer()
    try:
        inventory = get_merchant_repository().get_inventory(
            sku, merchant_id=store_agent.STORE_MERCHANT_ID
        )
        if inventory is None:
            raise HTTPException(status_code=404, detail="没有找到这个 SKU")
        return {"source": "merchant_v1", "inventory": inventory.to_dict()}
    except MerchantError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/merchant/orders")
def merchant_orders(status: str | None = None, limit: int = 20) -> dict:
    """当前买家在真实商家库中的订单。"""
    buyer_id, _ = _buyer()
    try:
        orders = get_merchant_repository().list_orders(
            store_agent.STORE_MERCHANT_ID,
            buyer_id=store_agent.merchant_buyer_id(buyer_id),
            status=status,
            limit=limit,
        )
        return {"source": "merchant_v1", "orders": [order.to_dict() for order in orders]}
    except MerchantError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/merchant/orders/{order_id}")
def merchant_order_detail(order_id: str) -> dict:
    """当前买家的单笔真实商家订单。"""
    buyer_id, _ = _buyer()
    try:
        order = get_merchant_repository().get_order(
            order_id,
            merchant_id=store_agent.STORE_MERCHANT_ID,
            buyer_id=store_agent.merchant_buyer_id(buyer_id),
        )
        if order is None:
            raise HTTPException(status_code=404, detail="没有找到这笔订单")
        return {"source": "merchant_v1", "order": order.to_dict()}
    except MerchantError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/app/messages")
def list_app_messages(
    thread_id: str = "companion",
    limit: int = 50,
    before: str | None = None,
) -> dict:
    buyer_id, _ = _buyer()
    return {
        "messages": store.list_app_messages(buyer_id, thread_id, limit=limit, before=before)
    }


@router.delete("/app/messages")
def clear_app_messages(thread_id: str = "companion") -> dict:
    buyer_id, _ = _buyer()
    return {"deleted": store.clear_app_messages(buyer_id, thread_id)}


@router.post("/app/messages")
def save_app_message(req: AppMessageIn) -> dict:
    buyer_id, _ = _buyer()
    try:
        return store.save_app_message(
            buyer_id,
            req.thread_id,
            req.role,
            req.content,
            metadata=req.metadata,
        )
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/admin/reconciliation")
def admin_reconciliation(limit: int = 200) -> dict:
    """C 订单与商家订单对账（仅平台管理员）。"""
    _require_admin()
    return store.reconcile_orders(limit=limit)


@router.get("/admin/audit")
def c_end_admin_audit(
    limit: int = 50,
    offset: int = 0,
    buyer_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """C 端交易审计：跨买家订单/报价，支持买家/报价状态/自然日筛选与分页。

    status 是报价状态，同时作用于两张表：报价列表按 status 过滤，
    订单列表按订单关联的 c_quote.status 过滤；summary 仍只描述**当前页**，
    全量条数另由 orders_total / quotes_total 给出（两张表共用同一 limit/offset）。
    """
    _require_admin()
    if status and status.upper() not in {"PENDING", "CONSUMED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="报价状态不合法")
    orders = store.list_all_orders(
        limit=limit,
        offset=offset,
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    quotes = store.list_all_quotes(
        limit=limit,
        offset=offset,
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    orders_total = store.count_all_orders(
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    quotes_total = store.count_all_quotes(
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    status_counts: dict[str, int] = {}
    for quote in quotes:
        quote_status = str(quote.get("status") or "UNKNOWN")
        status_counts[quote_status] = status_counts.get(quote_status, 0) + 1
    return {
        "orders": orders,
        "quotes": quotes,
        "orders_total": orders_total,
        "quotes_total": quotes_total,
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
        "summary": {
            "order_count": len(orders),
            "gmv": round(sum(float(order.get("total_amount") or 0) for order in orders), 2),
            "quote_count": len(quotes),
            "quote_status": status_counts,
            "pending_quotes": status_counts.get("PENDING", 0),
        },
    }


@router.get("/admin/audit/export")
def c_end_admin_audit_export(
    limit: int = 50,
    buyer_id: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> Response:
    """C 端审计订单 CSV 导出（仅系统管理员）。

    - 筛选参数与 `/api/c/admin/audit` 一致，前端可原样复用；
    - `status`（报价状态）按订单关联的 c_quote.status 过滤，与列表同口径；
    - CSV 带 UTF-8 BOM，Excel 打开中文不乱码；路由是精确匹配，不与 `/quotes/{quote_id}` 冲突。
    """
    _require_admin()
    if status and status.upper() not in {"PENDING", "CONSUMED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="报价状态不合法")
    csv_text = store.export_audit_orders_csv(
        limit=limit,
        buyer_id=buyer_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )
    filename = f"c_end_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/quotes/{quote_id}")
def get_quote(quote_id: str) -> dict:
    buyer_id, _ = _buyer()
    try:
        quote = store.get_quote(quote_id, buyer_id)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc
    if quote is None:
        raise HTTPException(status_code=404, detail="报价不存在")
    return quote


@router.post("/quotes/{quote_id}/prepare")
def prepare_quote_order(quote_id: str) -> dict:
    buyer_id, _ = _buyer()
    try:
        return store.prepare_order(buyer_id, [], quote_id=quote_id)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.post("/quotes/{quote_id}/cancel")
def cancel_quote(quote_id: str) -> dict:
    buyer_id, _ = _buyer()
    try:
        return store.cancel_quote(quote_id, buyer_id)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.patch("/admin/merchant/orders/{order_id}/status")
def admin_update_merchant_order_status(order_id: str, req: MerchantOrderStatusIn) -> dict:
    """平台管理员模拟商家订单状态流转；真实 OMS 由商家侧回调替代。"""
    _require_admin()
    try:
        order = get_merchant_write_repository().update_order_status(
            store_agent.STORE_MERCHANT_ID,
            order_id,
            req.status,
            tracking_no=req.tracking_no,
            carrier=req.carrier,
        )
    except MerchantError as exc:
        code = getattr(exc, "code", "MERCHANT_ERROR")
        status = 404 if code == "MERCHANT_NOT_FOUND" else 409 if code in {
            "MERCHANT_CONFLICT",
            "MERCHANT_STOCK",
            "MERCHANT_EXPIRED",
        } else 400
        raise HTTPException(status_code=status, detail=exc.to_dict()) from exc
    return {"source": "merchant_v1", "order": order.to_dict()}


@router.get("/orders")
def list_orders(limit: int = 50) -> dict:
    buyer_id, _ = _buyer()
    return {"orders": store.list_orders(buyer_id, limit=limit)}


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, req: CancelOrderIn | None = None) -> dict:
    """取消订单：DRAFT 释放预占；CONFIRMED 走商家取消/模拟退款并恢复库存。"""
    buyer_id, _ = _buyer()
    try:
        order = store.get_order(order_id)
        if order is None:
            raise store.CStoreError("ORDER_NOT_FOUND", "订单不存在")
        if order["buyer_id"] != buyer_id:
            raise store.CStoreError("ORDER_FORBIDDEN", "不能取消其他用户的订单")
        if order["status"] == "DRAFT":
            return store.cancel_order_draft(buyer_id, order_id)
        return store.cancel_confirmed_order(
            buyer_id,
            order_id,
            request_id=req.request_id if req else None,
        )
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/friends")
def list_friends() -> dict:
    buyer_id, _ = _buyer()
    return {"friends": social.list_friends(buyer_id)}


@router.get("/friends/{friend_id}/messages")
def list_messages(friend_id: str, limit: int = 20, before: str | None = None) -> dict:
    """单聊历史消息：默认返回最近 20 条（时间正序）。

    before 是分页游标（`created_at|message_id`，也兼容只传 created_at），
    传入后返回该游标之前的一页；不传则返回最新一页。
    """
    buyer_id, _ = _buyer()
    try:
        return {
            "messages": social.get_messages(
                buyer_id, friend_id, limit=limit, before=before
            )
        }
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


def _send_store_message_once(
    buyer_id: str,
    friend_id: str,
    content: str,
    client_id: str | None,
) -> tuple[dict, bool]:
    """店宠消息的幂等包装；返回 (result, replay)。"""
    if not client_id:
        return social.send_message(
            buyer_id,
            friend_id,
            content,
            reply_provider=lambda text: store_agent.reply_with_meta(buyer_id, text),
            commentary_provider=lambda text, reply_text: companion_agent.commentary(
                buyer_id, text, reply_text
            ),
        ), False

    request_fingerprint = idempotency.fingerprint(content, friend_id)
    claim = idempotency.claim(
        client_id=client_id,
        owner_id=buyer_id,
        endpoint="c_store_send",
        request_fingerprint=request_fingerprint,
    )
    if claim["state"] == "replay":
        return dict(claim["response"]), True
    if claim["state"] == "in_progress":
        raise idempotency.IdempotencyConflict("同一条消息正在处理中，请勿重复发送")

    try:
        result = social.send_message(
            buyer_id,
            friend_id,
            content,
            reply_provider=lambda text: store_agent.reply_with_meta(buyer_id, text),
            commentary_provider=lambda text, reply_text: companion_agent.commentary(
                buyer_id, text, reply_text
            ),
        )
    except Exception:
        idempotency.release(
            client_id=client_id,
            owner_id=buyer_id,
            endpoint="c_store_send",
        )
        raise
    idempotency.complete(
        client_id=client_id,
        owner_id=buyer_id,
        endpoint="c_store_send",
        response=result,
    )
    return result, False


@router.post("/friends/{friend_id}/messages")
def send_message(friend_id: str, req: SendMessageIn) -> dict:
    buyer_id, _ = _buyer()
    client_id = (req.client_message_id or "").strip() or None
    if client_id and not _CLIENT_ID_RE.fullmatch(client_id):
        raise HTTPException(status_code=400, detail="client_message_id 格式不合法")
    try:
        result, replay = _send_store_message_once(buyer_id, friend_id, req.content, client_id)
        if replay:
            result["idempotent_replay"] = True
        return result
    except idempotency.IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.websocket("/ws/chat/{friend_id}")
async def chat_websocket(websocket: WebSocket, friend_id: str) -> None:
    token = websocket.cookies.get(auth.SESSION_COOKIE)
    account = auth.resolve_session(token) if token else None
    if account is None or account.get("status") != auth.STATUS_ACTIVE:
        await websocket.close(code=1008)
        return
    if account.get("is_demo"):
        await websocket.close(code=1008)
        return
    buyer_id = f"buyer_{account['id']}"
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            content = str(payload.get("content") or "")
            client_id = str(payload.get("client_message_id") or "").strip() or None
            if client_id and not _CLIENT_ID_RE.fullmatch(client_id):
                await websocket.send_json({
                    "type": "error",
                    "error": {"code": "INVALID_CLIENT_MESSAGE_ID", "message": "client_message_id 格式不合法"},
                })
                continue
            try:
                result, replay = await asyncio.to_thread(
                    _send_store_message_once,
                    buyer_id,
                    friend_id,
                    content,
                    client_id,
                )
                if replay:
                    result["idempotent_replay"] = True
                await websocket.send_json({"type": "chat", **result})
            except idempotency.IdempotencyConflict as exc:
                await websocket.send_json({
                    "type": "error",
                    "error": {"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)},
                })
            except store.CStoreError as exc:
                await websocket.send_json({
                    "type": "error",
                    "error": {"code": exc.code, "message": exc.message},
                })
    except WebSocketDisconnect:
        return


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


@router.get("/orders/{order_id}/after-sales")
def list_order_after_sales(order_id: str) -> dict:
    buyer_id, _ = _buyer()
    order = store.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order["buyer_id"] != buyer_id:
        raise HTTPException(status_code=403, detail="不能查看其他用户的订单")
    return {"tickets": store.list_after_sales(buyer_id, order_id=order_id)}


@router.post("/orders/{order_id}/after-sales")
def create_order_after_sale(order_id: str, req: AfterSaleIn) -> dict:
    buyer_id, _ = _buyer()
    try:
        return store.create_after_sale(
            buyer_id,
            order_id,
            sale_type=req.type,
            reason=req.reason,
        )
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/admin/after-sales")
def admin_after_sales(status: str | None = None, limit: int = 100) -> dict:
    _require_admin()
    tickets = store.list_after_sales(limit=limit)
    if status:
        expected = status.upper()
        tickets = [ticket for ticket in tickets if ticket["status"] == expected]
    return {"tickets": tickets}


@router.patch("/admin/after-sales/{ticket_id}")
def admin_resolve_after_sale(ticket_id: str, req: AfterSaleResolveIn) -> dict:
    _require_admin()
    try:
        return store.resolve_after_sale(ticket_id, approved=req.approved)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.post("/agent/run")
def c_agent_run(req: CAgentRunIn) -> dict:
    buyer_id, _ = _buyer()
    client_id = (req.client_message_id or "").strip() or None
    if client_id and not _CLIENT_ID_RE.fullmatch(client_id):
        raise HTTPException(status_code=400, detail="client_message_id 格式不合法")
    thread_id = (req.thread_id or "").strip() or f"c_thread_{uuid.uuid4().hex[:16]}"
    if not _THREAD_RE.fullmatch(thread_id):
        raise HTTPException(status_code=400, detail="thread_id 格式不合法")

    request_fingerprint = idempotency.fingerprint(req.message, req.thread_id)
    if client_id:
        try:
            claim = idempotency.claim(
                client_id=client_id,
                owner_id=buyer_id,
                endpoint="c_agent_run",
                request_fingerprint=request_fingerprint,
            )
        except idempotency.IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if claim["state"] == "replay":
            replay = dict(claim["response"])
            replay["idempotent_replay"] = True
            return replay
        if claim["state"] == "in_progress":
            raise HTTPException(status_code=409, detail="同一条消息正在处理中，请勿重复发送")

    try:
        result = c_agent.run_c_agent(
            req.message.strip(),
            buyer_id=buyer_id,
            thread_id=thread_id,
            checkpointer=get_checkpointer(),
        )
    except ValueError as exc:
        if client_id:
            idempotency.release(client_id=client_id, owner_id=buyer_id, endpoint="c_agent_run")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        if client_id:
            idempotency.release(client_id=client_id, owner_id=buyer_id, endpoint="c_agent_run")
        raise HTTPException(status_code=502, detail=f"C 端 Agent 运行失败：{exc}") from exc

    response = {
        "thread_id": thread_id,
        "status": result["status"],
        "interrupted": result["interrupted"],
        "requires_confirmation": result["interrupted"],
        "draft": result["draft"],
        "order": result["order"],
        # 模型输出统一过 persona guard；确认/取消文案由代码生成，不走这里。
        "reply": c_persona.guard(_last_ai_text(result["messages"]), tier="L2").text
        if _last_ai_text(result["messages"])
        else "",
    }
    if client_id:
        idempotency.complete(
            client_id=client_id,
            owner_id=buyer_id,
            endpoint="c_agent_run",
            response=response,
        )
    return response


@router.post("/agent/resume")
def c_agent_resume(req: CAgentResumeIn) -> dict:
    buyer_id, _ = _buyer()
    thread_id = req.thread_id.strip()
    if not _THREAD_RE.fullmatch(thread_id):
        raise HTTPException(status_code=400, detail="thread_id 格式不合法")
    try:
        result = c_agent.resume_c_agent(
            buyer_id=buyer_id,
            thread_id=thread_id,
            approved=req.approved,
            checkpointer=get_checkpointer(),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"C 端 Agent 恢复失败：{exc}") from exc
    return {
        "thread_id": thread_id,
        "status": result["status"],
        "interrupted": result["interrupted"],
        "order": result["order"],
        "reply": _last_ai_text(result["messages"]),
    }


def register_c_end(app) -> None:
    app.include_router(router)
