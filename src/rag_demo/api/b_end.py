"""B 端账号级 AI 人设 HTTP API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.b_end import persona as b_persona, store

router = APIRouter(prefix="/api/b", tags=["b-end"])


class PersonaPatchIn(BaseModel):
    """局部更新：None = 不改；name/address 传空串 = 回到默认 / 账号昵称。"""

    name: str | None = Field(default=None, max_length=b_persona.NAME_LIMIT)
    user_address: str | None = Field(default=None, max_length=b_persona.ADDRESS_LIMIT)
    tone_profile: str | None = Field(default=None, max_length=32)


def _account() -> dict:
    account = auth.current_account()
    if account is None:
        raise HTTPException(status_code=401, detail="请先登录")
    if account.get("status") != auth.STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="账号不可用")
    return account


def _payload(account: dict) -> dict:
    row = store.get_persona(account.get("id"))
    resolved = b_persona.resolve_identity(account, row)
    return {
        "name": resolved["name"],
        "user_address": (row or {}).get("user_address") or "",
        "tone_profile": resolved["tone_profile"],
        "resolved": resolved,
        "defaults": {
            "name": b_persona.DEFAULT_NAME,
            "user_address": "",
            "tone_profile": b_persona.DEFAULT_TONE,
        },
        "tones": b_persona.TONE_CHOICES,
        "prompt_version": b_persona.PROMPT_VERSION,
    }


@router.get("/persona")
def get_persona() -> dict:
    """当前账号的 AI 人设（名字 / 称呼 / 语气档位）。"""
    return _payload(_account())


@router.patch("/persona")
def update_persona(req: PersonaPatchIn) -> dict:
    """保存当前账号的 AI 人设；不传的字段保持不变。"""
    account = _account()

    if req.name is not None and req.name.strip():
        ok, reason = b_persona.validate_name(req.name)
        if not ok:
            raise HTTPException(status_code=400, detail=reason)
    if req.user_address is not None:
        ok, reason = b_persona.validate_address(req.user_address)
        if not ok:
            raise HTTPException(status_code=400, detail=reason)
    if req.tone_profile is not None and req.tone_profile.strip():
        ok, reason = b_persona.validate_tone(req.tone_profile)
        if not ok:
            raise HTTPException(status_code=400, detail=reason)

    store.upsert_persona(
        account.get("id"),
        name=req.name.strip() if req.name is not None else None,
        user_address=req.user_address.strip() if req.user_address is not None else None,
        tone_profile=req.tone_profile.strip() if req.tone_profile is not None else None,
    )
    return _payload(account)


@router.delete("/persona")
def reset_persona() -> dict:
    """恢复默认人设（小千 / 账号昵称 / 专业直给）。"""
    account = _account()
    store.reset_persona(account.get("id"))
    return _payload(account)


def register_b_end(app) -> None:
    app.include_router(router)
