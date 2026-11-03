"""商家级动作策略与额度。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store
from rag_demo.merchant import get_merchant_write_repository
from rag_demo.superagent import actions
from rag_demo.superagent import router as sa_router
from rag_demo.superagent import store as sa_store


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
    changes = store.list_policy_audit("m_gear_002")
    assert len(changes) == 1
    assert changes[0]["before"]["compensation_max_amount"] == 50
    assert changes[0]["after"]["compensation_max_amount"] == 20
    assert changes[0]["changed_by"] == "owner"
    # 相同配置不重复记审计。
    store.upsert_merchant_policy(
        "m_gear_002",
        allowed_actions=["CREATE_AFTER_SALE", "ISSUE_COMPENSATION"],
        compensation_max_amount=20,
        refund_max_amount=100,
        require_note=True,
        updated_by="owner",
    )
    assert len(store.list_policy_audit("m_gear_002")) == 1
    paged = store.query_policy_audit("m_gear_002", limit=1, offset=0)
    assert paged["total"] == 1
    assert len(paged["items"]) == 1
    today = paged["items"][0]["changed_at"][:10]
    assert store.query_policy_audit("m_gear_002", date_from=today)["total"] == 1
    assert store.query_policy_audit(
        "m_gear_002", date_from=f"{today}T00:00", date_to=f"{today}T23:59"
    )["total"] == 1
    assert store.query_policy_audit("m_gear_002", date_from="2099-01-01")["total"] == 0
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


def test_action_audit_lists_executed_action(c_store):
    order_id = _completed_order()
    accepted = sa_router.ingest_event(
        source="manual",
        content=f"订单 {order_id} 补偿 10 元",
        channel="test",
        thread_key="policy:audit",
        merchant_id="m_gear_002",
    )
    work_item_id = accepted["work_item"]["work_item_id"]
    sa_store.start_work_item(work_item_id)
    action = {
        "action_type": "ISSUE_COMPENSATION",
        "order_id": order_id,
        "amount": 10,
        "reason": "审计测试",
    }
    sa_store.finish_work_item(
        work_item_id, {"summary": "补偿", "action": action}, approval=True, action=action
    )
    sa_store.decide_approval(work_item_id, approved=True, note="同意")
    actions.execute_approved(work_item_id)

    result = sa_store.list_action_audit("m_gear_002")
    assert result["items"]
    row = next(item for item in result["items"] if item["work_item_id"] == work_item_id)
    assert row["action_type"] == "ISSUE_COMPENSATION"
    assert row["order_id"] == order_id
    assert row["execution_status"] == "EXECUTED"
    assert row["work_status"] == "DONE"
    today = row["executed_at"][:10]
    scoped = sa_store.list_action_audit("m_gear_002", date_from=today, date_to=today)
    assert scoped["total"] >= 1
    hourly = sa_store.list_action_audit(
        "m_gear_002", date_from=f"{today}T00:00", date_to=f"{today}T23:59"
    )
    assert hourly["total"] >= 1
    assert sa_store.list_action_audit("m_gear_002", date_from="2099-01-01")["total"] == 0
