# -*- coding: utf-8 -*-
"""混合记忆的纯逻辑边界（不调 LLM / 不连库）。"""
from rag_demo import chat_memory


def _history(n):
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(n)
    ]


def test_short_term_keeps_last_12_messages():
    assert len(chat_memory.short_term(_history(30))) == 12
    assert chat_memory.short_term(_history(30))[0]["content"] == "m18"
    assert len(chat_memory.short_term(_history(3))) == 3


def test_system_prompt_contains_summary_entities_and_recent():
    memory = {"summary": "用户在问上海高价值用户", "entities": {"城市": "上海", "会员等级": "黄金"}}
    text = chat_memory.system_prompt(memory, _history(14))
    assert "上海高价值用户" in text
    assert "城市=上海" in text
    assert "会员等级=黄金" in text
    assert "m12" in text and "m13" in text
    assert "m0" not in text


def test_memory_entities_are_cleaned():
    cleaned = chat_memory._clean_entities({"城市": " 上海 ", "空": "", "summary": "不应进实体"})
    assert cleaned == {"城市": "上海"}


def test_rewrite_context_includes_entities():
    text = chat_memory.rewrite_prompt_context(
        {"summary": "摘要", "entities": {"城市": "上海"}}, _history(2)
    )
    assert "摘要" in text
    assert "城市=上海" in text
