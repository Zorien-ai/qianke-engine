"""双宠谈判 v1：受控预算/平台满减/报价落库。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import negotiation, store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def test_negotiation_accepts_budget_with_platform_discount(c_store):
    result = negotiation.run_negotiation("buyer_1", need="跑鞋", budget=300, quantity=1)
    assert result["status"] == "ACCEPTED"
    assert result["total_amount"] == 269.0
    assert result["discount_amount"] == 30.0
    assert result["quote"]["quote_id"].startswith("quote_neg_")
    assert result["quote"]["product_refs"][0]["product_id"] == "P001"
    actors = [item["actor"] for item in result["transcript"]]
    assert actors[0] == "c_pet" and "b_pet" in actors and actors[-1] == "b_pet"

    draft = c_store.prepare_order("buyer_1", [], quote_id=result["quote"]["quote_id"])
    assert draft["total_amount"] == 269.0
    assert draft["items"][0]["product_id"] == "P001"


def test_negotiation_falls_back_to_cheaper_product(c_store):
    result = negotiation.run_negotiation("buyer_1", need="跑鞋", budget=200)
    assert result["status"] == "ACCEPTED"
    assert result["quote"]["product_refs"][0]["product_id"] == "P005"
    assert result["total_amount"] == 129.0
    assert result["discount_amount"] == 0.0
    assert any("超过预算" in item["text"] for item in result["transcript"])


def test_negotiation_rejects_when_budget_too_low(c_store):
    result = negotiation.run_negotiation("buyer_1", need="跑鞋", budget=50)
    assert result["status"] == "REJECTED"
    assert result["reason"] == "BUDGET_TOO_LOW"
    assert result["quote"] is None
    assert all(item["actor"] in {"c_pet", "b_pet"} for item in result["transcript"])


def test_negotiation_validates_input(c_store):
    with pytest.raises(negotiation.NegotiationError) as exc:
        negotiation.run_negotiation("buyer_1", need="", budget=100)
    assert exc.value.code == "NEGOTIATION_INVALID"
    with pytest.raises(negotiation.NegotiationError):
        negotiation.run_negotiation("buyer_1", need="跑鞋", budget=0)


def test_tea_negotiation_uses_tea_merchant(c_store):
    c_store.bind_store_friend("m_tea_001", "store_tea")
    result = negotiation.run_negotiation(
        "buyer_1",
        need="龙井",
        budget=400,
        quantity=1,
        friend_id="store_tea",
    )
    assert result["status"] == "ACCEPTED"
    assert result["quote"]["merchant_id"] == "m_tea_001"
    assert result["quote"]["merchant_name"] == "山雾茶业"
    assert result["quote"]["product_refs"][0]["product_id"].startswith("P-TEA-")
    assert any("山雾茶业店宠" == item["name"] for item in result["transcript"])
    draft = c_store.prepare_order("buyer_1", [], quote_id=result["quote"]["quote_id"])
    assert draft["merchant_id"] == "m_tea_001"


def test_negotiation_with_sku_quote_uses_sku_price_and_quantity(c_store):
    c_store.bind_store_friend("m_tea_001", "store_tea")
    result = negotiation.run_negotiation(
        "buyer_1",
        need="明前龙井",
        budget=200,
        quantity=2,
        friend_id="store_tea",
        sku="SKU-TEA-001-50G",
    )
    assert result["status"] == "ACCEPTED"
    ref = result["quote"]["product_refs"][0]
    assert ref["sku"] == "SKU-TEA-001-50G"
    assert ref["spec"] == "50g 罐装"
    assert ref["unit_price"] == 68.0
    assert ref["quantity"] == 2
    assert result["total_amount"] == 136.0

    draft = c_store.prepare_order("buyer_1", [], quote_id=result["quote"]["quote_id"])
    assert draft["total_amount"] == 136.0
    assert draft["items"][0]["unit_price"] == 68.0
    assert draft["items"][0]["sku"] == "SKU-TEA-001-50G"

    order = c_store.confirm_order(
        "buyer_1",
        draft["order_id"],
        draft["confirmation_token"],
        request_id="req_quote_sku_confirm_001",
    )
    assert order["status"] == "CONFIRMED"
    assert order["total_amount"] == 136.0
    assert order["merchant_order_id"] == order["order_id"]


def test_negotiation_rejects_insufficient_sku_stock(c_store):
    c_store.bind_store_friend("m_tea_001", "store_tea")
    result = negotiation.run_negotiation(
        "buyer_1",
        need="福鼎白牡丹",
        budget=1000,
        quantity=20,
        friend_id="store_tea",
        sku="SKU-TEA-004-300G",
    )
    assert result["status"] == "REJECTED"
    assert result["reason"] == "INSUFFICIENT_STOCK"
    assert result["quote"] is None
    assert any("只剩 18 件" in item["text"] for item in result["transcript"])
