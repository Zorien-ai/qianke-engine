"""C 商城下单与商家库存预占/订单写入的联动测试。"""
from __future__ import annotations

import sqlite3

import pytest

from rag_demo.c_end import store
from rag_demo.merchant import get_merchant_repository, get_merchant_write_repository


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def _merchant_stock(sku: str) -> int:
    inventory = get_merchant_repository().get_inventory(sku)
    assert inventory is not None
    return inventory.available_qty


def _c_stock(c_store, product_id: str) -> int:
    conn = sqlite3.connect(str(c_store._db_path()))
    try:
        return conn.execute(
            "SELECT stock FROM c_product WHERE product_id = ?", (product_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_prepare_reserves_and_confirm_writes_merchant_order(c_store):
    sku = "SKU-GEAR-P001-STD"
    assert _merchant_stock(sku) == 20

    draft = c_store.prepare_order("buyer_1", [{"product_id": "P001", "quantity": 2}])
    assert draft["merchant_reservation_id"] == draft["order_id"]
    assert _merchant_stock(sku) == 18
    assert _c_stock(c_store, "P001") == 20

    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_merchant_order_001",
    )
    assert order["status"] == "CONFIRMED"
    assert order["merchant_order_id"] == order["order_id"]
    assert order["merchant_status"] == "CREATED"
    assert order["merchant_source"] == "merchant_v1"
    assert _merchant_stock(sku) == 18
    assert _c_stock(c_store, "P001") == 18

    merchant_order = get_merchant_repository().get_order(
        order["order_id"], merchant_id="m_gear_002", buyer_id="b_2001"
    )
    assert merchant_order is not None
    assert merchant_order.status == "CREATED"
    assert merchant_order.total_amount == 598


def test_cancel_releases_merchant_reservation(c_store):
    sku = "SKU-GEAR-P002-STD"
    assert _merchant_stock(sku) == 15
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P002", "quantity": 1}])
    assert _merchant_stock(sku) == 14
    result = c_store.cancel_order_draft("buyer_1", draft["order_id"])
    assert result["status"] == "CANCELLED"
    assert _merchant_stock(sku) == 15
    assert _c_stock(c_store, "P002") == 15


def test_repeated_confirm_does_not_double_deduct(c_store):
    sku = "SKU-GEAR-P003-STD"
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 3}])
    first = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_merchant_idem_001",
    )
    repeated = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_merchant_idem_001",
    )
    assert repeated["order_id"] == first["order_id"]
    assert _merchant_stock(sku) == 47
    assert _c_stock(c_store, "P003") == 47


def test_merchant_stock_shortage_blocks_prepare(c_store):
    sku = "SKU-GEAR-P006-STD"
    writer = get_merchant_write_repository()
    writer.reserve_inventory(
        "m_gear_002",
        "rsv_test_exhaust_p006",
        [{"product_id": "P006", "quantity": 18}],
        ttl_seconds=900,
        buyer_id="b_2001",
    )
    assert _merchant_stock(sku) == 0
    with pytest.raises(c_store.CStoreError) as exc:
        c_store.prepare_order("buyer_1", [{"product_id": "P006", "quantity": 1}])
    assert exc.value.code == "INSUFFICIENT_STOCK"
    assert _c_stock(c_store, "P006") == 18


def test_order_list_includes_merchant_status(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P004", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_merchant_list_001",
    )
    orders = c_store.list_orders("buyer_1")
    assert orders[0]["order_id"] == order["order_id"]
    assert orders[0]["merchant_status"] == "CREATED"
    assert orders[0]["merchant_source"] == "merchant_v1"


def test_order_list_exposes_logistics_after_shipping(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P005", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_merchant_ship_001",
    )
    writer = get_merchant_write_repository()
    writer.update_order_status("m_gear_002", order["order_id"], "PAID")
    writer.update_order_status(
        "m_gear_002",
        order["order_id"],
        "SHIPPED",
        tracking_no="SF1234567890",
        carrier="顺丰速运",
    )
    shipped = c_store.list_orders("buyer_1")[0]
    assert shipped["merchant_status"] == "SHIPPED"
    assert shipped["merchant_tracking_no"] == "SF1234567890"
    assert shipped["merchant_carrier"] == "顺丰速运"
    assert shipped["merchant_status_at"]
    timeline = {entry["status"]: entry["at"] for entry in shipped["merchant_timeline"]}
    assert "CREATED" in timeline and "PAID" in timeline and "SHIPPED" in timeline


