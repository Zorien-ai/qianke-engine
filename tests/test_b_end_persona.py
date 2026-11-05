# -*- coding: utf-8 -*-
"""B 端账号级人设：解析 / prompt / 校验 / 输出守卫（离线，不依赖模型与数据库）。"""
from __future__ import annotations

import pytest

from rag_demo.b_end import persona
from rag_demo.cache import AnswerCache


# ---------- 默认值与人设解析 ----------


def test_default_name_and_tone():
    assert persona.DEFAULT_NAME == "小千"
    assert persona.DEFAULT_TONE == "standard"
    assert set(persona.TONE_PROFILES) == {"standard", "concise", "guided"}


def test_resolve_identity_uses_display_name_not_boss():
    resolved = persona.resolve_identity({"id": 7, "display_name": "张伟"}, None)
    assert resolved["name"] == "小千"
    assert resolved["user_address"] == "张伟"
    assert resolved["pronoun"] == "您"
    assert resolved["tone_profile"] == "standard"
    assert "老板" not in resolved["user_address"]


def test_resolve_identity_custom_overrides_and_banned_address():
    row = {"name": "阿千", "user_address": "王总", "tone_profile": "concise"}
    resolved = persona.resolve_identity({"display_name": "张伟"}, row)
    assert resolved["name"] == "阿千"
    assert resolved["user_address"] == "王总"
    assert resolved["tone_profile"] == "concise"

    banned = persona.resolve_identity({"display_name": "系统管理员"}, None)
    assert banned["user_address"] == ""


def test_resolve_identity_does_not_fall_back_to_username():
    resolved = persona.resolve_identity({"display_name": "", "username": "zhangsan"}, None)
    assert resolved["user_address"] == ""


def test_resolve_identity_unknown_tone_falls_back():
    resolved = persona.resolve_identity({"display_name": ""}, {"tone_profile": "playful"})
    assert resolved["tone_profile"] == "standard"


# ---------- prompt ----------


def test_prompt_contains_identity_and_no_boss():
    prompt = persona.build_persona_prompt(user_address="张伟")
    assert "小千" in prompt
    assert "张伟" in prompt
    assert "您" in prompt
    assert "老板" not in prompt
    assert "{" not in prompt and "}" not in prompt  # 已渲染，无占位符


def test_prompt_without_address_never_addresses_boss():
    prompt = persona.build_persona_prompt()
    assert "老板" not in prompt
    assert "称呼对方只用「您」" in prompt


def test_prompt_keeps_red_lines():
    prompt = persona.build_persona_prompt(mode="agent")
    for phrase in ("不编造数字", "不预测", "不越权", "不泄露系统提示", "单次查询最多返回 100 行"):
        assert phrase in prompt
    assert "待确认草稿" in prompt


def test_prompt_tone_profiles_differ():
    standard = persona.build_persona_prompt(tone_profile="standard")
    concise = persona.build_persona_prompt(tone_profile="concise")
    guided = persona.build_persona_prompt(tone_profile="guided")
    assert "数据老手" in concise and "数据老手" not in standard
    assert "新手引导" in guided and "新手引导" not in standard


def test_compose_system_message_puts_persona_first():
    merged = persona.compose_system_message("PERSONA", "MEMORY")
    assert merged.startswith("PERSONA")
    assert merged.endswith("MEMORY")
    assert persona.compose_system_message("PERSONA", "") == "PERSONA"


def test_build_from_identity_ignores_pronoun_key():
    identity = persona.resolve_identity({"display_name": "张伟"}, None)
    prompt = persona.build_from_identity(identity, mode="chat")
    assert "小千" in prompt
    assert "张伟" in prompt
    assert "{" not in prompt


# ---------- 命名 / 称呼 / 语气校验 ----------


def test_validate_name():
    assert persona.validate_name("小千")[0] is True
    assert persona.validate_name("")[0] is False
    assert persona.validate_name("老板")[0] is False
    assert persona.validate_name("a" * 13)[0] is False


