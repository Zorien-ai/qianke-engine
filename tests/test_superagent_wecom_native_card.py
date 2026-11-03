"""企业微信原生按钮卡片：payload、event 解析、命令转换。"""
from __future__ import annotations

import json

import pytest

from rag_demo.c_end import store
from rag_demo.superagent import router as sa_router
from rag_demo.superagent import store as sa_store
from rag_demo.superagent import wecom_approval, wecom_native_card


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setenv("QIANKE_WECOM_NATIVE_CARD", "1")
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    sa_store.init()
    return store


def _pending(store_module):
    accepted = sa_router.ingest_event(
        source="wecom", content="订单退款", channel="wecom:text",
        thread_key=f"native:{store_module._now()}",
        metadata={"from_user": "approver", "agent_id": "1000002"},
    )
    item_id = accepted["work_item"]["work_item_id"]
    sa_store.start_work_item(item_id)
    action = {"action_type": "CREATE_AFTER_SALE", "order_id": "order_native", "sale_type": ""}
    sa_store.finish_work_item(item_id, {"summary": "待审批", "action": action}, approval=True, action=action)
    return sa_store.get_work_item(item_id)


def test_native_card_payload_and_parse(c_store):
    item = _pending(c_store)
    card = wecom_native_card.build_card(item)
    assert card["card_type"] == "button_interaction"
    assert card["task_id"].endswith(item["work_item_id"])
    assert [button["text"] for button in card["button_list"]] == ["仅退款", "退货退款", "驳回"]
    key = card["button_list"][0]["key"]
    message = {
        "MsgType": "event",
        "Event": "template_card_event",
        "EventKey": key,
        "FromUserName": "approver",
        "AgentID": "1000002",
    }
    event = wecom_native_card.parse_event(message)
    assert event["work_item_id"] == item["work_item_id"]
    assert event["sale_type"] == "REFUND_ONLY"
    assert wecom_native_card.to_command(event) == f"同意 {item['work_item_id'][-6:]} 仅退款"


def test_native_event_reuses_approval_command(c_store, monkeypatch):
    item = _pending(c_store)
    captured = []
    monkeypatch.setattr(
        wecom_approval,
        "handle_message",
        lambda message: captured.append(message["Content"]) or True,
    )
    key = json.dumps({"a": "approve", "w": item["work_item_id"], "s": "RETURN_REFUND"})
    handled = wecom_native_card.handle_event({
        "MsgType": "event",
        "Event": "template_card_event",
        "EventKey": key,
        "FromUserName": "approver",
        "AgentID": "1000002",
    })
    assert handled is True
    assert captured == [f"同意 {item['work_item_id'][-6:]} 退货退款"]
