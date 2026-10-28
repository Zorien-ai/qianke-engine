"""C 端 mock 商品/模拟订单存储测试。"""
from __future__ import annotations

import sqlite3

import pytest

from rag_demo.c_end import store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def _product_stock(c_store, product_id: str) -> int:
    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        return conn.execute(
            "SELECT stock FROM c_product WHERE product_id = ?", (product_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_prepare_confirm_is_explicit_and_idempotent(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P001", "quantity": 2}])
    assert draft["status"] == "DRAFT"
    assert draft["total_amount"] == 598.0
    assert _product_stock(c_store, "P001") == 20

    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_order_001",
    )
    assert order["status"] == "CONFIRMED"
    assert order["total_amount"] == 598.0
    assert _product_stock(c_store, "P001") == 18

    repeated = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_order_001",
    )
    assert repeated["order_id"] == order["order_id"]
    assert _product_stock(c_store, "P001") == 18


def test_confirm_rejects_wrong_token(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P002", "quantity": 1}])
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.confirm_order("buyer_1", draft["order_id"], "wrong-token")
    assert exc.value.code == "INVALID_CONFIRMATION"
    assert _product_stock(c_store, "P002") == 15


def test_price_change_requires_reprepare(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        conn.execute("UPDATE c_product SET price = 99 WHERE product_id = 'P003'")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(c_store.CStoreError) as exc:
        c_store.confirm_order(
            "buyer_1",
            draft["order_id"],
            draft["confirmation_token"],
            request_id="req_c_price_changed",
        )
    assert exc.value.code == "ORDER_CHANGED"


def test_insufficient_stock_rejected(c_store):
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.prepare_order("buyer_1", [{"product_id": "P004", "quantity": 99}])
    assert exc.value.code == "INSUFFICIENT_STOCK"


def test_other_buyer_cannot_confirm(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P005", "quantity": 1}])
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.confirm_order("buyer_2", draft["order_id"], draft["confirmation_token"])
    assert exc.value.code == "ORDER_FORBIDDEN"
