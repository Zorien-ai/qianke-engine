"""B 端千客用户池：会话 + 交易并集、订单归属、租户隔离。"""
from __future__ import annotations

import pytest

from rag_demo.b_end import user_pool
from rag_demo.c_end import social, store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    social.init()
    return store


def _add_order(order_id, buyer_id, merchant_id, status, amount, created_at):
    conn = store._connect()
    try:
        conn.execute(
            "INSERT INTO c_order(order_id, buyer_id, status, total_amount, created_at, "
            "merchant_id, snapshot_json) VALUES (?, ?, ?, ?, ?, ?, '[]')",
            (order_id, buyer_id, status, amount, created_at, merchant_id),
        )
        conn.commit()
    finally:
        conn.close()


def _add_order_with_item(order_id, buyer_id, product_id, status, amount):
    conn = store._connect()
    try:
        conn.execute(
            "INSERT INTO c_order(order_id, buyer_id, status, total_amount, created_at, "
            "snapshot_json) VALUES (?, ?, ?, ?, ?, '[]')",
            (order_id, buyer_id, status, amount, "2026-11-01T10:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO c_order_item(order_id, product_id, quantity, unit_price) "
            "VALUES (?, ?, 1, ?)",
            (order_id, product_id, amount),
        )
        conn.commit()
    finally:
        conn.close()


def _add_message(owner_id, friend_id):
    conn = store._connect()
    try:
        conn.execute(
            "INSERT INTO c_message(message_id, owner_id, friend_id, sender_id, receiver_id, "
            "content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, '{}', ?)",
            (
                f"msg_{owner_id}_{friend_id}",
                owner_id,
                friend_id,
                owner_id,
                friend_id,
                "想找一双通勤跑鞋",
                "2026-11-10T09:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_pool_unions_orders_and_chats(c_store):
    _add_order("o1", "buyer_a", "m_gear_002", "CONFIRMED", 100.0, "2026-11-01T10:00:00+00:00")
    _add_order("o2", "buyer_a", "m_gear_002", "CANCELLED", 999.0, "2026-11-02T10:00:00+00:00")
    _add_message("buyer_c", "store_demo")
    store.upsert_chat_user_profile(
        "m_gear_002",
        "buyer_d",
        profile={"needs": ["通勤跑鞋"], "preferences": ["轻量"], "confidence": 0.8},
        profile_text="需求：通勤跑鞋；偏好：轻量",
        confidence=0.8,
        source_message_count=4,
    )

    result = user_pool.refresh_merchant_pool(
        "m_gear_002", embedder=lambda text: [0.1] * 8
    )
    assert result["upserted"] == 3

    a = store.get_qianke_user_profile("m_gear_002", "buyer_a")
    assert a is not None
    assert a["has_order"] is True
    assert a["order_count"] == 1
    assert a["order_amount"] == 100.0
    assert a["has_chat"] is False

    c = store.get_qianke_user_profile("m_gear_002", "buyer_c")
    assert c is not None
    assert c["has_chat"] is True
    assert c["has_order"] is False
    assert "会话" in c["profile_text"]

    d = store.get_qianke_user_profile("m_gear_002", "buyer_d")
    assert d is not None
    assert d["has_chat"] is True
    assert d["chat_profile"]["needs"] == ["通勤跑鞋"]
    assert "通勤跑鞋" in d["profile_text"]


def test_order_attributed_by_item_product_when_merchant_missing(c_store):
    _add_order_with_item("o_tea", "buyer_t", "P-TEA-001", "CONFIRMED", 298.0)
    result = user_pool.refresh_merchant_pool(
        "m_tea_001", embedder=lambda text: [0.1] * 8
    )
    assert result["upserted"] == 1
    profile = store.get_qianke_user_profile("m_tea_001", "buyer_t")
    assert profile is not None
    assert profile["order_amount"] == 298.0
    assert profile["top_category"] == "绿茶"
    assert store.get_qianke_user_profile("m_gear_002", "buyer_t") is None


def test_pool_is_merchant_scoped(c_store):
    _add_order("o_gear", "buyer_a", "m_gear_002", "CONFIRMED", 100.0, "2026-11-01T10:00:00+00:00")
    _add_order("o_tea", "buyer_b", "m_tea_001", "CONFIRMED", 200.0, "2026-11-02T10:00:00+00:00")
    user_pool.refresh_merchant_pool("m_gear_002", embedder=lambda text: [0.1] * 8)
    user_pool.refresh_merchant_pool("m_tea_001", embedder=lambda text: [0.1] * 8)

    assert store.get_qianke_user_profile("m_gear_002", "buyer_b") is None
    assert store.get_qianke_user_profile("m_tea_001", "buyer_a") is None
    assert user_pool.pool_summary("m_gear_002")["count"] == 1
    assert user_pool.pool_summary("m_tea_001")["count"] == 1


def test_search_falls_back_to_text_without_embedding(c_store):
    _add_message("buyer_c", "store_demo")
    user_pool.refresh_merchant_pool("m_gear_002", embedder=lambda text: None)
    rows = store.search_qianke_user_profiles("m_gear_002", "buyer_c", None, limit=5)
    assert [row["buyer_id"] for row in rows] == ["buyer_c"]
