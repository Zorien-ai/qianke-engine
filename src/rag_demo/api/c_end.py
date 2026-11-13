"""C 端商品浏览与模拟订单 HTTP API。"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.agent.checkpoint import get_checkpointer
from rag_demo.c_end import agent as c_agent
from rag_demo.c_end import companion_agent, express, group, idempotency, memory_daily, negotiation, persona as c_persona, social, store, store_agent
from rag_demo.merchant import MerchantConflictError, MerchantError, MerchantNotFoundError, get_merchant_repository, get_merchant_write_repository

router = APIRouter(prefix="/api/c", tags=["c-end"])
logger = logging.getLogger(__name__)
_THREAD_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
_AVATAR_KIND_RE = re.compile(r"^(companion|user)$")


def _maybe_superagent_trigger(
    *,
    buyer_id: str,
    content: str,
    channel: str,
    thread_key: str,
) -> None:
    """聊天消息进入 Super-agent；默认关闭，失败绝不阻塞聊天。"""
    try:
        from rag_demo.superagent import triggers as sa_triggers

        sa_triggers.maybe_trigger_capp(
            buyer_id=buyer_id,
            content=content,
            channel=channel,
            thread_key=thread_key,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Super-agent 聊天 Trigger 失败 channel=%s", channel)


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


class ReturnShipmentIn(BaseModel):
    tracking_no: str = Field(..., min_length=1, max_length=64)
    carrier: str | None = Field(default=None, max_length=64)


class AfterSaleReceiveIn(BaseModel):
    accepted: bool


class CAgentRunIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    thread_id: str | None = Field(default=None, max_length=128)
    client_message_id: str | None = Field(default=None, max_length=128)
    mode: str | None = Field(default=None, pattern="^(companion|advisor|order|transaction)$")


class CAgentResumeIn(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=128)
    approved: bool


class DiaryPatchIn(BaseModel):
    enabled: bool


class MerchantStoreFriendIn(BaseModel):
    merchant_id: str = Field(..., min_length=1, max_length=80)
    friend_id: str = Field(..., min_length=1, max_length=80)


class MerchantFriendIn(BaseModel):
    merchant_id: str = Field(..., min_length=1, max_length=80)


class MerchantSopIn(BaseModel):
    merchant_id: str = Field(..., min_length=1, max_length=80)
    topic: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=80)
    content: str = Field(..., min_length=1, max_length=1000)


class CompanionPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=12)
    user_nickname: str | None = Field(default=None, max_length=12)
    species: str | None = Field(default=None, max_length=60)
    persona: str | None = Field(default=None, max_length=60)
    appearance: str | None = Field(default=None, max_length=60)


class RhythmPatchIn(BaseModel):
    enabled: bool | None = None
    quiet_start: str | None = Field(default=None, pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    quiet_end: str | None = Field(default=None, pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    pause_hours: int | None = Field(default=None, ge=0, le=720)


class LogisticsSignedIn(BaseModel):
    event_id: str = Field(pattern="^[A-Za-z0-9_.:-]{8,128}$")
    provider: str = Field(default="", max_length=40)
    order_id: str = Field(pattern="^[A-Za-z0-9_-]{1,128}$")
    status: str = Field(default="SIGNED", max_length=20)
    occurred_at: str | None = Field(default=None, max_length=40)
    tracking_no: str | None = Field(default=None, max_length=64)
    carrier: str | None = Field(default=None, max_length=64)


class SendMessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)
    client_message_id: str | None = Field(default=None, max_length=128)


class MerchantOrderStatusIn(BaseModel):
    status: str = Field(..., pattern="^(PAID|SHIPPED|COMPLETED|CANCELLED)$")
    tracking_no: str | None = Field(default=None, max_length=64)
    carrier: str | None = Field(default=None, max_length=64)


class NegotiationItemIn(BaseModel):
    sku: str = Field(..., min_length=1, max_length=128)
    quantity: int = Field(default=1, ge=1, le=20)


class NegotiationIn(BaseModel):
    need: str = Field(..., min_length=1, max_length=80)
    budget: float = Field(..., gt=0, le=100000)
    quantity: int = Field(default=1, ge=1, le=20)
    friend_id: str | None = Field(default=None, max_length=80)
    sku: str | None = Field(default=None, max_length=128)
    items: list[NegotiationItemIn] | None = Field(default=None, max_length=10)


class AppMessageIn(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(..., pattern="^(user|companion|assistant|system)$")
    content: str = Field(..., min_length=1, max_length=2000)
    metadata: dict = Field(default_factory=dict)


class GroupCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    member_ids: list[str] = Field(default_factory=list, max_length=20)


class GroupMessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=1000)


def _last_ai_text(messages: list) -> str:
    for msg in reversed(messages or []):
        if getattr(msg, "content", None) and getattr(msg, "type", "") == "ai":
            return str(msg.content)
    return ""


def _http_error(exc: store.CStoreError) -> HTTPException:
    if exc.code == "AVATAR_TOO_LARGE":
        status = 413
    elif exc.code in {"AVATAR_NOT_FOUND", "AFTER_SALE_NOT_FOUND", "ORDER_NOT_FOUND", "GROUP_NOT_FOUND"}:
        status = 404
    elif exc.code in {"AFTER_SALE_FORBIDDEN", "ORDER_FORBIDDEN", "GROUP_FORBIDDEN"}:
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
            "AFTER_SALE_NOT_RETURNABLE",
        } else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


@router.post("/negotiations")
def negotiate(req: NegotiationIn) -> dict:
    """C 伙伴与商家店宠的受控谈判；只生成 PENDING 报价，不自动下单。"""
    buyer_id, _ = _buyer()
    try:
        if req.friend_id and store.merchant_for_store_friend(req.friend_id) is None:
            raise HTTPException(status_code=404, detail="店宠不存在或未绑定商家")
        return negotiation.run_negotiation(
            buyer_id,
            need=req.need,
            budget=req.budget,
            quantity=req.quantity,
            friend_id=req.friend_id,
            sku=req.sku,
            items=[item.model_dump() for item in req.items] if req.items else None,
        )
    except negotiation.NegotiationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


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


@router.get("/companion/memories")
def list_companion_memories() -> dict:
    buyer_id, _ = _buyer()
    companion = store.get_companion(buyer_id)
    return {
        "memories": store.list_memories(buyer_id, limit=20),
        "digests": store.list_memory_digests(buyer_id, limit=5),
        "diary_enabled": bool(companion.get("diary_enabled")),
    }


@router.get("/companion/diary")
def list_companion_diary(limit: int = 30) -> dict:
    buyer_id, _ = _buyer()
    return {
        "enabled": store.get_diary_enabled(buyer_id),
        "diaries": store.list_diaries(buyer_id, limit=limit),
    }


@router.patch("/companion/diary")
def update_companion_diary(req: DiaryPatchIn) -> dict:
    buyer_id, _ = _buyer()
    companion = store.set_diary_enabled(buyer_id, req.enabled)
    return {"enabled": bool(companion.get("diary_enabled")), "companion": companion}


@router.post("/companion/diary/run")
def run_companion_daily() -> dict:
    """手动执行当前用户当天任务；定时任务默认仍由脚本/cron 驱动。"""
    buyer_id, _ = _buyer()
    day = datetime.now(memory_daily.LOCAL_TZ).date().isoformat()
    return memory_daily.run_daily(buyer_id, day)


@router.get("/companion/rhythm")
def get_companion_rhythm() -> dict:
    buyer_id, _ = _buyer()
    return store.get_rhythm(buyer_id)


@router.patch("/companion/rhythm")
def update_companion_rhythm(req: RhythmPatchIn) -> dict:
    buyer_id, _ = _buyer()
    try:
        return store.update_rhythm(
            buyer_id,
            enabled=req.enabled,
            quiet_start=req.quiet_start,
            quiet_end=req.quiet_end,
            pause_hours=req.pause_hours,
        )
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.post("/companion/checkin")
def poll_companion_checkin() -> dict:
    """用户打开 App 时领取一条站内回访；默认关闭，免打扰与频率在服务端兜底。"""
    buyer_id, _ = _buyer()
    checkin = store.claim_due_checkin(buyer_id)
    if checkin is None:
        return {"checkin": None}
    store.save_app_message(
        buyer_id,
        "companion",
        "companion",
        checkin["content"],
        {"checkin_id": checkin["checkin_id"], "kind": checkin["kind"]},
    )
    return {"checkin": checkin}


_LOGISTICS_SIGNED_STATUSES = {"SIGNED", "DELIVERED", "COMPLETED"}


def _valid_logistics_signature(raw: bytes, timestamp: str | None, signature: str | None) -> bool:
    secret = (os.environ.get("QIANKE_LOGISTICS_WEBHOOK_SECRET") or "").strip()
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - ts) > 300:
        return False
    provided = signature[7:] if signature.startswith("sha256=") else signature
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("utf-8") + raw,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


@router.post("/webhooks/logistics/signed")
async def logistics_signed_callback(request: Request) -> dict:
    """物流签收回调：只接受 SIGNED/DELIVERED/COMPLETED，HMAC 验签 + 事件幂等。

    这是供应商无关的接入点；真实物流需要把“已签收”事件转发到这里。
    未配置 QIANKE_LOGISTICS_WEBHOOK_SECRET 时直接拒绝，不会静默放行。
    """
    secret = (os.environ.get("QIANKE_LOGISTICS_WEBHOOK_SECRET") or "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail={"code": "LOGISTICS_WEBHOOK_DISABLED", "message": "物流回调未配置密钥"},
        )
    raw = await request.body()
    if not _valid_logistics_signature(
        raw,
        request.headers.get("X-Qianke-Timestamp"),
        request.headers.get("X-Qianke-Signature"),
    ):
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_SIGNATURE", "message": "物流回调签名无效或已过期"},
        )
    try:
        payload = LogisticsSignedIn.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001 - 回调体不合法统一 400
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_LOGISTICS_EVENT", "message": "物流回调体不合法"},
        ) from exc
    status = payload.status.strip().upper()
    if status not in _LOGISTICS_SIGNED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail={"code": "NOT_SIGNED_EVENT", "message": "只接受已签收事件，运输中事件请忽略"},
        )

    existing = store.get_logistics_event(payload.event_id)
    if existing is not None:
        if existing["order_id"] != payload.order_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "EVENT_CONFLICT", "message": "event_id 已用于其他订单"},
            )
        return {"ok": True, "duplicate": True, "order_id": payload.order_id, "status": "COMPLETED"}

    merchant_id = store._MERCHANT_ID
    try:
        merchant_order = get_merchant_repository().get_order(
            payload.order_id,
            merchant_id=merchant_id,
        )
    except MerchantError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "MERCHANT_UNAVAILABLE", "message": "商家订单读取失败"},
        ) from exc
    if merchant_order is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ORDER_NOT_FOUND", "message": "订单不存在"},
        )
    if str(merchant_order.status).upper() in {"CANCELLED", "REFUNDED"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "ORDER_NOT_SIGNABLE", "message": "已取消/已退款订单不能签收"},
        )
    if str(merchant_order.status).upper() != "COMPLETED":
        try:
            get_merchant_write_repository().update_order_status(
                merchant_id,
                payload.order_id,
                "COMPLETED",
            )
        except MerchantConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "ORDER_STATUS_CONFLICT", "message": "订单当前状态不能签收"},
            ) from exc
        except MerchantNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "ORDER_NOT_FOUND", "message": "订单不存在"},
            ) from exc
        except MerchantError as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "MERCHANT_UNAVAILABLE", "message": "商家订单更新失败"},
            ) from exc

    buyer_id = store.get_c_order_buyer(payload.order_id)
    followup_scheduled = False
    if buyer_id:
        try:
            followup_scheduled = store.schedule_order_followup(buyer_id, payload.order_id) is not None
        except Exception:  # noqa: BLE001 - 回访失败不能影响物流签收主链路
            logger.warning("物流签收后安排回访失败 order=%s", payload.order_id, exc_info=True)

    store.record_logistics_event(
        event_id=payload.event_id,
        provider=payload.provider,
        order_id=payload.order_id,
        status=status,
        occurred_at=payload.occurred_at,
        payload_hash=hashlib.sha256(raw).hexdigest(),
    )
    logger.info("物流签收成功 order=%s event=%s", payload.order_id, payload.event_id)
    return {
        "ok": True,
        "duplicate": False,
        "order_id": payload.order_id,
        "status": "COMPLETED",
        "followup_scheduled": followup_scheduled,
    }


@router.delete("/companion/memories/{memory_id}")
def delete_companion_memory(memory_id: str) -> dict:
    buyer_id, _ = _buyer()
    return {"deleted": store.delete_memory(buyer_id, memory_id)}


@router.delete("/companion/memories")
def clear_companion_memories() -> dict:
    buyer_id, _ = _buyer()
    return {"deleted": store.clear_memories(buyer_id)}


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
def merchant_products(
    keyword: str | None = None,
    limit: int = 20,
    friend_id: str | None = None,
) -> dict:
    """真实商家商品查询（只读）；可从店宠会话 friend_id 解析商家。"""
    _buyer()
    resolved_merchant = store_agent.resolve_merchant_id(friend_id=friend_id)
    try:
        repo = get_merchant_repository()
        products = repo.list_products(resolved_merchant, keyword=keyword, limit=limit)
        payload = []
        for product in products:
            skus = repo.list_product_skus(product.product_id, merchant_id=resolved_merchant)
            item = product.to_dict()
            sku_payload = []
            for sku in skus:
                inventory = repo.get_inventory(sku.sku, merchant_id=resolved_merchant)
                sku_payload.append({
                    "sku": sku.sku,
                    "spec": sku.spec,
                    "price": float(sku.price),
                    "stock": inventory.available_qty if inventory else 0,
                    "reserved_qty": inventory.reserved_qty if inventory else 0,
                    "in_stock": inventory.in_stock if inventory else False,
                })
            item["skus"] = sku_payload
            if sku_payload:
                item.update({
                    "sku": sku_payload[0]["sku"],
                    "price": sku_payload[0]["price"],
                    "stock": sku_payload[0]["stock"],
                })
            payload.append(item)
        return {"source": "merchant_v1", "products": payload}
    except MerchantError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/merchant/inventory/{sku}")
def merchant_inventory(sku: str, friend_id: str | None = None) -> dict:
    """真实商家 SKU 库存查询（只读）。"""
    _buyer()
    resolved_merchant = store_agent.resolve_merchant_id(friend_id=friend_id)
    try:
        inventory = get_merchant_repository().get_inventory(
            sku, merchant_id=resolved_merchant
        )
        if inventory is None:
            raise HTTPException(status_code=404, detail="没有找到这个 SKU")
        return {"source": "merchant_v1", "inventory": inventory.to_dict()}
    except MerchantError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/merchant/orders")
def merchant_orders(
    status: str | None = None,
    limit: int = 20,
    friend_id: str | None = None,
) -> dict:
    """当前买家在真实商家库中的订单。"""
    buyer_id, _ = _buyer()
    resolved_merchant = store_agent.resolve_merchant_id(friend_id=friend_id)
    try:
        orders = get_merchant_repository().list_orders(
            resolved_merchant,
            buyer_id=store_agent.merchant_buyer_id(buyer_id),
            status=status,
            limit=limit,
        )
        return {"source": "merchant_v1", "orders": [order.to_dict() for order in orders]}
    except MerchantError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/merchant/orders/{order_id}")
def merchant_order_detail(order_id: str, friend_id: str | None = None) -> dict:
    """当前买家的单笔真实商家订单。"""
    buyer_id, _ = _buyer()
    resolved_merchant = store_agent.resolve_merchant_id(friend_id=friend_id)
    try:
        order = get_merchant_repository().get_order(
            order_id,
            merchant_id=resolved_merchant,
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


@router.get("/groups")
def list_groups() -> dict:
    buyer_id, _ = _buyer()
    return {"groups": group.list_groups(buyer_id)}


@router.post("/groups")
def create_group(req: GroupCreateIn) -> dict:
    buyer_id, _ = _buyer()
    try:
        return group.create_group(buyer_id, req.name, req.member_ids)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/groups/{group_id}/messages")
def list_group_messages(group_id: str, limit: int = 30, before: str | None = None) -> dict:
    buyer_id, _ = _buyer()
    try:
        return {
            "messages": group.list_messages(buyer_id, group_id, limit=limit, before=before),
        }
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.post("/groups/{group_id}/messages")
def send_group_message(group_id: str, req: GroupMessageIn) -> dict:
    buyer_id, _ = _buyer()
    try:
        result = group.send_message(buyer_id, group_id, req.content)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc
    _maybe_superagent_trigger(
        buyer_id=buyer_id,
        content=req.content,
        channel=f"group:{group_id}",
        thread_key=f"capp:group:{group_id}",
    )
    return result


@router.get("/threads/unread")
def thread_unread() -> dict:
    buyer_id, _ = _buyer()
    return {
        "threads": store.get_thread_unread(buyer_id),
        "mentions": store.unread_mention_count(buyer_id),
    }


@router.post("/threads/{thread_id}/read")
def mark_thread_read(thread_id: str) -> dict:
    buyer_id, _ = _buyer()
    try:
        return store.mark_thread_read(buyer_id, thread_id)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/mentions")
def list_mentions(unread_only: bool = False, limit: int = 50) -> dict:
    buyer_id, _ = _buyer()
    return {
        "mentions": store.list_mentions(buyer_id, unread_only=unread_only, limit=limit),
        "unread": store.unread_mention_count(buyer_id),
    }


@router.post("/mentions/read")
def read_mentions() -> dict:
    buyer_id, _ = _buyer()
    return {"read": store.mark_all_mentions_read(buyer_id)}


@router.get("/admin/merchant-store-friends")
def admin_merchant_store_friends() -> dict:
    """管理端：查看店宠会话与商家的绑定。"""
    _require_admin()
    mappings = store.list_store_friend_mappings()
    return {"items": mappings, "count": len(mappings)}


@router.post("/admin/merchant-store-friends")
def admin_bind_merchant_store_friend(req: MerchantStoreFriendIn) -> dict:
    """管理端：把一个店宠 friend_id 绑定到真实商家。"""
    _require_admin()
    try:
        mapping = store.bind_store_friend(req.merchant_id, req.friend_id)
    except store.CStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"binding": mapping}


@router.get("/admin/merchant-sops")
def admin_merchant_sops(merchant_id: str | None = None) -> dict:
    """管理端：查看商家级 SOP；不传 merchant_id 时返回所有商家。"""
    _require_admin()
    if merchant_id:
        items = store.list_merchant_sops(merchant_id)
    else:
        items = []
        for mapping in store.list_store_friend_mappings():
            mid = str(mapping.get("merchant_id") or "")
            if mid and not any(item.get("merchant_id") == mid for item in items):
                items.extend(store.list_merchant_sops(mid))
    return {"items": items, "count": len(items)}


@router.put("/admin/merchant-sops")
def admin_upsert_merchant_sop(req: MerchantSopIn) -> dict:
    """管理端：新增/更新商家级 SOP。"""
    _require_admin()
    try:
        item = store.upsert_merchant_sop(
            req.merchant_id,
            req.topic,
            title=req.title,
            content=req.content,
        )
    except store.CStoreError as exc:
        raise _http_error(exc) from exc
    return {"item": item}


@router.get("/admin/chat-profiles")
def admin_chat_profiles(merchant_id: str | None = None, limit: int = 100) -> dict:
    """管理端：全量会话用户画像（只读）。"""
    _require_admin()
    profiles = store.list_chat_user_profiles(merchant_id, limit=limit)
    return {"merchant_id": merchant_id or "", "profiles": profiles, "count": len(profiles)}


@router.delete("/admin/chat-profiles/{merchant_id}/{buyer_id}")
def admin_delete_chat_profile(merchant_id: str, buyer_id: str) -> dict:
    _require_admin()
    deleted = store.delete_chat_user_profile(merchant_id, buyer_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="画像不存在或已删除")
    return {"deleted": True, "merchant_id": merchant_id, "buyer_id": buyer_id}


@router.get("/admin/reconciliation")
def admin_reconciliation(limit: int = 200) -> dict:
    """C 订单与商家订单对账（仅平台管理员，只读）。"""
    _require_admin()
    return store.reconcile_orders(limit=limit)


@router.post("/admin/reconciliation/run")
def admin_run_reconciliation(limit: int = 200) -> dict:
    """手动执行对账并留痕；不自动修改订单。"""
    _require_admin()
    return store.run_reconciliation("MANUAL", limit=limit)


@router.get("/admin/reconciliation/runs")
def admin_reconciliation_runs(limit: int = 20) -> dict:
    _require_admin()
    return {"runs": store.list_reconciliation_runs(limit=limit)}


@router.get("/admin/reconciliation/alerts")
def admin_reconciliation_alerts(unread_only: bool = False, limit: int = 50) -> dict:
    _require_admin()
    return {
        "alerts": store.list_reconciliation_alerts(unread_only=unread_only, limit=limit),
        "unread": store.unread_reconciliation_alert_count(),
    }


@router.post("/admin/reconciliation/alerts/read")
def admin_read_reconciliation_alerts() -> dict:
    _require_admin()
    return {"read": store.mark_reconciliation_alerts_read()}


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


@router.get("/merchants/available")
def available_merchants() -> dict:
    """C 端可添加的店宠：来自已绑定的商家店宠映射。"""
    buyer_id, _ = _buyer()
    existing = {str(friend.get("friend_id")) for friend in social.list_friends(buyer_id)}
    items = []
    for mapping in store.list_store_friend_mappings():
        friend_id = str(mapping.get("friend_id") or "")
        if not friend_id:
            continue
        items.append({
            "merchant_id": str(mapping.get("merchant_id") or ""),
            "friend_id": friend_id,
            "name": str(mapping.get("merchant_name") or friend_id),
            "note": "店宠 · 售前 / 售后 / 砍价",
            "is_friend": friend_id in existing,
        })
    return {"merchants": items, "count": len(items)}


@router.post("/friends/merchants")
def add_merchant_friend(req: MerchantFriendIn) -> dict:
    """把指定商家的店宠加入当前买家好友。"""
    buyer_id, _ = _buyer()
    mapping = next(
        (item for item in store.list_store_friend_mappings() if str(item.get("merchant_id")) == req.merchant_id),
        None,
    )
    if mapping is None:
        raise HTTPException(status_code=404, detail="商家店宠不存在或未绑定")
    friend_id = str(mapping.get("friend_id") or "")
    existed = any(str(friend.get("friend_id")) == friend_id for friend in social.list_friends(buyer_id))
    friend = social.add_friend(
        buyer_id,
        friend_id,
        str(mapping.get("merchant_name") or friend_id),
        "merchant",
        "店宠 · 售前 / 售后 / 砍价",
    )
    return {"friend": friend, "added": not existed}


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
            reply_provider=lambda text: store_agent.reply_with_meta(buyer_id, text, friend_id=friend_id, implicit_wake=True),
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
            reply_provider=lambda text: store_agent.reply_with_meta(buyer_id, text, friend_id=friend_id, implicit_wake=True),
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
        else:
            _maybe_superagent_trigger(
                buyer_id=buyer_id,
                content=req.content,
                channel=f"friend:{friend_id}",
                thread_key=f"capp:friend:{buyer_id}:{friend_id}",
            )
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
                else:
                    await asyncio.to_thread(
                        _maybe_superagent_trigger,
                        buyer_id=buyer_id,
                        content=content,
                        channel=f"friend:{friend_id}",
                        thread_key=f"capp:friend:{buyer_id}:{friend_id}",
                    )
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


@router.websocket("/ws/group/{group_id}")
async def group_chat_websocket(websocket: WebSocket, group_id: str) -> None:
    token = websocket.cookies.get(auth.SESSION_COOKIE)
    account = auth.resolve_session(token) if token else None
    if account is None or account.get("status") != auth.STATUS_ACTIVE:
        await websocket.close(code=1008)
        return
    if account.get("is_demo"):
        await websocket.close(code=1008)
        return
    if not _THREAD_RE.fullmatch(group_id or ""):
        await websocket.close(code=1008)
        return
    buyer_id = f"buyer_{account['id']}"
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_json()
            content = str(payload.get("content") or "").strip()
            try:
                result = await asyncio.to_thread(
                    group.send_message,
                    buyer_id,
                    group_id,
                    content,
                )
                await asyncio.to_thread(
                    _maybe_superagent_trigger,
                    buyer_id=buyer_id,
                    content=content,
                    channel=f"group:{group_id}",
                    thread_key=f"capp:group:{group_id}",
                )
                await websocket.send_json({"type": "group_chat", **result})
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


@router.get("/orders/{order_id}/tracking")
def get_order_tracking(order_id: str) -> dict:
    """查询当前买家订单的物流轨迹；只查本人订单，未配置服务商时 503。"""
    buyer_id, _ = _buyer()
    order = store.get_order(order_id)
    if order is None or order.get("buyer_id") != buyer_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "ORDER_NOT_FOUND", "message": "订单不存在"},
        )
    tracking_no = str(order.get("merchant_tracking_no") or "").strip()
    if not tracking_no:
        raise HTTPException(
            status_code=404,
            detail={"code": "TRACKING_NOT_AVAILABLE", "message": "这笔订单还没有物流单号"},
        )
    try:
        tracking = express.query_tracking(order.get("merchant_carrier"), tracking_no)
    except express.ExpressError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return {
        "ok": True,
        "order_id": order_id,
        "carrier": order.get("merchant_carrier") or tracking["carrier_code"],
        **tracking,
    }


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


@router.get("/admin/merchant/orders")
def admin_merchant_orders(
    status: str | None = None,
    buyer_id: str | None = None,
    limit: int = 100,
) -> dict:
    """平台管理员查看商家订单运营台（全部买家）。"""
    _require_admin()
    merchant_buyer = (
        store_agent.merchant_buyer_id(buyer_id) if buyer_id and buyer_id.startswith("buyer_") else buyer_id
    )
    try:
        orders = get_merchant_repository().list_orders(
            store_agent.STORE_MERCHANT_ID,
            buyer_id=merchant_buyer,
            status=status,
            limit=limit,
        )
    except MerchantError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": getattr(exc, "code", "MERCHANT_ERROR"), "message": str(exc)},
        ) from exc
    return {"source": "merchant_v1", "orders": [order.to_dict() for order in orders]}


@router.post("/orders/{order_id}/after-sales/{ticket_id}/return-shipment")
def submit_return_shipment(order_id: str, ticket_id: str, req: ReturnShipmentIn) -> dict:
    buyer_id, _ = _buyer()
    ticket = store.get_after_sale(ticket_id, buyer_id)
    if ticket["order_id"] != order_id:
        raise HTTPException(status_code=404, detail="售后工单不属于该订单")
    try:
        return store.submit_return_shipment(
            buyer_id,
            ticket_id,
            tracking_no=req.tracking_no,
            carrier=req.carrier,
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


@router.post("/admin/after-sales/{ticket_id}/receive")
def admin_receive_after_sale(ticket_id: str, req: AfterSaleReceiveIn) -> dict:
    _require_admin()
    try:
        return store.receive_after_sale(ticket_id, accepted=req.accepted)
    except store.CStoreError as exc:
        raise _http_error(exc) from exc


@router.get("/agent/session")
def c_agent_session() -> dict:
    """返回当前买家的稳定小鱼会话；用于刷新/换设备后恢复同一段对话。"""
    buyer_id, _ = _buyer()
    try:
        return c_agent.get_c_agent_session(buyer_id, get_checkpointer())
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/agent/run")
def c_agent_run(req: CAgentRunIn) -> dict:
    buyer_id, _ = _buyer()
    client_id = (req.client_message_id or "").strip() or None
    if client_id and not _CLIENT_ID_RE.fullmatch(client_id):
        raise HTTPException(status_code=400, detail="client_message_id 格式不合法")
    thread_id = (req.thread_id or "").strip() or f"c_thread_{uuid.uuid4().hex[:16]}"
    if not _THREAD_RE.fullmatch(thread_id):
        raise HTTPException(status_code=400, detail="thread_id 格式不合法")

    request_fingerprint = idempotency.fingerprint(req.message, req.thread_id, req.mode or "")
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
            mode=req.mode,
        )
    except ValueError as exc:
        if client_id:
            idempotency.release(client_id=client_id, owner_id=buyer_id, endpoint="c_agent_run")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        if client_id:
            idempotency.release(client_id=client_id, owner_id=buyer_id, endpoint="c_agent_run")
        raise HTTPException(status_code=502, detail=f"C 端 Agent 运行失败：{exc}") from exc

    try:
        memories_added = store.save_memories(buyer_id, req.message)
    except Exception:  # noqa: BLE001 - 记忆写入失败不应影响对话主链路
        memories_added = []
        logger.warning("C 端记忆保存失败，已忽略", exc_info=True)

    response = {
        "thread_id": thread_id,
        "mode": result.get("mode", ""),
        "route": result.get("route", ""),
        "confidence": result.get("confidence", 0),
        "slots": result.get("slots") or {},
        "status": result["status"],
        "interrupted": result["interrupted"],
        "requires_confirmation": result["interrupted"],
        "draft": result["draft"],
        "order": result["order"],
        "memories_added": len(memories_added),
        "product_refs": result.get("product_refs") or [],
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
    from rag_demo.api.b_workbench import register_b_workbench
    from rag_demo.api.superagent import register_superagent

    register_b_workbench(app)
    register_superagent(app)
    app.include_router(router)
