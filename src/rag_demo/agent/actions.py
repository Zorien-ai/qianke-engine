"""B 端经营分析 Agent 的受控写操作：运营跟进任务。

设计约束：
- Agent 只能创建“待确认草稿”，不能直接落正式任务；
- 用户通过独立 API 确认后，才写入 CONFIRMED；
- 只写本模块的 agent_action 表，不直接改业务库、订单、用户或活动；
- 每个动作绑定 account_id + dataset + request_id，便于审计与租户隔离。
"""
from __future__ import annotations

import contextvars
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

BASE_DIR = Path(__file__).resolve().parents[3]
_DB_PATH: Path | None = None
_DB_LOCK = None

_ACTOR: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "agent_action_actor", default=None
)


class ActionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        raw = os.environ.get("QIANKE_AGENT_ACTION_DB")
        _DB_PATH = Path(raw) if raw else BASE_DIR / "var" / "agent_actions.sqlite"
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_action (
                action_id   TEXT PRIMARY KEY,
                account_id  TEXT NOT NULL,
                dataset     TEXT NOT NULL,
                request_id  TEXT NOT NULL,
                action_type TEXT NOT NULL,
                title       TEXT NOT NULL,
                description TEXT NOT NULL,
                owner       TEXT NOT NULL,
                priority    TEXT NOT NULL,
                due_date    TEXT NOT NULL,
                status      TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                confirmed_at TEXT,
                confirmed_by TEXT,
                completed_at TEXT
            )
            """
        )
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(agent_action)").fetchall()
        }
        if "completed_at" not in columns:
            conn.execute("ALTER TABLE agent_action ADD COLUMN completed_at TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_action_request "
            "ON agent_action(account_id, dataset, request_id, created_at)"
        )
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_actor() -> dict[str, Any]:
    actor = _ACTOR.get()
    if not actor:
        raise ActionError("ACTION_CONTEXT_MISSING", "当前运行缺少可写的账号/数据集上下文")
    return actor


@contextmanager
def action_scope(dataset: str, account: dict[str, Any] | None, request_id: str) -> Iterator[None]:
    token = _ACTOR.set({
        "account_id": str((account or {}).get("id") or ""),
        "dataset": str(dataset or ""),
        "request_id": str(request_id or ""),
        "is_demo": bool((account or {}).get("is_demo")),
    })
    try:
        yield
    finally:
        _ACTOR.reset(token)


def _payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "action_id": row["action_id"],
        "account_id": row["account_id"],
        "dataset": row["dataset"],
        "request_id": row["request_id"],
        "action_type": row["action_type"],
        "title": row["title"],
        "description": row["description"],
        "owner": row["owner"],
        "priority": row["priority"],
        "due_date": row["due_date"],
        "status": row["status"],
        "created_at": row["created_at"],
        "confirmed_at": row["confirmed_at"],
        "confirmed_by": row["confirmed_by"],
        "completed_at": row["completed_at"],
    }


def create_followup_draft(
    *,
    title: str,
    description: str,
    owner: str = "",
    priority: str = "normal",
    due_date: str = "",
) -> dict[str, Any]:
    actor = current_actor()
    if actor["is_demo"]:
        raise ActionError("DEMO_READ_ONLY", "演示账号不能创建运营任务")
    if not actor["account_id"] or not actor["dataset"]:
        raise ActionError("ACTION_CONTEXT_MISSING", "缺少账号或数据集")
    title = str(title or "").strip()
    if len(title) < 2 or len(title) > 80:
        raise ActionError("INVALID_TITLE", "任务标题需为 2–80 字")
    description = str(description or "").strip()
    if len(description) > 1000:
        raise ActionError("INVALID_DESCRIPTION", "任务说明不能超过 1000 字")
    owner = str(owner or "").strip()
    if len(owner) > 40:
        raise ActionError("INVALID_OWNER", "负责人不能超过 40 字")
    priority = str(priority or "normal").strip().lower()
    if priority not in {"low", "normal", "high"}:
        raise ActionError("INVALID_PRIORITY", "priority 只允许 low / normal / high")
    due_date = str(due_date or "").strip()
    if len(due_date) > 20:
        raise ActionError("INVALID_DUE_DATE", "截止日期格式不合法")

    init()
    action_id = f"act_{uuid.uuid4().hex[:16]}"
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO agent_action(action_id, account_id, dataset, request_id, action_type, "
            "title, description, owner, priority, due_date, status, created_at) "
            "VALUES (?, ?, ?, ?, 'followup_task', ?, ?, ?, ?, ?, 'DRAFT', ?)",
            (
                action_id,
                actor["account_id"],
                actor["dataset"],
                actor["request_id"],
                title,
                description,
                owner,
                priority,
                due_date,
                _now(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM agent_action WHERE action_id = ?", (action_id,)).fetchone()
        return _payload(row)
    finally:
        conn.close()


def confirm_action(action_id: str, account: dict[str, Any]) -> dict[str, Any]:
    if (account or {}).get("is_demo"):
        raise ActionError("DEMO_READ_ONLY", "演示账号不能确认运营任务")
    account_id = str((account or {}).get("id") or "")
    init()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM agent_action WHERE action_id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionError("ACTION_NOT_FOUND", "待确认动作不存在")
        if row["account_id"] != account_id:
            raise ActionError("ACTION_FORBIDDEN", "不能确认其他账号的动作")
        if row["status"] != "DRAFT":
            raise ActionError("ACTION_NOT_DRAFT", "该动作已处理，不能重复确认")
        conn.execute(
            "UPDATE agent_action SET status = 'CONFIRMED', confirmed_at = ?, confirmed_by = ? "
            "WHERE action_id = ?",
            (_now(), account_id, action_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM agent_action WHERE action_id = ?", (action_id,)).fetchone()
        return _payload(row)
    finally:
        conn.close()


def cancel_action(action_id: str, account: dict[str, Any]) -> dict[str, Any]:
    account_id = str((account or {}).get("id") or "")
    init()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM agent_action WHERE action_id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionError("ACTION_NOT_FOUND", "待确认动作不存在")
        if row["account_id"] != account_id:
            raise ActionError("ACTION_FORBIDDEN", "不能取消其他账号的动作")
        if row["status"] != "DRAFT":
            raise ActionError("ACTION_NOT_DRAFT", "该动作已处理，不能取消")
        conn.execute("UPDATE agent_action SET status = 'CANCELLED' WHERE action_id = ?", (action_id,))
        conn.commit()
        row = conn.execute("SELECT * FROM agent_action WHERE action_id = ?", (action_id,)).fetchone()
        return _payload(row)
    finally:
        conn.close()


def complete_action(action_id: str, account: dict[str, Any]) -> dict[str, Any]:
    """把已确认任务标记为完成；只允许任务所属账号操作。"""
    if (account or {}).get("is_demo"):
        raise ActionError("DEMO_READ_ONLY", "演示账号不能完成运营任务")
    account_id = str((account or {}).get("id") or "")
    init()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM agent_action WHERE action_id = ?", (action_id,)).fetchone()
        if row is None:
            raise ActionError("ACTION_NOT_FOUND", "动作不存在")
        if row["account_id"] != account_id:
            raise ActionError("ACTION_FORBIDDEN", "不能完成其他账号的动作")
        if row["status"] != "CONFIRMED":
            raise ActionError("ACTION_NOT_CONFIRMED", "只有已确认任务才能标记完成")
        conn.execute(
            "UPDATE agent_action SET status = 'COMPLETED', completed_at = ? WHERE action_id = ?",
            (_now(), action_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM agent_action WHERE action_id = ?", (action_id,)).fetchone()
        return _payload(row)
    finally:
        conn.close()


def list_actions(
    account: dict[str, Any],
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """列出当前账号的运营任务，可按状态过滤。"""
    account_id = str((account or {}).get("id") or "")
    if not account_id:
        return []
    normalized = str(status or "").strip().upper()
    if normalized and normalized not in {"DRAFT", "CONFIRMED", "COMPLETED", "CANCELLED"}:
        raise ActionError("INVALID_STATUS", "status 只允许 DRAFT / CONFIRMED / COMPLETED / CANCELLED")
    init()
    conn = _connect()
    try:
        sql = "SELECT * FROM agent_action WHERE account_id = ?"
        params: list[Any] = [account_id]
        if normalized:
            sql += " AND status = ?"
            params.append(normalized)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        rows = conn.execute(sql, params).fetchall()
        return [_payload(row) for row in rows]
    finally:
        conn.close()


def list_for_request(
    request_id: str,
    account: dict[str, Any],
    limit: int = 10,
) -> list[dict[str, Any]]:
    account_id = str((account or {}).get("id") or "")
    if not request_id or not account_id:
        return []
    init()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM agent_action WHERE account_id = ? AND request_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (account_id, str(request_id), max(1, min(int(limit), 50))),
        ).fetchall()
        return [_payload(row) for row in rows]
    finally:
        conn.close()
