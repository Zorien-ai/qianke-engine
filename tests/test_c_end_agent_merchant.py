"""C 端伙伴 Agent 的真实商家商品/订单工具测试。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import agent as c_agent
from rag_demo.c_end import store
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


def _tools():
    return {item.name: item for item in c_agent._tools("buyer_1")}


def test_companion_agent_reads_merchant_products(merchant_env):
    result = _tools()["recommend_products"].invoke({"need": "跑鞋", "budget": 300})
    assert result["ok"] is True
    assert result["source"] == "merchant_v1"
    product = next(item for item in result["products"] if item["product_id"] == "P001")
    assert product["sku"] == "SKU-GEAR-P001-STD"
    assert product["stock"] == 20
    assert product["in_stock"] is True


def test_companion_agent_queries_own_merchant_orders(merchant_env):
    result = _tools()["query_my_orders"].invoke({"status": "SHIPPED"})
    assert result["ok"] is True
    assert result["source"] == "merchant_v1"
    order_ids = {order["order_id"] for order in result["orders"]}
    assert "ORD-20261007-0007" in order_ids
    assert all(order["buyer_id"] == "b_2001" for order in result["orders"])


def test_companion_agent_order_lookup_is_scoped(merchant_env):
    missing = _tools()["query_my_orders"].invoke({"order_id": "ORD-20261001-0001"})
    assert missing["ok"] is False
    assert missing["error"]["code"] == "ORDER_NOT_FOUND"
