"""C 端 mention 元数据、会话未读与 @ 通知。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import mentions, social, store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    social.init()
    return store


def test_extract_mentions_known_members_only():
    found = mentions.extract_mentions("@店宠 问一下 @小鱼 和 @小满，@店宠 重复")
    assert [item["token"] for item in found] == ["@店宠", "@小鱼", "@小满"]
    assert found[0]["thread_id"] == "store_demo"
    assert found[1]["thread_id"] == "companion"


def test_app_message_persists_mentions_and_metadata(c_store):
    message = c_store.save_app_message(
        "buyer_1",
        "companion",
        "user",
        "@店宠 这双跑鞋多少钱",
    )
    stored = c_store.list_app_messages("buyer_1", "companion")
    row = next(item for item in stored if item["message_id"] == message["message_id"])
    assert row["metadata"]["mentions"][0]["target_id"] == "store_demo"
    records = c_store.list_mentions("buyer_1")
    assert records[0]["token"] == "@店宠"
    assert records[0]["target_id"] == "store_demo"


def test_thread_unread_and_read(c_store):
    # 首次调用建立已读基线，历史消息不产生未读。
    assert c_store.get_thread_unread("buyer_1")["companion"] == 0
    c_store.save_app_message("buyer_1", "companion", "companion", "收到，@我 来帮你查")
    unread = c_store.get_thread_unread("buyer_1")
    assert unread["companion"] == 1
    assert unread["store_demo"] == 0
    unread_mentions = c_store.list_mentions("buyer_1", unread_only=True)
    assert any(item["target_id"] == "me" for item in unread_mentions)

    c_store.mark_thread_read("buyer_1", "companion")
    assert c_store.get_thread_unread("buyer_1")["companion"] == 0
    assert c_store.unread_mention_count("buyer_1") == 0


def test_social_message_has_mentions_and_unread(c_store):
    assert c_store.get_thread_unread("buyer_1")["store_demo"] == 0
    result = social.send_message(
        "buyer_1",
        "store_demo",
        "@店宠 查一下库存",
        reply_provider=lambda text: ("库存还有 18 件", True),
    )
    assert result["message"]["metadata"]["mentions"][0]["target_id"] == "store_demo"
    unread = c_store.get_thread_unread("buyer_1")
    assert unread["store_demo"] >= 1
    c_store.mark_thread_read("buyer_1", "store_demo")
    assert c_store.get_thread_unread("buyer_1")["store_demo"] == 0


def test_mark_thread_read_rejects_unknown_thread(c_store):
    with pytest.raises(store.CStoreError):
        c_store.mark_thread_read("buyer_1", "not_a_thread")
