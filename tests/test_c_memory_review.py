# -*- coding: utf-8 -*-
"""Phase 3A：会话结束自动生成候选（不直接激活）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rag_demo.c_end import memory_review, store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end_review.sqlite"))
    monkeypatch.setenv("QIANKE_C_MEMORY_WRITE_MODE", "candidate")
    monkeypatch.delenv("QIANKE_C_MEMORY_REVIEW_IDLE_MINUTES", raising=False)
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def _seed_messages(monkeypatch, *messages: str, at: str = "2026-11-20T10:00:00+00:00") -> list[dict]:
    monkeypatch.setattr(store, "_next_message_time", lambda: at)
    saved = []
    for text in messages:
        saved.append(store.save_app_message("buyer_1", "companion", "user", text))
    return saved


def _now_after_idle() -> datetime:
    return datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def test_idle_session_generates_candidates(c_store, monkeypatch):
    saved = _seed_messages(monkeypatch, "我喜欢跑步，我的预算 500 元")
    result = memory_review.review_owner("buyer_1", now=_now_after_idle())

    assert result["ok"] is True
    assert result["reason"] == "REVIEWED"
    assert result["candidate_count"] == 2
    assert store.list_memories("buyer_1") == []

    candidates = store.list_memory_candidates("buyer_1")
    assert {item["content"] for item in candidates} == {"喜欢跑步", "预算 500 元"}
    assert all(item["source"] == "session_review" for item in candidates)
    assert candidates[0]["source_message_ids"] == [saved[0]["message_id"]]


def test_recent_session_is_not_reviewed(c_store, monkeypatch):
    _seed_messages(monkeypatch, "我喜欢跑步", at="2026-11-20T11:55:00+00:00")
    result = memory_review.review_owner("buyer_1", now=_now_after_idle())
    assert result["reason"] == "NOT_IDLE"
    assert result["candidates"] == []
    assert store.list_memory_candidates("buyer_1") == []


def test_questions_and_empty_sessions_produce_no_candidates(c_store, monkeypatch):
    _seed_messages(monkeypatch, "我喜欢什么吗？", "你还记得我吗")
    result = memory_review.review_owner("buyer_1", now=_now_after_idle())
    assert result["ok"] is True
    assert result["reason"] == "NO_CANDIDATES"
    assert store.list_memory_candidates("buyer_1") == []

    empty = memory_review.review_owner("buyer_2", now=_now_after_idle())
    assert empty["reason"] == "NO_MESSAGES"


def test_repeat_review_is_idempotent(c_store, monkeypatch):
    _seed_messages(monkeypatch, "我喜欢跑步")
    first = memory_review.review_owner("buyer_1", now=_now_after_idle())
    second = memory_review.review_owner("buyer_1", now=_now_after_idle())
    assert first["candidate_count"] == 1
    assert second["candidate_count"] == 0
    assert len(store.list_memory_candidates("buyer_1")) == 1


def test_direct_mode_skips_review(c_store, monkeypatch):
    _seed_messages(monkeypatch, "我喜欢跑步")
    monkeypatch.setenv("QIANKE_C_MEMORY_WRITE_MODE", "direct")
    result = memory_review.review_owner("buyer_1", now=_now_after_idle())
    assert result["reason"] == "CANDIDATE_MODE_DISABLED"
    assert store.list_memory_candidates("buyer_1") == []


def test_review_all_only_touches_owner_messages(c_store, monkeypatch):
    _seed_messages(monkeypatch, "我喜欢跑步")
    result = memory_review.review_all(owners=["buyer_1"], now=_now_after_idle())
    assert result["checked"] == 1
    assert result["reviewed"] == 1
    assert result["candidates_created"] == 1
    assert store.list_memory_candidates("buyer_2") == []
