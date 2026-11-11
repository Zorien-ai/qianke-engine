"""店宠 Agent 接真实商家数据层的工具测试。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

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


def test_second_merchant_catalog_is_isolated(merchant_env):
    tea = store_agent._tools("buyer_1", merchant_id="m_tea_001")
    tools = {item.name: item for item in tea}
    result = tools["search_catalog"].invoke({"need": "龙井"})
    assert result["ok"] is True
    assert result["source"] == "merchant_v1"
    assert any(item["product_id"] == "P-TEA-001" for item in result["products"])
    assert all(not item["product_id"].startswith("P-") or item["product_id"].startswith("P-TEA-") for item in result["products"])


def test_friend_mapping_routes_reply_to_tea_merchant(merchant_env):
    store.bind_store_friend("m_tea_001", "store_tea")
    assert store_agent.resolve_merchant_id(friend_id="store_tea") == "m_tea_001"

    class _FakeLLM:
        def __init__(self):
            self.responses = [
                AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "search_catalog",
                        "args": {"need": "龙井"},
                        "id": "call_tea_1",
                        "type": "tool_call",
                    }],
                ),
                AIMessage(content="推荐明前龙井"),
            ]
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            return self.responses.pop(0)

    fake = _FakeLLM()
    result = store_agent.reply_with_meta(
        "buyer_1",
        "@店宠 推荐一款龙井",
        llm=fake,
        friend_id="store_tea",
    )
    assert result.awakened is True
    assert result.text == "推荐明前龙井"
    assert any(item["product_id"] == "P-TEA-001" for item in result.metadata.get("product_refs", []))
    assert fake.calls == 2


def test_merchant_sop_is_scoped_per_merchant(merchant_env):
    gear = {item["topic"]: item["content"] for item in store.list_merchant_sops("m_gear_002")}
    tea = {item["topic"]: item["content"] for item in store.list_merchant_sops("m_tea_001")}
    assert "偏远地区" in gear["shipping"]
    assert "防震包装" in tea["shipping"]
    assert gear["return"] != tea["return"]

    tea_tools = {item.name: item for item in store_agent._tools("buyer_1", "m_tea_001")}
    result = tea_tools["search_store_policy"].invoke({"topic": "发货"})
    assert result["ok"] is True
    assert any("防震包装" in item["content"] for item in result["policies"])
    assert all("偏远地区" not in item["content"] for item in result["policies"])
