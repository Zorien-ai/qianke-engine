"""企业微信结果回写：消息构造与发送边界。"""
from __future__ import annotations

from rag_demo.superagent import wecom_send


def test_send_text_success(monkeypatch):
    monkeypatch.setenv("QIANKE_WECOM_CORP_ID", "ww_test")
    monkeypatch.setenv("QIANKE_WECOM_CORP_SECRET", "secret")
    monkeypatch.setenv("QIANKE_WECOM_AGENT_ID", "1000002")
    monkeypatch.setattr(wecom_send, "_get_token", lambda: "token")
    captured = {}

    def fake_post(payload):
        captured.update(payload)
        return {"errcode": 0, "msgid": "msg_1"}

    monkeypatch.setattr(wecom_send, "_post_message", fake_post)
    result = wecom_send.send_text("user_1", "hello", agent_id="1000002")
    assert result["sent"] is True
    assert captured["touser"] == "user_1"
    assert captured["agentid"] == 1000002
    assert captured["text"]["content"] == "hello"


def test_notify_builds_from_wecom_trigger(monkeypatch):
    monkeypatch.setenv("QIANKE_WECOM_CORP_ID", "ww_test")
    monkeypatch.setenv("QIANKE_WECOM_CORP_SECRET", "secret")
    monkeypatch.setenv("QIANKE_WECOM_AGENT_ID", "1000002")
    captured = {}

    def fake_send(to_user, content, agent_id=None):
        captured.update({"to": to_user, "content": content, "agent": agent_id})
        return {"sent": True}

    monkeypatch.setattr(wecom_send, "send_text", fake_send)
    item = {
        "work_item_id": "saw_1",
        "status": "WAITING_APPROVAL",
        "result": {"summary": "调查结论", "action": {"action_type": "CANCEL_ORDER", "order_id": "order_1"}},
        "triggers": [
            {"source": "wecom", "metadata": {"from_user": "user_1", "agent_id": "1000002"}}
        ],
    }
    result = wecom_send.notify_work_item(item, stage="INVESTIGATED")
    assert result["sent"] is True
    assert captured["to"] == "user_1"
    assert "调查结论" in captured["content"]
    assert "CANCEL_ORDER" in captured["content"]


def test_send_skips_without_config(monkeypatch):
    for key in ("QIANKE_WECOM_CORP_ID", "QIANKE_WECOM_CORP_SECRET", "QIANKE_WECOM_AGENT_ID"):
        monkeypatch.delenv(key, raising=False)
    result = wecom_send.send_text("user_1", "hello")
    assert result["sent"] is False
    assert result["reason"] == "WECOM_SEND_NOT_CONFIGURED"
