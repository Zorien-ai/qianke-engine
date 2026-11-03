"""Super-agent 持久化：Trigger / Thread / WorkItem / Approval。

复用 C 端 SQLite 作为控制面存储；不存任何商家订单正文，只存事件与 Worker 结论。
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from typing import Any

from rag_demo.c_end import store

DEFAULT_MERCHANT_ID = "m_gear_002"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sa_thread (
    thread_id   TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL DEFAULT 'm_gear_002',
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
    merchant_id  TEXT NOT NULL DEFAULT 'm_gear_002',
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
    decided_at   TEXT,
    action_json  TEXT NOT NULL DEFAULT '{}',
    execution_status TEXT NOT NULL DEFAULT 'NONE',
    execution_result_json TEXT NOT NULL DEFAULT '{}',
    executed_at  TEXT,
    idempotency_key TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sa_approval_work_item
    ON sa_approval (work_item_id);

CREATE TABLE IF NOT EXISTS sa_job (
    job_id       TEXT PRIMARY KEY,
    work_item_id TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'WORKER',
    status       TEXT NOT NULL DEFAULT 'PENDING',
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    available_at TEXT NOT NULL,
    lease_until  TEXT,
    worker_id    TEXT,
    last_error   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sa_job_work_item
    ON sa_job (work_item_id, kind);

CREATE INDEX IF NOT EXISTS idx_sa_job_claim
    ON sa_job (status, available_at);
"""

_APPROVAL_MIGRATIONS = (
    ("action_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("execution_status", "TEXT NOT NULL DEFAULT 'NONE'"),
    ("execution_result_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("executed_at", "TEXT"),
    ("idempotency_key", "TEXT"),
    ("card_send_response_code", "TEXT"),
    ("card_event_response_code", "TEXT"),
)


def init() -> None:
    store.init()
    with store._DB_LOCK:
        conn = store._connect()
        try:
            conn.executescript(_SCHEMA)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(sa_approval)").fetchall()
            }
            for name, ddl in _APPROVAL_MIGRATIONS:
                if name not in columns:
                    conn.execute(f"ALTER TABLE sa_approval ADD COLUMN {name} {ddl}")
            for table in ("sa_thread", "sa_work_item"):
                cols = {
                    row["name"]
                    for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                }
                if "merchant_id" not in cols:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN merchant_id TEXT NOT NULL DEFAULT 'm_gear_002'"
                    )
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
    merchant_id: str = DEFAULT_MERCHANT_ID,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """写入事件并归并到 Thread；租户通过 merchant_id 隔离。"""
    init()
    merchant_id = (merchant_id or DEFAULT_MERCHANT_ID).strip() or DEFAULT_MERCHANT_ID
    raw_key = (thread_key or f"{source}:{channel}:default").strip() or "default"
    # 默认租户保持历史 key；非默认租户加前缀，避免跨商家碰撞。
    thread_key = raw_key if merchant_id == DEFAULT_MERCHANT_ID else f"{merchant_id}:{raw_key}"
    now = _now()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        thread = conn.execute(
            "SELECT * FROM sa_thread WHERE thread_key = ?", (thread_key,)
        ).fetchone()
        title = content.strip().replace("\n", " ")[:60] or "外部事件"
        if thread is not None and thread["merchant_id"] != merchant_id:
            raise store.CStoreError("SA_TENANT_MISMATCH", "Thread 不属于当前商家")
        if thread is None:
            thread_id = f"sat_{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT INTO sa_thread(thread_id, merchant_id, channel, thread_key, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?)",
                (thread_id, merchant_id, channel, thread_key, title, now, now),
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
            "SELECT * FROM sa_work_item WHERE thread_id = ? AND merchant_id = ? AND status IN "
            "('PENDING','RUNNING','WAITING_APPROVAL') ORDER BY created_at DESC LIMIT 1",
            (thread_id, merchant_id),
        ).fetchone()
        created = False
        if active is None:
            work_item_id = f"saw_{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT INTO sa_work_item(work_item_id, thread_id, merchant_id, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'PENDING', ?, ?)",
                (work_item_id, thread_id, merchant_id, title, now, now),
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
            "merchant_id": row["merchant_id"],
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


