"""Super-agent SQLite → PostgreSQL 回填测试。"""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from rag_demo.c_end import store as c_store
from rag_demo.superagent import store as sa_store

psycopg2 = pytest.importorskip("psycopg2")
from rag_demo.control.settings import pg_settings  # noqa: E402
from rag_demo.control.superagent_repository import PostgresSuperagentRepository  # noqa: E402

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_superagent_to_pg.py"
_spec = importlib.util.spec_from_file_location("migrate_superagent_to_pg", _SCRIPT)
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
def sqlite_sa(tmp_path, monkeypatch):
    db = tmp_path / "control.sqlite"
    monkeypatch.setenv("QIANKE_C_END_DB", str(db))
    monkeypatch.setenv("QIANKE_SUPERAGENT_DB", str(db))
    monkeypatch.setattr(c_store, "_DB_PATH", None)
    sa_store.init()
    out = sa_store.create_trigger(
        source="test", content="回填测试", channel="manual", thread_key="backfill:1"
    )
    sa_store.enqueue_job(out["work_item"]["work_item_id"], kind="ACTION")
    return out


@pytest.fixture()
def pg_names():
    schema = f"qianke_control_migrate_{uuid.uuid4().hex[:8]}"
    queue_schema = f"sa_queue_test_{uuid.uuid4().hex[:8]}"
    yield schema, queue_schema
    settings = pg_settings()
    conn = _admin_connect(settings)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            cur.execute(f'DROP SCHEMA IF EXISTS "{queue_schema}" CASCADE')
    finally:
        conn.close()


def test_backfill_copies_superagent_rows(sqlite_sa, pg_names):
    schema, queue_schema = pg_names
    summary = migrate_mod.migrate(
        schema=schema, queue_schema=queue_schema, include_jobs=True, apply=True
    )
    assert summary["source"]["sa_thread"] == 1
    assert summary["source"]["sa_trigger"] == 1
    assert summary["source"]["sa_work_item"] == 1
    assert summary["jobs"] == 1
    assert summary["target"] == {
        "sa_thread": 1, "sa_trigger": 1, "sa_work_item": 1, "sa_approval": 0,
        "queue_jobs": 1,
    }
    # 幂等重跑
    again = migrate_mod.migrate(
        schema=schema, queue_schema=queue_schema, include_jobs=True, apply=True
    )
    assert again["target"]["sa_work_item"] == 1
    assert again["target"]["queue_jobs"] == 1

    repo = PostgresSuperagentRepository(schema=schema)
    try:
        thread = repo.get_thread(sqlite_sa["thread"]["thread_id"])
        assert thread is not None
        assert thread["merchant_id"] == "m_gear_002"
        assert len(thread["triggers"]) == 1
        item = repo.get_work_item(sqlite_sa["work_item"]["work_item_id"])
        assert item is not None and item["status"] == "PENDING"
        assert repo.counts() == {
            "sa_thread": 1, "sa_trigger": 1, "sa_work_item": 1, "sa_approval": 0,
        }
    finally:
        repo.close()
