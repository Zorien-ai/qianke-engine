"""C 端问题 Router：四类路由、槽位和显式模式。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import router


@pytest.mark.parametrize(
    ("message", "route", "mode"),
    [
        ("今天有点累，陪我聊聊", "companion", "companion"),
        ("我叫小明，喜欢跑步", "companion", "companion"),
        ("推荐一款绿茶", "shopping", "advisor"),
        ("500 以内推荐一双跑鞋", "shopping", "advisor"),
        ("这个多少钱", "shopping", "advisor"),
        ("我要看看图片", "shopping", "advisor"),
        ("我要看看", "shopping", "advisor"),
        ("我的订单到哪了", "order", "order"),
        ("查一下物流，order_123", "order", "order"),
        ("我想买一双跑鞋", "transaction", "transaction"),
        ("确认订单", "transaction", "transaction"),
        ("帮我取消草稿", "transaction", "transaction"),
        ("退款进度怎么样", "order", "order"),
        ("我喜欢跑步，我的预算 500 元，别给我推荐跑鞋", "companion", "companion"),
    ],
)
def test_route_question_four_routes(message, route, mode):
    decision = router.route_question(message)
    assert decision.route == route
    assert decision.mode == mode
    assert 0 <= decision.confidence <= 1


def test_router_extracts_budget_and_order_id():
    decision = router.route_question("预算500，查一下 order_abc123 的物流")
    assert decision.slots["budget"] == 500
    assert decision.slots["order_id"] == "order_abc123"
    assert decision.route == "order"


def test_router_explicit_mode_wins():
    decision = router.route_question("今天有点累", requested_mode="advisor")
    assert decision.route == "shopping"
    assert decision.mode == "advisor"
    assert decision.source == "explicit"
