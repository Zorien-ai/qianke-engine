"""C 端 IM 社交壳（MVP mock）。

第一版只解决：
- 好友列表（含 mock 店宠）
- 单聊消息持久化
- WebSocket / HTTP 双入口
- 店宠 @ 唤醒的确定性 mock 回复

不做真实双人推送、商家 Agent 实盘接入；这些在下一阶段换真实消息总线。
"""
from __future__ import annotations

import uuid
from typing import Any

from rag_demo.c_end import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS c_friend (
    owner_id   TEXT NOT NULL,
    friend_id  TEXT NOT NULL,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, friend_id)
);

CREATE TABLE IF NOT EXISTS c_message (
    message_id TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL,
    friend_id  TEXT NOT NULL,
    sender_id  TEXT NOT NULL,
    receiver_id TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_message_owner_friend
    ON c_message (owner_id, friend_id, created_at);
"""


def init() -> None:
    with store._DB_LOCK:
        conn = store._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def _ensure_friends(conn, owner_id: str) -> None:
    seeds = [
        ("store_demo", "山野户外旗舰店", "merchant", "品牌店宠 · 售前/售后/砍价"),
        ("friend_demo", "小满", "user", "好友 · 周末徒步搭子"),
    ]
    for friend_id, name, kind, note in seeds:
        conn.execute(
            "INSERT OR IGNORE INTO c_friend(owner_id, friend_id, name, kind, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (owner_id, friend_id, name, kind, note, store._now()),
        )


def list_friends(owner_id: str) -> list[dict[str, Any]]:
    init()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_friends(conn, owner_id)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM c_friend WHERE owner_id = ? "
            "ORDER BY CASE kind WHEN 'merchant' THEN 0 ELSE 1 END, name",
            (owner_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _friend(conn, owner_id: str, friend_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM c_friend WHERE owner_id = ? AND friend_id = ?",
        (owner_id, friend_id),
    ).fetchone()
    return dict(row) if row else None


def get_messages(owner_id: str, friend_id: str, limit: int = 50) -> list[dict[str, Any]]:
    init()
    conn = store._connect()
    try:
        _ensure_friends(conn, owner_id)
        conn.commit()
        if _friend(conn, owner_id, friend_id) is None:
            raise store.CStoreError("FRIEND_NOT_FOUND", "好友不存在")
        rows = conn.execute(
            "SELECT * FROM c_message WHERE owner_id = ? AND friend_id = ? "
            "ORDER BY created_at ASC LIMIT ?",
            (owner_id, friend_id, max(1, min(int(limit), 200))),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _insert_message(conn, *, owner_id: str, friend_id: str, sender_id: str, receiver_id: str, content: str) -> dict[str, Any]:
    message_id = f"msg_{uuid.uuid4().hex[:20]}"
    created_at = store._now()
    conn.execute(
        "INSERT INTO c_message(message_id, owner_id, friend_id, sender_id, receiver_id, content, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (message_id, owner_id, friend_id, sender_id, receiver_id, content, created_at),
    )
    return {
        "message_id": message_id,
        "owner_id": owner_id,
        "friend_id": friend_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "content": content,
        "created_at": created_at,
    }


def _mock_store_reply(content: str) -> tuple[str, bool]:
    text = content.strip()
    if "@店宠" not in text and "店宠" not in text:
        return "（店宠未被唤醒：请 @店宠 并说明售前、售后或砍价需求）", False
    if "砍价" in text or "优惠" in text or "券" in text:
        return "喵~ 收到砍价请求。当前是 mock 店宠，优惠需要用户确认后才会生效。", True
    return "喵~ 店宠已收到你的问题，当前是 mock 回复，后续接入商家 Agent 后会查商品库和 SOP。", True


def send_message(owner_id: str, friend_id: str, content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise store.CStoreError("EMPTY_MESSAGE", "消息不能为空")
    if len(text) > 1000:
        raise store.CStoreError("MESSAGE_TOO_LONG", "消息不能超过 1000 字")

    init()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_friends(conn, owner_id)
        friend = _friend(conn, owner_id, friend_id)
        if friend is None:
            raise store.CStoreError("FRIEND_NOT_FOUND", "好友不存在")

        owner_message = _insert_message(
            conn,
            owner_id=owner_id,
            friend_id=friend_id,
            sender_id=owner_id,
            receiver_id=friend_id,
            content=text,
        )
        reply = None
        if friend["kind"] == "merchant":
            reply_text, awakened = _mock_store_reply(text)
            reply = _insert_message(
                conn,
                owner_id=owner_id,
                friend_id=friend_id,
                sender_id=friend_id,
                receiver_id=owner_id,
                content=reply_text,
            )
            reply["awakened"] = awakened
        conn.commit()
        return {"message": owner_message, "reply": reply}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
