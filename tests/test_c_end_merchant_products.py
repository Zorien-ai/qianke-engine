# -*- coding: utf-8 -*-
"""C 端商家商品接口：SKU 规格/价格/库存 payload。"""
from __future__ import annotations

import pytest

from rag_demo.api import c_end
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


def test_merchant_products_expose_all_skus(merchant_env, monkeypatch):
    monkeypatch.setattr(c_end, "_buyer", lambda: ("buyer_1", None))
    monkeypatch.setattr(c_end.store_agent, "resolve_merchant_id", lambda friend_id=None: "m_tea_001")
    data = c_end.merchant_products(friend_id="store_tea", limit=12)
    products = {item["product_id"]: item for item in data["products"]}
    product = products["P-TEA-001"]
    assert product["skus"]
    assert len(product["skus"]) >= 2
    assert all({"sku", "spec", "price", "stock", "in_stock"} <= set(sku) for sku in product["skus"])
    assert product["sku"] == product["skus"][0]["sku"]
    assert product["price"] == product["skus"][0]["price"]
    assert product["stock"] == product["skus"][0]["stock"]
