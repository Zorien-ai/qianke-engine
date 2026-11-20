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


def test_load_memory_adds_identity_and_freshness_metadata(monkeypatch):
    monkeypatch.setattr(
        chat_memory.chat_history,
        "get_context_state",
        lambda tenant, account, session: {
            "summary": "用户在问上海高价值用户",
            "entities": {"城市": "上海"},
            "updated_at": "2026-11-20T10:00:00+08:00",
        },
    )
    memory = chat_memory.load_memory("tenant_demo", 7, "session_1")
    assert memory["tenant_id"] == "tenant_demo"
    assert memory["customer_id"] == "account:7"
    assert memory["source"] == "chat_sessions.context_state"
    assert memory["updated_at"] == "2026-11-20T10:00:00+08:00"


def test_system_prompt_injects_source_freshness_and_confidence():
    memory = {
        "summary": "用户在问上海高价值用户",
        "entities": {"城市": "上海"},
        "tenant_id": "tenant_demo",
        "customer_id": "account:7",
        "source": "chat_sessions.context_state",
        "updated_at": "2026-11-20T10:00:00+08:00",
    }
    text = chat_memory.system_prompt(memory, _history(2))
    assert "会话记忆" in text
    assert "来源=chat_sessions.context_state" in text
    assert "更新=2026-11-20T10:00:00" in text
    assert "置信度=未校准" in text
    assert "城市=上海" in text


def test_system_prompt_keeps_legacy_shape_without_identity():
    memory = {"summary": "摘要", "entities": {"城市": "上海"}}
    text = chat_memory.system_prompt(memory, _history(2))
    assert "历史对话摘要：摘要" in text
    assert "已锁定的业务条件：城市=上海" in text
    assert "来源=" not in text
