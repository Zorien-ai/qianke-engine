"""SQLite 风格连接兼容层：让 superagent/store.py 在 PostgreSQL 后端运行。

只覆盖控制面 sa_* 使用的 SQL 子集：
- ? → %s
- BEGIN IMMEDIATE → BEGIN
- json_extract(...) → jsonb ->> ...
- 行返回 dict
"""
from __future__ import annotations

import re
from typing import Any

from .settings import pg_settings


def _import_psycopg2():
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("控制面 PostgreSQL 需要 psycopg2-binary") from exc
    return psycopg2, psycopg2.extras


_JSON_EXTRACT = re.compile(
    r"json_extract\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*,\s*'\$\.([A-Za-z0-9_]+)'\s*\)"
)


def translate_sql(sql: str) -> str:
    sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
    sql = _JSON_EXTRACT.sub(r"(\1::jsonb ->> '\2')", sql)
    if re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", sql, flags=re.IGNORECASE):
        sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.IGNORECASE)
        if "ON CONFLICT" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    sql = sql.replace("?", "%s")
    # psycopg2 参数化时会把字面量 % 当格式符；转义非占位符的 %。
    return re.sub(r"%(?!s)", "%%", sql)


class PGCursor:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount


class PGConnection:
    """sqlite3.Connection 的最小兼容实现。"""

    def __init__(self) -> None:
        psycopg2, _ = _import_psycopg2()
        settings = pg_settings()
        self.schema = settings["schema"]
        self._conn = psycopg2.connect(
            host=settings["host"],
            port=settings["port"],
            user=settings["user"],
            password=settings["password"],
            dbname=settings["dbname"],
            connect_timeout=settings["connect_timeout"],
        )
        self._conn.autocommit = False
        with self._conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{self.schema}"')
        self._conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> PGCursor:
        _, extras = _import_psycopg2()
        cur = self._conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.execute(translate_sql(sql), tuple(params) if params else None)
        return PGCursor(cur)

    def executemany(self, sql: str, seq: list[tuple]) -> PGCursor:
        _, extras = _import_psycopg2()
        cur = self._conn.cursor(cursor_factory=extras.RealDictCursor)
        cur.executemany(translate_sql(sql), seq)
        return PGCursor(cur)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def connect() -> PGConnection:
    return PGConnection()
