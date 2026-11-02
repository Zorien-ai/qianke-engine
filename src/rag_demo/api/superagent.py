"""Super-agent HTTP API：事件入口、Thread/WorkItem、审批、Watchdog。"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.c_end import store as c_store
from rag_demo.superagent import approval_card as sa_approval_card
from rag_demo.superagent import router as sa_router
from rag_demo.superagent import runtime as sa_runtime
from rag_demo.superagent import store as sa_store
from rag_demo.superagent import triggers as sa_triggers
from rag_demo.superagent import watchdog as sa_watchdog
from rag_demo.superagent import wecom as sa_wecom
from rag_demo.superagent import wecom_approval as sa_wecom_approval
from rag_demo.superagent import wecom_send as sa_wecom_send

router = APIRouter(prefix="/api/superagent", tags=["superagent"])
logger = logging.getLogger(__name__)
_WECOM_SEEN: set[str] = set()
_WECOM_LOCK = threading.Lock()


class EventIn(BaseModel):
    source: str = Field(default="manual", max_length=64)
    content: str = Field(..., min_length=1, max_length=4000)
    channel: str = Field(default="manual", max_length=64)
    thread_key: str | None = Field(default=None, max_length=160)
    merchant_id: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_run: bool = False


class BatchEventIn(BaseModel):
    events: list[EventIn] = Field(..., min_length=1, max_length=50)


class ApproveIn(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=1000)
    action_params: dict[str, Any] = Field(default_factory=dict)


class WatchdogIn(BaseModel):
    timeout_seconds: int = Field(default=180, ge=10, le=3600)


def _account() -> dict[str, Any]:
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号不可用")
    if not account.get("is_system_admin"):
        if c_store.get_merchant_member(account["id"]) is None:
            raise HTTPException(status_code=403, detail="当前账号没有 Super-agent 权限")
    return account


def _tenant_scope(account: dict[str, Any]) -> str | None:
    """系统管理员可跨租户；商家账号只能看绑定商家。"""
    if account.get("is_system_admin"):
        return None
    member = c_store.get_merchant_member(account["id"])
    if member is None:
        raise HTTPException(status_code=403, detail="账号未绑定商家")
    return str(member["merchant_id"])


def _resolve_merchant(account: dict[str, Any], requested: str | None) -> str:
    scope = _tenant_scope(account)
    if scope is not None:
        if requested and requested != scope:
            raise HTTPException(status_code=403, detail="不能访问其他商家的数据")
        return scope
    return requested or sa_store.DEFAULT_MERCHANT_ID


def _scoped_item(work_item_id: str, account: dict[str, Any]) -> dict[str, Any]:
    item = sa_store.get_work_item(work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="工作项不存在")
    scope = _tenant_scope(account)
    if scope is not None and item.get("merchant_id") != scope:
        raise HTTPException(status_code=404, detail="工作项不存在")
    return item


def _start(work_item_id: str) -> None:
    if not sa_runtime.start_worker(work_item_id):
        raise HTTPException(status_code=409, detail="工作项已经在运行")


@router.post("/events")
async def ingest_event(req: EventIn) -> dict[str, Any]:
    account = _account()
    merchant_id = _resolve_merchant(account, req.merchant_id)
    try:
        result = sa_router.ingest_event(
            source=req.source,
            content=req.content,
            channel=req.channel,
            thread_key=req.thread_key,
            merchant_id=merchant_id,
            metadata=req.metadata,
        )
    except sa_store.store.CStoreError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc
    if result.get("accepted") and req.auto_run and result.get("work_item"):
        item = result["work_item"]
        if item["status"] == "PENDING":
            _start(item["work_item_id"])
            result["auto_run_started"] = True
    return result


@router.post("/events/batch")
def ingest_event_batch(req: BatchEventIn) -> dict[str, Any]:
    """批量事件：Router 一次处理多条 Trigger，同一 Thread 只建一个 WorkItem。"""
    account = _account()
    payload = [event.model_dump() for event in req.events]
    for event in payload:
        event.pop("auto_run", None)
        event["merchant_id"] = _resolve_merchant(account, event.get("merchant_id"))
    return sa_router.ingest_batch(payload)


@router.post("/webhooks/{provider}")
async def inbound_webhook(provider: str, request: Request) -> dict[str, Any]:
    """通用 IM/外部事件入口；用共享密钥保护，供企业微信/飞书中转调用。"""
    provided = request.headers.get("X-Superagent-Secret")
    if not sa_triggers.verify_webhook_secret(provided):
        raise HTTPException(status_code=401, detail="Webhook 密钥未配置或不正确")
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="请求体必须是 JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求体必须是对象")
    content = str(body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content 不能为空")
    return sa_triggers.ingest_async(
        source=f"webhook:{provider[:32]}",
        content=content,
        channel=str(body.get("channel") or provider)[:64],
        thread_key=str(body.get("thread_key") or "").strip() or None,
        merchant_id=str(body.get("merchant_id") or "").strip() or None,
        metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
    )


@router.get("/threads")
def list_threads(limit: int = 50, merchant_id: str | None = None) -> dict[str, Any]:
    account = _account()
    scope = _tenant_scope(account)
    target = scope or merchant_id
    return {"threads": sa_store.list_threads(limit=limit, merchant_id=target)}


@router.get("/work-items")
def list_work_items(limit: int = 50, merchant_id: str | None = None) -> dict[str, Any]:
    account = _account()
    scope = _tenant_scope(account)
    target = scope or merchant_id
    return {"work_items": sa_store.list_work_items(limit=limit, merchant_id=target)}


@router.get("/jobs")
def list_jobs(limit: int = 50) -> dict[str, Any]:
    account = _account()
    if _tenant_scope(account) is not None:
        raise HTTPException(status_code=403, detail="只有系统管理员可以查看全局队列")
    return {"jobs": sa_store.list_jobs(limit=limit)}


@router.get("/work-items/{work_item_id}")
def get_work_item(work_item_id: str) -> dict[str, Any]:
    account = _account()
    return _scoped_item(work_item_id, account)


@router.post("/work-items/{work_item_id}/run")
async def run_work_item(work_item_id: str) -> dict[str, Any]:
    account = _account()
    item = _scoped_item(work_item_id, account)
    if item["status"] != "PENDING":
        raise HTTPException(status_code=409, detail=f"工作项当前状态为 {item['status']}，不能启动")
    sa_store.start_work_item(work_item_id)
    _start(work_item_id)
    return {"work_item_id": work_item_id, "status": "RUNNING", "started": True}


@router.post("/work-items/{work_item_id}/stop")
def stop_work_item(work_item_id: str) -> dict[str, Any]:
    account = _account()
    item = _scoped_item(work_item_id, account)
    if item["status"] not in ("PENDING", "RUNNING"):
        raise HTTPException(status_code=409, detail=f"工作项当前状态为 {item['status']}，不能停止")
    updated = sa_runtime.stop_worker(work_item_id)
    return {"work_item_id": work_item_id, "status": updated.get("status"), "stopped": True}


@router.post("/work-items/{work_item_id}/approve")
def approve_work_item(work_item_id: str, req: ApproveIn) -> dict[str, Any]:
    account = _account()
    item = _scoped_item(work_item_id, account)
    if item["status"] != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail="工作项不在待审批状态")
    if not req.approved:
        rejected = sa_store.decide_approval(work_item_id, approved=False, note=req.note)
        sa_wecom_send.notify_work_item(rejected, stage="REJECTED")
        return rejected
    if req.action_params:
        try:
            sa_store.update_approval_action(work_item_id, req.action_params)
        except sa_store.store.CStoreError as exc:
            raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc
    approval = sa_store.get_approval(work_item_id) or {}
    action = approval.get("action") or (item.get("result") or {}).get("action") or {}
    action_type = str(action.get("action_type") or "").upper()
    sale_type = str(action.get("sale_type") or "").upper()
    if action_type == "CREATE_AFTER_SALE" and sale_type not in {"REFUND_ONLY", "RETURN_REFUND"}:
        raise HTTPException(
            status_code=400,
            detail="售后动作需要 action_params.sale_type：REFUND_ONLY 或 RETURN_REFUND",
        )
    decided = sa_store.decide_approval(work_item_id, approved=True, note=req.note)
    if not sa_runtime.start_action(work_item_id):
        raise HTTPException(status_code=409, detail="动作执行任务已存在")
    return {**decided, "execution_pending": True}


@router.get("/approval-card/{work_item_id}", response_class=HTMLResponse)
def approval_card_page(work_item_id: str, token: str = Query(...)) -> HTMLResponse:
    """企业微信卡片点击打开的无登录审批页；只靠签名 token 鉴权。"""
    ok, error = sa_approval_card.verify_token(work_item_id, token)
    if not ok:
        return HTMLResponse(sa_approval_card.render_result("审批链接无效", error), status_code=403)
    item = sa_store.get_work_item(work_item_id)
    if item is None:
        return HTMLResponse(sa_approval_card.render_result("工作项不存在", "请回到企业微信重新发起。"), status_code=404)
    if item.get("status") != "WAITING_APPROVAL":
        return HTMLResponse(
            sa_approval_card.render_result("无需审批", f"当前状态：{item.get('status')}"),
            status_code=409,
        )
    return HTMLResponse(sa_approval_card.render_page(item, token))


@router.post("/approval-card/{work_item_id}", response_class=HTMLResponse)
async def approval_card_submit(work_item_id: str, request: Request) -> HTMLResponse:
    form = await request.form()
    token = str(form.get("token") or "")
    decision = str(form.get("decision") or "")
    ok, error = sa_approval_card.verify_token(work_item_id, token)
    if not ok:
        return HTMLResponse(sa_approval_card.render_result("审批链接无效", error), status_code=403)
    success, message = sa_approval_card.approve_from_card(
        work_item_id,
        decision=decision,
        tracking_no=str(form.get("tracking_no") or ""),
        carrier=str(form.get("carrier") or ""),
    )
    if success:
        return HTMLResponse(sa_approval_card.render_result("审批已提交", message))
    item = sa_store.get_work_item(work_item_id)
    if item is None:
        return HTMLResponse(sa_approval_card.render_result("审批失败", message), status_code=409)
    return HTMLResponse(sa_approval_card.render_page(item, token, error=message), status_code=409)


@router.post("/watchdog")
def watchdog(req: WatchdogIn) -> dict[str, Any]:
    account = _account()
    if _tenant_scope(account) is not None:
        raise HTTPException(status_code=403, detail="只有系统管理员可以执行全局 Watchdog")
    stuck = sa_store.scan_stuck_work_items(timeout_seconds=req.timeout_seconds)
    return {"stuck_count": len(stuck), "work_items": stuck}


def _wecom_crypto() -> sa_wecom.WeComCrypto:
    token, aes_key, corp_id = sa_wecom.config_from_env()
    if not token or not aes_key:
        raise HTTPException(status_code=503, detail="企业微信回调未配置 token / EncodingAESKey")
    try:
        return sa_wecom.WeComCrypto(token, aes_key, corp_id)
    except sa_wecom.WeComCryptoError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/wecom/callback", response_class=PlainTextResponse)
def wecom_callback_verify(
    msg_signature: str = Query(..., alias="msg_signature"),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
) -> str:
    """企业微信回调 URL 验证：验签并返回解密后的 echostr。"""
    crypto = _wecom_crypto()
    if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
        raise HTTPException(status_code=403, detail="企业微信签名不合法")
    try:
        return crypto.decrypt(echostr)
    except sa_wecom.WeComCryptoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wecom/callback", response_class=PlainTextResponse)
async def wecom_callback_message(
    request: Request,
    msg_signature: str = Query(..., alias="msg_signature"),
    timestamp: str = Query(...),
    nonce: str = Query(...),
) -> str:
    """企业微信消息回调：验签 → 解密 → 去重 → 生成 Super-agent Trigger。"""
    crypto = _wecom_crypto()
    raw = (await request.body()).decode("utf-8", errors="replace")
    try:
        root_encrypt = ""
        try:
            import xml.etree.ElementTree as ET

            root_encrypt = ET.fromstring(raw).findtext("Encrypt") or ""
        except Exception:  # noqa: BLE001
            raise sa_wecom.WeComCryptoError("企业微信 XML 解析失败")
        if not crypto.verify_signature(msg_signature, timestamp, nonce, root_encrypt):
            raise HTTPException(status_code=403, detail="企业微信签名不合法")
        plain = crypto.decrypt(root_encrypt)
        message = sa_wecom.parse_message(plain)
        msg_id = str(message.get("MsgId") or "")
        if msg_id:
            with _WECOM_LOCK:
                if msg_id in _WECOM_SEEN:
                    return "success"
                _WECOM_SEEN.add(msg_id)
                if len(_WECOM_SEEN) > 5000:
                    _WECOM_SEEN.clear()
        if sa_wecom_approval.handle_message(message):
            return "success"
        event = sa_wecom.message_to_event(message)
        if event is not None:
            event["merchant_id"] = (
                os.environ.get("QIANKE_WECOM_MERCHANT_ID") or sa_store.DEFAULT_MERCHANT_ID
            )
            sa_triggers.ingest_async(**event)
        return "success"
    except HTTPException:
        raise
    except sa_wecom.WeComCryptoError as exc:
        logger.warning("企业微信回调处理失败: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def register_superagent(app) -> None:
    # 主应用使用 lifespan；on_startup/on_event 在这个 FastAPI 版本不会被执行。
    # 常驻 Watchdog 是独立 daemon 线程，在注册 API 时启动，测试环境由 env 关闭。
    if sa_watchdog.enabled():
        sa_watchdog.start()
    sa_runtime.start_dispatcher()
    app.include_router(router)
