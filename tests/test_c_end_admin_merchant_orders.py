"""商家运营台管理员订单列表 API。"""
from __future__ import annotations

from rag_demo.api import c_end


def test_admin_merchant_orders_lists_all_buyers(monkeypatch):
    monkeypatch.setattr(c_end, "_require_admin", lambda: {"id": 1, "is_system_admin": True})
    data = c_end.admin_merchant_orders(limit=5)
    assert data["source"] == "merchant_v1"
    orders = data["orders"]
    assert orders
    assert len(orders) <= 5
    assert {"order_id", "buyer_id", "status", "total_amount", "items"} <= set(orders[0])


def test_admin_merchant_orders_filters_by_c_buyer_and_status(monkeypatch):
    monkeypatch.setattr(c_end, "_require_admin", lambda: {"id": 1, "is_system_admin": True})
    shipped = c_end.admin_merchant_orders(status="SHIPPED")
    assert all(order["status"] == "SHIPPED" for order in shipped["orders"])
    buyer_orders = c_end.admin_merchant_orders(buyer_id="buyer_1")
    assert all(order["buyer_id"] == "b_2001" for order in buyer_orders["orders"])
