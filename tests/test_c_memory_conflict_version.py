# -*- coding: utf-8 -*-
"""Phase 3C：冲突键、supersede、版本链。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end_conflict.sqlite"))
    monkeypatch.setenv("QIANKE_C_MEMORY_WRITE_MODE", "direct")
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def test_conflict_key_is_deterministic():
    assert store.memory_conflict_key("preference", "预算 500 元") == "budget"
    assert store.memory_conflict_key("preference", "尺码 42") == "size"
    assert store.memory_conflict_key("preference", "喜欢跑步") == "taste:跑步"
    assert store.memory_conflict_key("preference", "不喜欢跑步") == "taste:跑步"
    assert store.memory_conflict_key("boundary", "不要推荐跑鞋") == "avoid:跑鞋"
    assert store.memory_conflict_key("boundary", "对花生过敏") == "allergy:花生"
    assert store.memory_conflict_key("preference", "喜欢跑步") != store.memory_conflict_key("preference", "喜欢喝茶")


def test_direct_save_supersedes_budget(c_store):
    store.save_memories("buyer_1", "我的预算 500 元")
    old = store.list_memories("buyer_1")[0]
    store.save_memories("buyer_1", "我的预算 800 元")

    active = store.list_memories("buyer_1")
    assert len(active) == 1
    assert active[0]["content"] == "预算 800 元"
    assert active[0]["version"] == 2
    assert active[0]["supersedes_memory_id"] == old["memory_id"]

    history = store.list_memory_history("buyer_1", active[0]["memory_id"])
    assert history is not None
    assert [item["status"] for item in history["versions"]] == ["ACTIVE", "SUPERSEDED"]
    assert history["versions"][1]["superseded_by_memory_id"] == active[0]["memory_id"]


def test_confirm_candidate_supersedes_and_audits(c_store, monkeypatch):
    store.save_memories("buyer_1", "我的预算 500 元")
    old = store.list_memories("buyer_1")[0]
    monkeypatch.setenv("QIANKE_C_MEMORY_WRITE_MODE", "candidate")

    candidate = store.save_memories("buyer_1", "我的预算 800 元")[0]
    assert candidate["status"] == "PENDING_CONFIRMATION"
    assert candidate["conflict_key"] == "budget"
    assert candidate["supersedes_memory_id"] == old["memory_id"]

    confirmed = store.confirm_memory_candidate("buyer_1", candidate["memory_id"])
    assert confirmed is not None
    assert confirmed["status"] == "ACTIVE"
    assert int(confirmed["version"]) == 2
    assert store.list_memories("buyer_1")[0]["content"] == "预算 800 元"

    audit = store.list_memory_audit("buyer_1")
    actions = {item["action"] for item in audit}
    assert "CONFIRM" in actions
    assert "SUPERSEDE" in actions


def test_different_conflict_keys_do_not_supersede(c_store):
    store.save_memories("buyer_1", "我的预算 500 元，我穿42码")
    assert len(store.list_memories("buyer_1")) == 2
    store.save_memories("buyer_1", "我的预算 800 元")
    active = store.list_memories("buyer_1")
    assert len(active) == 2
    assert {item["conflict_key"] for item in active} == {"budget", "size"}


def test_history_is_owner_scoped(c_store):
    store.save_memories("buyer_1", "我的预算 500 元")
    memory = store.list_memories("buyer_1")[0]
    assert store.list_memory_history("buyer_1", memory["memory_id"]) is not None
    assert store.list_memory_history("buyer_2", memory["memory_id"]) is None