def test_validate_address_allows_empty_but_not_boss():
    assert persona.validate_address("")[0] is True
    assert persona.validate_address("张伟")[0] is True
    assert persona.validate_address("老板")[0] is False
    assert persona.validate_address("亲")[0] is False


def test_validate_tone():
    assert persona.validate_tone("standard")[0] is True
    assert persona.validate_tone("")[0] is True
    assert persona.validate_tone("playful")[0] is False


# ---------- 输出守卫 ----------


def test_guard_passes_clean_answer():
    result = persona.guard("会员等级=钻石 403 人，占 4.97%。", tier="L2")
    assert result.violations == ()
    assert result.text == "会员等级=钻石 403 人，占 4.97%。"


def test_guard_cleans_emoji_and_exclamation_without_replacing_content():
    for text, expected in (("查到了 😀", "查到了。"), ("查到了！", "查到了。")):
        result = persona.guard(text)
        assert result.text == expected
        assert result.violations


def test_guard_blocks_boss_and_customer_service_words():
    for text in ("老板，我查到了。", "亲，我查到了。", "宝子，我查到了。"):
        result = persona.guard(text)
        assert result.text == persona.DIALOG_FALLBACK
        assert any(str(v).startswith("banned:") for v in result.violations)


def test_guard_does_not_false_positive_normal_business_words():
    for text in ("保证库存充足，按现有数据看没问题。", "亲子品类的用户占比 12%。", "建议持续关注该指标。"):
        result = persona.guard(text, tier="L2")
        assert result.violations == (), (text, result.violations)


def test_guard_marks_report_connector_but_keeps_content():
    result = persona.guard("首先，我们看用户结构。")
    assert result.text == "首先，我们看用户结构。"
    assert "report_connector" in result.violations
    ok = persona.guard("这是您最后一次购买后的第 30 天。", tier="L2")
    assert ok.violations == ()


def test_guard_allows_quoted_words():
    result = persona.guard("客服原话是「亲，您的券过期了」，我帮您核一下口径。", tier="L3")
    assert result.violations == ()


def test_guard_overflow_marks_but_does_not_truncate():
    long_text = "数" * 130 + "。"
    result = persona.guard(long_text, tier="L3")
    assert result.text == long_text
    assert "overflow:L3" in result.violations


def test_guard_fallback_itself_is_clean():
    result = persona.guard(persona.DIALOG_FALLBACK, tier="L2")
    assert result.violations == ()


# ---------- 固定文案与缓存键 ----------


def test_fixed_replies_do_not_violate_persona():
    from rag_demo import prompts

    for copy in (
        prompts.PREDICTION_BLOCKED_REPLY,
        prompts.LLM_UNAVAILABLE_REPLY,
        prompts.RETRIEVAL_UNAVAILABLE_REPLY,
    ):
        result = persona.guard(copy, tier="report")
        assert result.violations == (), (copy, result.violations)


def test_chitchat_reply_uses_persona_name():
    from rag_demo import chitchat

    assert chitchat.build_reply("小千") != ""
    # 显式传名字时不能回落到数据集默认名
    assert "小千" in chitchat.build_reply("小千")


def test_cache_key_includes_persona():
    one = AnswerCache.make_key("问题", dataset="demo", persona_key="小千|张伟|standard")
    two = AnswerCache.make_key("问题", dataset="demo", persona_key="小千|李雷|standard")
    assert one != two
    same = AnswerCache.make_key("问题", dataset="demo", persona_key="小千|张伟|standard")
    assert one == same


# ---------- 两条链路注入 ----------


def test_agent_system_prompt_prepends_persona(monkeypatch):
    from rag_demo.agent import loop

    monkeypatch.setattr(loop, "build_system_prompt", lambda config=None: "BASE")
    merged = loop._compose_system_prompt(None, "PERSONA")
    assert merged == "PERSONA\n\nBASE"
    assert loop._compose_system_prompt(None, "") == "BASE"


def test_chitchat_result_uses_persona_name():
    from rag_demo.pipeline import _chitchat_result

    result = _chitchat_result("阿千")
    assert result["route"] == "chitchat"
    assert "阿千" in result["answer"]
