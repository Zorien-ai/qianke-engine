"""请求级幂等执行记录。

设计目标：
- 同一个 (request_id, scope) 只允许一次逻辑执行；
- 并发重复请求不能重复跑 Agent / 重复产生副作用；
- 已完成请求可以回放响应；
- 运行中或已失败请求返回明确状态，而不是静默重跑。

第一版使用账号库 PostgreSQL；测试使用 InMemoryExecutionStore。
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Literal, Protocol

ClaimState = Literal["claimed", "in_progress", "completed", "failed", "conflict"]


@dataclass(frozen=True)
class ClaimResult:
    state: ClaimState
    execution_id: str | None = None
    response: dict[str, Any] | None = None
    error: str | None = None


class ExecutionStore(Protocol):
    def claim(self, request_id: str, scope: str, request_hash: str) -> ClaimResult: ...

    def complete(
        self,
        request_id: str,
        scope: str,
        execution_id: str,
        response: dict[str, Any],
    ) -> None: ...

    def fail(self, request_id: str, scope: str, error: str) -> None: ...


@dataclass
class _MemoryEntry:
    status: str
    execution_id: str | None = None
    response: dict[str, Any] | None = None
    error: str | None = None
    request_hash: str = ""


class InMemoryExecutionStore:
    """线程安全的内存实现，用于单测和本地无账号库场景。"""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _MemoryEntry] = {}
        self._lock = threading.Lock()

    def claim(self, request_id: str, scope: str, request_hash: str) -> ClaimResult:
        key = (request_id, scope)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = _MemoryEntry(status="RUNNING", request_hash=request_hash)
                return ClaimResult(state="claimed")
            if entry.request_hash != request_hash:
                return ClaimResult(state="conflict")
            if entry.status == "COMPLETED":
                return ClaimResult(
                    state="completed",
                    execution_id=entry.execution_id,
                    response=entry.response,
                )
            if entry.status == "FAILED":
                return ClaimResult(state="failed", error=entry.error)
            return ClaimResult(state="in_progress", execution_id=entry.execution_id)

    def complete(
        self,
        request_id: str,
        scope: str,
        execution_id: str,
        response: dict[str, Any],
    ) -> None:
        key = (request_id, scope)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.status != "RUNNING":
                raise RuntimeError("执行记录不是 RUNNING，无法完成")
            entry.status = "COMPLETED"
            entry.execution_id = execution_id
            entry.response = response
            entry.error = None

    def fail(self, request_id: str, scope: str, error: str) -> None:
        key = (request_id, scope)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if entry.status == "RUNNING":
                entry.status = "FAILED"
                entry.error = error[:2000]


class PostgresExecutionStore:
    """基于账号库的持久化实现（跨进程、跨重启）。"""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS agent_execution (
        request_id   TEXT NOT NULL,
        scope        TEXT NOT NULL,
        status       TEXT NOT NULL,
        request_hash TEXT NOT NULL DEFAULT '',
        execution_id TEXT,
        response     TEXT,
        error        TEXT,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (request_id, scope)
    );
    CREATE INDEX IF NOT EXISTS idx_agent_execution_status
        ON agent_execution (status, updated_at);
    ALTER TABLE agent_execution
        ADD COLUMN IF NOT EXISTS request_hash TEXT NOT NULL DEFAULT '';
    """

    def __init__(self) -> None:
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            from rag_demo import auth

            with auth._cursor() as cur:  # 复用账号库连接池；私有方法集中在此适配
                cur.execute(self._SCHEMA)
            self._schema_ready = True

    def claim(self, request_id: str, scope: str, request_hash: str) -> ClaimResult:
        from rag_demo import auth

        self._ensure_schema()
        with auth._cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_execution (request_id, scope, status, request_hash)
                VALUES (%s, %s, 'RUNNING', %s)
                ON CONFLICT (request_id, scope) DO NOTHING
                RETURNING request_id
                """,
                (request_id, scope, request_hash),
            )
            if cur.fetchone() is not None:
                return ClaimResult(state="claimed")

            cur.execute(
                """
                SELECT status, execution_id, response, error, request_hash
                FROM agent_execution
                WHERE request_id = %s AND scope = %s
                """,
                (request_id, scope),
            )
            row = cur.fetchone()
            if row is None:  # 理论上只会发生在极端并发/异常清理后
                return ClaimResult(state="failed", error="执行记录不存在")
            if row["request_hash"] and row["request_hash"] != request_hash:
                return ClaimResult(state="conflict")
            status = row["status"]
            if status == "COMPLETED":
                payload = json.loads(row["response"]) if row["response"] else None
                return ClaimResult(
                    state="completed",
                    execution_id=row["execution_id"],
                    response=payload,
                )
            if status == "FAILED":
                return ClaimResult(state="failed", error=row["error"])
            return ClaimResult(state="in_progress", execution_id=row["execution_id"])

    def complete(
        self,
        request_id: str,
        scope: str,
        execution_id: str,
        response: dict[str, Any],
    ) -> None:
        from rag_demo import auth

        self._ensure_schema()
        with auth._cursor() as cur:
            cur.execute(
                """
                UPDATE agent_execution
                SET status = 'COMPLETED',
                    execution_id = %s,
                    response = %s,
                    error = NULL,
                    updated_at = now()
                WHERE request_id = %s AND scope = %s AND status = 'RUNNING'
                """,
                (
                    execution_id,
                    json.dumps(response, ensure_ascii=False, default=str),
                    request_id,
                    scope,
                ),
            )
            if cur.rowcount != 1:
                raise RuntimeError("执行记录不是 RUNNING，无法完成")

    def fail(self, request_id: str, scope: str, error: str) -> None:
        from rag_demo import auth

        self._ensure_schema()
        with auth._cursor() as cur:
            cur.execute(
                """
                UPDATE agent_execution
                SET status = 'FAILED', error = %s, updated_at = now()
                WHERE request_id = %s AND scope = %s AND status = 'RUNNING'
                """,
                (error[:2000], request_id, scope),
            )


_store: ExecutionStore | None = None
_store_lock = threading.Lock()


def get_execution_store() -> ExecutionStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = PostgresExecutionStore()
    return _store
