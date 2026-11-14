"""C 端联系人增强：好友申请、群通知、会话偏好。

边界：
- 好友申请只做持久化与接受/拒绝，不在这里发消息或推送；
- 群通知是站内通知表，当前不产生系统群通知，等有 producer 再接；
- 会话偏好只存用户自己的置顶/免打扰/隐藏，不改变消息数据。
"""
from __future__ import annotations

import uuid
from typing import Any

from rag_demo.c_end import group, social, store

FRIEND_REQUEST_STATUSES = ("PENDING", "ACCEPTED", "REJECTED")
GROUP_NOTICE_STATUSES = ("UNREAD", "READ")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS c_friend_request (
    request_id     TEXT PRIMARY KEY,
    owner_id       TEXT NOT NULL,
    requester_id   TEXT NOT NULL,
    requester_name TEXT NOT NULL,
    requester_kind TEXT NOT NULL DEFAULT 'user',
    message        TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'PENDING',
    created_at     TEXT NOT NULL,
    resolved_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_c_friend_request_owner_status
    ON c_friend_request (owner_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS c_group_notice (
    notice_id  TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL,
    group_id   TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL DEFAULT 'group',
    title      TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'UNREAD',
    created_at TEXT NOT NULL,
    read_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_c_group_notice_owner_status
    ON c_group_notice (owner_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS c_conversation_pref (
    owner_id   TEXT NOT NULL,
    thread_id  TEXT NOT NULL,
    pinned     INTEGER NOT NULL DEFAULT 0,
    muted      INTEGER NOT NULL DEFAULT 0,
    hidden     INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (owner_id, thread_id)
);
"""


def init() -> None:
    """确保 C 端基础表和新增强表都存在。"""
    store.init()
    social.init()
    group.init()
    if store._cend_pg_enabled():
        store._ensure_pg_schema()
        return
    with store._DB_LOCK:
        conn = store._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()


def _clean_id(value: Any, label: str, max_len: int = 120) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_len:
        raise store.CStoreError("CONTACT_INVALID", f"{label}不能为空且不能超过 {max_len} 字")
    return text


def _clean_text(value: Any, label: str, max_len: int, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise store.CStoreError("CONTACT_INVALID", f"{label}不能为空")
    if len(text) > max_len:
        raise store.CStoreError("CONTACT_INVALID", f"{label}不能超过 {max_len} 字")
    return text


def _friend_request_payload(row) -> dict[str, Any]:
    payload = dict(row)
    payload["status"] = str(payload.get("status") or "PENDING").upper()
    return payload


def _get_friend_request(conn, owner_id: str, request_id: str):
    row = conn.execute(
        "SELECT * FROM c_friend_request WHERE owner_id = ? AND request_id = ?",
        (owner_id, request_id),
    ).fetchone()
    if row is None:
        raise store.CStoreError("FRIEND_REQUEST_NOT_FOUND", "好友申请不存在")
    return row


def create_friend_request(
    owner_id: str,
    requester_id: str,
    requester_name: str,
    *,
    requester_kind: str = "user",
    message: str = "",
    note: str = "",
) -> dict[str, Any]:
    """内部 producer 使用：给 owner 创建一条待处理好友申请。

    当前 C 端没有“其他用户发申请”的公开入口；后续真实 IM/B 端接入时复用本函数。
    """
    owner = _clean_id(owner_id, "接收人")
    requester = _clean_id(requester_id, "申请人")
    if owner == requester:
        raise store.CStoreError("CONTACT_INVALID", "不能给自己发好友申请")
    name = _clean_text(requester_name, "申请人名称", 120, required=True)
    kind = _clean_text(requester_kind, "申请人类型", 32) or "user"
    init()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM c_friend_request WHERE owner_id = ? AND requester_id = ? "
            "AND status = 'PENDING' ORDER BY created_at DESC LIMIT 1",
            (owner, requester),
        ).fetchone()
        if existing is not None:
            conn.commit()
            return _friend_request_payload(existing)
        request_id = f"fr_{uuid.uuid4().hex[:20]}"
        now = store._now()
        conn.execute(
            "INSERT INTO c_friend_request(request_id, owner_id, requester_id, requester_name, "
            "requester_kind, message, note, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)",
            (
                request_id,
                owner,
                requester,
                name,
                kind,
                _clean_text(message, "申请说明", 200),
                _clean_text(note, "备注", 120),
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM c_friend_request WHERE request_id = ?", (request_id,)
        ).fetchone()
        conn.commit()
        return _friend_request_payload(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_friend_requests(owner_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
    owner = _clean_id(owner_id, "接收人")
    status_value = str(status or "").strip().upper()
    if status_value and status_value not in FRIEND_REQUEST_STATUSES:
        raise store.CStoreError("CONTACT_INVALID", "好友申请状态不合法")
    init()
    conn = store._connect()
    try:
        if status_value:
            rows = conn.execute(
                "SELECT * FROM c_friend_request WHERE owner_id = ? AND status = ? "
                "ORDER BY created_at DESC LIMIT 100",
                (owner, status_value),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM c_friend_request WHERE owner_id = ? "
                "ORDER BY created_at DESC LIMIT 100",
                (owner,),
            ).fetchall()
        return [_friend_request_payload(row) for row in rows]
    finally:
        conn.close()


def resolve_friend_request(owner_id: str, request_id: str, *, accepted: bool) -> dict[str, Any]:
    owner = _clean_id(owner_id, "接收人")
    request = _clean_id(request_id, "申请 ID")
    init()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _get_friend_request(conn, owner, request)
        status = str(row["status"] or "").upper()
        if status == "PENDING":
            new_status = "ACCEPTED" if accepted else "REJECTED"
            conn.execute(
                "UPDATE c_friend_request SET status = ?, resolved_at = ? "
                "WHERE owner_id = ? AND request_id = ? AND status = 'PENDING'",
                (new_status, store._now(), owner, request),
            )
            conn.commit()
            should_add_friend = accepted
        elif status == "ACCEPTED" and accepted:
            conn.commit()
            should_add_friend = True
        else:
            conn.commit()
            should_add_friend = False
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # 单独连接执行加好友，避免在 c_friend_request 的写事务里嵌套开启
    # social 的新连接导致 SQLite database is locked。
    friend = None
    if should_add_friend:
        friend = social.add_friend(
            owner,
            str(row["requester_id"]),
            str(row["requester_name"]),
            str(row["requester_kind"] or "user"),
            str(row["note"] or ""),
        )

    conn = store._connect()
    try:
        latest = conn.execute(
            "SELECT * FROM c_friend_request WHERE owner_id = ? AND request_id = ?",
            (owner, request),
        ).fetchone()
        return {
            "request": _friend_request_payload(latest),
            "friend": friend,
        }
    finally:
        conn.close()


def create_group_notice(
    owner_id: str,
    title: str,
    *,
    group_id: str = "",
    kind: str = "group",
    content: str = "",
) -> dict[str, Any]:
    """内部 producer 使用：给当前用户写一条群通知。"""
    owner = _clean_id(owner_id, "接收人")
    title_value = _clean_text(title, "通知标题", 120, required=True)
    init()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        notice_id = f"gn_{uuid.uuid4().hex[:20]}"
        conn.execute(
            "INSERT INTO c_group_notice(notice_id, owner_id, group_id, kind, title, content, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'UNREAD', ?)",
            (
                notice_id,
                owner,
                _clean_text(group_id, "群 ID", 120),
                _clean_text(kind, "通知类型", 32) or "group",
                title_value,
                _clean_text(content, "通知内容", 1000),
                store._now(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM c_group_notice WHERE notice_id = ?", (notice_id,)
        ).fetchone()
        conn.commit()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_group_notices(
    owner_id: str,
    *,
    unread_only: bool = False,
    limit: int = 50,
) -> list[dict[str, Any]]:
    owner = _clean_id(owner_id, "接收人")
    bounded = max(1, min(int(limit or 50), 200))
    init()
    conn = store._connect()
    try:
        if unread_only:
            rows = conn.execute(
                "SELECT * FROM c_group_notice WHERE owner_id = ? AND status = 'UNREAD' "
                "ORDER BY created_at DESC LIMIT ?",
                (owner, bounded),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM c_group_notice WHERE owner_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (owner, bounded),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def mark_group_notice_read(owner_id: str, notice_id: str) -> dict[str, Any]:
    owner = _clean_id(owner_id, "接收人")
    notice = _clean_id(notice_id, "通知 ID")
    init()
    conn = store._connect()
    try:
        row = conn.execute(
            "SELECT * FROM c_group_notice WHERE owner_id = ? AND notice_id = ?",
            (owner, notice),
        ).fetchone()
        if row is None:
            raise store.CStoreError("GROUP_NOTICE_NOT_FOUND", "群通知不存在")
        if str(row["status"] or "").upper() != "READ":
            conn.execute(
                "UPDATE c_group_notice SET status = 'READ', read_at = ? "
                "WHERE owner_id = ? AND notice_id = ?",
                (store._now(), owner, notice),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM c_group_notice WHERE owner_id = ? AND notice_id = ?",
                (owner, notice),
            ).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_conversation_prefs(owner_id: str) -> list[dict[str, Any]]:
    owner = _clean_id(owner_id, "用户")
    init()
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM c_conversation_pref WHERE owner_id = ? ORDER BY updated_at DESC",
            (owner,),
        ).fetchall()
        return [
            {
                "thread_id": row["thread_id"],
                "pinned": bool(row["pinned"]),
                "muted": bool(row["muted"]),
                "hidden": bool(row["hidden"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def update_conversation_pref(
    owner_id: str,
    thread_id: str,
    *,
    pinned: bool | None = None,
    muted: bool | None = None,
    hidden: bool | None = None,
) -> dict[str, Any]:
    owner = _clean_id(owner_id, "用户")
    thread = _clean_id(thread_id, "会话 ID")
    init()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM c_conversation_pref WHERE owner_id = ? AND thread_id = ?",
            (owner, thread),
        ).fetchone()
        current_pinned = bool(row["pinned"]) if row else False
        current_muted = bool(row["muted"]) if row else False
        current_hidden = bool(row["hidden"]) if row else False
        next_pinned = current_pinned if pinned is None else bool(pinned)
        next_muted = current_muted if muted is None else bool(muted)
        next_hidden = current_hidden if hidden is None else bool(hidden)
        now = store._now()
        conn.execute(
            "INSERT INTO c_conversation_pref(owner_id, thread_id, pinned, muted, hidden, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(owner_id, thread_id) DO UPDATE SET "
            "pinned = excluded.pinned, muted = excluded.muted, hidden = excluded.hidden, "
            "updated_at = excluded.updated_at",
            (owner, thread, int(next_pinned), int(next_muted), int(next_hidden), now),
        )
        conn.commit()
        return {
            "thread_id": thread,
            "pinned": next_pinned,
            "muted": next_muted,
            "hidden": next_hidden,
            "updated_at": now,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
