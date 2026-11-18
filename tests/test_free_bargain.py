"""C 端自由砍价：底价、自动审批、商家审批、报价折扣。"""
from __future__ import annotations

from pathlib import Path

import pytest

from rag_demo.c_end import free_bargain, store


@pytest.fixture()
def bargain_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_CEND_BACKEND", "sqlite")
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setenv("QIANKE_BARGAIN_DIALOGUE_MODE", "template")
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    store.create_tenant("m_sim_tea", "山岚茶事")
    store.bind_store_friend("m_sim_tea", "sim_store_tea")
    monkeypatch.setattr(
        free_bargain,
        "_merchant_sku",
        lambda merchant_id, sku: {
            "product_id": "SIM-TEA-01",
            "title": "明前龙井",
            "category": "绿茶",
            "sku": sku,
            "spec": "100g/罐",
            "price": 198.0,
            "stock": 10,
            "source": "test",
        },
    )
    return store


def test_default_policy_and_auto_quote(bargain_store, monkeypatch):
    policy = store.get_bargain_policy("m_sim_tea")
    assert policy["floor_ratio"] == 0.85
    assert policy["auto_approve_discount_ratio"] == 0.05

    session = free_bargain.create_bargain(
        "buyer_193",
        friend_id="sim_store_tea",
        sku="SIM-TEA-01-S1",
        target_price=190,
    )
    assert session["status"] == "NEGOTIATING"
    assert session["current_offer"]["approval_required"] is False
    accepted = free_bargain.accept_offer(
        "buyer_193", session["bargain_id"], session["current_offer"]["offer_id"]
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["quote"]["quote_id"].startswith("quote_bargain_")
    assert accepted["quote"]["total_amount"] == 190.0
    assert accepted["current_offer"]["merchant_discount"] == 8.0


def test_approval_flow_creates_quote_only_after_merchant(bargain_store):
    session = free_bargain.create_bargain(
        "buyer_193",
        friend_id="sim_store_tea",
        sku="SIM-TEA-01-S1",
        target_price=180,
    )
    waiting = free_bargain.accept_offer(
        "buyer_193", session["bargain_id"], session["current_offer"]["offer_id"]
    )
    assert waiting["status"] == "WAITING_APPROVAL"
    assert waiting["quote"] is None
    approvals = store.list_bargain_approvals("m_sim_tea", status="PENDING")
    assert len(approvals) == 1
    approval = approvals[0]
    result = free_bargain.decide_approval(
        approval["approval_id"], approved=True, decided_by="owner", note="演示"
    )
    assert result["status"] == "ACCEPTED"
    assert result["quote"]["total_amount"] == 180.0
    assert result["approval"]["status"] == "APPROVED"


def test_merchant_can_reject_approval(bargain_store):
    session = free_bargain.create_bargain(
        "buyer_193",
        friend_id="sim_store_tea",
        sku="SIM-TEA-01-S1",
        target_price=180,
    )
    waiting = free_bargain.accept_offer(
        "buyer_193", session["bargain_id"], session["current_offer"]["offer_id"]
    )
    approval = waiting["approval"]
    result = free_bargain.decide_approval(
        approval["approval_id"], approved=False, decided_by="owner", note="低于活动线"
    )
    assert result["status"] == "REJECTED"
    assert result["quote"] is None


def test_below_floor_counters_to_floor(bargain_store):
    session = free_bargain.create_bargain(
        "buyer_193",
        friend_id="sim_store_tea",
        sku="SIM-TEA-01-S1",
        target_price=100,
    )
    offer = session["current_offer"]
    # 最大商家让利 10% 先于 85% 硬底价生效，当前有效最低价为 178.20。
    assert offer["payable"] == 178.2
    assert offer["approval_required"] is True


def test_quote_discount_applies_merchant_bargain(bargain_store):
    assert store._quote_discount(
        198.0,
        ["merchant_bargain"],
        [{"kind": "merchant_bargain", "discount_amount": 18.0}],
    ) == 18.0
    assert store._quote_discount(
        328.0,
        ["platform_full_reduce", "merchant_bargain"],
        [{"kind": "merchant_bargain", "discount_amount": 18.0}],
    ) == 48.0


def test_cross_buyer_cannot_access_bargain(bargain_store):
    session = free_bargain.create_bargain(
        "buyer_193",
        friend_id="sim_store_tea",
        sku="SIM-TEA-01-S1",
    )
    with pytest.raises(store.CStoreError) as exc:
        store.get_bargain_session(session["bargain_id"], buyer_id="buyer_999")
    assert exc.value.code == "BARGAIN_FORBIDDEN"


def test_price_change_blocks_stale_quote(bargain_store, monkeypatch):
    session = free_bargain.create_bargain(
        "buyer_193",
        friend_id="sim_store_tea",
        sku="SIM-TEA-01-S1",
        target_price=190,
    )
    monkeypatch.setattr(
        free_bargain,
        "_merchant_sku",
        lambda merchant_id, sku: {
            "product_id": "SIM-TEA-01",
            "title": "明前龙井",
            "category": "绿茶",
            "sku": sku,
            "spec": "100g/罐",
            "price": 199.0,
            "stock": 10,
            "source": "test",
        },
    )
    with pytest.raises(free_bargain.BargainError) as exc:
        free_bargain.accept_offer(
            "buyer_193", session["bargain_id"], session["current_offer"]["offer_id"]
        )
    assert exc.value.code == "BARGAIN_STALE"
