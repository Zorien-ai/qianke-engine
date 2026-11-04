"""Super-agent 控制表 PostgreSQL 只读 repository（P2-A）。"""
from __future__ import annotations

from typing import Any

from .postgres_repository import PostgresControlRepository


class PostgresSuperagentRepository:
    backend = "postgres"

    def __init__(self, schema: str | None = None) -> None:
        self._control = PostgresControlRepository(schema=schema)
        self.schema = self._control.schema

    def init_schema(self) -> None:
        self._control.init_schema()

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        with self._control._cursor() as cur:
            cur.execute(f'SELECT * FROM "{self.schema}".sa_thread WHERE thread_id = %s', (thread_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                f'SELECT * FROM "{self.schema}".sa_trigger WHERE thread_id = %s '
                "ORDER BY created_at ASC",
                (thread_id,),
            )
            triggers = [dict(item) for item in cur.fetchall()]
        return {**dict(row), "triggers": triggers}

    def list_threads(self, *, merchant_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if merchant_id:
            where = "WHERE merchant_id = %s"
            params.append(merchant_id)
        params.append(max(1, min(int(limit), 200)))
        with self._control._cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{self.schema}".sa_thread {where} '
                "ORDER BY updated_at DESC LIMIT %s",
                tuple(params),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_work_item(self, work_item_id: str) -> dict[str, Any] | None:
        with self._control._cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{self.schema}".sa_work_item WHERE work_item_id = %s',
                (work_item_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def list_work_items(
        self, *, merchant_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if merchant_id:
            where = "WHERE merchant_id = %s"
            params.append(merchant_id)
        params.append(max(1, min(int(limit), 200)))
        with self._control._cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{self.schema}".sa_work_item {where} '
                "ORDER BY created_at DESC LIMIT %s",
                tuple(params),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_approval(self, work_item_id: str) -> dict[str, Any] | None:
        with self._control._cursor() as cur:
            cur.execute(
                f'SELECT * FROM "{self.schema}".sa_approval WHERE work_item_id = %s',
                (work_item_id,),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def counts(self) -> dict[str, int]:
        with self._control._cursor() as cur:
            result = {}
            for table in ("sa_thread", "sa_trigger", "sa_work_item", "sa_approval"):
                cur.execute(f'SELECT COUNT(*) AS n FROM "{self.schema}".{table}')
                result[table] = int(cur.fetchone()["n"])
            return result

    def close(self) -> None:
        self._control.close()
