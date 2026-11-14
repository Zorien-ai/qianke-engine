"""C 端联系人增强存储测试：好友申请 / 群通知 / 会话偏好。"""
from __future__ import annotations

import sqlite3

import pytest

from rag_demo.c_end import contacts, social, store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_contacts.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    contacts.init()
    return store


def test_friend_request_accept_adds_friend(c_store):
    request = contacts.create_friend_request(
        "buyer_1",
        "friend_new",
        "新朋友",
        requester_kind="user",
        message="周末一起徒步",
        note="好友 · 徒步搭子",
    )
    assert request["status"] == "PENDING"

    pending = contacts.list_friend_requests("buyer_1", status="PENDING")
    assert [item["request_id"] for item in pending] == [request["request_id"]]

    resolved = contacts.resolve_friend_request("buyer_1", request["request_id"], accepted=True)
    assert resolved["request"]["status"] == "ACCEPTED"
    assert resolved["friend"]["friend_id"] == "friend_new"

    friends = social.list_friends("buyer_1")
    assert any(item["friend_id"] == "friend_new" for item in friends)

    # 重复接受保持幂等，不重复创建申请。
    again = contacts.resolve_friend_request("buyer_1", request["request_id"], accepted=True)
    assert again["request"]["status"] == "ACCEPTED"


def test_friend_request_reject_does_not_add_friend(c_store):
    request = contacts.create_friend_request("buyer_1", "friend_rejected", "被拒用户")
    resolved = contacts.resolve_friend_request("buyer_1", request["request_id"], accepted=False)
    assert resolved["request"]["status"] == "REJECTED"
    assert resolved["friend"] is None
    assert all(item["friend_id"] != "friend_rejected" for item in social.list_friends("buyer_1"))


def test_friend_request_is_owner_scoped(c_store):
    request = contacts.create_friend_request("buyer_1", "friend_new", "新朋友")
    with pytest.raises(store.CStoreError) as exc:
        contacts.resolve_friend_request("buyer_2", request["request_id"], accepted=True)
    assert exc.value.code == "FRIEND_REQUEST_NOT_FOUND"


def test_conversation_prefs_are_user_scoped_and_upserted(c_store):
    first = contacts.update_conversation_pref("buyer_1", "friend_demo", pinned=True)
    assert first["pinned"] is True
    assert first["muted"] is False

    second = contacts.update_conversation_pref(
        "buyer_1", "friend_demo", pinned=False, muted=True, hidden=False
    )
    assert second["pinned"] is False
    assert second["muted"] is True

    prefs = contacts.list_conversation_prefs("buyer_1")
    assert len(prefs) == 1
    assert prefs[0]["thread_id"] == "friend_demo"

    assert contacts.list_conversation_prefs("buyer_2") == []


def test_group_notices_and_read_state(c_store):
    first = contacts.create_group_notice(
        "buyer_1", "群成员变更", group_id="group_demo", content="小满加入了群聊"
    )
    second = contacts.create_group_notice(
        "buyer_1", "群公告更新", group_id="group_demo", kind="notice"
    )
    assert first["status"] == "UNREAD"

    notices = contacts.list_group_notices("buyer_1")
    assert [item["notice_id"] for item in notices] == [
        second["notice_id"],
        first["notice_id"],
    ]

    read = contacts.mark_group_notice_read("buyer_1", first["notice_id"])
    assert read["status"] == "READ"
    assert contacts.list_group_notices("buyer_1", unread_only=True) == [
        item for item in notices if item["notice_id"] == second["notice_id"]
    ]

    with pytest.raises(store.CStoreError) as exc:
        contacts.mark_group_notice_read("buyer_2", first["notice_id"])
    assert exc.value.code == "GROUP_NOTICE_NOT_FOUND"


def test_remove_friend_removes_relation_but_keeps_messages(c_store):
    social.send_message("buyer_1", "friend_demo", "你好")
    result = social.remove_friend("buyer_1", "friend_demo")
    assert result["removed"] is True
    assert all(item["friend_id"] != "friend_demo" for item in social.list_friends("buyer_1"))
    # 历史消息不因删除好友而删除（好友关系已不可见，直接核对库内消息）。
    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM c_message WHERE owner_id = 'buyer_1' AND friend_id = 'friend_demo'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1

    with pytest.raises(store.CStoreError) as exc:
        social.remove_friend("buyer_1", "friend_demo")
    assert exc.value.code == "FRIEND_NOT_FOUND"
