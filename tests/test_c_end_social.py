"""C 端 IM 社交壳存储测试。"""
from __future__ import annotations

import sqlite3

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


def _insert_raw(
    c_store,
    message_id: str,
    created_at: str,
    content: str,
    *,
    owner_id: str = "buyer_1",
    friend_id: str = "store_demo",
) -> None:
    """直接落库，便于构造确定性的 created_at / message_id（含同时间戳场景）。"""
    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        conn.execute(
            "INSERT INTO c_message(message_id, owner_id, friend_id, sender_id, receiver_id, "
            "content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, '{}', ?)",
            (message_id, owner_id, friend_id, owner_id, friend_id, content, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_history(c_store, count: int = 25) -> list[dict]:
    """按分钟递增塞 count 条消息，created_at 可预测（升序）。"""
    history = []
    for index in range(count):
        created_at = f"2026-10-29T10:{index:02d}:00+00:00"
        message_id = f"msg_history_{index:04d}"
        _insert_raw(c_store, message_id, created_at, f"消息{index}")
        history.append({"message_id": message_id, "created_at": created_at})
    return history


def _cursor(message: dict) -> str:
    return f"{message['created_at']}|{message['message_id']}"


def test_get_messages_paginates_without_duplicates_or_gaps(c_store):
    """limit=10 逐页向前翻：无重复、无遗漏、每页时间正序、默认取最近 20 条。"""
    history = _seed_history(c_store, 25)

    latest = social.get_messages("buyer_1", "store_demo")
    assert [message["message_id"] for message in latest] == [
        item["message_id"] for item in history[-20:]
    ]

    pages: list[list[str]] = []
    seen: set[str] = set()
    before = None
    for _ in range(10):  # 上限防止实现有 bug 时死循环
        page = social.get_messages("buyer_1", "store_demo", limit=10, before=before)
        if not page:
            break
        ids = [message["message_id"] for message in page]
        # 页内按时间正序
        assert [message["created_at"] for message in page] == sorted(
            message["created_at"] for message in page
        )
        # 页间无重复
        assert not seen & set(ids)
        seen |= set(ids)
        pages.append(ids)
        before = _cursor(page[0])

    collected = [message_id for ids in reversed(pages) for message_id in ids]
    assert collected == [item["message_id"] for item in history]
    assert len(collected) == len(set(collected)) == 25


def test_get_messages_stable_order_when_timestamps_tie(c_store):
    """同一 created_at 的多条消息用 message_id 兜底排序，逐条翻页也不重不漏。"""
    tie_at = "2026-10-29T12:00:00+00:00"
    _insert_raw(c_store, "msg_tie_early", "2026-10-29T11:00:00+00:00", "更早")
    for suffix in ("a", "b", "c", "d"):
        _insert_raw(c_store, f"msg_tie_{suffix}", tie_at, f"同时间{suffix}")
    _insert_raw(c_store, "msg_tie_late", "2026-10-29T13:00:00+00:00", "更晚")

    collected = []
    before = None
    for _ in range(20):
        page = social.get_messages("buyer_1", "store_demo", limit=1, before=before)
        if not page:
            break
        collected.append(page[0]["message_id"])
        before = _cursor(page[0])

    # 逐条向前翻页，收集到的是从新到旧；反转后应与全局时间正序一致。
    assert list(reversed(collected)) == [
        "msg_tie_early",
        "msg_tie_a",
        "msg_tie_b",
        "msg_tie_c",
        "msg_tie_d",
        "msg_tie_late",
    ]


def test_get_messages_accepts_legacy_timestamp_cursor(c_store):
    """旧调用方只传 created_at 的 before 仍然可用（兼容 companion 分页模式）。"""
    _seed_history(c_store, 6)
    latest = social.get_messages("buyer_1", "store_demo", limit=2)
    assert [message["message_id"] for message in latest] == [
        "msg_history_0004",
        "msg_history_0005",
    ]

    older = social.get_messages(
        "buyer_1", "store_demo", limit=10, before=latest[0]["created_at"]
    )
    assert [message["message_id"] for message in older] == [
        "msg_history_0000",
        "msg_history_0001",
        "msg_history_0002",
        "msg_history_0003",
    ]


def test_get_messages_tolerates_invalid_cursor(c_store):
    """空游标按“最新一页”处理；非法游标返回空页而不是抛异常。"""
    _seed_history(c_store, 3)
    assert len(social.get_messages("buyer_1", "store_demo", before="")) == 3
    assert len(social.get_messages("buyer_1", "store_demo", before="   ")) == 3
    assert social.get_messages("buyer_1", "store_demo", before="not-a-cursor") == []
    assert social.get_messages("buyer_1", "store_demo", before="bad|msg_x") == []
    # 缺 message_id 的合并游标退化成 created_at 兼容模式。
    fallback = social.get_messages(
        "buyer_1", "store_demo", before="2026-10-29T10:01:00+00:00|"
    )
    assert [message["message_id"] for message in fallback] == ["msg_history_0000"]

    # 未知好友仍然抛业务错误，不被游标容错吞掉。
    with pytest.raises(store.CStoreError) as exc:
        social.get_messages("buyer_1", "nobody", before="not-a-cursor")
    assert exc.value.code == "FRIEND_NOT_FOUND"


def test_get_messages_clamps_limit(c_store):
    _seed_history(c_store, 5)
    assert len(social.get_messages("buyer_1", "store_demo", limit=0)) == 1
    assert len(social.get_messages("buyer_1", "store_demo", limit=9999)) == 5
