"""C 端消费者注册 / 验证码登录接口（公开，不走企业审核）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.api.security import cookie_secure
from rag_demo.c_end import consumer_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/c/auth", tags=["c-auth"])


class SendCodeIn(BaseModel):
    phone: str = Field(..., min_length=11, max_length=20)


class ConsumerRegisterIn(BaseModel):
    phone: str = Field(..., min_length=11, max_length=20)
    code: str = Field(..., min_length=4, max_length=8)
    nickname: str = Field(..., min_length=2, max_length=20)
    password: str = Field(..., min_length=8, max_length=128)
    agree_terms: bool = False


class CodeLoginIn(BaseModel):
    phone: str = Field(..., min_length=11, max_length=20)
    code: str = Field(..., min_length=4, max_length=8)
    remember: bool = False


def _set_session(response: Response, request: Request, user: dict, remember: bool = False) -> dict:
    ttl = auth.REMEMBER_TTL_SECONDS if remember else auth.SESSION_TTL_SECONDS
    token = auth.create_session(user["id"], ttl)
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=ttl if remember else None,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
        path="/",
    )
    account = auth.resolve_session(token)
    if account is None:
        raise HTTPException(status_code=403, detail="该账号不可用")
    auth.set_current_account(account)
    return account


def _public_account(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "display_name": user.get("display_name"),
        "account_type": user.get("account_type"),
        "role": user.get("role"),
        "status": user.get("status"),
        "status_label": user.get("status_label"),
        "is_system_admin": bool(user.get("is_system_admin")),
        "is_enterprise_admin": bool(user.get("is_enterprise_admin")),
        "is_demo": bool(user.get("is_demo")),
    }


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/sms/send")
def send_sms_code(payload: SendCodeIn, request: Request) -> dict:
    try:
        return consumer_auth.send_code(payload.phone, client_ip=_client_ip(request))
    except ValueError as exc:
        message = str(exc)
        status = 429 if "频繁" in message or "上限" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc
    except RuntimeError as exc:
        logger.error("短信发送失败: %s", exc)
        raise HTTPException(status_code=503, detail="短信服务暂不可用") from exc


@router.post("/register")
def consumer_register(payload: ConsumerRegisterIn, request: Request, response: Response) -> dict:
    if not payload.agree_terms:
        raise HTTPException(status_code=400, detail="请先同意用户协议和隐私政策")
    if not consumer_auth.verify_code(payload.phone, payload.code):
        raise HTTPException(status_code=400, detail="验证码不正确或已过期")
    try:
        user = auth.create_consumer(payload.phone, payload.password, payload.nickname)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    account = _set_session(response, request, user)
    logger.info("C 端消费者注册并登录: %s", user.get("username"))
    return {"status": "ok", "account": _public_account(account)}


@router.post("/login/code")
def consumer_code_login(payload: CodeLoginIn, request: Request, response: Response) -> dict:
    if not consumer_auth.verify_code(payload.phone, payload.code):
        raise HTTPException(status_code=400, detail="验证码不正确或已过期")
    phone = consumer_auth.normalize_phone(payload.phone)
    user = auth.find_user_by_login(phone)
    if user is None or user.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=401, detail="账号不存在或不可用")
    if user.get("is_demo"):
        raise HTTPException(status_code=403, detail="演示账号不能使用 C 端验证码登录")
    account = _set_session(response, request, user, remember=payload.remember)
    logger.info("C 端验证码登录: %s", user.get("username"))
    return {"status": "ok", "account": _public_account(account)}


@router.get("/providers")
def providers() -> dict:
    """给登录页判断是否展示“演示验证码”提示。"""
    return {
        "sms_dev_mode": bool(consumer_auth.is_dev_mode()),
        "sms_provider_configured": bool(
            __import__("os").environ.get("QIANKE_SMS_PROVIDER", "").strip()
            not in ("", "dev")
        ),
    }


def register_c_auth(app) -> None:
    app.include_router(router)
