"""Super-agent MVP：Router / Thread / WorkItem / 审批 / Worker 回退。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store
from rag_demo.superagent import router as sa_router
from rag_demo.superagent import store as sa_store
from rag_demo.superagent import worker as sa_worker


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    sa_store.init()
    return store


def test_router_filters_noise_and_creates_work_item(c_store):
    ignored = sa_router.ingest_event(source="im", content="今天天气不错", channel="group")
    assert ignored["accepted"] is False
    assert sa_store.list_work_items() == []

    accepted = sa_router.ingest_event(
        source="im",
        content="帮我查一下 order_abc123 的物流，用户要退款",
        channel="group",
        thread_key="group:1",
    )
    assert accepted["accepted"] is True
    assert accepted["created_work_item"] is True
    item = accepted["work_item"]
    assert item["status"] == "PENDING"
    assert item["triggers"][0]["content"].startswith("帮我查一下")


def test_thread_key_reuses_active_work_item(c_store):
    first = sa_router.ingest_event(
        source="im", content="订单异常，物流没更新", channel="group", thread_key="thread:1"
    )
    second = sa_router.ingest_event(
        source="im", content="售后要退货退款", channel="group", thread_key="thread:1"
    )
    assert first["thread"]["thread_id"] == second["thread"]["thread_id"]
    assert first["work_item"]["work_item_id"] == second["work_item"]["work_item_id"]
    assert second["created_work_item"] is False
    triggers = sa_store.get_thread(first["thread"]["thread_id"])["triggers"]
    assert len(triggers) == 2


def test_worker_fallback_and_approval(c_store, monkeypatch):
    accepted = sa_router.ingest_event(
        source="im", content="帮我看一下 order_abc123 的售后", channel="group"
    )
    item_id = accepted["work_item"]["work_item_id"]

    def broken_agent():
        raise RuntimeError("no model in test")

    monkeypatch.setattr(sa_worker, "build_agent", broken_agent)
    item = sa_worker.run_work_item(item_id)
    assert item["status"] == "WAITING_APPROVAL"
    assert item["approval_status"] == "PENDING"
    assert item["result"]["worker"] == "deterministic_fallback"
    assert "需要人工确认" in item["result"]["summary"]

    approved = sa_store.decide_approval(item_id, approved=True, note="ok")
    assert approved["status"] == "DONE"
    assert approved["approval_status"] == "APPROVED"


def test_watchdog_marks_stuck_items(c_store):
    accepted = sa_router.ingest_event(
        source="im", content="订单有问题，退款", channel="group"
    )
    item_id = accepted["work_item"]["work_item_id"]
    sa_store.start_work_item(item_id)
    # 直接把 started_at 改到过去，模拟长时间 RUNNING。
    conn = c_store._connect()
    try:
        conn.execute(
            "UPDATE sa_work_item SET started_at = '2000-01-01T00:00:00+00:00' WHERE work_item_id = ?",
            (item_id,),
        )
        conn.commit()
    finally:
        conn.close()
    stuck = sa_store.scan_stuck_work_items(timeout_seconds=10)
    assert any(item["work_item_id"] == item_id for item in stuck)
    assert sa_store.get_work_item(item_id)["status"] == "STUCK"
