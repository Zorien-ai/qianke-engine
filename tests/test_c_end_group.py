"""C 端群聊：默认群、成员、多 @ 回复。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import group, store, store_agent


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    group.init()
    return store


def test_default_group_has_three_members(c_store):
    groups = group.list_groups("buyer_1")
    assert groups
    default = next(item for item in groups if item["group_id"] == group.DEFAULT_GROUP_ID)
    assert default["name"] == "周末徒步群"
    assert [member["name"] for member in default["members"]] == ["小鱼", "山野店宠", "小满"]
    assert default["members"][1]["kind"] == "merchant"


def test_group_multi_mention_triggers_multiple_replies(c_store, monkeypatch):
    monkeypatch.setattr(
        store_agent,
        "reply_with_meta",
        lambda owner_id, text: store_agent.StoreReply("库存还有 18 件", True, {}),
    )
    result = group.send_message("buyer_1", group.DEFAULT_GROUP_ID, "@店宠 @小鱼 这双鞋还有货吗")
    assert result["message"]["content"].startswith("@店宠 @小鱼")
    assert len(result["replies"]) == 2
    assert [reply["sender_name"] for reply in result["replies"]] == ["山野店宠", "小鱼"]
    assert result["replies"][0]["content"] == "库存还有 18 件"
    messages = group.list_messages("buyer_1", group.DEFAULT_GROUP_ID)
    assert len(messages) == 3
    assert messages[0]["metadata"]["mentions"][0]["target_id"] == "store_demo"


def test_group_mention_friend_and_no_mention(c_store):
    result = group.send_message("buyer_1", group.DEFAULT_GROUP_ID, "@小满 周末去哪")
    assert len(result["replies"]) == 1
    assert result["replies"][0]["sender_name"] == "小满"

    result = group.send_message("buyer_1", group.DEFAULT_GROUP_ID, "大家好")
    assert result["replies"] == []


def test_group_is_owner_scoped(c_store):
    created = group.create_group("buyer_1", "买家1的私群", ["store_demo"])
    with pytest.raises(store.CStoreError) as exc:
        group.send_message("buyer_2", created["group_id"], "@店宠 你好")
    assert exc.value.code == "GROUP_NOT_FOUND"


def test_create_custom_group(c_store):
    created = group.create_group("buyer_1", "售后讨论组", ["store_demo", "companion"])
    assert created["name"] == "售后讨论组"
    assert [member["member_id"] for member in created["members"]] == ["store_demo", "companion"]
    listed = group.list_groups("buyer_1")
    assert any(item["group_id"] == created["group_id"] for item in listed)


def test_group_unread_and_mentions(c_store):
    group.list_groups("buyer_1")
    baseline = c_store.get_thread_unread("buyer_1")
    assert baseline.get(group.DEFAULT_GROUP_ID) == 0

    result = group.send_message("buyer_1", group.DEFAULT_GROUP_ID, "@小满 @我 明天几点集合")
    assert result["replies"]
    unread = c_store.get_thread_unread("buyer_1")
    assert unread[group.DEFAULT_GROUP_ID] >= 1
    mentions = c_store.list_mentions("buyer_1", unread_only=True)
    assert any(item["thread_id"] == group.DEFAULT_GROUP_ID and item["target_id"] == "me" for item in mentions)

    c_store.mark_thread_read("buyer_1", group.DEFAULT_GROUP_ID)
    assert c_store.get_thread_unread("buyer_1")[group.DEFAULT_GROUP_ID] == 0
    assert not any(
        item["thread_id"] == group.DEFAULT_GROUP_ID
        for item in c_store.list_mentions("buyer_1", unread_only=True)
    )
