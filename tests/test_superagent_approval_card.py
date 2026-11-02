"""企业微信卡片审批：签名链接、模板卡片与审批提交。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store
from rag_demo.superagent import approval_card, router as sa_router, runtime as sa_runtime, store as sa_store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setenv("QIANKE_APPROVAL_CARD_SECRET", "test-card-secret")
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    sa_store.init()
    return store


def _pending(c_store):
    accepted = sa_router.ingest_event(
        source="wecom", content="订单退款", channel="wecom:text",
        thread_key="card:test",
        metadata={"from_user": "approver", "agent_id": "1000002"},
    )
    item_id = accepted["work_item"]["work_item_id"]
    sa_store.start_work_item(item_id)
    action = {"action_type": "CREATE_AFTER_SALE", "order_id": "order_card", "sale_type": ""}
    sa_store.finish_work_item(item_id, {"summary": "待审批", "action": action}, approval=True, action=action)
    return item_id


def test_card_token_and_page(c_store):
    item_id = _pending(c_store)
    item = sa_store.get_work_item(item_id)
    token = approval_card.make_token(item_id)
    assert approval_card.verify_token(item_id, token)[0] is True
    assert approval_card.verify_token(item_id, token + "x")[0] is False
    page = approval_card.render_page(item, token)
    assert "仅退款" in page and "退货退款" in page and "驳回" in page
    card = approval_card.build_card(item)
    assert card["card_type"] == "text_notice"
    assert item_id in card["card_action"]["url"]


def test_card_approve_starts_action(c_store, monkeypatch):
    item_id = _pending(c_store)
    monkeypatch.setattr(sa_runtime, "start_action", lambda work_item_id: True)
    ok, message = approval_card.approve_from_card(item_id, decision="approve:RETURN_REFUND")
    assert ok is True
    item = sa_store.get_work_item(item_id)
    assert item["status"] == "EXECUTING"
    assert item["approval"]["action"]["sale_type"] == "RETURN_REFUND"
