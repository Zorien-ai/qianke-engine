"""B 端会话画像：30 分钟空闲抽取、结构化校验、租户存储。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rag_demo import auth
from rag_demo.agent.tools.chat_profile import get_chat_user_profile, search_chat_user_profiles
from rag_demo.c_end import chat_profile, social, store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    social.init()
    return store


def _seed_conversation(owner_id: str = "buyer_1"):
    social.send_message(owner_id, "store_demo", "我想找一双通勤跑鞋，预算 500 元")
    social.send_message(owner_id, "store_demo", "不要推荐太重的")
    conn = store._connect()
    try:
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        conn.execute("UPDATE c_message SET created_at = ? WHERE owner_id = ?", (old, owner_id))
        conn.commit()
    finally:
        conn.close()


def _fake_profile_llm(messages):
    return (
        '{"needs":["通勤跑鞋"],"preferences":["轻量"],"boundaries":["不要推荐太重的"],'
        '"budget":"500 元","sizes":{"shoe":"42"},"purchase_stage":"compare",'
        '"open_questions":[],"confidence":0.85}'
    )


def test_extract_profile_and_store(c_store):
    _seed_conversation()
    result = chat_profile.extract_for_owner(
        "buyer_1",
        llm=_fake_profile_llm,
        embedder=lambda text: [0.1] * 1024,
    )
    assert result["ok"] is True
    profile = store.get_chat_user_profile(chat_profile.STORE_MERCHANT_ID, "buyer_1")
    assert profile is not None
    assert profile["profile"]["needs"] == ["通勤跑鞋"]
    assert profile["profile"]["boundaries"] == ["不要推荐太重的"]
    assert profile["source_message_count"] == 4
    assert profile["version"] == 1

    # 无新消息不重复抽取。
    again = chat_profile.extract_for_owner(
        "buyer_1",
        llm=_fake_profile_llm,
        embedder=lambda text: [0.1] * 1024,
    )
    assert again["ok"] is False
    assert again["reason"] == "NO_NEW_MESSAGES"


def test_extract_rejects_empty_profile(c_store):
    _seed_conversation()
    result = chat_profile.extract_for_owner(
        "buyer_1",
        llm=lambda messages: "{}",
        embedder=lambda text: [0.1] * 1024,
    )
    assert result["ok"] is False
    assert result["reason"] == "EXTRACT_EMPTY"
    assert store.get_chat_user_profile(chat_profile.STORE_MERCHANT_ID, "buyer_1") is None


def test_profile_is_scoped_by_merchant(c_store):
    _seed_conversation()
    chat_profile.extract_for_owner(
        "buyer_1",
        llm=_fake_profile_llm,
        embedder=lambda text: [0.1] * 1024,
    )
    assert store.get_chat_user_profile(chat_profile.STORE_MERCHANT_ID, "buyer_1") is not None
    assert store.get_chat_user_profile("m_other", "buyer_1") is None


def test_search_profiles_falls_back_to_text(c_store):
    _seed_conversation()
    chat_profile.extract_for_owner(
        "buyer_1",
        llm=_fake_profile_llm,
        embedder=lambda text: [0.1] * 1024,
    )
    results = store.search_chat_user_profiles(
        chat_profile.STORE_MERCHANT_ID, "通勤跑鞋", None, limit=5
    )
    assert results
    assert results[0]["buyer_id"] == "buyer_1"



def test_profile_tool_is_tenant_scoped(c_store, monkeypatch):
    _seed_conversation()
    chat_profile.extract_for_owner(
        "buyer_1",
        llm=_fake_profile_llm,
        embedder=lambda text: [0.1] * 1024,
    )
    c_store.bind_merchant_member(1, chat_profile.STORE_MERCHANT_ID, role="owner")
    monkeypatch.setattr(
        auth,
        "current_account",
        lambda: {"id": 1, "status": "active", "role": "cs", "is_system_admin": False},
    )
    result = get_chat_user_profile.invoke({"buyer_id": "buyer_1"})
    assert result["ok"] is True
    assert result["summary"]
    assert result["profile"]["needs"]

    monkeypatch.setattr(
        auth,
        "current_account",
        lambda: {"id": 99, "status": "active", "role": "cs", "is_system_admin": False},
    )
    denied = get_chat_user_profile.invoke({"buyer_id": "buyer_1"})
    assert denied["ok"] is False
    assert denied["error"]["code"] == "NO_MERCHANT"


def test_profile_search_tool_returns_summary_only(c_store, monkeypatch):
    _seed_conversation()
    chat_profile.extract_for_owner(
        "buyer_1",
        llm=_fake_profile_llm,
        embedder=lambda text: [0.1] * 1024,
    )
    c_store.bind_merchant_member(1, chat_profile.STORE_MERCHANT_ID, role="owner")
    monkeypatch.setattr(
        auth,
        "current_account",
        lambda: {"id": 1, "status": "active", "role": "cs", "is_system_admin": False},
    )
    result = search_chat_user_profiles.invoke({"query": "通勤跑鞋", "limit": 5})
    assert result["ok"] is True
    assert result["items"]
    assert result["items"][0]["buyer_id"] == "buyer_1"
    assert "summary" in result["items"][0]
