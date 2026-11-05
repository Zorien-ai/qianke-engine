"""PostgreSQL 分布式登录限流契约测试。"""
from __future__ import annotations

import uuid

import pytest

from rag_demo.api.security import PostgresLoginRateLimiter
from rag_demo.control.settings import pg_settings

psycopg2 = pytest.importorskip("psycopg2")


def _pg_available() -> bool:
    try:
        conn = psycopg2.connect(
            host=pg_settings()["host"], port=pg_settings()["port"],
            user=pg_settings()["user"], password=pg_settings()["password"],
            dbname=pg_settings()["dbname"], connect_timeout=5,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="PostgreSQL 不可用")


def test_postgres_login_rate_limiter_shared_window():
    schema = f"qianke_login_{uuid.uuid4().hex[:8]}"
    settings = pg_settings()
    conn = psycopg2.connect(
        host=settings["host"], port=settings["port"], user=settings["user"],
        password=settings["password"], dbname=settings["dbname"], connect_timeout=5,
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
        limiter = PostgresLoginRateLimiter(max_attempts=2, window_seconds=60, schema=schema)
        assert limiter.retry_after("1.2.3.4:alice") == 0
        limiter.record_failure("1.2.3.4:alice")
        assert limiter.retry_after("1.2.3.4:alice") == 0
        limiter.record_failure("1.2.3.4:alice")
        assert limiter.retry_after("1.2.3.4:alice") > 0
        limiter.reset("1.2.3.4:alice")
        assert limiter.retry_after("1.2.3.4:alice") == 0
    finally:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        conn.close()
