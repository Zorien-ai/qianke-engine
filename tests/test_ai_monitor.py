# -*- coding: utf-8 -*-
"""AI 监控与 Token 计费的纯逻辑边界。"""
from rag_demo import ai_monitor


def test_range_delta_supported_values():
    assert ai_monitor._range_delta("1h").total_seconds() == 3600
    assert ai_monitor._range_delta("24h").total_seconds() == 86400
    assert ai_monitor._range_delta("7d").total_seconds() == 7 * 86400


def test_range_delta_falls_back_to_24h():
    assert ai_monitor._range_delta("unexpected").total_seconds() == 86400


def test_trial_wallet_and_packs_are_positive():
    assert ai_monitor.TRIAL_TOKENS > 0
    assert any(pack[2] > 0 and pack[3] > 0 for pack in ai_monitor.SEED_PACKS)


def test_seed_prices_are_internal_cost_only():
    # 销售价留空，后续由管理端配置；seed 只承担内部成本口径。
    assert all(cost_in >= 0 and cost_out >= 0 for _, cost_in, cost_out in ai_monitor.SEED_PRICES)
