"""Super-agent PostgreSQL 控制写路径契约测试（P2-B）。"""
from __future__ import annotations

import uuid

import pytest

from rag_demo.c_end import store as c_store
from rag_demo.superagent import store as sa_store

psycopg2 = pytest.importorskip("psycopg2")
from rag_demo.control.settings import pg_settings  # noqa: E402
from rag_demo.superagent import queue_pg  # noqa: E402


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
def pg_control(monkeypatch):
    schema = f"qianke_p2b_test_{uuid.uuid4().hex[:8]}"
    queue_schema = f"sa_queue_test_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("QIANKE_CONTROL_BACKEND", "postgres")
    monkeypatch.setenv("QIANKE_CONTROL_PG_SCHEMA", schema)
    monkeypatch.setattr(queue_pg, "SCHEMA", queue_schema)
    sa_store.init()
    yield schema
    conn = _admin_connect(pg_settings())
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            cur.execute(f'DROP SCHEMA IF EXISTS "{queue_schema}" CASCADE')
    finally:
        conn.close()


def test_pg_control_work_item_flow(pg_control):
    out = sa_store.create_trigger(
        source="test", content="PG 审批流", channel="manual", thread_key="p2b:flow"
    )
    assert out["thread"]["thread_id"]
    work_item_id = out["work_item"]["work_item_id"]

    assert sa_store.start_work_item(work_item_id)["status"] == "RUNNING"
    assert sa_store.finish_work_item(
        work_item_id, {"ok": True}, approval=True,
        action={"action_type": "CANCEL_ORDER", "order_id": "o_pg_test"},
    )["status"] == "WAITING_APPROVAL"
    assert sa_store.decide_approval(work_item_id, approved=True, note="ok")["status"] == "EXECUTING"
    item = sa_store.complete_execution(work_item_id, success=True, result={"done": True})
    assert item["status"] == "DONE"
    assert item["result"]["execution"]["success"] is True
    approval = sa_store.get_approval(work_item_id)
    assert approval["execution_status"] == "EXECUTED"
    assert sa_store.work_item_stats()["done"] == 1
    assert sa_store.approval_stats()["approved_executed"] == 1

    audit = sa_store.list_action_audit("m_gear_002", action_type="CANCEL_ORDER")
    assert audit["total"] == 1
    assert sa_store.list_action_audit("m_gear_002", date_from="2099-01-01")["total"] == 0


def test_pg_control_idempotent_approval(pg_control):
    out = sa_store.create_trigger(
        source="test", content="幂等", channel="manual", thread_key="p2b:idem"
    )
    work_item_id = out["work_item"]["work_item_id"]
    sa_store.start_work_item(work_item_id)
    sa_store.finish_work_item(work_item_id, {}, approval=True, action={"action_type": "CANCEL_ORDER"})
    first = sa_store.decide_approval(work_item_id, approved=True)
    second = sa_store.decide_approval(work_item_id, approved=True)
    assert first["status"] == second["status"] == "EXECUTING"
    assert sa_store.get_approval(work_item_id)["status"] == "APPROVED"


def test_pg_control_queue_uses_sa_queue(pg_control):
    out = sa_store.create_trigger(
        source="test", content="队列", channel="manual", thread_key="p2b:queue"
    )
    work_item_id = out["work_item"]["work_item_id"]
    job = sa_store.enqueue_job(work_item_id, kind="ACTION")
    assert job["job_id"]
    assert sa_store.get_job(job["job_id"])["status"] == "PENDING"
    assert sa_store.job_stats()["pending"] == 1
    claimed = sa_store.claim_next_job("worker-test")
    assert claimed["job_id"] == job["job_id"]
    assert claimed["status"] == "RUNNING"
