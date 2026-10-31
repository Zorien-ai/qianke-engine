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
