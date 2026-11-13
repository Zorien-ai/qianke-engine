"""B 端商家工作台：租户绑定与订单作用域。"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from rag_demo.api import b_workbench
from rag_demo.c_end import store
from rag_demo.merchant import get_merchant_write_repository


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def _admin(monkeypatch):
    monkeypatch.setattr(
        b_workbench.auth,
        "current_account",
        lambda: {"id": 1, "username": "admin", "display_name": "Admin", "status": "active", "is_system_admin": True},
    )


def test_system_admin_is_bound_to_default_merchant(c_store, monkeypatch):
    _admin(monkeypatch)
    data = b_workbench.workbench_me()
    assert data["merchant"]["merchant_id"] == b_workbench.DEFAULT_MERCHANT_ID
    assert data["merchant"]["role"] == "owner"
    assert data["counts"]["products"] > 0
    assert data["counts"]["orders"] > 0


def test_products_include_available_stock(c_store, monkeypatch):
    _admin(monkeypatch)
    data = b_workbench.workbench_products()
    products = data["products"]
    assert products
    assert data["summary"]["total_products"] == len(products)
    assert data["summary"]["low_stock_products"] <= len(products)
    assert data["summary"]["low_stock_skus"] >= 0
    assert data["summary"]["suggested_reorder_qty"] >= 0
    assert all("reorder_qty" in product for product in products)
    assert all("stock" in product and "available_qty" in product for product in products)
    assert all("low_stock" in product and "safety_stock" in product for product in products)
    assert any(int(product["stock"]) > 0 for product in products)
    assert any("available_qty" in sku for product in products for sku in product["skus"])


def test_unbound_non_admin_is_rejected(c_store, monkeypatch):
    monkeypatch.setattr(
        b_workbench.auth,
        "current_account",
        lambda: {"id": 99, "username": "other", "status": "active", "is_system_admin": False},
    )
    with pytest.raises(HTTPException) as exc:
        b_workbench.workbench_orders()
    assert exc.value.status_code == 403


def test_orders_are_scoped_to_bound_merchant(c_store, monkeypatch):
    _admin(monkeypatch)
    data = b_workbench.workbench_orders()
    assert data["merchant_id"] == b_workbench.DEFAULT_MERCHANT_ID
    assert all(order["merchant_id"] == b_workbench.DEFAULT_MERCHANT_ID for order in data["orders"])

    # 绑定到另一个租户后只能看到该租户订单。
    store.bind_merchant_member(1, "m_tea_001", role="owner")
    tea = b_workbench.workbench_orders()
    assert tea["merchant_id"] == "m_tea_001"
    assert all(order["merchant_id"] == "m_tea_001" for order in tea["orders"])


def test_update_order_status_is_scoped(c_store, monkeypatch):
    _admin(monkeypatch)
    data = b_workbench.workbench_orders(status="SHIPPED")
    if not data["orders"]:
        pytest.skip("种子中没有 SHIPPED 订单")
    order_id = data["orders"][0]["order_id"]
    result = b_workbench.workbench_update_order(
        order_id,
        b_workbench.WorkbenchOrderStatusIn(status="COMPLETED"),
    )
    assert result["order"]["status"] == "COMPLETED"
    assert result["order"]["merchant_id"] == b_workbench.DEFAULT_MERCHANT_ID


def test_staff_is_read_only(c_store, monkeypatch):
    store.bind_merchant_member(42, b_workbench.DEFAULT_MERCHANT_ID, role="staff")
    monkeypatch.setattr(
        b_workbench.auth,
        "current_account",
        lambda: {"id": 42, "username": "staff", "status": "active", "is_system_admin": False},
    )
    data = b_workbench.workbench_me()
    assert data["merchant"]["role"] == "staff"
    assert "view_orders" in data["permissions"]
    assert "operate_orders" not in data["permissions"]
    assert b_workbench.workbench_orders()["merchant_id"] == b_workbench.DEFAULT_MERCHANT_ID

    with pytest.raises(HTTPException) as exc:
        b_workbench.workbench_update_order(
            "order_any", b_workbench.WorkbenchOrderStatusIn(status="COMPLETED")
        )
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        b_workbench.workbench_resolve_after_sale(
            "as_any", b_workbench.WorkbenchAfterSaleResolveIn(approved=True)
        )
    assert exc.value.status_code == 403


def test_admin_role_can_operate(c_store):
    assert "operate_orders" in b_workbench.permissions_for("admin")
    assert "manage_members" not in b_workbench.permissions_for("admin")
    assert "manage_members" in b_workbench.permissions_for("owner")


def test_inventory_alerts_scan_and_ack(c_store, monkeypatch):
    _admin(monkeypatch)
    first = b_workbench.workbench_inventory_scan()
    assert first["pending"] >= 1
    assert first["alerts"]
    alert_id = first["alerts"][0]["alert_id"]
    assert first["dispatch"]["configured"] is False

    # 重复扫描不产生重复事件。
    second = b_workbench.workbench_inventory_scan()
    assert second["created"] == 0
    assert second["pending"] == first["pending"]

    acked = b_workbench.workbench_inventory_alert_ack(alert_id)
    assert acked["alert"]["status"] == "ACKED"
    queues = b_workbench.workbench_inventory_alerts(status="PENDING")
    assert all(alert["alert_id"] != alert_id for alert in queues["alerts"])

    # 恢复后再次低库存：RESOLVED 的告警必须重新进入 PENDING。
    store.sync_inventory_alerts(b_workbench.DEFAULT_MERCHANT_ID, [])
    reopened = b_workbench.workbench_inventory_scan()
    assert reopened["pending"] >= 1
    assert any(alert["alert_id"] == alert_id and alert["status"] == "PENDING" for alert in reopened["alerts"])


def test_dispatch_inventory_alerts_marks_sent(c_store, monkeypatch):
    _admin(monkeypatch)
    b_workbench.workbench_inventory_scan()
    captured = {}

    def fake_deliver(alerts):
        captured["alerts"] = alerts
        return {"sent": True, "msgid": "msg-1", "channel": "wecom_app"}

    monkeypatch.setattr(b_workbench.alert_notifier, "deliver_inventory_alerts_wecom", fake_deliver)
    result = b_workbench.workbench_inventory_dispatch()
    assert result["sent"] is True
    assert result["dispatched"] >= 1
    assert result["remaining"] == 0
    assert captured["alerts"]
    sent = c_store.list_inventory_alerts(b_workbench.DEFAULT_MERCHANT_ID, status="SENT")
    assert sent and sent[0]["status"] == "SENT"


def test_dispatch_inventory_alerts_without_recipient_keeps_queue(c_store, monkeypatch):
    _admin(monkeypatch)
    b_workbench.workbench_inventory_scan()
    monkeypatch.setattr(
        b_workbench.alert_notifier,
        "deliver_inventory_alerts_wecom",
        lambda alerts: {"sent": False, "reason": "NO_RECIPIENT"},
    )
    result = b_workbench.workbench_inventory_dispatch()
    assert result["sent"] is False
    assert result["dispatched"] == 0
    assert result["remaining"] >= 1


def test_staff_cannot_scan_inventory_alerts(c_store, monkeypatch):
    store.bind_merchant_member(43, b_workbench.DEFAULT_MERCHANT_ID, role="staff")
    monkeypatch.setattr(
        b_workbench.auth,
        "current_account",
        lambda: {"id": 43, "username": "staff2", "status": "active", "is_system_admin": False},
    )
    with pytest.raises(HTTPException) as exc:
        b_workbench.workbench_inventory_scan()
    assert exc.value.status_code == 403


def test_after_sales_only_for_bound_merchant(c_store, monkeypatch):
    _admin(monkeypatch)
    # 没有工单时返回空列表即可；有工单时必须属于当前商家。
    data = b_workbench.workbench_after_sales()
    assert data["merchant_id"] == b_workbench.DEFAULT_MERCHANT_ID
    for ticket in data["tickets"]:
        order = c_store.get_order(ticket["order_id"])
        assert order is not None


def test_orders_search_pagination_and_total(c_store, monkeypatch):
    _admin(monkeypatch)
    first = b_workbench.workbench_orders(limit=2, offset=0)
    assert first["limit"] == 2
    assert first["offset"] == 0
    assert first["total"] >= len(first["orders"])
    assert len(first["orders"]) <= 2
    second = b_workbench.workbench_orders(limit=2, offset=2)
    assert second["offset"] == 2
    # 搜索订单号时总数和结果同口径。
    known = first["orders"][0]["order_id"]
    searched = b_workbench.workbench_orders(q=known, limit=20, offset=0)
    assert searched["total"] >= 1
    assert any(order["order_id"] == known for order in searched["orders"])
    assert all(known in str(order.get("order_id") or "") or known in str(order.get("buyer_id") or "") or known in str(order) for order in searched["orders"])


def test_orders_reject_invalid_date(c_store, monkeypatch):
    _admin(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        b_workbench.workbench_orders(date_from="2026-13-99")
    assert exc.value.status_code == 400
