"""C 端订单物流查询接口：本人可见、无运单号、未配置服务商。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_demo import auth
from rag_demo.api.c_end import router
from rag_demo.c_end import express, store
from rag_demo.merchant import get_merchant_write_repository, reset_merchant_repository_cache


@pytest.fixture()
def tracking_api(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setenv("QIANKE_MERCHANT_DB", str(tmp_path / "merchant.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    reset_merchant_repository_cache()
    store.init()
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(
        auth,
        "current_account",
        lambda: {"id": 1, "username": "buyer_a", "status": auth.STATUS_ACTIVE},
    )
    yield TestClient(app)
    reset_merchant_repository_cache()


def _shipped_order() -> str:
    draft = store.prepare_order("buyer_1", [{"product_id": "P001", "quantity": 1}])
    order = store.confirm_order("buyer_1", draft["order_id"], draft["confirmation_token"])
    writer = get_merchant_write_repository()
    writer.update_order_status(store._MERCHANT_ID, order["order_id"], "PAID")
    writer.update_order_status(
        store._MERCHANT_ID,
        order["order_id"],
        "SHIPPED",
        tracking_no="SF123456789",
        carrier="SF",
    )
    return order["order_id"]


def test_tracking_api_returns_normalized_tracking(tracking_api, monkeypatch):
    order_id = _shipped_order()
    monkeypatch.setattr(
        express,
        "query_tracking",
        lambda carrier, tracking_no: {
            "provider": "kuaidi100",
            "carrier_code": "shunfeng",
            "tracking_no": tracking_no,
            "state": "5",
            "state_text": "派送中",
            "events": [{"time": "2026-11-10 09:00:00", "text": "快件派送中"}],
            "from_cache": False,
        },
    )
    response = tracking_api.get(f"/api/c/orders/{order_id}/tracking")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["state_text"] == "派送中"
    assert data["events"][0]["text"] == "快件派送中"
    assert data["carrier"] == "SF"


def test_tracking_api_hides_other_buyer_order(tracking_api):
    order_id = _shipped_order()
    response = tracking_api.get(f"/api/c/orders/{order_id}/tracking")
    assert response.status_code in {200, 503}
    # 用另一个账号访问同一订单必须 404
    from rag_demo import auth as auth_module

    original = auth_module.current_account
    auth_module.current_account = lambda: {"id": 2, "username": "buyer_b", "status": auth.STATUS_ACTIVE}
    try:
        other = tracking_api.get(f"/api/c/orders/{order_id}/tracking")
    finally:
        auth_module.current_account = original
    assert other.status_code == 404


def test_tracking_api_unconfigured_is_503(tracking_api, monkeypatch):
    order_id = _shipped_order()

    def fail(carrier, tracking_no):
        raise express.ExpressError("EXPRESS_NOT_CONFIGURED", "物流查询未配置", 503)

    monkeypatch.setattr(express, "query_tracking", fail)
    response = tracking_api.get(f"/api/c/orders/{order_id}/tracking")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EXPRESS_NOT_CONFIGURED"
