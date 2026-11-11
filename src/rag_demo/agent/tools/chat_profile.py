"""B 端会话画像查询 Tool。

租户边界：
- 已绑定商家的账号只能查自己的 merchant_id；
- 系统管理员可以显式传 merchant_id；
- 两个 Tool 都不返回原始聊天记录，只返回画像摘要与结构化 JSON。
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from rag_demo import auth
from rag_demo.agent import actions
from rag_demo.c_end import store


class _ScopeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message


def _merchant_scope(requested: str | None = None) -> str:
    account = auth.current_account()
    account_id = int(account["id"]) if account else 0
    is_system_admin = bool(account.get("is_system_admin")) if account else False
    if account is None:
        # Agent 在独立执行上下文里运行，HTTP 的 auth contextvar 不会自动带进来；
        # action_scope 是同一执行链上的可信账号上下文。
        try:
            actor = actions.current_actor()
        except Exception:  # noqa: BLE001
            actor = None
        if actor:
            raw_id = str(actor.get("account_id") or "")
            account_id = int(raw_id) if raw_id.isdigit() else 0
            is_system_admin = bool(actor.get("is_system_admin"))
    if not account_id:
        raise _ScopeError("UNAUTHENTICATED", "请先登录")
    member = store.get_merchant_member(account_id)
    if member is not None:
        return str(member["merchant_id"])
    if is_system_admin:
        merchant_id = str(requested or "").strip()
        if merchant_id:
            return merchant_id
        raise _ScopeError("MERCHANT_REQUIRED", "管理员查询画像需要提供 merchant_id")
    raise _ScopeError("NO_MERCHANT", "当前账号未绑定商家，不能查询用户画像")


def _error(exc: _ScopeError) -> dict[str, Any]:
    return {"ok": False, "error": {"code": exc.code, "message": exc.message}}


class GetProfileInput(BaseModel):
    buyer_id: str = Field(..., min_length=1, max_length=80, description="买家 ID，例如 buyer_123")
    merchant_id: str | None = Field(default=None, max_length=80, description="仅系统管理员可指定")


@tool(args_schema=GetProfileInput)
def get_chat_user_profile(buyer_id: str, merchant_id: str | None = None) -> dict[str, Any]:
    """查询当前商家下某个 C 买家的会话画像摘要和结构化 JSON。"""
    try:
        scope = _merchant_scope(merchant_id)
        profile = store.get_chat_user_profile(scope, str(buyer_id).strip())
        if profile is None:
            return {"ok": False, "error": {"code": "PROFILE_NOT_FOUND", "message": "没有找到该用户的画像"}}
        return {
            "ok": True,
            "merchant_id": scope,
            "buyer_id": profile["buyer_id"],
            "summary": profile["profile_text"],
            "profile": profile["profile"],
            "confidence": profile["confidence"],
            "source_message_count": profile["source_message_count"],
            "extracted_at": profile["extracted_at"],
            "version": profile["version"],
        }
    except _ScopeError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": {"code": "PROFILE_QUERY_FAILED", "message": "画像查询失败"}}


class SearchProfilesInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=200, description="自然语言条件")
    limit: int = Field(default=5, ge=1, le=20)
    merchant_id: str | None = Field(default=None, max_length=80, description="仅系统管理员可指定")


@tool(args_schema=SearchProfilesInput)
def search_chat_user_profiles(
    query: str,
    limit: int = 5,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    """在当前商家内按语义搜索 C 买家会话画像，只返回摘要与 buyer_id。"""
    try:
        scope = _merchant_scope(merchant_id)
        embedding = None
        try:
            from rag_demo.retrieval.remote_models import RemoteEmbedding

            vector = RemoteEmbedding().encode(str(query))
            embedding = [float(x) for x in vector]
        except Exception:  # noqa: BLE001 - 无 embedding 时退回文本匹配
            embedding = None
        rows = store.search_chat_user_profiles(scope, str(query), embedding, limit=limit)
        items = [
            {
                "buyer_id": row["buyer_id"],
                "summary": row["profile_text"],
                "confidence": row["confidence"],
                "extracted_at": row["extracted_at"],
                "distance": row.get("distance"),
            }
            for row in rows
        ]
        return {"ok": True, "merchant_id": scope, "count": len(items), "items": items}
    except _ScopeError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": {"code": "PROFILE_SEARCH_FAILED", "message": "画像搜索失败"}}


__all__ = ["get_chat_user_profile", "search_chat_user_profiles"]
