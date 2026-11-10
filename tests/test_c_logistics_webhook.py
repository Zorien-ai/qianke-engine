"""物流签收回调：只接已签收事件，HMAC 验签、防重放、幂等。"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_demo.api.c_end import router
from rag_demo.c_end import store
from rag_demo.merchant import (
    get_merchant_repository,
    get_merchant_write_repository,
    reset_merchant_repository_cache,
)

SECRET = "test-logistics-secret"


@pytest.fixture()
def logistics_env(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setenv("QIANKE_MERCHANT_DB", str(tmp_path / "merchant.sqlite"))
    monkeypatch.setenv("QIANKE_LOGISTICS_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(store, "_DB_PATH", None)
    reset_merchant_repository_cache()
    store.init()
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    reset_merchant_repository_cache()


def _confirmed_order() -> dict:
    draft = store.prepare_order("buyer_1", [{"product_id": "P001", "quantity": 1}])
    return store.confirm_order("buyer_1", draft["order_id"], draft["confirmation_token"])


def _ship(order_id: str) -> None:
    writer = get_merchant_write_repository()
    writer.update_order_status(store._MERCHANT_ID, order_id, "PAID")
    writer.update_order_status(
        store._MERCHANT_ID,
        order_id,
        "SHIPPED",
        tracking_no="SF123456789",
        carrier="SF",
    )


def _signed_request(client: TestClient, payload: dict, *, secret: str = SECRET):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    signature = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/c/webhooks/logistics/signed",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Qianke-Timestamp": ts,
            "X-Qianke-Signature": f"sha256={signature}",
        },
    )


def test_signed_event_completes_order_and_schedules_followup(logistics_env):
    order = _confirmed_order()
    _ship(order["order_id"])
    payload = {
        "event_id": "evt_signed_0001",
        "provider": "test-carrier",
        "order_id": order["order_id"],
        "status": "SIGNED",
        "tracking_no": "SF123456789",
        "carrier": "SF",
    }
    response = _signed_request(logistics_env, payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["duplicate"] is False
    assert data["status"] == "COMPLETED"
    assert data["followup_scheduled"] is True

    merchant = get_merchant_repository().get_order(
        order["order_id"], merchant_id=store._MERCHANT_ID
    )
    assert merchant.status == "COMPLETED"
    assert merchant.completed_at

    conn = store._connect()
    try:
        checkin = conn.execute(
            "SELECT * FROM c_companion_checkin WHERE ref_id = ?", (order["order_id"],)
        ).fetchone()
        event = conn.execute(
            "SELECT * FROM c_logistics_event WHERE event_id = ?", ("evt_signed_0001",)
        ).fetchone()
    finally:
        conn.close()
    assert checkin is not None
    assert event is not None
    assert event["status"] == "SIGNED"

    duplicate = _signed_request(logistics_env, payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True


def test_shipped_event_is_rejected(logistics_env):
    order = _confirmed_order()
    _ship(order["order_id"])
    payload = {
        "event_id": "evt_shipped_0001",
        "order_id": order["order_id"],
        "status": "SHIPPED",
    }
    response = _signed_request(logistics_env, payload)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "NOT_SIGNED_EVENT"


def test_bad_signature_is_rejected(logistics_env):
    order = _confirmed_order()
    payload = {"event_id": "evt_bad_0001", "order_id": order["order_id"], "status": "SIGNED"}
    response = _signed_request(logistics_env, payload, secret="wrong-secret")
    assert response.status_code == 401


def test_webhook_disabled_without_secret(logistics_env, monkeypatch):
    monkeypatch.delenv("QIANKE_LOGISTICS_WEBHOOK_SECRET", raising=False)
    response = logistics_env.post(
        "/api/c/webhooks/logistics/signed",
        json={"event_id": "evt_disabled_0001", "order_id": "order_1", "status": "SIGNED"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LOGISTICS_WEBHOOK_DISABLED"
