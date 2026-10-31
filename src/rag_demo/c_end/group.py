"""C 端群聊 v1：默认徒步群 + 多成员 @。

范围：
- 群/成员持久化；
- 群消息 HTTP；
- 一条消息可 @ 多个成员，按 mention 顺序触发对应成员回复；
- 不做群未读、群文件、WebSocket 群推送。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from rag_demo.c_end import companion_agent, mentions, store, store_agent

DEFAULT_GROUP_ID = "group_demo"
DEFAULT_GROUP_NAME = "周末徒步群"
KNOWN_MEMBERS: dict[str, dict[str, str]] = {
    "companion": {"member_id": "companion", "name": "小鱼", "kind": "companion"},
    "store_demo": {"member_id": "store_demo", "name": "山野店宠", "kind": "merchant"},
    "friend_demo": {"member_id": "friend_demo", "name": "小满", "kind": "friend"},
}
DEFAULT_MEMBER_IDS = ("companion", "store_demo", "friend_demo")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS c_group (
    group_id   TEXT NOT NULL,
    owner_id   TEXT NOT NULL,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, group_id)
);

CREATE TABLE IF NOT EXISTS c_group_member (
    owner_id  TEXT NOT NULL,
    group_id  TEXT NOT NULL,
    member_id TEXT NOT NULL,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL,
    sort      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (owner_id, group_id, member_id)
);

CREATE TABLE IF NOT EXISTS c_group_message (
    message_id  TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL,
    group_id    TEXT NOT NULL,
    sender_id   TEXT NOT NULL,
    sender_name TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_c_group_message_owner_group
    ON c_group_message (owner_id, group_id, created_at);
"""


def init() -> None:
    store.init()
    with store._DB_LOCK:
        conn = store._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def _member_payload(row) -> dict[str, str]:
    return {
        "member_id": row["member_id"],
        "name": row["name"],
        "kind": row["kind"],
    }


