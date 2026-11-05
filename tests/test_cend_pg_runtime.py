"""C 端 store PostgreSQL 运行时契约测试（P3-B）。"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from rag_demo.c_end import group, idempotency, social, store as c_store

psycopg2 = pytest.importorskip("psycopg2")
from rag_demo.control.settings import pg_settings  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_cend_to_pg.py"
_spec = importlib.util.spec_from_file_location("migrate_cend_to_pg_runtime", _SCRIPT)
migrate_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(migrate_mod)


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
def cend_pg(tmp_path, monkeypatch):
    schema = f"qianke_cend_rt_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(c_store, "_DB_PATH", None)
    monkeypatch.setattr(c_store, "_CEND_PG_INITIALIZED_SCHEMA", None)
    monkeypatch.setenv("QIANKE_CONTROL_PG_SCHEMA", schema)
    monkeypatch.setenv("QIANKE_CEND_BACKEND", "sqlite")
    c_store.init()
    social.init()
    group.init()
    idempotency.init()
    migrate_mod.migrate(schema=schema, apply=True)
    monkeypatch.setenv("QIANKE_CEND_BACKEND", "postgres")
    monkeypatch.setattr(c_store, "_CEND_PG_INITIALIZED_SCHEMA", None)
    c_store.init()
    yield schema
    conn = _admin_connect(pg_settings())
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        conn.close()


def test_cend_pg_read_and_quote_write(cend_pg):
    products = c_store.list_products()
    assert len(products) >= 1
    assert {tenant["merchant_id"] for tenant in c_store.list_tenants()} >= {"m_gear_002"}
    orders = c_store.list_all_orders(limit=5)
    assert isinstance(orders, list)

    quote_id = f"q_pg_rt_{uuid.uuid4().hex[:8]}"
    quote = c_store.create_quote(
        "buyer_1", "friend_test",
        {"quote_id": quote_id, "product_refs": [{"product_id": "P003"}], "policy_refs": []},
    )
    assert quote is not None and quote["quote_id"] == quote_id
    assert c_store.get_quote(quote_id, "buyer_1")["quote_id"] == quote_id
