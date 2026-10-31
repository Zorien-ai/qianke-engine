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
