# -*- coding: utf-8 -*-
"""对话历史：会话与消息的持久化（控制面库 rag_auth）。

为什么放控制面库而不是物理租户库：
- 租户库可能重建/清空，会话历史不应随之消失；
- 会话列表/删除/保留策略集中处理更简单；
- 仍然用 tenant_id + account_id 双过滤，隔离边界与 ai_monitor 一致。

⚠ 所有对外函数都必须带 tenant_id 与 account_id；不存在“只按 session_id 查”。
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any

import psycopg2
import psycopg2.extras

from rag_demo import auth

logger = logging.getLogger(__name__)

_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()

DDL = [
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id              TEXT PRIMARY KEY,
        tenant_id       TEXT NOT NULL,
        account_id      BIGINT NOT NULL,
        title           TEXT NOT NULL DEFAULT '新对话',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_message_at TIMESTAMPTZ,
        message_count   INTEGER NOT NULL DEFAULT 0,
        context_state   JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS context_state JSONB NOT NULL DEFAULT '{}'::jsonb",
    "CREATE INDEX IF NOT EXISTS chat_sessions_owner_time ON chat_sessions (tenant_id, account_id, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id                  TEXT PRIMARY KEY,
        session_id          TEXT NOT NULL REFERENCES chat_sessions (id) ON DELETE CASCADE,
        tenant_id           TEXT NOT NULL,
        account_id          BIGINT NOT NULL,
        turn_id             TEXT NOT NULL,
        role                TEXT NOT NULL,
        content             TEXT NOT NULL DEFAULT '',
        rewritten_question  TEXT,
        route               TEXT,
        sources             JSONB NOT NULL DEFAULT '[]'::jsonb,
        status              TEXT NOT NULL DEFAULT 'success',
        created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS chat_messages_session_time ON chat_messages (session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS chat_messages_owner_time ON chat_messages (tenant_id, account_id, created_at DESC)",
]


def _connect():
    return psycopg2.connect(**auth.PG_CONFIG)


def ensure_schema(conn=None) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        own = conn is None
        conn = conn or _connect()
        try:
            with conn.cursor() as cur:
                for statement in DDL:
                    cur.execute(statement)
            conn.commit()
            _SCHEMA_READY = True
        finally:
            if own:
                conn.close()


def _cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _iso(value):
    return value.isoformat() if value is not None else None


def _session(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "last_message_at": _iso(row["last_message_at"]),
        "message_count": int(row["message_count"] or 0),
    }


def _message(row) -> dict:
    sources = row["sources"] or []
    if not isinstance(sources, list):
        sources = []
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"] or "",
        "rewritten_question": row["rewritten_question"],
        "route": row["route"],
        "sources": sources,
        "status": row["status"],
        "created_at": _iso(row["created_at"]),
    }


def _title_from_question(content: str) -> str:
    text = " ".join((content or "").split())
    if not text:
        return "新对话"
    return text[:36] + ("…" if len(text) > 36 else "")


def create_session(tenant_id: str, account_id: int, title: str | None = None) -> dict:
    ensure_schema()
    sid = uuid.uuid4().hex
    clean_title = (title or "").strip()[:80] or "新对话"
    conn = _connect()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                """INSERT INTO chat_sessions (id, tenant_id, account_id, title)
                   VALUES (%s, %s, %s, %s) RETURNING *""",
                (sid, tenant_id, int(account_id), clean_title),
            )
            row = cur.fetchone()
        conn.commit()
        return _session(row)
    finally:
        conn.close()


def list_sessions(tenant_id: str, account_id: int, limit: int = 30) -> list[dict]:
    ensure_schema()
    limit = max(1, min(int(limit or 30), 100))
    conn = _connect()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                """SELECT * FROM chat_sessions
                   WHERE tenant_id=%s AND account_id=%s
                   ORDER BY updated_at DESC
                   LIMIT %s""",
                (tenant_id, int(account_id), limit),
            )
            return [_session(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_session(tenant_id: str, account_id: int, session_id: str) -> dict | None:
    ensure_schema()
    conn = _connect()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                """SELECT * FROM chat_sessions
                   WHERE id=%s AND tenant_id=%s AND account_id=%s""",
                (session_id, tenant_id, int(account_id)),
            )
            row = cur.fetchone()
            return _session(row) if row else None
    finally:
        conn.close()


def get_messages(tenant_id: str, account_id: int, session_id: str, limit: int = 200) -> list[dict]:
    ensure_schema()
    limit = max(1, min(int(limit or 200), 500))
    conn = _connect()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                """SELECT m.* FROM chat_messages m
                   JOIN chat_sessions s ON s.id = m.session_id
                   WHERE m.session_id=%s AND s.tenant_id=%s AND s.account_id=%s
                   ORDER BY m.created_at DESC
                   LIMIT %s""",
                (session_id, tenant_id, int(account_id), limit),
            )
            rows = cur.fetchall()
            rows.reverse()
            return [_message(row) for row in rows]
    finally:
        conn.close()


def load_recent(tenant_id: str, account_id: int, session_id: str, limit: int = 6) -> list[dict]:
    """最近 N 条消息（按时间正序），只给改写与上下文使用。"""
    return get_messages(tenant_id, account_id, session_id, limit=limit)


def rename_session(tenant_id: str, account_id: int, session_id: str, title: str) -> dict | None:
    ensure_schema()
    clean = " ".join((title or "").split())[:80]
    if not clean:
        raise ValueError("会话标题不能为空")
    conn = _connect()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                """UPDATE chat_sessions SET title=%s, updated_at=now()
                   WHERE id=%s AND tenant_id=%s AND account_id=%s RETURNING *""",
                (clean, session_id, tenant_id, int(account_id)),
            )
            row = cur.fetchone()
        conn.commit()
        return _session(row) if row else None
    finally:
        conn.close()


def delete_session(tenant_id: str, account_id: int, session_id: str) -> bool:
    ensure_schema()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chat_sessions WHERE id=%s AND tenant_id=%s AND account_id=%s",
                (session_id, tenant_id, int(account_id)),
            )
            deleted = cur.rowcount > 0
        conn.commit()
        return deleted
    finally:
        conn.close()


def append_message(
    tenant_id: str,
    account_id: int,
    session_id: str,
    turn_id: str,
    role: str,
    content: str,
    *,
    rewritten_question: str | None = None,
    route: str | None = None,
    sources: list | None = None,
    status: str = "success",
) -> bool:
    """追加一条消息；会话不属于该账号时返回 False，调用方不能借此写别人的会话。"""
    ensure_schema()
    conn = _connect()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT title FROM chat_sessions WHERE id=%s AND tenant_id=%s AND account_id=%s",
                (session_id, tenant_id, int(account_id)),
            )
            session = cur.fetchone()
            if session is None:
                conn.rollback()
                return False
            payload = json.dumps(sources or [], ensure_ascii=False, default=str)
            cur.execute(
                """INSERT INTO chat_messages
                   (id, session_id, tenant_id, account_id, turn_id, role, content,
                    rewritten_question, route, sources, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                (
                    uuid.uuid4().hex, session_id, tenant_id, int(account_id), turn_id,
                    role, content or "", rewritten_question, route, payload, status,
                ),
            )
            title = session["title"]
            if role == "user" and title in ("", "新对话"):
                cur.execute(
                    "UPDATE chat_sessions SET title=%s WHERE id=%s",
                    (_title_from_question(content), session_id),
                )
            cur.execute(
                """UPDATE chat_sessions
                   SET updated_at=now(), last_message_at=now(),
                       message_count=message_count+1
                   WHERE id=%s""",
                (session_id,),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def get_context_state(tenant_id: str, account_id: int, session_id: str) -> dict:
    """读取会话的长期摘要 / 实体状态（JSON）。不可用时返回空状态，不阻断问答。"""
    try:
        ensure_schema()
        conn = _connect()
        try:
            with _cursor(conn) as cur:
                cur.execute(
                    """SELECT context_state FROM chat_sessions
                       WHERE id=%s AND tenant_id=%s AND account_id=%s""",
                    (session_id, tenant_id, int(account_id)),
                )
                row = cur.fetchone()
                if row is None:
                    return {}
                state = row.get("context_state") or {}
                return state if isinstance(state, dict) else {}
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 记忆读取失败只降级，不能阻断当前对话
        logger.exception("读取会话记忆失败 session=%s", session_id)
        return {}


def update_context_state(tenant_id: str, account_id: int, session_id: str, state: dict) -> None:
    """写入长期摘要 / 实体状态；仅允许更新当前账号自己的会话。"""
    ensure_schema()
    payload = json.dumps(state or {}, ensure_ascii=False, default=str)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE chat_sessions SET context_state=%s::jsonb
                   WHERE id=%s AND tenant_id=%s AND account_id=%s""",
                (payload, session_id, tenant_id, int(account_id)),
            )
        conn.commit()
    finally:
        conn.close()
