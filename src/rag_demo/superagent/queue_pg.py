"""Super-agent PostgreSQL Job 队列。

当 QIANKE_QUEUE_BACKEND=postgres 时启用；使用 FOR UPDATE SKIP LOCKED，
支持多 Worker 进程并发领取、租约续期和死信。
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA = "sa_queue"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(seconds)))).isoformat()


def _params() -> dict[str, Any]:
    return {
        "host": os.environ.get("QIANKE_QUEUE_PG_HOST") or os.environ.get("RAG_PG_HOST") or "127.0.0.1",
        "port": int(os.environ.get("QIANKE_QUEUE_PG_PORT") or os.environ.get("RAG_PG_PORT") or 5432),
        "user": os.environ.get("QIANKE_QUEUE_PG_USER") or os.environ.get("RAG_PG_USER") or "postgres",
        "password": os.environ.get("QIANKE_QUEUE_PG_PASSWORD")
        or os.environ.get("RAG_PG_PASSWORD")
        or "",
        "dbname": os.environ.get("QIANKE_QUEUE_PG_DB")
        or os.environ.get("RAG_AUTH_PG_DB")
        or "rag_auth",
    }


def _connect():
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(connect_timeout=5, **_params())
    conn.autocommit = False
    return conn


def _ensure() -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SCHEMA}.sa_job (
                    job_id TEXT PRIMARY KEY,
                    work_item_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 2,
                    available_at TEXT NOT NULL,
                    lease_until TEXT,
                    worker_id TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(work_item_id, kind)
                )
                """
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_sa_job_claim ON {SCHEMA}.sa_job "
                "(status, available_at, created_at)"
            )
        conn.commit()
    finally:
        conn.close()


def _row(row) -> dict[str, Any]:
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


def get_job(job_id: str) -> dict[str, Any] | None:
    import psycopg2.extras

    _ensure()
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {SCHEMA}.sa_job WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
            return _row(row) if row else None
    finally:
        conn.close()


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    import psycopg2.extras

    _ensure()
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {SCHEMA}.sa_job ORDER BY created_at DESC LIMIT %s",
                (max(1, min(int(limit), 200)),),
            )
            return [_row(row) for row in cur.fetchall()]
    finally:
        conn.close()


def enqueue_job(work_item_id: str, *, kind: str = "WORKER", max_attempts: int = 2) -> dict[str, Any]:
    import psycopg2.extras
    import psycopg2.errors

    _ensure()
    existing = find_by_work_item(work_item_id, kind)
    if existing:
        return existing
    job_id = f"saj_{uuid.uuid4().hex[:16]}"
    now = _now()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {SCHEMA}.sa_job(job_id, work_item_id, kind, status, attempts, "
                "max_attempts, available_at, created_at, updated_at) "
                "VALUES (%s, %s, %s, 'PENDING', 0, %s, %s, %s, %s) "
                "ON CONFLICT (work_item_id, kind) DO NOTHING",
                (job_id, work_item_id, kind, max(1, int(max_attempts)), now, now, now),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
    finally:
        conn.close()
    result = find_by_work_item(work_item_id, kind)
    assert result is not None
    return result


def find_by_work_item(work_item_id: str, kind: str) -> dict[str, Any] | None:
    import psycopg2.extras

    _ensure()
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {SCHEMA}.sa_job WHERE work_item_id = %s AND kind = %s",
                (work_item_id, kind),
            )
            row = cur.fetchone()
            return _row(row) if row else None
    finally:
        conn.close()


