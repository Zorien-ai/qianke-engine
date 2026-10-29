"""店宠 Agent 接真实商家数据层的工具测试。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store, store_agent
from rag_demo.merchant import reset_merchant_repository_cache


@pytest.fixture()
def merchant_env(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_MERCHANT_DB", str(tmp_path / "merchant.sqlite"))
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    reset_merchant_repository_cache()
    store.init()
    yield
    reset_merchant_repository_cache()


def _tool(name: str):
    tools = store_agent._tools("buyer_1")
    return {item.name: item for item in tools}[name]


def test_catalog_reads_merchant_products_and_inventory(merchant_env):
    result = _tool("search_catalog").invoke({"need": "跑鞋", "budget": 300})
    assert result["ok"] is True
    assert result["source"] == "merchant_v1"
    product = next(item for item in result["products"] if item["product_id"] == "P001")
    assert product["sku"] == "SKU-GEAR-P001-STD"
    assert product["stock"] == 20
    assert product["in_stock"] is True
    assert product["source"] == "merchant_v1"


def test_inventory_query_is_read_only(merchant_env):
    result = _tool("search_inventory").invoke({"sku": "SKU-GEAR-P001-STD"})
    assert result["ok"] is True
    assert result["source"] == "merchant_v1"
    assert result["inventory"]["available_qty"] == 20
    assert result["inventory"]["in_stock"] is True


def test_orders_are_scoped_to_current_buyer(merchant_env):
    result = _tool("search_my_orders").invoke({"status": "SHIPPED"})
    assert result["ok"] is True
    assert result["source"] == "merchant_v1"
    assert {order["order_id"] for order in result["orders"]} == {
        "ORD-20261004-0004",
        "ORD-20261007-0007",
    }
    assert all(order["buyer_id"] == "b_2001" for order in result["orders"])


def test_order_lookup_by_id_and_unknown(merchant_env):
    found = _tool("search_my_orders").invoke({"order_id": "ORD-20261008-0008"})
    assert found["ok"] is True
    assert found["order"]["status"] == "COMPLETED"

    missing = _tool("search_my_orders").invoke({"order_id": "ORD-NOT-EXISTS"})
    assert missing["ok"] is False
    assert missing["error"]["code"] == "ORDER_NOT_FOUND"