def test_cancel_confirmed_order_restores_both_stocks(c_store):
    sku = "SKU-GEAR-P001-STD"
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P001", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_merchant_cancel_001",
    )
    assert _merchant_stock(sku) == 19
    assert _c_stock(c_store, "P001") == 19
    cancelled = c_store.cancel_confirmed_order(
        "buyer_1",
        order["order_id"],
        request_id="req_c_merchant_cancel_001",
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["merchant_status"] == "CANCELLED"
    assert cancelled["merchant_refund_amount"] == 0.0
    assert cancelled["can_cancel"] is False
    assert _merchant_stock(sku) == 20
    assert _c_stock(c_store, "P001") == 20
    assert any(row["order_id"] == order["order_id"] for row in c_store.list_orders("buyer_1"))


def test_cancel_paid_order_refunds_amount(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P002", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_merchant_cancel_paid_001",
    )
    get_merchant_write_repository().update_order_status(
        "m_gear_002", order["order_id"], "PAID"
    )
    cancelled = c_store.cancel_confirmed_order("buyer_1", order["order_id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["merchant_refund_amount"] == 199.0
    assert cancelled["merchant_refunded_at"]


def test_reconcile_detects_merchant_cancel_without_c_cancel(c_store):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P003", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_c_merchant_reconcile_001",
    )
    # 只取消商家侧，故意制造 C/商家状态分叉，验证对账能发现。
    get_merchant_write_repository().cancel_order("m_gear_002", order["order_id"])
    report = c_store.reconcile_orders()
    assert report["ok"] is False
    assert any(
        issue["order_id"] == order["order_id"] and issue["issue"] == "STATUS_DIVERGENCE"
        for issue in report["issues"]
    )


def _shipped_order(c_store, request_id: str):
    draft = c_store.prepare_order("buyer_1", [{"product_id": "P001", "quantity": 1}])
    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id=request_id,
    )
    writer = get_merchant_write_repository()
    writer.update_order_status("m_gear_002", order["order_id"], "PAID")
    writer.update_order_status(
        "m_gear_002",
        order["order_id"],
        "SHIPPED",
        tracking_no="SF1234567890",
        carrier="顺丰速运",
    )
    return order


def test_after_sale_approved_refunds_order(c_store):
    order = _shipped_order(c_store, "req_c_after_sale_001")
    ticket = c_store.create_after_sale(
        "buyer_1",
        order["order_id"],
        sale_type="REFUND_ONLY",
        reason="尺码不合适",
    )
    assert ticket["status"] == "OPEN"
    payload = c_store.get_order(order["order_id"])
    assert payload["can_after_sale"] is False
    assert payload["after_sale"]["ticket_id"] == ticket["ticket_id"]

    resolved = c_store.resolve_after_sale(ticket["ticket_id"], approved=True)
    assert resolved["status"] == "APPROVED"
    assert resolved["refund_amount"] == 299.0
    refunded = c_store.get_order(order["order_id"])
    assert refunded["status"] == "REFUNDED"
    assert refunded["merchant_status"] == "REFUNDED"
    assert refunded["merchant_refund_amount"] == 299.0
    assert any(row["order_id"] == order["order_id"] for row in c_store.list_orders("buyer_1"))


def test_after_sale_rejected_keeps_order(c_store):
    order = _shipped_order(c_store, "req_c_after_sale_002")
    ticket = c_store.create_after_sale(
        "buyer_1",
        order["order_id"],
        sale_type="RETURN_REFUND",
        reason="不想要了",
    )
    resolved = c_store.resolve_after_sale(ticket["ticket_id"], approved=False)
    assert resolved["status"] == "REJECTED"
    payload = c_store.get_order(order["order_id"])
    assert payload["status"] == "CONFIRMED"
    assert payload["merchant_status"] == "SHIPPED"
    assert payload["can_after_sale"] is True
