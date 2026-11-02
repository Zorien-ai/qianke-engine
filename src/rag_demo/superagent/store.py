"""Super-agent 持久化：Trigger / Thread / WorkItem / Approval。

复用 C 端 SQLite 作为控制面存储；不存任何商家订单正文，只存事件与 Worker 结论。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from rag_demo.c_end import store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sa_thread (
    thread_id   TEXT PRIMARY KEY,
    channel     TEXT NOT NULL,
    thread_key  TEXT NOT NULL,
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'OPEN',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sa_thread_key
    ON sa_thread (thread_key);

CREATE TABLE IF NOT EXISTS sa_trigger (
    trigger_id  TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    source      TEXT NOT NULL,
    channel     TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'ACCEPTED',
    created_at  TEXT NOT NULL,
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sa_trigger_thread
    ON sa_trigger (thread_id, created_at);

CREATE TABLE IF NOT EXISTS sa_work_item (
    work_item_id TEXT PRIMARY KEY,
    thread_id    TEXT NOT NULL,
    title        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'PENDING',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT,
    result_json  TEXT NOT NULL DEFAULT '{}',
    error        TEXT,
    approval_status TEXT NOT NULL DEFAULT 'NONE'
);

CREATE INDEX IF NOT EXISTS idx_sa_work_item_status
    ON sa_work_item (status, created_at DESC);

CREATE TABLE IF NOT EXISTS sa_approval (
    approval_id  TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'PENDING',
    note         TEXT,
    created_at   TEXT NOT NULL,
    decided_at   TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sa_approval_work_item
    ON sa_approval (work_item_id);
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


def _now() -> str:
    return store._now()


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def create_trigger(
    *,
    source: str,
    content: str,
    channel: str = "manual",
    thread_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """写入事件并归并到 Thread；同一 thread_key 的连续事件复用 Thread。"""
    init()
    thread_key = (thread_key or f"{source}:{channel}:default").strip() or "default"
    now = _now()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        thread = conn.execute(
            "SELECT * FROM sa_thread WHERE thread_key = ?", (thread_key,)
        ).fetchone()
        if thread is None:
            thread_id = f"sat_{uuid.uuid4().hex[:16]}"
            title = content.strip().replace("\n", " ")[:60] or "外部事件"
            conn.execute(
                "INSERT INTO sa_thread(thread_id, channel, thread_key, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'OPEN', ?, ?)",
                (thread_id, channel, thread_key, title, now, now),
            )
        else:
            thread_id = thread["thread_id"]
            conn.execute(
                "UPDATE sa_thread SET updated_at = ? WHERE thread_id = ?", (now, thread_id)
            )
        trigger_id = f"satr_{uuid.uuid4().hex[:16]}"
        conn.execute(
            "INSERT INTO sa_trigger(trigger_id, thread_id, source, channel, content, "
            "metadata_json, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'ACCEPTED', ?)",
            (trigger_id, thread_id, source, channel, content, _json(metadata), now),
        )
        # 同一 Thread 已有活跃工作项时，只追加 Trigger，不重复建工作项。
        active = conn.execute(
            "SELECT * FROM sa_work_item WHERE thread_id = ? AND status IN "
            "('PENDING','RUNNING','WAITING_APPROVAL') ORDER BY created_at DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        created = False
        if active is None:
            work_item_id = f"saw_{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT INTO sa_work_item(work_item_id, thread_id, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'PENDING', ?, ?)",
                (work_item_id, thread_id, title, now, now),
            )
            created = True
        else:
            work_item_id = active["work_item_id"]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "trigger": get_trigger(trigger_id),
        "thread": get_thread(thread_id),
        "work_item": get_work_item(work_item_id),
        "created_work_item": created,
    }


def get_trigger(trigger_id: str) -> dict[str, Any] | None:
    init()
    conn = store._connect()
    try:
        row = conn.execute(
            "SELECT * FROM sa_trigger WHERE trigger_id = ?", (trigger_id,)
        ).fetchone()
        return _trigger_payload(row) if row else None
    finally:
        conn.close()


def get_thread(thread_id: str) -> dict[str, Any] | None:
    init()
    conn = store._connect()
    try:
        row = conn.execute(
            "SELECT * FROM sa_thread WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            return None
        triggers = conn.execute(
            "SELECT * FROM sa_trigger WHERE thread_id = ? ORDER BY created_at ASC",
            (thread_id,),
        ).fetchall()
        return {
            "thread_id": row["thread_id"],
            "channel": row["channel"],
            "thread_key": row["thread_key"],
            "title": row["title"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "triggers": [_trigger_payload(item) for item in triggers],
        }
    finally:
        conn.close()


def list_threads(limit: int = 50) -> list[dict[str, Any]]:
    init()
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sa_thread ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        return [
            {
                "thread_id": row["thread_id"],
                "channel": row["channel"],
                "thread_key": row["thread_key"],
                "title": row["title"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def list_work_items(limit: int = 50) -> list[dict[str, Any]]:
    init()
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sa_work_item ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        ).fetchall()
        return [_work_item_payload(row) for row in rows]
    finally:
        conn.close()


def get_work_item(work_item_id: str) -> dict[str, Any] | None:
    init()
    conn = store._connect()
    try:
        row = conn.execute(
            "SELECT * FROM sa_work_item WHERE work_item_id = ?", (work_item_id,)
        ).fetchone()
        if row is None:
            return None
        item = _work_item_payload(row)
        triggers = conn.execute(
            "SELECT * FROM sa_trigger WHERE thread_id = ? ORDER BY created_at ASC",
            (row["thread_id"],),
        ).fetchall()
        item["triggers"] = [_trigger_payload(t) for t in triggers]
        return item
    finally:
        conn.close()


def start_work_item(work_item_id: str) -> dict[str, Any]:
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute(
            "UPDATE sa_work_item SET status = 'RUNNING', started_at = COALESCE(started_at, ?), "
            "updated_at = ?, error = NULL "
            "WHERE work_item_id = ? AND status IN ('PENDING', 'RUNNING')",
            (now, now, work_item_id),
        )
        conn.commit()
    finally:
        conn.close()
    item = get_work_item(work_item_id)
    if item is None:
        raise store.CStoreError("SA_WORK_ITEM_NOT_FOUND", "工作项不存在")
    return item


def finish_work_item(work_item_id: str, result: dict[str, Any], *, approval: bool = True) -> dict[str, Any]:
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE sa_work_item SET status = CASE WHEN ? THEN 'WAITING_APPROVAL' ELSE 'DONE' END, "
            "updated_at = ?, finished_at = ?, result_json = ?, approval_status = ? "
            "WHERE work_item_id = ?",
            (1 if approval else 0, now, now, _json(result), "PENDING" if approval else "NONE", work_item_id),
        )
        if approval:
            approval_id = f"saa_{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT OR REPLACE INTO sa_approval(approval_id, work_item_id, status, created_at) "
                "VALUES (?, ?, 'PENDING', ?)",
                (approval_id, work_item_id, now),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_work_item(work_item_id) or {}


def fail_work_item(work_item_id: str, error: str) -> dict[str, Any]:
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute(
            "UPDATE sa_work_item SET status = 'FAILED', error = ?, updated_at = ?, finished_at = ? "
            "WHERE work_item_id = ?",
            (str(error)[:2000], now, now, work_item_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_work_item(work_item_id) or {}


def decide_approval(work_item_id: str, *, approved: bool, note: str = "") -> dict[str, Any]:
    init()
    now = _now()
    status = "APPROVED" if approved else "REJECTED"
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE sa_approval SET status = ?, note = ?, decided_at = ? "
            "WHERE work_item_id = ? AND status = 'PENDING'",
            (status, str(note)[:1000], now, work_item_id),
        )
        conn.execute(
            "UPDATE sa_work_item SET status = ?, approval_status = ?, updated_at = ? "
            "WHERE work_item_id = ?",
            ("DONE" if approved else "REJECTED", status, now, work_item_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_work_item(work_item_id) or {}


def scan_stuck_work_items(timeout_seconds: int = 180) -> list[dict[str, Any]]:
    """Watchdog：标记长时间 RUNNING 的工作项，不执行恢复写操作。"""
    init()
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(10, int(timeout_seconds)))).isoformat()
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sa_work_item WHERE status = 'RUNNING' AND started_at < ?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE sa_work_item SET status = 'STUCK', updated_at = ?, "
                "error = 'watchdog: running too long' WHERE work_item_id = ?",
                (_now(), row["work_item_id"]),
            )
        conn.commit()
        return [_work_item_payload(row) for row in rows]
    finally:
        conn.close()


def _trigger_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "trigger_id": row["trigger_id"],
        "thread_id": row["thread_id"],
        "source": row["source"],
        "channel": row["channel"],
        "content": row["content"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "status": row["status"],
        "created_at": row["created_at"],
        "processed_at": row["processed_at"],
    }


def _work_item_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "work_item_id": row["work_item_id"],
        "thread_id": row["thread_id"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "result": json.loads(row["result_json"] or "{}"),
        "error": row["error"],
        "approval_status": row["approval_status"],
    }
