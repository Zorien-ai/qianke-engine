# -*- coding: utf-8 -*-
"""意图路由业务词兜底测试（不加载 BERT 模型）。"""
from rag_demo.tools.router import decide, has_business_signal, rule_is_chitchat


def test_business_slang_question_is_not_chitchat():
    # 实测 BERT 曾把「很能花钱的女生都有谁」判成闲聊；业务词必须强制 rag，且不调模型
    hit, prob, via = decide("很能花钱的女生都有谁")
    assert hit is False
    assert prob is None
    assert via == "business_guard"


def test_business_words_in_question_force_rag():
    for question in [
        "哪些用户最近下单了",
        "深圳的女性会员画像",
        "帮我看看高客单用户",
        "退回流程怎么走",
    ]:
        assert has_business_signal(question) is True
        assert decide(question)[2] == "business_guard"


def test_chitchat_questions_without_business_words_still_blocked():
    # 无业务词时仍走原规则：寒暄短句命中，真闲聊应继续被拦
    assert has_business_signal("你好") is False
    assert rule_is_chitchat("你好") is True
    assert has_business_signal("今天天气怎么样") is False
    assert rule_is_chitchat("今天天气怎么样") is True
    assert has_business_signal("帮我写首诗") is False


def test_empty_question_is_rag():
    assert decide("") == (False, None, "rule")
    assert has_business_signal("") is False
