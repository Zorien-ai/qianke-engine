"""商家级动作策略与额度。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store
from rag_demo.merchant import get_merchant_write_repository
from rag_demo.superagent import actions


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def _completed_order() -> str:
    draft = store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    order = store.confirm_order(
        "buyer_1", draft["order_id"], draft["confirmation_token"], request_id="policy_test"
    )
    repo = get_merchant_write_repository()
    for status in ("PAID", "SHIPPED", "COMPLETED"):
        repo.update_order_status(
            "m_gear_002",
            order["order_id"],
            status,
            tracking_no="SF-POLICY-TEST" if status == "SHIPPED" else None,
        )
    return order["order_id"]


def test_default_policy_allows_every_action(c_store):
    policy = store.get_merchant_policy("m_gear_002")
    assert set(policy["allowed_actions"]) == actions.ALLOWED_ACTIONS
    assert policy["compensation_max_amount"] == 50
    assert policy["refund_max_amount"] == 1000
    assert policy["require_note"] is False


def test_policy_upsert_and_validation(c_store):
    policy = store.upsert_merchant_policy(
        "m_gear_002",
        allowed_actions=["CREATE_AFTER_SALE", "ISSUE_COMPENSATION"],
        compensation_max_amount=20,
        refund_max_amount=100,
        require_note=True,
        updated_by="owner",
    )
    assert policy["allowed_actions"] == ["CREATE_AFTER_SALE", "ISSUE_COMPENSATION"]
    assert policy["compensation_max_amount"] == 20
    assert policy["require_note"] is True
    with pytest.raises(store.CStoreError):
        store.upsert_merchant_policy(
            "m_gear_002",
            allowed_actions=[],
            compensation_max_amount=20,
            refund_max_amount=100,
        )
    with pytest.raises(store.CStoreError):
        store.upsert_merchant_policy(
            "m_gear_002",
            allowed_actions=["DROP_DATABASE"],
            compensation_max_amount=20,
            refund_max_amount=100,
        )


def test_check_action_policy(c_store):
    store.upsert_merchant_policy(
        "m_gear_002",
        allowed_actions=["ISSUE_COMPENSATION", "REFUND_AFTER_SALE"],
        compensation_max_amount=10,
        refund_max_amount=100,
    )
    assert store.check_action_policy("m_gear_002", "ISSUE_COMPENSATION", amount=10) == (True, "")
    assert store.check_action_policy("m_gear_002", "ISSUE_COMPENSATION", amount=11)[0] is False
    assert store.check_action_policy("m_gear_002", "CANCEL_ORDER")[0] is False
    assert store.check_action_policy("m_gear_002", "REFUND_AFTER_SALE", refund_amount=101)[0] is False


def test_action_execution_enforces_policy(c_store):
    order_id = _completed_order()
    store.upsert_merchant_policy(
        "m_gear_002",
        allowed_actions=["ISSUE_COMPENSATION"],
        compensation_max_amount=10,
        refund_max_amount=100,
    )
    with pytest.raises(actions.ActionError) as exc:
        actions._execute(
            {"action_type": "CANCEL_ORDER", "order_id": order_id}, "m_gear_002"
        )
    assert exc.value.code == "ACTION_NOT_ALLOWED_BY_POLICY"

    with pytest.raises(actions.ActionError) as exc:
        actions._execute(
            {"action_type": "ISSUE_COMPENSATION", "order_id": order_id, "amount": 20},
            "m_gear_002",
        )
    assert exc.value.code == "COMPENSATION_EXCEEDS_POLICY"
