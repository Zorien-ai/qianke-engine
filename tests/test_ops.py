"""运维探针：readiness 与 Prometheus 文本。"""
from __future__ import annotations

import pytest

from rag_demo.api import ops
from rag_demo.c_end import store
from rag_demo.superagent import store as sa_store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    sa_store.init()
    return store


def test_readiness_reports_all_checks(c_store, monkeypatch):
    import rag_demo.merchant as merchant

    class FakeRepo:
        backend = "sqlite"

        def list_products(self, merchant_id, limit=1):
            return []

    monkeypatch.setattr(merchant, "get_merchant_repository", lambda: FakeRepo())
    ok, payload = ops.readiness()
    assert ok is True
    assert payload["status"] == "ok"
    names = {item["name"] for item in payload["checks"]}
    assert names == {"control_store", "superagent_store", "queue", "merchant_store"}
    assert all(item["ok"] for item in payload["checks"])


def test_metrics_contains_queue_and_tenant_gauges(c_store):
    text = ops.metrics_text()
    assert "qianke_up 1" in text
    assert "qianke_queue_jobs{status=\"pending\"}" in text
    assert "qianke_work_items" in text
    assert "qianke_approvals" in text
    assert "qianke_tenants" in text
