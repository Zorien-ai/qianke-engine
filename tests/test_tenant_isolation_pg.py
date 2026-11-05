"""租户隔离 PG 契约测试（P3-B / M1 试点）。"""
from __future__ import annotations

import uuid

import pytest

from rag_demo.c_end import store as c_store
from rag_demo.superagent import store as sa_store

psycopg2 = pytest.importorskip("psycopg2")
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
def tenant_pg(monkeypatch):
    schema = f"qianke_tenant_iso_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("QIANKE_CONTROL_BACKEND", "postgres")
    monkeypatch.setenv("QIANKE_CONTROL_PG_SCHEMA", schema)
    monkeypatch.setenv("QIANKE_CEND_BACKEND", "postgres")
    monkeypatch.setattr(c_store, "_CEND_PG_INITIALIZED_SCHEMA", None)
    monkeypatch.setattr(sa_store, "_PG_INITIALIZED_SCHEMA", None)
    c_store.init()
    c_store.create_tenant("m_iso_a", "隔离 A")
    c_store.create_tenant("m_iso_b", "隔离 B")
    c_store.bind_merchant_member(7001, "m_iso_a", role="owner")
    c_store.bind_merchant_member(7002, "m_iso_b", role="owner")
    sa_store.init()
    sa_store.create_trigger(
        source="test", content="A 的事件", channel="manual",
        thread_key="iso:a", merchant_id="m_iso_a",
    )
    sa_store.create_trigger(
        source="test", content="B 的事件", channel="manual",
        thread_key="iso:b", merchant_id="m_iso_b",
    )
    yield schema
    conn = _admin_connect(pg_settings())
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        conn.close()
    c_store._CEND_PG_INITIALIZED_SCHEMA = None
    sa_store._PG_INITIALIZED_SCHEMA = None


def test_pg_tenant_work_items_are_scoped(tenant_pg):
    items_a = sa_store.list_work_items(limit=20, merchant_id="m_iso_a")
    items_b = sa_store.list_work_items(limit=20, merchant_id="m_iso_b")
    assert len(items_a) == 1 and items_a[0]["merchant_id"] == "m_iso_a"
    assert len(items_b) == 1 and items_b[0]["merchant_id"] == "m_iso_b"
    assert c_store.get_merchant_member(7001)["merchant_id"] == "m_iso_a"
    assert c_store.get_merchant_member(7002)["merchant_id"] == "m_iso_b"
