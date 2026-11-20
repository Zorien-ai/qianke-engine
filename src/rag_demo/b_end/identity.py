# -*- coding: utf-8 -*-
"""B 端客户身份消歧（Phase 3B）。

唯一主键：buyer_id。
Phase 3B 只做精确别名匹配：buyer_id / display_name / username / contact。
多命中一律 AMBIGUOUS，不自动猜；不返回原始手机号/邮箱。
"""
from __future__ import annotations

import re
from typing import Any

from rag_demo import auth
from rag_demo.c_end import store

_BUYER_ACCOUNT_RE = re.compile(r"^buyer_(\d+)$")


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _contact_digits(value: Any) -> str:
    raw = str(value or "").strip()
    digits = re.sub(r"[\s\-()]", "", raw)
    if digits.startswith("+86"):
        digits = digits[3:]
    elif digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits


def _contact_norm(value: Any) -> str:
    raw = str(value or "").strip()
    if "@" in raw:
        return raw.casefold()
    return _contact_digits(raw)


def _masked_contact(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "@" in raw:
        local, _, domain = raw.partition("@")
        return f"{local[:1]}***@{domain}"
    digits = _contact_digits(raw)
    if len(digits) == 11:
        return f"{digits[:3]}****{digits[-4:]}"
    return "***"


def _merchant_buyer_ids(merchant_id: str, *, limit: int = 500) -> list[str]:
    buyers: list[str] = []
    seen: set[str] = set()
    for profile in store.list_chat_user_profiles(merchant_id, limit=limit):
        buyer_id = str(profile.get("buyer_id") or "").strip()
        if buyer_id and buyer_id not in seen:
            seen.add(buyer_id)
            buyers.append(buyer_id)
    for profile in store.list_qianke_user_profiles(merchant_id, limit=limit):
        buyer_id = str(profile.get("buyer_id") or "").strip()
        if buyer_id and buyer_id not in seen:
            seen.add(buyer_id)
            buyers.append(buyer_id)
    return buyers


def _aliases(buyer_id: str) -> list[tuple[str, str, bool]]:
    """返回 (字段名, 原始别名, 是否敏感)。敏感字段只用于匹配，不原样返回。"""
    aliases: list[tuple[str, str, bool]] = [("buyer_id", buyer_id, False)]
    match = _BUYER_ACCOUNT_RE.match(buyer_id)
    if not match:
        return aliases
    try:
        user = auth.find_user_by_id(int(match.group(1)))
    except Exception:  # noqa: BLE001 - 认证库不可用时只保留 buyer_id 精确匹配
        user = None
    if not isinstance(user, dict):
        return aliases
    for field, sensitive in (("display_name", False), ("username", False), ("contact", True)):
        value = str(user.get(field) or "").strip()
        if value:
            aliases.append((field, value, sensitive))
    return aliases


def resolve_customer_identity(
    merchant_id: str,
    query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """在当前商户内把 alias 解析成唯一 buyer_id；不跨商户、不模糊猜。"""
    merchant = str(merchant_id or "").strip()
    text = _normalize(query)
    if not merchant:
        return {
            "status": "FORBIDDEN",
            "tenant_id": "",
            "customer_id": None,
            "confidence": 0.0,
            "evidence": [],
            "candidates": [],
            "needs_clarification": True,
            "next_action": "REJECT",
        }
    if not text:
        return {
            "status": "NOT_FOUND",
            "tenant_id": f"b_merchant:{merchant}",
            "customer_id": None,
            "confidence": 0.0,
            "evidence": [],
            "candidates": [],
            "needs_clarification": True,
            "next_action": "ASK",
        }

    contact_query = _contact_norm(query)
    matches: list[dict[str, Any]] = []
    for buyer_id in _merchant_buyer_ids(merchant):
        matched: list[str] = []
        for field, value, sensitive in _aliases(buyer_id):
            normalized = _contact_norm(value) if sensitive else _normalize(value)
            if not normalized:
                continue
            if normalized == (contact_query if sensitive else text):
                matched.append(field)
        if not matched:
            continue
        user = auth.find_user_by_id(int(_BUYER_ACCOUNT_RE.match(buyer_id).group(1))) if _BUYER_ACCOUNT_RE.match(buyer_id) else None
        matches.append({
            "buyer_id": buyer_id,
            "display_name": str((user or {}).get("display_name") or ""),
            "masked_contact": _masked_contact((user or {}).get("contact")),
            "matched_fields": matched,
        })
        if len(matches) >= max(1, min(int(limit), 20)):
            break

    tenant_id = f"b_merchant:{merchant}"
    if len(matches) == 1:
        return {
            "status": "RESOLVED",
            "tenant_id": tenant_id,
            "customer_id": matches[0]["buyer_id"],
            "confidence": 1.0,
            "evidence": matches[0]["matched_fields"],
            "candidates": matches,
            "needs_clarification": False,
            "next_action": "USE",
        }
    if len(matches) > 1:
        return {
            "status": "AMBIGUOUS",
            "tenant_id": tenant_id,
            "customer_id": None,
            "confidence": 0.0,
            "evidence": ["multiple_matches"],
            "candidates": matches,
            "needs_clarification": True,
            "next_action": "ASK",
        }
    return {
        "status": "NOT_FOUND",
        "tenant_id": tenant_id,
        "customer_id": None,
        "confidence": 0.0,
        "evidence": [],
        "candidates": [],
        "needs_clarification": True,
        "next_action": "ASK",
    }
