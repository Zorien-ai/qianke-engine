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


def test_companion_is_configurable_not_hardcoded_fish(c_store):
    companion = c_store.get_companion("buyer_1")
    assert companion["species"] == "digital_companion"
    assert companion["name"] == "小伴"

    updated = c_store.update_companion(
        "buyer_1",
        name="阿团",
        species="cat",
        persona="calm",
        appearance="cat-v1",
    )
    assert updated["name"] == "阿团"
    assert updated["species"] == "cat"
    assert c_store.get_companion("buyer_1")["appearance"] == "cat-v1"


def test_confirm_rewards_companion_once(c_store):
    before = c_store.get_companion("buyer_1")
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_companion_reward_1",
    )
    after = c_store.get_companion("buyer_1")
    assert after["exp"] == before["exp"] + 10
    assert after["satiety"] == min(100, before["satiety"] + 5)

    c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_companion_reward_1",
    )
    repeated = c_store.get_companion("buyer_1")
    assert repeated["exp"] == after["exp"]
    assert repeated["satiety"] == after["satiety"]


def test_quote_links_order_and_consumes_audit(c_store):
    quote = c_store.create_quote(
        "buyer_1",
        "store_demo",
        {
            "quote_id": "quote_audit_1",
            "product_refs": [{"product_id": "P001", "title": "轻量跑鞋", "price": 299.0}],
            "policy_refs": [{"policy_id": "platform_full_reduce", "title": "满减活动"}],
        },
    )
    assert quote["status"] == "PENDING"

    draft = c_store.prepare_order("buyer_1", [], quote_id="quote_audit_1")
    assert draft["quote_id"] == "quote_audit_1"
    assert draft["original_amount"] == 299.0
    assert draft["discount_amount"] == 30.0
    assert draft["total_amount"] == 269.0
    assert draft["policy_ids"] == ["platform_full_reduce"]

    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_quote_audit_1",
    )
    assert order["quote_id"] == "quote_audit_1"
    assert order["policy_ids"] == ["platform_full_reduce"]
    assert c_store.get_quote("quote_audit_1", "buyer_1")["status"] == "CONSUMED"
