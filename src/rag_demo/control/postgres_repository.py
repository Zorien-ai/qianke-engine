"""PostgreSQL 控制面 repository（P1 骨架：schema/健康/表清单/行数）。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .settings import pg_settings

_SCHEMA_FILE = Path(__file__).with_name("schema_pg.sql")


def _import_psycopg2():
    try:
        import psycopg2
        import psycopg2.extras
        from psycopg2 import pool
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("控制面 PostgreSQL 需要 psycopg2-binary") from exc
    return psycopg2, psycopg2.extras, pool


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class PostgresControlRepository:
    backend = "postgres"

    def __init__(self, schema: str | None = None) -> None:
        self._settings = pg_settings(schema=schema)
        self.schema = self._settings["schema"]
        psycopg2, _, pool = _import_psycopg2()
        self._pool = pool.ThreadedConnectionPool(
            1,
            4,
            host=self._settings["host"],
            port=self._settings["port"],
            user=self._settings["user"],
            password=self._settings["password"],
            dbname=self._settings["dbname"],
            connect_timeout=self._settings["connect_timeout"],
        )
        self._closed = False

    @property
    def settings(self) -> dict[str, Any]:
        return dict(self._settings)

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        if self._closed:
            raise RuntimeError("控制面 repository 已关闭")
        psycopg2, extras, _ = _import_psycopg2()
        conn = self._pool.getconn()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def init_schema(self) -> None:
        sql = _SCHEMA_FILE.read_text(encoding="utf-8").replace("__SCHEMA__", self.schema)
        with self._cursor() as cur:
            cur.execute(sql)

    def list_tables(self) -> list[str]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
                "ORDER BY table_name",
                (self.schema,),
            )
            return [str(row["table_name"]) for row in cur.fetchall()]

    def counts(self) -> dict[str, int]:
        result = {}
        with self._cursor() as cur:
            for table in self.list_tables():
                cur.execute(f"SELECT COUNT(*) AS n FROM {_quote(self.schema)}.{_quote(table)}")
                result[table] = int(cur.fetchone()["n"])
        return result

    def health(self) -> dict[str, Any]:
        with self._cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
        return {"ok": True, "backend": "postgres", "schema": self.schema}

    def close(self) -> None:
        if not self._closed:
            self._pool.closeall()
            self._closed = True
