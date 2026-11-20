# -*- coding: utf-8 -*-
"""Phase 3B：B 端客户身份消歧（精确匹配 / 多命中补问 / 脱敏）。"""
from __future__ import annotations

import pytest

from rag_demo import auth
from rag_demo.agent.tools.chat_profile import resolve_customer_identity
from rag_demo.b_end import identity
from rag_demo.c_end import store


@pytest.fixture()
def identity_env(monkeypatch):
    profiles = [
        {"buyer_id": "buyer_1"},
        {"buyer_id": "buyer_2"},
        {"buyer_id": "buyer_3"},
    ]
    monkeypatch.setattr(store, "list_chat_user_profiles", lambda merchant_id, limit=500: profiles if merchant_id == "m_1" else [])
    monkeypatch.setattr(store, "list_qianke_user_profiles", lambda merchant_id, limit=500: [])
    users = {
        1: {"id": 1, "display_name": "林小满", "username": "c_13800138000", "contact": "13800138000"},
        2: {"id": 2, "display_name": "陈一诺", "username": "c_13800138002", "contact": "13800138002"},
        3: {"id": 3, "display_name": "林小满", "username": "c_13800138003", "contact": "lin@example.com"},
    }
    monkeypatch.setattr(auth, "find_user_by_id", lambda user_id: users.get(int(user_id)))
    return profiles


def test_exact_buyer_id_resolves(identity_env):
    result = identity.resolve_customer_identity("m_1", "buyer_1")
    assert result["status"] == "RESOLVED"
    assert result["customer_id"] == "buyer_1"
    assert result["confidence"] == 1.0
    assert "buyer_id" in result["evidence"]


def test_display_name_unique_resolves(identity_env):
    result = identity.resolve_customer_identity("m_1", "陈一诺")
    assert result["status"] == "RESOLVED"
    assert result["customer_id"] == "buyer_2"
    assert "display_name" in result["evidence"]


def test_duplicate_display_name_is_ambiguous(identity_env):
    result = identity.resolve_customer_identity("m_1", "林小满")
    assert result["status"] == "AMBIGUOUS"
    assert result["customer_id"] is None
    assert result["needs_clarification"] is True
    assert result["next_action"] == "ASK"
    assert {item["buyer_id"] for item in result["candidates"]} == {"buyer_1", "buyer_3"}


def test_phone_resolves_but_never_returns_raw(identity_env):
    result = identity.resolve_customer_identity("m_1", "13800138002")
    assert result["status"] == "RESOLVED"
    assert result["customer_id"] == "buyer_2"
    assert "contact" in result["evidence"]
    assert result["candidates"][0]["masked_contact"] == "138****8002"
    assert "13800138002" not in str(result)


def test_email_is_case_insensitive_and_masked(identity_env):
    result = identity.resolve_customer_identity("m_1", "LIN@example.com")
    assert result["status"] == "RESOLVED"
    assert result["customer_id"] == "buyer_3"
    assert result["candidates"][0]["masked_contact"] == "l***@example.com"
    assert "lin@example.com" not in str(result)


def test_not_found_and_cross_merchant_are_not_revealed(identity_env):
    missing = identity.resolve_customer_identity("m_1", "不存在")
    assert missing["status"] == "NOT_FOUND"
    assert missing["next_action"] == "ASK"

    # 候选只来自当前商户；查询别的 buyer 不会跨商户命中。
    assert identity.resolve_customer_identity("m_other", "buyer_1")["status"] == "NOT_FOUND"


def test_agent_tool_contract(identity_env, monkeypatch):
    monkeypatch.setattr(
        "rag_demo.agent.tools.chat_profile._merchant_scope",
        lambda requested=None: "m_1",
    )
    result = resolve_customer_identity.invoke({"query": "buyer_1"})
    assert result["status"] == "RESOLVED"
    assert result["customer_id"] == "buyer_1"
