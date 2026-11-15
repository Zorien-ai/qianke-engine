"""画像三层模型：冷启动 / 消费 / 会话的确定性映射测试。"""
from __future__ import annotations

from rag_demo.b_end import insights, user_pool


def test_build_profile_text_contains_three_layers():
    record = {
        "buyer_id": "buyer_193",
        "order_count": 2,
        "order_amount": 396.0,
        "avg_order_amount": 198.0,
        "last_order_at": "2026-11-15T12:00:00+00:00",
        "top_category": "绿茶",
        "has_order": True,
        "has_chat": True,
        "attributes": {
            "gender": "男",
            "age_range": "18-24",
            "city": "杭州",
            "member_level": "银卡",
        },
        "chat_profile_text": "需求：了解发货时间",
    }
    text = user_pool.build_profile_text(record)
    assert "冷启动属性" in text
    assert "性别 男" in text
    assert "年龄段 18-24" in text
    assert "在本商户有 2 笔有效订单" in text
    assert "会话画像" in text


def test_qianke_card_exposes_three_layers():
    row = {
        "buyer_id": "buyer_193",
        "order_count": 2,
        "order_amount": 396.0,
        "avg_order_amount": 198.0,
        "last_order_at": "2026-11-15T12:00:00+00:00",
        "top_category": "绿茶",
        "has_order": True,
        "has_chat": True,
        "profile": {
            "attributes": {
                "gender": "男",
                "age_range": "18-24",
                "city": "杭州",
                "member_level": "银卡",
                "registered_at": "2026-11-15 20:11:37",
                "source": "simulation_seed",
            },
            "chat": {"recent_messages": ["想了解发货时间", "支持 7 天无理由退货"]},
        },
        "chat_profile": {"needs": ["了解发货时间"]},
        "confidence": 0.6,
    }
    card = insights._card_from_qianke(row)
    assert card["has_base"] is True
    assert card["fields"]["gender"] == "男"
    assert card["fields"]["age"] == "18-24"
    assert card["stats"]["order_count"] == 2
    assert card["chat"]["needs"] == ["了解发货时间"]
    assert card["chat"]["recent_messages"] == ["想了解发货时间", "支持 7 天无理由退货"]
