"""对账告警 Webhook：配置、payload、失败不影响主流程。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import alerts, store
from rag_demo.merchant import get_merchant_write_repository


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def _divergence(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_webhook_001",
    )
    get_merchant_write_repository().cancel_order("m_gear_002", order["order_id"])
    return order


def test_webhook_not_configured_does_not_send(c_store, monkeypatch):
    monkeypatch.delenv(alerts.WEBHOOK_URL_ENV, raising=False)
    _divergence(c_store)
    report = c_store.run_reconciliation("MANUAL")
    assert report["webhook"]["sent"] is False
    assert report["webhook"]["reason"] == "NOT_CONFIGURED"


def test_webhook_sends_alert_payload(c_store, monkeypatch):
    monkeypatch.setenv(alerts.WEBHOOK_URL_ENV, "http://127.0.0.1:9/hook")
    captured: dict = {}

    def fake_post(url, token, payload):
        captured["url"] = url
        captured["token"] = token
        captured["payload"] = payload
        return True, 200, ""

    monkeypatch.setattr(alerts, "_post_webhook", fake_post)
    order = _divergence(c_store)
    report = c_store.run_reconciliation("MANUAL")
    assert report["webhook"]["sent"] is True
    payload = captured["payload"]
    assert payload["event"] == "reconciliation.alert"
    assert payload["run_id"] == report["run_id"]
    assert payload["alerts"][0]["order_id"] == order["order_id"]
    assert payload["alerts"][0]["issue"] == "STATUS_DIVERGENCE"
    assert "人工确认" in payload["alerts"][0]["suggestion"]


def test_webhook_failure_does_not_break_reconciliation(c_store, monkeypatch):
    monkeypatch.setenv(alerts.WEBHOOK_URL_ENV, "http://127.0.0.1:9/hook")

    def fake_post(url, token, payload):
        return False, 0, "connection refused"

    monkeypatch.setattr(alerts, "_post_webhook", fake_post)
    _divergence(c_store)
    report = c_store.run_reconciliation("MANUAL")
    assert report["ok"] is False
    assert report["issue_count"] == 1
    assert report["webhook"]["sent"] is False
    assert report["webhook"]["reason"] == "DELIVERY_FAILED"


def test_webhook_rejects_non_http_url(c_store, monkeypatch):
    monkeypatch.setenv(alerts.WEBHOOK_URL_ENV, "file:///tmp/hook")
    _divergence(c_store)
    report = c_store.run_reconciliation("MANUAL")
    assert report["webhook"]["sent"] is False
    assert report["webhook"]["reason"] == "INVALID_URL"
