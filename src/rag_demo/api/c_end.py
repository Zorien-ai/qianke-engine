"""C 端商品浏览与模拟订单 HTTP API。"""
from __future__ import annotations

import asyncio
import re
import uuid

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.agent.checkpoint import get_checkpointer
from rag_demo.c_end import agent as c_agent
from rag_demo.c_end import companion_agent, social, store, store_agent

router = APIRouter(prefix="/api/c", tags=["c-end"])
_THREAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


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


class CAgentRunIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    thread_id: str | None = Field(default=None, max_length=128)


class CAgentResumeIn(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=128)
    approved: bool


class CompanionPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=20)
    species: str | None = Field(default=None, max_length=60)
    persona: str | None = Field(default=None, max_length=60)
    appearance: str | None = Field(default=None, max_length=60)


class SendMessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)


def _last_ai_text(messages: list) -> str:
    for msg in reversed(messages or []):
        if getattr(msg, "content", None) and getattr(msg, "type", "") == "ai":
            return str(msg.content)
    return ""


def _http_error(exc: store.CStoreError) -> HTTPException:
    status = 409 if exc.code in {
        "INSUFFICIENT_STOCK",
        "ORDER_CHANGED",
        "ORDER_NOT_DRAFT",
        "INVALID_CONFIRMATION",
        "ORDER_FORBIDDEN",
        "IDEMPOTENCY_CONFLICT",
        "QUOTE_FORBIDDEN",
        "QUOTE_NOT_PENDING",
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
            species=req.species,
            persona=req.persona,
            appearance=req.appearance,
        )
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


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


@router.get("/orders")
def list_orders(limit: int = 50) -> dict:
    buyer_id, _ = _buyer()
    return {"orders": store.list_orders(buyer_id, limit=limit)}


@router.post("/orders/{draft_id}/cancel")
def cancel_order_draft(draft_id: str) -> dict:
    buyer_id, _ = _buyer()
    try:
        return store.cancel_order_draft(buyer_id, draft_id)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/friends")
def list_friends() -> dict:
    buyer_id, _ = _buyer()
    return {"friends": social.list_friends(buyer_id)}


@router.get("/friends/{friend_id}/messages")
def list_messages(friend_id: str, limit: int = 50) -> dict:
    buyer_id, _ = _buyer()
    try:
        return {"messages": social.get_messages(buyer_id, friend_id, limit=limit)}
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.post("/friends/{friend_id}/messages")
def send_message(friend_id: str, req: SendMessageIn) -> dict:
    buyer_id, _ = _buyer()
    try:
        return social.send_message(
            buyer_id,
            friend_id,
            req.content,
            reply_provider=lambda text: store_agent.reply_with_meta(buyer_id, text),
            commentary_provider=lambda text, reply_text: companion_agent.commentary(
                buyer_id, text, reply_text
            ),
        )
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
            try:
                result = await asyncio.to_thread(
                    social.send_message,
                    buyer_id,
                    friend_id,
                    content,
                    reply_provider=lambda text: store_agent.reply_with_meta(buyer_id, text),
                    commentary_provider=lambda text, reply_text: companion_agent.commentary(
                        buyer_id, text, reply_text
                    ),
                )
                await websocket.send_json({"type": "chat", **result})
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


@router.post("/agent/run")
def c_agent_run(req: CAgentRunIn) -> dict:
    buyer_id, _ = _buyer()
    thread_id = (req.thread_id or "").strip() or f"c_thread_{uuid.uuid4().hex[:16]}"
    if not _THREAD_RE.fullmatch(thread_id):
        raise HTTPException(status_code=400, detail="thread_id 格式不合法")
    try:
        result = c_agent.run_c_agent(
            req.message.strip(),
            buyer_id=buyer_id,
            thread_id=thread_id,
            checkpointer=get_checkpointer(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"C 端 Agent 运行失败：{exc}") from exc
    return {
        "thread_id": thread_id,
        "status": result["status"],
        "interrupted": result["interrupted"],
        "requires_confirmation": result["interrupted"],
        "draft": result["draft"],
        "order": result["order"],
        "reply": _last_ai_text(result["messages"]),
    }


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
