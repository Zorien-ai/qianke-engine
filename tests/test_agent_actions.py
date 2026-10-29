"""B 端受控写操作：运营跟进任务草稿与确认。"""
from __future__ import annotations

import pytest

from rag_demo.agent import actions


def _account(account_id: str = "101", demo: bool = False) -> dict:
    return {"id": account_id, "status": "active", "is_demo": demo}


def test_followup_task_is_draft_until_confirmed(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_AGENT_ACTION_DB", str(tmp_path / "actions.sqlite"))
    monkeypatch.setattr(actions, "_DB_PATH", None)
    account = _account()
    with actions.action_scope("test", account, "req_1"):
        action = actions.create_followup_draft(
            title="召回上海黑卡用户",
            description="基于流失分析生成跟进任务",
            owner="运营一组",
            priority="high",
        )
    assert action["status"] == "DRAFT"
    assert action["account_id"] == "101"
    assert actions.list_for_request("req_1", account)[0]["action_id"] == action["action_id"]

    confirmed = actions.confirm_action(action["action_id"], account)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_by"] == "101"


def test_demo_cannot_write(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_AGENT_ACTION_DB", str(tmp_path / "actions_demo.sqlite"))
    monkeypatch.setattr(actions, "_DB_PATH", None)
    with actions.action_scope("test", _account("101", demo=True), "req_2"):
        with pytest.raises(actions.ActionError) as exc:
            actions.create_followup_draft(title="演示任务", description="")
        assert exc.value.code == "DEMO_READ_ONLY"


def test_cross_account_cannot_confirm(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_AGENT_ACTION_DB", str(tmp_path / "actions_cross.sqlite"))
    monkeypatch.setattr(actions, "_DB_PATH", None)
    with actions.action_scope("test", _account("101"), "req_3"):
        action = actions.create_followup_draft(title="跨账号任务", description="")

    with pytest.raises(actions.ActionError) as exc:
        actions.confirm_action(action["action_id"], _account("202"))
    assert exc.value.code == "ACTION_FORBIDDEN"
