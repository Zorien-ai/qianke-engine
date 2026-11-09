"""C 端伙伴长期记忆：确定性抽取、可见、可删除。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import agent as c_agent
from rag_demo.c_end import store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end_memory.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def test_extract_memories_preferences_and_boundaries():
    items = store.extract_memories("我喜欢跑步，我的预算 500 元。别给我推荐跑鞋。")
    contents = {(item["kind"], item["content"]) for item in items}
    assert ("preference", "喜欢跑步") in contents
    assert ("preference", "预算 500 元") in contents
    assert ("boundary", "不要推荐跑鞋") in contents


def test_extract_memories_skips_pii():
    assert store.extract_memories("我喜欢跑步，手机 13800138000") == []
    assert store.extract_memories("我的邮箱 alice@example.com，预算 500 元") == []


def test_extract_memories_skips_questions():
    assert store.extract_memories("你还记得我喜欢什么吗") == []
    assert store.extract_memories("我预算 500 元，推荐哪款？") == []


def test_memory_crud_and_prompt_injection(c_store):
    added = store.save_memories("buyer_1", "我喜欢跑步，我的预算 500 元，别给我推荐跑鞋")
    assert len(added) == 3
    memories = store.list_memories("buyer_1")
    assert len(memories) == 3
    assert {item["kind"] for item in memories} == {"preference", "boundary"}

    prompt = c_agent.build_system_prompt("buyer_1", mode="companion")
    assert "你记得的事" in prompt
    assert "预算 500 元" in prompt
    assert "不要推荐跑鞋" in prompt

    target = memories[0]["memory_id"]
    assert store.delete_memory("buyer_1", target) is True
    assert len(store.list_memories("buyer_1")) == 2
    assert store.delete_memory("buyer_1", target) is False
    assert store.clear_memories("buyer_1") == 2
    assert store.list_memories("buyer_1") == []


def test_memory_not_injected_for_other_buyer(c_store):
    store.save_memories("buyer_1", "我喜欢跑步")
    prompt = c_agent.build_system_prompt("buyer_2", mode="companion")
    assert "喜欢跑步" not in prompt
