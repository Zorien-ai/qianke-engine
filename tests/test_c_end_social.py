"""C 端 IM 社交壳存储测试。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import social, store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_social.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    social.init()
    return store


def test_friends_are_seeded(c_store):
    friends = social.list_friends("buyer_1")
    assert any(f["friend_id"] == "store_demo" for f in friends)
    assert any(f["friend_id"] == "friend_demo" for f in friends)


def test_store_pet_requires_at_wake(c_store):
    inactive = social.send_message("buyer_1", "store_demo", "这个多少钱？")
    assert inactive["reply"]["awakened"] is False
    assert "未被唤醒" in inactive["reply"]["content"]

    active = social.send_message("buyer_1", "store_demo", "@店宠 我想砍价")
    assert active["reply"]["awakened"] is True
    assert "砍价" in active["reply"]["content"]


def test_user_friend_has_no_mock_reply(c_store):
    result = social.send_message("buyer_1", "friend_demo", "周末去徒步吗？")
    assert result["reply"] is None
    messages = social.get_messages("buyer_1", "friend_demo")
    assert len(messages) == 1
    assert messages[0]["content"] == "周末去徒步吗？"


def test_messages_are_persisted(c_store):
    social.send_message("buyer_1", "store_demo", "@店宠 今天有活动吗")
    messages = social.get_messages("buyer_1", "store_demo")
    assert len(messages) >= 2
    assert messages[0]["sender_id"] == "buyer_1"
    assert messages[-1]["sender_id"] == "store_demo"


def test_unknown_friend_rejected(c_store):
    with pytest.raises(store.CStoreError) as exc:
        social.send_message("buyer_1", "nobody", "hi")
    assert exc.value.code == "FRIEND_NOT_FOUND"
