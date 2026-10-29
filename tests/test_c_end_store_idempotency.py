"""店宠消息 HTTP 幂等包装：同一 client_message_id 只执行一次。"""
from __future__ import annotations

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
