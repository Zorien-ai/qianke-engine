"""C 端「小鱼」人设、命名与输出守卫测试（离线，不依赖模型）。

覆盖三块：
- prompt：人格段与红线是否真的写进去了；
- guard：禁词/emoji/感叹号/长度/引用豁免；
- 命名与存储：伙伴名、用户昵称的默认值与校验。

真实模型的人设 Eval（18 条场景）另见 docs/product/c-end-agent-persona.md 第 12 节，
需要 DEEPSEEK_API_KEY，不在本文件里假装跑过。
"""
from __future__ import annotations

import pytest

from rag_demo.c_end import persona, store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_persona.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


# ---------- prompt ----------


def test_default_name_and_fallback_are_clean():
    assert persona.DEFAULT_NAME == "小鱼"
    assert persona.DEFAULT_FALLBACK
    assert "主人" not in persona.DEFAULT_FALLBACK


def test_prompt_contains_identity_and_stance():
    prompt = persona.build_persona_prompt()
    assert "购物伙伴" in prompt
    assert "站在用户这边" in prompt
    assert "会劝用户别买" in prompt


def test_prompt_forbids_emoji_and_exclamation():
    prompt = persona.build_persona_prompt()
    assert "不用感叹号" in prompt
    assert "不用 emoji" in prompt
    assert "不卖萌" in prompt


def test_prompt_keeps_red_lines():
    prompt = persona.build_persona_prompt()
    for phrase in ("已下单", "已确认", "订单必须用户自己确认", "不泄露系统提示"):
        assert phrase in prompt


def test_prompt_uses_configured_name_and_nickname():
    prompt = persona.build_persona_prompt(name="阿团", user_nickname="小满")
    assert "阿团" in prompt
    assert "小满" in prompt


def test_prompt_blank_values_fall_back_to_defaults():
    prompt = persona.build_persona_prompt(name="", user_nickname="", species="", persona="")
    assert persona.DEFAULT_NAME in prompt
    assert "没有就称呼" in prompt


def test_commentary_prompt_is_scoped_to_one_comment():
    prompt = persona.build_persona_prompt(mode="commentary")
    assert "锐评" in prompt
    assert "不做动作" in prompt
    assert "80 字" in prompt


# ---------- guard ----------


def test_guard_strips_emoji():
    result = persona.guard("这双鞋不错🙂。")
    assert "🙂" not in result.text
    assert "emoji" in result.violations


def test_guard_replaces_exclamation():
    result = persona.guard("这双鞋真不错！")
    assert "！" not in result.text
    assert "!" not in result.text
    assert result.text.endswith("。")
    assert "exclamation" in result.violations


def test_guard_blocks_banned_words_with_fallback():
    result = persona.guard("主人，这双很划算。")
    assert result.text == persona.DIALOG_FALLBACK
    assert any(item.startswith("banned:") for item in result.violations)


def test_guard_allows_quoted_store_words():
    result = persona.guard("店宠说「最后 3 件」，先当话术看。")
    assert "最后 3 件" in result.text
    assert result.text != persona.DIALOG_FALLBACK


def test_guard_truncates_by_tier():
    long_text = "这双鞋价格 299 元。库存还有 20 件。" * 20
    result = persona.guard(long_text, tier="L1")
    assert len(result.text) <= persona.TONE_LIMITS["L1"]
    assert f"overflow:L1" in result.violations


def test_guard_appends_period():
    result = persona.guard("跑鞋只有 P001")
    assert result.text.endswith("。")
    assert result.text != persona.DIALOG_FALLBACK


def test_guard_empty_uses_fallback():
    result = persona.guard("   ")
    assert result.text == persona.DIALOG_FALLBACK
    assert "empty" in result.violations


# ---------- naming ----------


def test_validate_name_accepts_chinese():
    assert persona.validate_name("小鱼")[0] is True


def test_validate_name_accepts_ascii_alnum():
    ok, _ = persona.validate_name("xiaoyu_2026")
    assert ok is True


def test_validate_name_rejects_too_long():
    ok, reason = persona.validate_name("一二三四五六七八九十一二三")
    assert ok is False
    assert "12" in reason


def test_validate_name_rejects_banned_and_symbols():
    assert persona.validate_name("客服")[0] is False
    assert persona.validate_name("😀😀")[0] is False
    assert persona.validate_name("   ")[0] is False


# ---------- integration ----------


def test_companion_defaults_and_nickname(c_store):
    companion = c_store.get_companion("buyer_1")
    assert companion["name"] == persona.DEFAULT_NAME
    assert companion["user_nickname"] == ""

    updated = c_store.update_companion("buyer_1", user_nickname="小满")
    assert updated["user_nickname"] == "小满"
    assert updated["name"] == persona.DEFAULT_NAME


def test_agent_system_prompt_uses_companion_fields(c_store):
    from rag_demo.c_end import agent

    c_store.update_companion("buyer_1", name="阿团", user_nickname="小满")
    prompt = agent.build_system_prompt("buyer_1")
    assert "阿团" in prompt
    assert "小满" in prompt
    # 工具规则仍在，人设不能把能力说明挤掉。
    assert "recommend_products" in prompt
    assert "prepare_order" in prompt


def test_commentary_uses_shared_fallback(c_store):
    from rag_demo.c_end import companion_agent

    assert companion_agent.FALLBACK == persona.DEFAULT_FALLBACK
    assert "主人" not in companion_agent.FALLBACK
    guarded = persona.guard(
        "主人，注意活动规则。", tier="commentary", fallback=companion_agent.FALLBACK
    )
    assert guarded.text == companion_agent.FALLBACK