def _group_payload(conn, owner_id: str, row) -> dict[str, Any]:
    members = conn.execute(
        "SELECT * FROM c_group_member WHERE owner_id = ? AND group_id = ? ORDER BY sort, member_id",
        (owner_id, row["group_id"]),
    ).fetchall()
    return {
        "group_id": row["group_id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "members": [_member_payload(member) for member in members],
    }


def _ensure_default_group(conn, owner_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO c_group(group_id, owner_id, name, created_at) VALUES (?, ?, ?, ?)",
        (DEFAULT_GROUP_ID, owner_id, DEFAULT_GROUP_NAME, store._now()),
    )
    for index, member_id in enumerate(DEFAULT_MEMBER_IDS):
        member = KNOWN_MEMBERS[member_id]
        conn.execute(
            "INSERT OR IGNORE INTO c_group_member(owner_id, group_id, member_id, name, kind, sort) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (owner_id, DEFAULT_GROUP_ID, member["member_id"], member["name"], member["kind"], index),
        )


def list_groups(owner_id: str) -> list[dict[str, Any]]:
    init()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_default_group(conn, owner_id)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM c_group WHERE owner_id = ? ORDER BY created_at ASC, group_id",
            (owner_id,),
        ).fetchall()
        return [_group_payload(conn, owner_id, row) for row in rows]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_group(owner_id: str, name: str, member_ids: list[str]) -> dict[str, Any]:
    init()
    clean_name = str(name or "").strip()
    if not clean_name or len(clean_name) > 40:
        raise store.CStoreError("INVALID_GROUP", "群名不能为空且不能超过 40 字")
    ids = [str(item).strip() for item in member_ids if str(item).strip()]
    if not ids:
        ids = list(DEFAULT_MEMBER_IDS)
    if len(ids) > 20:
        raise store.CStoreError("INVALID_GROUP", "群成员不能超过 20 人")
    unknown = [item for item in ids if item not in KNOWN_MEMBERS]
    if unknown:
        raise store.CStoreError("INVALID_GROUP", "群成员不合法")
    group_id = f"group_{uuid.uuid4().hex[:16]}"
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO c_group(group_id, owner_id, name, created_at) VALUES (?, ?, ?, ?)",
            (group_id, owner_id, clean_name, store._now()),
        )
        for index, member_id in enumerate(dict.fromkeys(ids)):
            member = KNOWN_MEMBERS[member_id]
            conn.execute(
                "INSERT INTO c_group_member(owner_id, group_id, member_id, name, kind, sort) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (owner_id, group_id, member["member_id"], member["name"], member["kind"], index),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return next(group for group in list_groups(owner_id) if group["group_id"] == group_id)


def get_group(owner_id: str, group_id: str) -> dict[str, Any]:
    for group in list_groups(owner_id):
        if group["group_id"] == group_id:
            return group
    raise store.CStoreError("GROUP_NOT_FOUND", "群不存在")


def list_messages(owner_id: str, group_id: str, *, limit: int = 30, before: str | None = None) -> list[dict[str, Any]]:
    init()
    conn = store._connect()
    try:
        group = conn.execute(
            "SELECT * FROM c_group WHERE owner_id = ? AND group_id = ?",
            (owner_id, group_id),
        ).fetchone()
        if group is None:
            raise store.CStoreError("GROUP_NOT_FOUND", "群不存在")
        params: list[Any] = [owner_id, group_id]
        where = "owner_id = ? AND group_id = ?"
        if before:
            where += " AND created_at < ?"
            params.append(str(before))
        params.append(max(1, min(int(limit), 100)))
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM c_group_message WHERE "
            f"{where} ORDER BY created_at DESC LIMIT ?) ORDER BY created_at ASC",
            params,
        ).fetchall()
        return [
            {
                "message_id": row["message_id"],
                "group_id": row["group_id"],
                "sender_id": row["sender_id"],
                "sender_name": row["sender_name"],
                "content": row["content"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def _insert_message(
    conn,
    *,
    owner_id: str,
    group_id: str,
    sender_id: str,
    sender_name: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message_id = f"gmsg_{uuid.uuid4().hex[:20]}"
    created_at = store._next_message_time()
    meta = mentions.attach_metadata(metadata, content)
    conn.execute(
        "INSERT INTO c_group_message(message_id, owner_id, group_id, sender_id, sender_name, "
        "content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (message_id, owner_id, group_id, sender_id, sender_name, content, json.dumps(meta, ensure_ascii=False), created_at),
    )
    return {
        "message_id": message_id,
        "group_id": group_id,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "content": content,
        "metadata": meta,
        "created_at": created_at,
    }


def _companion_group_reply(owner_id: str) -> str:
    try:
        name = store.get_companion(owner_id).get("name") or "小鱼"
    except Exception:
        name = "小鱼"
    return f"{name}：我看到了。价格、优惠和售后以商家/结算页为准，需要确认的我来帮你记。"


def send_message(owner_id: str, group_id: str, content: str) -> dict[str, Any]:
    init()
    text = str(content or "").strip()
    if not text:
        raise store.CStoreError("EMPTY_MESSAGE", "消息不能为空")
    if len(text) > 1000:
        raise store.CStoreError("MESSAGE_TOO_LONG", "消息不能超过 1000 字")
    group = get_group(owner_id, group_id)
    member_by_id = {member["member_id"]: member for member in group["members"]}
    mentioned = [
        mention for mention in mentions.extract_mentions(text)
        if mention["target_id"] in member_by_id
    ]
    replies: list[dict[str, Any]] = []
    for mention in mentioned:
        target = member_by_id[mention["target_id"]]
        if target["kind"] == "merchant":
            reply = store_agent.reply_with_meta(owner_id, text)
            reply_text = str(reply.text)
            metadata = dict(reply.metadata or {})
            if metadata.get("quote_id"):
                try:
                    store.create_quote(owner_id, group_id, metadata)
                except Exception:  # noqa: BLE001
                    pass
        elif target["kind"] == "companion":
            reply_text = _companion_group_reply(owner_id)
            metadata = {}
        else:
            reply_text = "小满：收到，等你们聊完我补充。"
            metadata = {}
        replies.append({
            "sender_id": target["member_id"],
            "sender_name": target["name"],
            "content": reply_text,
            "metadata": metadata,
        })

    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        message = _insert_message(
            conn,
            owner_id=owner_id,
            group_id=group_id,
            sender_id=owner_id,
            sender_name="我",
            content=text,
        )
        stored_replies = [
            _insert_message(
                conn,
                owner_id=owner_id,
                group_id=group_id,
                sender_id=reply["sender_id"],
                sender_name=reply["sender_name"],
                content=reply["content"],
                metadata=reply["metadata"],
            )
            for reply in replies
        ]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"message": message, "replies": stored_replies}
