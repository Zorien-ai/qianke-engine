"""C 端客户端消息幂等：防止网络重试重复执行 Agent / 重复生成订单草稿。

只记录“客户端消息 ID → 已完成的响应”。它不代替业务确认：
- 首次请求 claim → 执行 → complete；
- 重复请求直接回放已完成响应；
- 同 ID 正在执行时返回冲突，避免并发重复。
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any

from rag_demo.c_end import store

_LOCK = threading.Lock()


class IdempotencyConflict(RuntimeError):
    """同一 client_message_id 已用于不同内容，或正在执行。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(message: str, thread_id: str | None = None) -> str:
    payload = f"{message.strip()}\n{thread_id or ''}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def init() -> None:
    with _LOCK:
        conn = store._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS c_client_request (
                    client_id   TEXT NOT NULL,
                    owner_id    TEXT NOT NULL,
                    endpoint    TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    response_json TEXT,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    PRIMARY KEY (client_id, owner_id, endpoint)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def claim(
    *,
    client_id: str,
    owner_id: str,
    endpoint: str,
    request_fingerprint: str,
) -> dict[str, Any]:
    """返回 {state: claimed|replay|in_progress, response?}。

    - claimed：本次请求获得执行权；
    - replay：已有完成响应，直接回放；
    - in_progress：同一 ID 正在执行。
    """
    init()
    with _LOCK:
        conn = store._connect()
        try:
            row = conn.execute(
                "SELECT * FROM c_client_request WHERE client_id = ? AND owner_id = ? AND endpoint = ?",
                (client_id, owner_id, endpoint),
            ).fetchone()
            if row is not None:
                if row["fingerprint"] != request_fingerprint:
                    raise IdempotencyConflict("client_message_id 已用于不同内容")
                if row["status"] == "COMPLETED" and row["response_json"]:
                    return {"state": "replay", "response": json.loads(row["response_json"])}
                return {"state": "in_progress"}
            now = _now()
            conn.execute(
                "INSERT INTO c_client_request(client_id, owner_id, endpoint, fingerprint, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'IN_PROGRESS', ?, ?)",
                (client_id, owner_id, endpoint, request_fingerprint, now, now),
            )
            conn.commit()
            return {"state": "claimed"}
        finally:
            conn.close()


def complete(
    *,
    client_id: str,
    owner_id: str,
    endpoint: str,
    response: dict[str, Any],
) -> None:
    init()
    with _LOCK:
        conn = store._connect()
        try:
            conn.execute(
                "UPDATE c_client_request SET status = 'COMPLETED', response_json = ?, updated_at = ? "
                "WHERE client_id = ? AND owner_id = ? AND endpoint = ?",
                (json.dumps(response, ensure_ascii=False), _now(), client_id, owner_id, endpoint),
            )
            conn.commit()
        finally:
            conn.close()


def release(*, client_id: str, owner_id: str, endpoint: str) -> None:
    """执行失败时释放执行权，允许客户端用同一 ID 重试。"""
    init()
    with _LOCK:
        conn = store._connect()
        try:
            conn.execute(
                "DELETE FROM c_client_request WHERE client_id = ? AND owner_id = ? AND endpoint = ? "
                "AND status = 'IN_PROGRESS'",
                (client_id, owner_id, endpoint),
            )
            conn.commit()
        finally:
            conn.close()
