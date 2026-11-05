"""B 端账号级 AI 人设存储（SQLite）。

设计约束：
- 一个账号一条记录；只存「表现层」配置（名字 / 称呼 / 语气档位），不存权限。
- 没有记录 = 用默认值（小千 / 账号昵称 / standard），不预置数据。
- 与 C 端伙伴存储同形态（SQLite + 进程内锁），后续迁 Postgres 时作为迁移项。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rag_demo.config import BASE_DIR

_DB_LOCK = threading.Lock()
_DB_PATH: Path | None = None
_INIT_DONE = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS b_agent_persona (
    account_id   INTEGER PRIMARY KEY,
    name         TEXT NOT NULL DEFAULT '',
    user_address TEXT NOT NULL DEFAULT '',
    tone_profile TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL
);
"""


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        raw = os.environ.get("QIANKE_B_PERSONA_DB") or str(
            Path(BASE_DIR) / "var" / "b_agent_persona.sqlite"
        )
        _DB_PATH = Path(raw)
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    global _INIT_DONE
    with _DB_LOCK, _connect() as conn:
        conn.executescript(_SCHEMA)
    _INIT_DONE = True


def _ensure_init() -> None:
    if not _INIT_DONE:
        init()


def get_persona(account_id: int | None) -> dict[str, Any] | None:
    if account_id is None:
        return None
    _ensure_init()
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT account_id, name, user_address, tone_profile, updated_at "
            "FROM b_agent_persona WHERE account_id = ?",
            (int(account_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def upsert_persona(
    account_id: int | None,
    *,
    name: str | None = None,
    user_address: str | None = None,
    tone_profile: str | None = None,
) -> dict[str, Any] | None:
    """局部更新：None 表示该项不改；空字符串表示清空（回到默认 / 账号昵称）。"""
    if account_id is None:
        return None
    _ensure_init()
    current = get_persona(account_id) or {
        "account_id": int(account_id),
        "name": "",
        "user_address": "",
        "tone_profile": "",
        "updated_at": "",
    }
    next_row = {
        "name": current["name"] if name is None else str(name).strip(),
        "user_address": (
            current["user_address"] if user_address is None else str(user_address).strip()
        ),
        "tone_profile": (
            current["tone_profile"] if tone_profile is None else str(tone_profile).strip()
        ),
    }
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """INSERT INTO b_agent_persona
               (account_id, name, user_address, tone_profile, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(account_id) DO UPDATE SET
                   name = excluded.name,
                   user_address = excluded.user_address,
                   tone_profile = excluded.tone_profile,
                   updated_at = excluded.updated_at""",
            (
                int(account_id),
                next_row["name"],
                next_row["user_address"],
                next_row["tone_profile"],
                _now(),
            ),
        )
    return get_persona(account_id)


def reset_persona(account_id: int | None) -> None:
    """删除账号级配置，回到默认人设。"""
    if account_id is None:
        return
    _ensure_init()
    with _DB_LOCK, _connect() as conn:
        conn.execute("DELETE FROM b_agent_persona WHERE account_id = ?", (int(account_id),))


__all__ = [
    "get_persona",
    "init",
    "reset_persona",
    "upsert_persona",
]
