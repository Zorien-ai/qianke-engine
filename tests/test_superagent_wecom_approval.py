"""企业微信内审批命令：解析、权限、动作参数。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store
from rag_demo.superagent import router as sa_router
from rag_demo.superagent import runtime as sa_runtime
from rag_demo.superagent import store as sa_store
from rag_demo.superagent import wecom_approval, wecom_send


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    sa_store.init()
    return store


@pytest.fixture(autouse=True)
def _capture_replies(monkeypatch):
    replies = []
    monkeypatch.setattr(wecom_send, "send_text", lambda to, text, **kwargs: replies.append((to, text)) or {"sent": True})
    return replies


def _pending_item(c_store, *, action_type="CREATE_AFTER_SALE", from_user="approver"):
    accepted = sa_router.ingest_event(
        source="wecom",
        content="订单 order_test 售后处理",
        channel="wecom:text",
        thread_key=f"command:{action_type}:{from_user}",
        metadata={"from_user": from_user, "agent_id": "1000002"},
    )
    item_id = accepted["work_item"]["work_item_id"]
    sa_store.start_work_item(item_id)
    action = {"action_type": action_type, "order_id": "order_test", "sale_type": ""}
    sa_store.finish_work_item(item_id, {"summary": "待审批", "action": action}, approval=True, action=action)
    return item_id


def test_parse_commands():
    assert wecom_approval.parse_command("同意 abc123 仅退款")["sale_type"] == "REFUND_ONLY"
    assert wecom_approval.parse_command("同意 abc123 退货退款")["sale_type"] == "RETURN_REFUND"
    assert wecom_approval.parse_command("同意 abc123 发货 SF123456")["tracking_no"] == "SF123456"
    assert wecom_approval.parse_command("驳回 abc123")["decision"] == "REJECT"
    assert wecom_approval.parse_command("今天天气不错") is None


def test_approve_with_sale_type(c_store, monkeypatch):
    item_id = _pending_item(c_store)
    monkeypatch.setattr(sa_runtime, "start_action", lambda work_item_id: True)
    handled = wecom_approval.handle_message({
        "MsgType": "text",
        "Content": f"同意 {item_id[-6:]} 退货退款",
        "FromUserName": "approver",
        "AgentID": "1000002",
    })
    assert handled is True
    item = sa_store.get_work_item(item_id)
    assert item["status"] == "EXECUTING"
    assert item["approval"]["action"]["sale_type"] == "RETURN_REFUND"


def test_unauthorized_user_rejected(c_store):
    item_id = _pending_item(c_store, from_user="owner")
    handled = wecom_approval.handle_message({
        "MsgType": "text",
        "Content": f"同意 {item_id[-6:]} 仅退款",
        "FromUserName": "other",
        "AgentID": "1000002",
    })
    assert handled is True
    assert sa_store.get_work_item(item_id)["status"] == "WAITING_APPROVAL"


def test_reject_command(c_store):
    item_id = _pending_item(c_store)
    handled = wecom_approval.handle_message({
        "MsgType": "text",
        "Content": f"驳回 {item_id[-6:]}",
        "FromUserName": "approver",
        "AgentID": "1000002",
    })
    assert handled is True
    assert sa_store.get_work_item(item_id)["status"] == "REJECTED"
