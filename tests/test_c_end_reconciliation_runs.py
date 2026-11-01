"""对账任务留痕：run_reconciliation / list_reconciliation_runs。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store
from rag_demo.merchant import get_merchant_write_repository


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def test_run_reconciliation_persists_clean_run(c_store):
    report = c_store.run_reconciliation("manual")
    assert report["trigger"] == "MANUAL"
    assert report["ok"] is True
    assert report["issue_count"] == 0
    runs = c_store.list_reconciliation_runs(limit=5)
    assert runs[0]["run_id"] == report["run_id"]
    assert runs[0]["ok"] is True
    assert runs[0]["issues"] == []


def test_run_reconciliation_persists_issues(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_reconcile_run_001",
    )
    # 只取消商家侧，制造状态分叉。
    get_merchant_write_repository().cancel_order("m_gear_002", order["order_id"])
    report = c_store.run_reconciliation("MANUAL")
    assert report["ok"] is False
    assert report["issue_count"] >= 1
    assert any(item["order_id"] == order["order_id"] for item in report["issues"])

    runs = c_store.list_reconciliation_runs(limit=10)
    stored = next(item for item in runs if item["run_id"] == report["run_id"])
    assert stored["issue_count"] == report["issue_count"]
    assert any(item["issue"] == "STATUS_DIVERGENCE" for item in stored["issues"])


def test_list_reconciliation_runs_limit_and_order(c_store):
    first = c_store.run_reconciliation("MANUAL")
    second = c_store.run_reconciliation("SCHEDULED")
    runs = c_store.list_reconciliation_runs(limit=1)
    assert len(runs) == 1
    assert runs[0]["run_id"] in {first["run_id"], second["run_id"]}
    all_runs = c_store.list_reconciliation_runs(limit=10)
    assert len(all_runs) >= 2


def _create_divergence(c_store, request_id: str):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id=request_id,
    )
    get_merchant_write_repository().cancel_order("m_gear_002", order["order_id"])
    return order


def test_reconciliation_alerts_are_created_and_deduped(c_store):
    order = _create_divergence(c_store, "req_reconcile_alert_001")
    report = c_store.run_reconciliation("MANUAL")
    assert report["alert_count"] >= 1
    alerts = c_store.list_reconciliation_alerts()
    assert len(alerts) == 1
    assert alerts[0]["order_id"] == order["order_id"]
    assert alerts[0]["issue"] == "STATUS_DIVERGENCE"
    assert "人工确认" in alerts[0]["suggestion"]
    assert c_store.unread_reconciliation_alert_count() == 1

    # 同一问题重复对账不新增第二条告警。
    second = c_store.run_reconciliation("SCHEDULED")
    assert second["alert_count"] == 1
    assert len(c_store.list_reconciliation_alerts()) == 1

    assert c_store.mark_reconciliation_alerts_read() == 1
    assert c_store.unread_reconciliation_alert_count() == 0
    assert c_store.list_reconciliation_alerts(unread_only=True) == []


def test_reconciliation_alert_resolves_when_issue_disappears(c_store):
    order = _create_divergence(c_store, "req_reconcile_alert_002")
    c_store.run_reconciliation("MANUAL")
    assert len(c_store.list_reconciliation_alerts()) == 1

    # 把 C 侧也取消，状态重新一致后，下一次对账应把告警标记 resolved。
    c_store.cancel_confirmed_order("buyer_1", order["order_id"], request_id="req_alert_fix_001")
    report = c_store.run_reconciliation("MANUAL")
    assert report["ok"] is True
    assert report["alert_count"] == 0
    assert c_store.list_reconciliation_alerts() == []
