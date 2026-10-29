"""C 端客户端消息幂等：防止网络重试重复执行 Agent / 重复生成订单草稿。

只记录“客户端消息 ID → 已完成的响应”。它不代替业务确认：
- 首次请求 claim → 执行 → complete；
- 重复请求直接回放已完成响应；
- 同 ID 正在执行时返回冲突，避免并发重复。

TTL 清理：
- 默认保留 7 天（`DEFAULT_TTL_SECONDS`），可用环境变量
  `QIANKE_C_IDEMPOTENCY_TTL_SECONDS`（秒）覆盖；
- `prune()` 删除过期的 COMPLETED 与超时未完成的 IN_PROGRESS（崩溃遗留的执行权），
  并在 `claim()` 时按节流间隔自动触发；清理只删过期行，不影响未过期的 replay/conflict。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from rag_demo.c_end import store

_LOCK = threading.Lock()

TTL_ENV = "QIANKE_C_IDEMPOTENCY_TTL_SECONDS"
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60
# 自动清理节流：两次 prune 至少间隔这么久，避免每条消息都扫表。
_PRUNE_INTERVAL_SECONDS = 3600
# 进程启动后第一次 claim 就应该触发一次清理。
_last_prune_at = float("-inf")


class IdempotencyConflict(RuntimeError):
    """同一 client_message_id 已用于不同内容，或正在执行。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ttl_seconds(max_age_seconds: int | None = None) -> int:
    """TTL 秒数：显式参数 > 环境变量 > 默认 7 天；非法值回退默认。"""
    if max_age_seconds is not None:
        try:
            return max(0, int(max_age_seconds))
        except (TypeError, ValueError):
            return DEFAULT_TTL_SECONDS
    raw = (os.environ.get(TTL_ENV) or "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            return DEFAULT_TTL_SECONDS
        if value > 0:
            return value
    return DEFAULT_TTL_SECONDS


def _cutoff(max_age_seconds: int) -> str:
    """与 `_now()` 同格式的过期时间点（UTC、秒级），保证字符串比较可用。"""
    deadline = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
    return deadline.isoformat(timespec="seconds")


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
    _auto_prune()
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


def prune(max_age_seconds: int | None = None) -> int:
    """删除过期幂等记录，返回删除条数。

    - COMPLETED：按 `updated_at` 从完成时刻起算 TTL，过期才删（replay 缓存不再保留）；
    - IN_PROGRESS：按 `created_at` 判断超时（执行权 claim 后长期未完成，视为进程崩溃遗留）。

    只删过期行；未过期记录与 claim/replay/conflict 语义完全不受影响。
    """
    cutoff = _cutoff(_ttl_seconds(max_age_seconds))
    init()
    with _LOCK:
        conn = store._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM c_client_request WHERE "
                "(status = 'COMPLETED' AND updated_at < ?) OR "
                "(status = 'IN_PROGRESS' AND created_at < ?)",
                (cutoff, cutoff),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
        finally:
            conn.close()


def _auto_prune() -> None:
    """claim 时按节流间隔自动清理；清理只是尽力而为，失败不能影响主流程。"""
    global _last_prune_at
    now = time.monotonic()
    if now - _last_prune_at < _PRUNE_INTERVAL_SECONDS:
        return
    _last_prune_at = now
    try:
        prune()
    except Exception:  # noqa: BLE001 - 清理失败不应让 claim 失败
        pass
