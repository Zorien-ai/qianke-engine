"""店宠消息 HTTP 幂等包装：同一 client_message_id 只执行一次；TTL 过期后可重新执行。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from rag_demo.api import c_end
from rag_demo.c_end import store


def test_store_send_replays_without_second_agent_call(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    calls = []

    def fake_send(buyer_id, friend_id, content, **kwargs):
        calls.append((buyer_id, friend_id, content))
        return {"reply": {"content": "收到"}, "companion_message": None}

    monkeypatch.setattr(c_end.social, "send_message", fake_send)
    first, replay = c_end._send_store_message_once(
        "buyer_1", "store_demo", "今天有活动吗", "cmsg_store_01"
    )
    assert replay is False
    assert first["reply"]["content"] == "收到"

    second, replay2 = c_end._send_store_message_once(
        "buyer_1", "store_demo", "今天有活动吗", "cmsg_store_01"
    )
    assert replay2 is True
    assert second["reply"]["content"] == "收到"
    assert len(calls) == 1


def test_expired_store_idempotency_re_executes_after_prune(tmp_path, monkeypatch):
    """TTL 到期被 prune 后，同一 client_message_id 允许重新执行；conflict 语义不变。"""
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    calls: list[str] = []

    def fake_send(buyer_id, friend_id, content, **kwargs):
        calls.append(content)
        return {"reply": {"content": "收到"}, "companion_message": None}

    monkeypatch.setattr(c_end.social, "send_message", fake_send)

    first, replay = c_end._send_store_message_once(
        "buyer_1", "store_demo", "今天有活动吗", "cmsg_store_ttl01"
    )
    assert replay is False and first["reply"]["content"] == "收到"

    # 未过期：第二次同 ID 只回放，不再调用 social.send_message
    _, replay2 = c_end._send_store_message_once(
        "buyer_1", "store_demo", "今天有活动吗", "cmsg_store_ttl01"
    )
    assert replay2 is True
    assert len(calls) == 1

    # 把记录拨到 2 小时前并用 TTL=1 小时清理：过期缓存被删除
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    conn = sqlite3.connect(str(store._db_path()))
    try:
        conn.execute(
            "UPDATE c_client_request SET created_at = ?, updated_at = ? "
            "WHERE client_id = 'cmsg_store_ttl01'",
            (old, old),
        )
        conn.commit()
    finally:
        conn.close()
    assert c_end.idempotency.prune(max_age_seconds=3600) == 1

    # TTL 到期后同 ID 重新执行（新请求，非回放）
    _, replay3 = c_end._send_store_message_once(
        "buyer_1", "store_demo", "今天有活动吗", "cmsg_store_ttl01"
    )
    assert replay3 is False
    assert len(calls) == 2

    # 新记录仍然约束冲突：同 ID 不同内容 → IdempotencyConflict
    with pytest.raises(c_end.idempotency.IdempotencyConflict):
        c_end._send_store_message_once(
            "buyer_1", "store_demo", "换个问题", "cmsg_store_ttl01"
        )
