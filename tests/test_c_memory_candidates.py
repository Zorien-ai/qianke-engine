# -*- coding: utf-8 -*-
"""Phase 2B：候选记忆 → 用户确认/拒绝 → 写回/审计。"""
from __future__ import annotations

import pytest

from rag_demo.c_end import store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end_candidates.sqlite"))
    monkeypatch.delenv("QIANKE_C_MEMORY_WRITE_MODE", raising=False)
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def test_direct_mode_keeps_existing_behavior(c_store):
    added = store.save_memories("buyer_1", "我喜欢跑步")
    assert len(added) == 1
    assert len(store.list_memories("buyer_1")) == 1
    assert store.list_memory_candidates("buyer_1") == []


def test_candidate_mode_does_not_activate_memory(c_store, monkeypatch):
    monkeypatch.setenv("QIANKE_C_MEMORY_WRITE_MODE", "candidate")
    added = store.save_memories("buyer_1", "我喜欢跑步")
    assert len(added) == 1
    assert added[0]["status"] == "PENDING_CONFIRMATION"
    assert store.list_memories("buyer_1") == []

    candidates = store.list_memory_candidates("buyer_1")
    assert len(candidates) == 1
    assert candidates[0]["content"] == "喜欢跑步"
    assert candidates[0]["status"] == "PENDING_CONFIRMATION"


def test_confirm_candidate_activates_and_audits(c_store):
    candidate = store.create_memory_candidates(
        "buyer_1", message="我的预算 500 元"
    )[0]
    assert store.list_memories("buyer_1") == []

    confirmed = store.confirm_memory_candidate("buyer_1", candidate["memory_id"])
    assert confirmed is not None
    assert confirmed["status"] == "ACTIVE"
    assert confirmed["confirmed_at"]
    assert int(confirmed["version"]) == 1

    active = store.list_memories("buyer_1")
    assert len(active) == 1
    assert active[0]["memory_id"] == candidate["memory_id"]
    assert store.list_memory_candidates("buyer_1") == []

    audit = store.list_memory_audit("buyer_1", memory_id=candidate["memory_id"])
    assert audit[0]["action"] == "CONFIRM"
    assert audit[0]["detail"]["content"] == "预算 500 元"

    # 已确认的候选不能重复确认/拒绝。
    assert store.confirm_memory_candidate("buyer_1", candidate["memory_id"]) is None
    assert store.reject_memory_candidate("buyer_1", candidate["memory_id"]) is None


def test_reject_candidate_does_not_activate_and_audits(c_store):
    candidate = store.create_memory_candidates("buyer_1", message="我喜欢跑步")[0]
    rejected = store.reject_memory_candidate("buyer_1", candidate["memory_id"])
    assert rejected is not None
    assert rejected["status"] == "REJECTED"
    assert rejected["rejected_at"]
    assert store.list_memories("buyer_1") == []
    assert store.list_memory_candidates("buyer_1") == []

    audit = store.list_memory_audit("buyer_1", memory_id=candidate["memory_id"])
    assert audit[0]["action"] == "REJECT"


def test_cross_owner_cannot_confirm_candidate(c_store):
    candidate = store.create_memory_candidates("buyer_1", message="我喜欢跑步")[0]
    assert store.confirm_memory_candidate("buyer_2", candidate["memory_id"]) is None
    assert store.reject_memory_candidate("buyer_2", candidate["memory_id"]) is None
    assert len(store.list_memory_candidates("buyer_1")) == 1
    assert store.list_memories("buyer_2") == []


def test_candidate_creation_is_idempotent(c_store):
    first = store.create_memory_candidates("buyer_1", message="我喜欢跑步")
    second = store.create_memory_candidates("buyer_1", message="我喜欢跑步")
    assert len(first) == 1
    assert second == []
    assert len(store.list_memory_candidates("buyer_1")) == 1


def test_rejected_content_is_not_recreated(c_store):
    candidate = store.create_memory_candidates("buyer_1", message="我喜欢跑步")[0]
    store.reject_memory_candidate("buyer_1", candidate["memory_id"])
    assert store.create_memory_candidates("buyer_1", message="我喜欢跑步") == []