def list_threads(limit: int = 50, merchant_id: str | None = None) -> list[dict[str, Any]]:
    init()
    where = ""
    params: list[Any] = []
    if merchant_id:
        where = "WHERE merchant_id = ?"
        params.append(merchant_id)
    params.append(max(1, min(int(limit), 200)))
    conn = store._connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM sa_thread {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            {
                "thread_id": row["thread_id"],
                "merchant_id": row["merchant_id"],
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


def list_work_items(limit: int = 50, merchant_id: str | None = None) -> list[dict[str, Any]]:
    init()
    where = ""
    params: list[Any] = []
    if merchant_id:
        where = "WHERE merchant_id = ?"
        params.append(merchant_id)
    params.append(max(1, min(int(limit), 200)))
    conn = store._connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM sa_work_item {where} ORDER BY created_at DESC LIMIT ?",
            params,
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
        approval = conn.execute(
            "SELECT * FROM sa_approval WHERE work_item_id = ?", (work_item_id,)
        ).fetchone()
        item["approval"] = _approval_payload(approval) if approval else None
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


def finish_work_item(
    work_item_id: str,
    result: dict[str, Any],
    *,
    approval: bool = True,
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE sa_work_item SET status = CASE WHEN ? THEN 'WAITING_APPROVAL' ELSE 'DONE' END, "
            "updated_at = ?, finished_at = ?, result_json = ?, approval_status = ? "
            "WHERE work_item_id = ? AND status = 'RUNNING'",
            (1 if approval else 0, now, now, _json(result), "PENDING" if approval else "NONE", work_item_id),
        )
        if approval:
            approval_id = f"saa_{uuid.uuid4().hex[:16]}"
            conn.execute(
                "INSERT OR REPLACE INTO sa_approval(approval_id, work_item_id, status, created_at, action_json) "
                "VALUES (?, ?, 'PENDING', ?, ?)",
                (approval_id, work_item_id, now, _json(action or {})),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_work_item(work_item_id) or {}


def cancel_work_item(work_item_id: str, note: str = "cancelled by user") -> dict[str, Any]:
    """取消 PENDING/RUNNING 工作项；Worker 结束后不会再覆盖取消状态。"""
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute(
            "UPDATE sa_work_item SET status = 'CANCELLED', error = ?, updated_at = ?, finished_at = ? "
            "WHERE work_item_id = ? AND status IN ('PENDING', 'RUNNING')",
            (str(note)[:1000], now, now, work_item_id),
        )
        conn.commit()
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
            ("EXECUTING" if approved else "REJECTED", status, now, work_item_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_work_item(work_item_id) or {}


def complete_execution(
    work_item_id: str,
    *,
    success: bool,
    result: dict[str, Any],
    error: str = "",
) -> dict[str, Any]:
    """记录审批动作执行结果；失败不回滚已成功的外部动作，由审计和人工处理。"""
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE sa_approval SET execution_status = ?, execution_result_json = ?, "
            "executed_at = ? WHERE work_item_id = ?",
            ("EXECUTED" if success else "FAILED", _json(result), now, work_item_id),
        )
        conn.execute(
            "UPDATE sa_work_item SET status = ?, updated_at = ?, finished_at = ?, "
            "result_json = json_set(result_json, '$.execution', json(?)), "
            "error = ? WHERE work_item_id = ?",
            (
                "DONE" if success else "EXECUTION_FAILED",
                now,
                now,
                _json({"success": success, **result, "error": error}),
                (str(error)[:2000] or None) if not success else None,
                work_item_id,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_work_item(work_item_id) or {}


def get_approval(work_item_id: str) -> dict[str, Any] | None:
    init()
    conn = store._connect()
    try:
        row = conn.execute(
            "SELECT * FROM sa_approval WHERE work_item_id = ?", (work_item_id,)
        ).fetchone()
        return _approval_payload(row) if row else None
    finally:
        conn.close()


def set_card_response_code(work_item_id: str, code: str, *, source: str = "send") -> None:
    """保存发送卡片返回的 response_code，用于动作完成后二次更新卡片。"""
    column = "card_event_response_code" if source == "event" else "card_send_response_code"
    value = str(code or "").strip()
    if not value:
        return
    init()
    conn = store._connect()
    try:
        conn.execute(
            f"UPDATE sa_approval SET {column} = ? WHERE work_item_id = ?",
            (value, work_item_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_card_response_codes(work_item_id: str) -> dict[str, str]:
    init()
    conn = store._connect()
    try:
        row = conn.execute(
            "SELECT card_send_response_code, card_event_response_code "
            "FROM sa_approval WHERE work_item_id = ?",
            (work_item_id,),
        ).fetchone()
        if row is None:
            return {}
        return {
            "send": str(row["card_send_response_code"] or ""),
            "event": str(row["card_event_response_code"] or ""),
        }
    finally:
        conn.close()


def list_action_audit(
    merchant_id: str,
    limit: int = 100,
    offset: int = 0,
    *,
    action_type: str = "",
    execution_status: str = "",
    q: str = "",
) -> dict[str, Any]:
    """动作执行审计：支持动作/执行状态/关键词过滤与分页。"""
    init()
    where = ["w.merchant_id = ?", "a.action_json != '{}'"]
    params: list[Any] = [str(merchant_id or "").strip()]
    if action_type:
        where.append("json_extract(a.action_json, '$.action_type') = ?")
        params.append(str(action_type).strip().upper())
    if execution_status:
        where.append("a.execution_status = ?")
        params.append(str(execution_status).strip().upper())
    if q:
        like = f"%{str(q).strip()}%"
        where.append(
            "(w.work_item_id LIKE ? OR json_extract(a.action_json, '$.order_id') LIKE ? "
            "OR a.action_json LIKE ?)"
        )
        params.extend([like, like, like])
    clause = " AND ".join(where)
    conn = store._connect()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM sa_approval a JOIN sa_work_item w "
            f"ON w.work_item_id = a.work_item_id WHERE {clause}",
            params,
        ).fetchone()["n"]
        rows = conn.execute(
            "SELECT a.*, w.status AS work_status, w.merchant_id AS work_merchant_id "
            "FROM sa_approval a JOIN sa_work_item w ON w.work_item_id = a.work_item_id "
            f"WHERE {clause} "
            "ORDER BY COALESCE(a.executed_at, a.decided_at, a.created_at) DESC LIMIT ? OFFSET ?",
            (*params, max(1, min(int(limit), 200)), max(0, int(offset))),
        ).fetchall()
        result = []
        for row in rows:
            try:
                action = json.loads(row["action_json"] or "{}")
            except (TypeError, ValueError):
                action = {}
            try:
                execution = json.loads(row["execution_result_json"] or "{}")
            except (TypeError, ValueError):
                execution = {}
            result.append({
                "approval_id": row["approval_id"],
                "work_item_id": row["work_item_id"],
                "merchant_id": row["work_merchant_id"],
                "work_status": row["work_status"],
                "approval_status": row["status"],
                "execution_status": row["execution_status"],
                "action": action,
                "order_id": action.get("order_id") or "",
                "action_type": action.get("action_type") or "",
                "execution_result": execution,
                "error": execution.get("error") or "",
                "created_at": row["created_at"],
                "decided_at": row["decided_at"],
                "executed_at": row["executed_at"],
            })
        return {"items": result, "total": int(total), "limit": limit, "offset": offset}
    finally:
        conn.close()
def _queue_is_pg() -> bool:
    return (os.environ.get("QIANKE_QUEUE_BACKEND") or "sqlite").strip().lower() in {"postgres", "postgresql", "pg"}


def _pg_queue():
    from rag_demo.superagent import queue_pg

    return queue_pg


def _iso_after(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(seconds)))).isoformat()


def enqueue_job(
    work_item_id: str,
    *,
    kind: str = "WORKER",
    max_attempts: int = 2,
) -> dict[str, Any]:
    """幂等入队：同一 WorkItem/kind 只保留一个 Job。"""
    if _queue_is_pg():
        return _pg_queue().enqueue_job(work_item_id, kind=kind, max_attempts=max_attempts)
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM sa_job WHERE work_item_id = ? AND kind = ?",
            (work_item_id, kind),
        ).fetchone()
        if existing is not None:
            conn.commit()
            return _job_payload(existing)
        job_id = f"saj_{uuid.uuid4().hex[:16]}"
        conn.execute(
            "INSERT INTO sa_job(job_id, work_item_id, kind, status, attempts, max_attempts, "
            "available_at, created_at, updated_at) VALUES (?, ?, ?, 'PENDING', 0, ?, ?, ?, ?)",
            (job_id, work_item_id, kind, max(1, int(max_attempts)), now, now, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    job = get_job(job_id)
    assert job is not None
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    if _queue_is_pg():
        return _pg_queue().get_job(job_id)
    init()
    conn = store._connect()
    try:
        row = conn.execute("SELECT * FROM sa_job WHERE job_id = ?", (job_id,)).fetchone()
        return _job_payload(row) if row else None
    finally:
        conn.close()


def list_jobs(
    limit: int = 50,
    *,
    offset: int = 0,
    status: str | None = None,
    kind: str | None = None,
    q: str = "",
) -> list[dict[str, Any]]:
    if _queue_is_pg():
        return _pg_queue().list_jobs(
            limit=limit, offset=offset, status=status, kind=kind, q=q
        )
    init()
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status.upper())
    if kind:
        where.append("kind = ?")
        params.append(kind.upper())
    if q:
        like = f"%{str(q).strip()}%"
        where.append(
            "(job_id LIKE ? OR work_item_id LIKE ? OR worker_id LIKE ? OR last_error LIKE ?)"
        )
        params.extend([like, like, like, like])
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
    conn = store._connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM sa_job {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [_job_payload(row) for row in rows]
    finally:
        conn.close()


def count_jobs(
    *,
    status: str | None = None,
    kind: str | None = None,
    q: str = "",
) -> int:
    if _queue_is_pg():
        return _pg_queue().count_jobs(status=status, kind=kind, q=q)
    init()
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status.upper())
    if kind:
        where.append("kind = ?")
        params.append(kind.upper())
    if q:
        like = f"%{str(q).strip()}%"
        where.append(
            "(job_id LIKE ? OR work_item_id LIKE ? OR worker_id LIKE ? OR last_error LIKE ?)"
        )
        params.extend([like, like, like, like])
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    conn = store._connect()
    try:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM sa_job {clause}", params).fetchone()
        return int(row["n"])
    finally:
        conn.close()


def job_stats() -> dict[str, Any]:
    if _queue_is_pg():
        return _pg_queue().job_stats()
    init()
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM sa_job GROUP BY status"
        ).fetchall()
        counts = {str(row["status"]).lower(): int(row["n"]) for row in rows}
        oldest = conn.execute(
            "SELECT MIN(created_at) AS ts FROM sa_job WHERE status = 'PENDING'"
        ).fetchone()
        return {
            "total": sum(counts.values()),
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "dead": counts.get("dead", 0),
            "oldest_pending_at": oldest["ts"] if oldest else None,
        }
    finally:
        conn.close()


def replay_job(job_id: str) -> dict[str, Any] | None:
    """把 DEAD/FAILED Job 重置为 PENDING，attempts 归零；由 dispatcher/Worker 重新领取。"""
    if _queue_is_pg():
        return _pg_queue().replay_job(job_id)
    init()
    now = _now()
    conn = store._connect()
    try:
        row = conn.execute("SELECT * FROM sa_job WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        if row["status"] not in ("DEAD", "FAILED"):
            raise store.CStoreError("JOB_NOT_REPLAYABLE", f"Job 状态为 {row['status']}，不能重放")
        conn.execute(
            "UPDATE sa_job SET status = 'PENDING', attempts = 0, available_at = ?, "
            "lease_until = NULL, worker_id = NULL, last_error = NULL, updated_at = ? WHERE job_id = ?",
            (now, now, job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_job(job_id)


def claim_job(job_id: str, worker_id: str, *, lease_seconds: int = 1800) -> dict[str, Any] | None:
    """原子领取 Job；PENDING 或租约过期的 RUNNING 可被领取。"""
    if _queue_is_pg():
        return _pg_queue().claim_job(job_id, worker_id, lease_seconds=lease_seconds)
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM sa_job WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            conn.rollback()
            return None
        claimable = row["status"] == "PENDING" and (row["available_at"] or now) <= now
        claimable = claimable or (
            row["status"] == "RUNNING" and (row["lease_until"] or "") < now
        )
        if not claimable:
            conn.rollback()
            return None
        attempts = int(row["attempts"]) + 1
        if attempts > int(row["max_attempts"]):
            conn.execute(
                "UPDATE sa_job SET status = 'DEAD', last_error = 'max attempts exceeded', "
                "updated_at = ? WHERE job_id = ?",
                (now, job_id),
            )
            conn.commit()
            return None
        conn.execute(
            "UPDATE sa_job SET status = 'RUNNING', attempts = ?, worker_id = ?, "
            "lease_until = ?, updated_at = ? WHERE job_id = ?",
            (attempts, worker_id, _iso_after(lease_seconds), now, job_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_job(job_id)


def finish_job(job_id: str, status: str, *, error: str = "") -> dict[str, Any] | None:
    if _queue_is_pg():
        return _pg_queue().finish_job(job_id, status, error=error)
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute(
            "UPDATE sa_job SET status = ?, last_error = ?, lease_until = NULL, updated_at = ? "
            "WHERE job_id = ?",
            (status, str(error)[:2000] or None, now, job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_job(job_id)


def retry_job(job_id: str, *, error: str = "", delay_seconds: int = 5) -> dict[str, Any] | None:
    if _queue_is_pg():
        return _pg_queue().retry_job(job_id, error=error, delay_seconds=delay_seconds)
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute(
            "UPDATE sa_job SET status = 'PENDING', available_at = ?, lease_until = NULL, "
            "worker_id = NULL, last_error = ?, updated_at = ? WHERE job_id = ?",
            (_iso_after(delay_seconds), str(error)[:2000], now, job_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_job(job_id)


def claim_next_job(
    worker_id: str, *, lease_seconds: int = 1800
) -> dict[str, Any] | None:
    """原子领取下一个可执行 Job；SQLite 单写者下用 BEGIN IMMEDIATE。"""
    if _queue_is_pg():
        return _pg_queue().claim_next_job(worker_id, lease_seconds=lease_seconds)
    init()
    now = _now()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM sa_job WHERE "
            "(status = 'PENDING' AND available_at <= ?) OR "
            "(status = 'RUNNING' AND lease_until IS NOT NULL AND lease_until < ?) "
            "ORDER BY created_at ASC LIMIT 1",
            (now, now),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        attempts = int(row["attempts"]) + 1
        if attempts > int(row["max_attempts"]):
            conn.execute(
                "UPDATE sa_job SET status = 'DEAD', last_error = 'max attempts exceeded', "
                "updated_at = ? WHERE job_id = ?",
                (now, row["job_id"]),
            )
            conn.commit()
            return None
        conn.execute(
            "UPDATE sa_job SET status = 'RUNNING', attempts = ?, worker_id = ?, "
            "lease_until = ?, updated_at = ? WHERE job_id = ?",
            (attempts, worker_id, _iso_after(lease_seconds), now, row["job_id"]),
        )
        conn.commit()
        job_id = row["job_id"]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_job(job_id)


def renew_lease(job_id: str, worker_id: str, *, lease_seconds: int = 1800) -> bool:
    """Worker 心跳续租；只能续自己持有的 RUNNING Job。"""
    if _queue_is_pg():
        return _pg_queue().renew_lease(job_id, worker_id, lease_seconds=lease_seconds)
    init()
    now = _now()
    conn = store._connect()
    try:
        cursor = conn.execute(
            "UPDATE sa_job SET lease_until = ?, updated_at = ? "
            "WHERE job_id = ? AND worker_id = ? AND status = 'RUNNING'",
            (_iso_after(lease_seconds), now, job_id, worker_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def requeue_expired_jobs() -> int:
    """把租约过期的 RUNNING Job 重新放回 PENDING；供启动恢复/看门狗调用。"""
    if _queue_is_pg():
        return _pg_queue().requeue_expired_jobs()
    init()
    now = _now()
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sa_job WHERE status = 'RUNNING' AND lease_until IS NOT NULL "
            "AND lease_until < ?",
            (now,),
        ).fetchall()
        for row in rows:
            if int(row["attempts"]) >= int(row["max_attempts"]):
                conn.execute(
                    "UPDATE sa_job SET status = 'DEAD', last_error = 'lease expired / max attempts', "
                    "updated_at = ? WHERE job_id = ?",
                    (now, row["job_id"]),
                )
            else:
                conn.execute(
                    "UPDATE sa_job SET status = 'PENDING', available_at = ?, lease_until = NULL, "
                    "worker_id = NULL, updated_at = ? WHERE job_id = ?",
                    (now, now, row["job_id"]),
                )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def pending_jobs(limit: int = 20) -> list[dict[str, Any]]:
    if _queue_is_pg():
        return _pg_queue().pending_jobs(limit=limit)
    init()
    now = _now()
    conn = store._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sa_job WHERE status = 'PENDING' AND available_at <= ? "
            "ORDER BY created_at ASC LIMIT ?",
            (now, max(1, min(int(limit), 100))),
        ).fetchall()
        return [_job_payload(row) for row in rows]
    finally:
        conn.close()


def update_approval_action(work_item_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """人工审批前补充动作参数；只允许在待审批状态修改。"""
    allowed = {"sale_type", "reason", "tracking_no", "carrier", "ticket_id", "amount"}
    clean = {key: (str(value).strip() if value is not None else "") for key, value in patch.items() if key in allowed}
    if not clean:
        return get_approval(work_item_id) or {}
    init()
    conn = store._connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT action_json FROM sa_approval WHERE work_item_id = ? AND status = 'PENDING'",
            (work_item_id,),
        ).fetchone()
        if row is None:
            raise store.CStoreError("SA_APPROVAL_NOT_PENDING", "审批单不存在或已处理")
        action = json.loads(row["action_json"] or "{}")
        action.update(clean)
        conn.execute(
            "UPDATE sa_approval SET action_json = ? WHERE work_item_id = ?",
            (_json(action), work_item_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_approval(work_item_id) or {}


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
        "merchant_id": row["merchant_id"],
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


def _approval_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "approval_id": row["approval_id"],
        "work_item_id": row["work_item_id"],
        "status": row["status"],
        "note": row["note"],
        "action": json.loads(row["action_json"] or "{}"),
        "execution_status": row["execution_status"],
        "execution_result": json.loads(row["execution_result_json"] or "{}"),
        "created_at": row["created_at"],
        "decided_at": row["decided_at"],
        "executed_at": row["executed_at"],
        "idempotency_key": row["idempotency_key"],
        "card_send_response_code": row["card_send_response_code"],
        "card_event_response_code": row["card_event_response_code"],
    }


def _job_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "work_item_id": row["work_item_id"],
        "kind": row["kind"],
        "status": row["status"],
        "attempts": int(row["attempts"]),
        "max_attempts": int(row["max_attempts"]),
        "available_at": row["available_at"],
        "lease_until": row["lease_until"],
        "worker_id": row["worker_id"],
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
