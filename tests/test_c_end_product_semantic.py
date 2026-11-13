# -*- coding: utf-8 -*-
"""C 端商品语义召回：茶叶/绿茶等宽泛表达也能命中在售商品。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import agent as c_agent
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


def _products(result):
    assert result["ok"] is True
    return result.get("products") or []


def test_tea_store_semantic_catalog_matches_tea_terms(merchant_env):
    tools = {item.name: item for item in store_agent._tools("buyer_1", merchant_id="m_tea_001")}
    for need in ("茶叶", "茶", "绿茶", "你家都有什么东西啊"):
        products = _products(tools["search_catalog"].invoke({"need": need}))
        assert products, need
        assert any(product["category"] in {"绿茶", "红茶", "白茶", "黑茶", "乌龙茶", "花茶", "普洱茶"} for product in products)


def test_companion_cross_merchant_fallback_for_tea(merchant_env):
    # CApp 小伴的旧默认商家是户外店；泛化“茶叶”应能兜底到真实茶叶商品。
    tools = {item.name: item for item in c_agent._tools("buyer_1")}
    products = _products(tools["recommend_products"].invoke({"need": "茶叶"}))
    assert products
    browse = _products(tools["recommend_products"].invoke({"need": "你家都有什么东西啊"}))
    assert browse
    assert any("龙井" in product["title"] or product["category"] == "绿茶" for product in products)
    assert any(product.get("merchant_id") == "m_tea_001" for product in products)
    assert all(product.get("image_url") or product.get("images") for product in products)


def test_merchant_chat_can_implicitly_wake_store_pet_but_group_still_requires_at():
    assert store_agent.intent_gate("你家有什么东西")[0] is False
    assert store_agent.intent_gate("你家有什么东西", implicit_wake=True)[:2] == (True, True)
    assert store_agent.intent_gate("@店宠 推荐茶叶")[:2] == (True, True)


def test_image_request_routes_to_advisor():
    assert c_agent.detect_mode("我要看看") == c_agent.MODE_ADVISOR
    assert c_agent._is_image_request("我要看看")
    assert not c_agent._is_image_request("今天有点累")
