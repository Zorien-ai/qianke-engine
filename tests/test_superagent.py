"""Super-agent MVP：Router / Thread / WorkItem / 审批 / Worker 回退。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store
from rag_demo.merchant import get_merchant_write_repository
from rag_demo.superagent import actions as sa_actions
from rag_demo.superagent import router as sa_router
from rag_demo.superagent import store as sa_store
from rag_demo.superagent import triggers as sa_triggers
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

    def broken_agent(*args, **kwargs):
        raise RuntimeError("no model in test")

    monkeypatch.setattr(sa_worker, "build_agent", broken_agent)
    item = sa_worker.run_work_item(item_id)
    assert item["status"] == "WAITING_APPROVAL"
    assert item["approval_status"] == "PENDING"
    assert item["result"]["worker"] == "deterministic_fallback"
    assert "需要人工确认" in item["result"]["summary"]

    approved = sa_store.decide_approval(item_id, approved=True, note="ok")
    assert approved["status"] == "EXECUTING"
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


def test_cancel_does_not_get_overwritten(c_store):
    accepted = sa_router.ingest_event(source="im", content="订单退款", channel="group")
    item_id = accepted["work_item"]["work_item_id"]
    sa_store.start_work_item(item_id)
    cancelled = sa_store.cancel_work_item(item_id)
    assert cancelled["status"] == "CANCELLED"
    sa_store.finish_work_item(item_id, {"summary": "late"}, approval=True)
    assert sa_store.get_work_item(item_id)["status"] == "CANCELLED"


def test_batch_merges_same_thread(c_store):
    result = sa_router.ingest_batch([
        {"source": "capp", "content": "订单物流异常", "thread_key": "batch:1"},
        {"source": "capp", "content": "买家要退款", "thread_key": "batch:1"},
        {"source": "capp", "content": "今天天气不错", "thread_key": "batch:1"},
    ])
    assert result["total"] == 3
    assert result["accepted"] == 2
    ids = {
        item["work_item"]["work_item_id"]
        for item in result["results"]
        if item.get("work_item")
    }
    assert len(ids) == 1


def test_auto_trigger_ingest_and_env_gate(c_store, monkeypatch):
    monkeypatch.setenv("QIANKE_SUPERAGENT_AUTO_TRIGGER", "1")
    monkeypatch.setenv("QIANKE_SUPERAGENT_AUTO_RUN", "0")
    result = sa_triggers.ingest_async(
        source="capp", content="订单退款", channel="friend:1", thread_key="capp:1"
    )
    assert result["accepted"] is True
    assert result["work_item"]["status"] == "PENDING"


def test_webhook_secret_verification(monkeypatch):
    monkeypatch.setenv(sa_triggers.WEBHOOK_SECRET_ENV, "secret-123")
    assert sa_triggers.verify_webhook_secret("secret-123") is True
    assert sa_triggers.verify_webhook_secret("bad") is False
    assert sa_triggers.verify_webhook_secret(None) is False


def test_semantic_slow_path(c_store, monkeypatch):
    monkeypatch.setenv("QIANKE_SUPERAGENT_LLM_ROUTER", "1")
    monkeypatch.setattr(
        sa_router,
        "semantic_classify",
        lambda text: (True, "SEMANTIC:购买商品未收到"),
    )
    result = sa_router.ingest_event(
        source="im",
        content="我上周买的东西到现在还没到，帮我处理一下",
        channel="semantic",
        thread_key="semantic:test",
    )
    assert result["accepted"] is True
    assert result["reason"].startswith("SEMANTIC:")


def test_approved_cancel_order_executes(c_store, monkeypatch):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_sa_action_cancel",
    )
    accepted = sa_router.ingest_event(
        source="im",
        content=f"请取消订单 {order['order_id']}，买家不想要了",
        channel="action",
        thread_key="action:cancel",
    )
    item_id = accepted["work_item"]["work_item_id"]

    def broken_agent(*args, **kwargs):
        raise RuntimeError("no model in test")

    monkeypatch.setattr(sa_worker, "build_agent", broken_agent)
    item = sa_worker.run_work_item(item_id)
    assert item["status"] == "WAITING_APPROVAL"
    assert item["approval"]["action"]["action_type"] == "CANCEL_ORDER"

    sa_store.decide_approval(item_id, approved=True, note="同意")
    executed = sa_actions.execute_approved(item_id)
    assert executed["status"] == "DONE"
    assert executed["approval"]["execution_status"] == "EXECUTED"
    assert c_store.get_order(order["order_id"])["status"] == "CANCELLED"
    assert get_merchant_write_repository().get_order(order["order_id"]).status == "CANCELLED"


def test_rejected_action_does_not_execute(c_store, monkeypatch):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_sa_action_reject",
    )
    accepted = sa_router.ingest_event(
        source="im",
        content=f"请取消订单 {order['order_id']}，买家不想要了",
        channel="action",
        thread_key="action:reject",
    )
    item_id = accepted["work_item"]["work_item_id"]

    def broken_agent(*args, **kwargs):
        raise RuntimeError("no model in test")

    monkeypatch.setattr(sa_worker, "build_agent", broken_agent)
    sa_worker.run_work_item(item_id)
    rejected = sa_store.decide_approval(item_id, approved=False, note="不同意")
    assert rejected["status"] == "REJECTED"
    assert c_store.get_order(order["order_id"])["status"] == "CONFIRMED"
