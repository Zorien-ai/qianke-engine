"""控制面 SQLite/PostgreSQL 双后端契约测试（P1）。"""
from __future__ import annotations

import uuid

import pytest

from rag_demo.c_end import store
from rag_demo.control.sqlite_repository import SQLiteControlRepository

EXPECTED_TABLES = {
    "c_after_sale", "c_app_message", "c_client_request", "c_companion", "c_companion_memory",
    "c_companion_rhythm", "c_companion_checkin", "c_logistics_event", "c_compensation",
    "c_inventory_alert",
    "c_friend", "c_group", "c_group_member", "c_group_message", "c_mention", "c_message",
    "c_order", "c_order_item", "c_product", "c_quote", "c_reconciliation_alert",
    "c_reconciliation_run", "c_merchant_tenant", "c_merchant_member", "c_merchant_policy",
    "c_merchant_policy_audit", "c_policy_audit_anchor", "c_login_attempt",
    "c_tenant_provision", "c_thread_read",
    "sa_thread", "sa_trigger", "sa_work_item", "sa_approval", "sa_job",
}


@pytest.fixture()
def sqlite_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "control.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    repo = SQLiteControlRepository()
    try:
        yield repo
    finally:
        repo.close()


def test_sqlite_schema_matches_expected(sqlite_repo):
    assert set(sqlite_repo.list_tables()) == EXPECTED_TABLES
    assert sqlite_repo.health()["ok"] is True
    counts = sqlite_repo.counts()
    assert set(counts) == EXPECTED_TABLES
    assert counts["c_product"] >= 0


psycopg2 = pytest.importorskip("psycopg2")
from rag_demo.control.postgres_repository import PostgresControlRepository  # noqa: E402
from rag_demo.control.settings import pg_settings  # noqa: E402


def _admin_connect(settings):
    return psycopg2.connect(
        host=settings["host"], port=settings["port"], user=settings["user"],
        password=settings["password"], dbname=settings["dbname"], connect_timeout=5,
    )


def _pg_available() -> bool:
    try:
        conn = _admin_connect(pg_settings())
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _pg_available(), reason="PostgreSQL 不可用")


@pytest.fixture()
def pg_repo():
    schema = f"qianke_control_test_{uuid.uuid4().hex[:10]}"
    repo = PostgresControlRepository(schema=schema)
    repo.init_schema()
    try:
        yield repo
    finally:
        settings = pg_settings(schema=schema)
        repo.close()
        conn = _admin_connect(settings)
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            conn.close()


def test_postgres_schema_matches_sqlite(pg_repo):
    tables = set(pg_repo.list_tables())
    assert tables == EXPECTED_TABLES
    assert pg_repo.health()["ok"] is True
    counts = pg_repo.counts()
    assert set(counts) == EXPECTED_TABLES
    assert all(value == 0 for value in counts.values())


def test_postgres_schema_init_is_idempotent(pg_repo):
    pg_repo.init_schema()
    assert set(pg_repo.list_tables()) == EXPECTED_TABLES
