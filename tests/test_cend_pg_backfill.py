"""C 端控制表 SQLite → PostgreSQL 回填测试（P3-A）。"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from rag_demo.c_end import group, idempotency, social, store as c_store

psycopg2 = pytest.importorskip("psycopg2")
from rag_demo.control.settings import pg_settings  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_cend_to_pg.py"
_spec = importlib.util.spec_from_file_location("migrate_cend_to_pg", _SCRIPT)
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
def sqlite_cend(tmp_path, monkeypatch):
    db = tmp_path / "c_end.sqlite"
    monkeypatch.setenv("QIANKE_C_END_DB", str(db))
    monkeypatch.setattr(c_store, "_DB_PATH", None)
    c_store.init()
    social.init()
    group.init()
    idempotency.init()
    return db


@pytest.fixture()
def pg_schema():
    schema = f"qianke_cend_test_{uuid.uuid4().hex[:8]}"
    yield schema
    settings = pg_settings()
    conn = _admin_connect(settings)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        conn.close()


def test_cend_backfill_copies_all_tables(sqlite_cend, pg_schema):
    summary = migrate_mod.migrate(schema=pg_schema, apply=True)
    assert summary["source"]["c_product"] >= 1
    assert summary["source"]["c_merchant_tenant"] >= 1
    assert summary["target"] == summary["source"]
    again = migrate_mod.migrate(schema=pg_schema, apply=True)
    assert again["target"] == summary["target"]
