"""SQLite 控制面 repository（P1 对照实现）。"""
from __future__ import annotations

from typing import Any

from rag_demo.c_end import group, idempotency, social, store
from rag_demo.superagent import store as sa_store


class SQLiteControlRepository:
    backend = "sqlite"

    def __init__(self) -> None:
        self.init_schema()

    def init_schema(self) -> None:
        store.init()
        sa_store.init()
        social.init()
        group.init()
        idempotency.init()

    def list_tables(self) -> list[str]:
        conn = store._connect()
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            return [str(row["name"]) for row in rows]
        finally:
            conn.close()

    def counts(self) -> dict[str, int]:
        result = {}
        conn = store._connect()
        try:
            for table in self.list_tables():
                row = conn.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()
                result[table] = int(row["n"])
        finally:
            conn.close()
        return result

    def health(self) -> dict[str, Any]:
        conn = store._connect()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return {"ok": True, "backend": "sqlite"}

    def close(self) -> None:
        return None
