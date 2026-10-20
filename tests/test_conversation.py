# -*- coding: utf-8 -*-
"""多轮追问改写的纯逻辑边界。"""
from rag_demo import conversation


def test_should_rewrite_followup_with_pronoun():
    history = [{"role": "user", "content": "高价值用户怎么定义的"}]
    assert conversation.should_rewrite("那女性呢", history) is True


def test_should_not_rewrite_without_history():
    assert conversation.should_rewrite("那女性呢", []) is False


def test_should_not_rewrite_greeting():
    history = [{"role": "user", "content": "你好"}]
    assert conversation.should_rewrite("谢谢", history) is False


def test_parse_json_handles_markdown_fence():
    data = conversation._parse_json('```json\n{"standalone_question": "高价值女性用户怎么定义"}\n```')
    assert data["standalone_question"] == "高价值女性用户怎么定义"


def test_parse_json_invalid_returns_none():
    assert conversation._parse_json("not json") is None

def test_chat_title_from_first_question():
    from rag_demo import chat_history
    assert chat_history._title_from_question("  高价值用户怎么定义的  ") == "高价值用户怎么定义的"
    assert chat_history._title_from_question("") == "新对话"
    assert len(chat_history._title_from_question("x" * 100)) <= 37