def claim_next_job(worker_id: str, *, lease_seconds: int = 1800) -> dict[str, Any] | None:
    import psycopg2.extras

    _ensure()
    now = _now()
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"UPDATE {SCHEMA}.sa_job SET status='DEAD', last_error='lease expired / max attempts', "
                "updated_at=%s WHERE status='RUNNING' AND lease_until IS NOT NULL "
                "AND lease_until < %s AND attempts >= max_attempts",
                (now, now),
            )
            cur.execute(
                f"""
                WITH candidate AS (
                    SELECT job_id FROM {SCHEMA}.sa_job
                    WHERE (status = 'PENDING' AND available_at <= %s)
                       OR (status = 'RUNNING' AND lease_until IS NOT NULL AND lease_until < %s)
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE {SCHEMA}.sa_job AS j
                SET status = 'RUNNING', attempts = j.attempts + 1,
                    worker_id = %s, lease_until = %s, updated_at = %s
                FROM candidate
                WHERE j.job_id = candidate.job_id AND j.attempts < j.max_attempts
                RETURNING j.*
                """,
                (now, now, worker_id, _after(lease_seconds), now),
            )
            row = cur.fetchone()
            conn.commit()
            return _row(row) if row else None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_job(job_id: str, worker_id: str, *, lease_seconds: int = 1800) -> dict[str, Any] | None:
    import psycopg2.extras

    _ensure()
    now = _now()
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {SCHEMA}.sa_job WHERE job_id = %s FOR UPDATE", (job_id,))
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                return None
            claimable = row["status"] == "PENDING" and (row["available_at"] or now) <= now
            claimable = claimable or (
                row["status"] == "RUNNING" and (row["lease_until"] or "") < now
            )
            attempts = int(row["attempts"]) + 1
            if not claimable:
                conn.rollback()
                return None
            if attempts > int(row["max_attempts"]):
                cur.execute(
                    f"UPDATE {SCHEMA}.sa_job SET status='DEAD', last_error='max attempts exceeded', "
                    "updated_at=%s WHERE job_id=%s",
                    (now, job_id),
                )
                conn.commit()
                return None
            cur.execute(
                f"UPDATE {SCHEMA}.sa_job SET status='RUNNING', attempts=%s, worker_id=%s, "
                "lease_until=%s, updated_at=%s WHERE job_id=%s RETURNING *",
                (attempts, worker_id, _after(lease_seconds), now, job_id),
            )
            updated = cur.fetchone()
            conn.commit()
            return _row(updated) if updated else None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_job(job_id: str, status: str, *, error: str = "") -> dict[str, Any] | None:
    _ensure()
    now = _now()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {SCHEMA}.sa_job SET status=%s, last_error=%s, lease_until=NULL, updated_at=%s "
                "WHERE job_id=%s",
                (status, str(error)[:2000] or None, now, job_id),
            )
        conn.commit()
    finally:
        conn.close()
    return get_job(job_id)


def retry_job(job_id: str, *, error: str = "", delay_seconds: int = 5) -> dict[str, Any] | None:
    _ensure()
    now = _now()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {SCHEMA}.sa_job SET status='PENDING', available_at=%s, lease_until=NULL, "
                "worker_id=NULL, last_error=%s, updated_at=%s WHERE job_id=%s",
                (_after(delay_seconds), str(error)[:2000], now, job_id),
            )
        conn.commit()
    finally:
        conn.close()
    return get_job(job_id)


def renew_lease(job_id: str, worker_id: str, *, lease_seconds: int = 1800) -> bool:
    _ensure()
    now = _now()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {SCHEMA}.sa_job SET lease_until=%s, updated_at=%s "
                "WHERE job_id=%s AND worker_id=%s AND status='RUNNING'",
                (_after(lease_seconds), now, job_id, worker_id),
            )
            changed = cur.rowcount > 0
        conn.commit()
        return changed
    finally:
        conn.close()


def requeue_expired_jobs() -> int:
    _ensure()
    now = _now()
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {SCHEMA}.sa_job SET status='DEAD', last_error='lease expired / max attempts', "
                "updated_at=%s WHERE status='RUNNING' AND lease_until IS NOT NULL AND lease_until < %s "
                "AND attempts >= max_attempts",
                (now, now),
            )
            dead = cur.rowcount
            cur.execute(
                f"UPDATE {SCHEMA}.sa_job SET status='PENDING', available_at=%s, lease_until=NULL, "
                "worker_id=NULL, updated_at=%s WHERE status='RUNNING' AND lease_until IS NOT NULL "
                "AND lease_until < %s AND attempts < max_attempts",
                (now, now, now),
            )
            changed = dead + cur.rowcount
        conn.commit()
        return changed
    finally:
        conn.close()


def pending_jobs(limit: int = 20) -> list[dict[str, Any]]:
    import psycopg2.extras

    _ensure()
    now = _now()
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {SCHEMA}.sa_job WHERE status='PENDING' AND available_at <= %s "
                "ORDER BY created_at ASC LIMIT %s",
                (now, max(1, min(int(limit), 100))),
            )
            return [_row(row) for row in cur.fetchall()]
    finally:
        conn.close()
