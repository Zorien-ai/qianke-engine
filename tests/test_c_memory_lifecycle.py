"""C 端记忆生命周期：重要性、强化、压缩、遗忘、日记。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from datetime import datetime, timedelta, timezone

import pytest

from rag_demo.c_end import memory_daily, store


@pytest.fixture()
def c_store(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    return store


def test_memory_importance_is_deterministic(c_store):
    added = store.save_memories("buyer_1", "我对花粉过敏，我的预算 500 元")
    by_content = {item["content"]: item["importance"] for item in added}
    assert by_content["对花粉过敏"] == 5
    assert by_content["预算 500 元"] == 4


def test_duplicate_memory_only_reinforces(c_store):
    first = store.save_memories("buyer_1", "我喜欢跑步")
    second = store.save_memories("buyer_1", "我喜欢跑步")
    assert len(first) == 1
    assert second == []
    memories = store.list_memories("buyer_1")
    assert len(memories) == 1
    assert memories[0]["reinforced_count"] == 2


def test_decay_lowers_low_importance_but_never_five(c_store):
    added = store.save_memories("buyer_1", "我喜欢跑步，我对花粉过敏")
    low = next(item for item in added if item["content"] == "喜欢跑步")
    high = next(item for item in added if item["content"] == "对花粉过敏")
    conn = c_store._connect()
    try:
        old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        conn.execute(
            "UPDATE c_companion_memory SET last_reinforced_at = ? WHERE memory_id IN (?, ?)",
            (old, low["memory_id"], high["memory_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    changed = store.decay_memories("buyer_1")
    assert changed == 1
    memories = {item["memory_id"]: item for item in store.list_memories("buyer_1")}
    assert memories[low["memory_id"]]["importance"] == 2
    assert memories[high["memory_id"]]["importance"] == 5


def test_compress_over_threshold_and_archive(c_store):
    for index in range(21):
        store.save_memories("buyer_1", f"我喜欢商品{index}")
    assert len(store.list_memories("buyer_1", limit=500)) == 21
    result = memory_daily.compress_memories("buyer_1", "2026-11-11")
    assert result["archived"] >= 1
    active = store.list_memories("buyer_1", limit=500)
    assert len(active) <= memory_daily.MEMORY_ACTIVE_LIMIT
    digests = store.list_memory_digests("buyer_1")
    assert digests
    assert digests[0]["source_memory_ids"]


def test_compress_failure_keeps_raw_memories(c_store, monkeypatch):
    for index in range(21):
        store.save_memories("buyer_1", f"我喜欢商品{index}")

    def fail(*args, **kwargs):
        raise RuntimeError("write failed")

    monkeypatch.setattr(store, "upsert_memory_digest", fail)
    with pytest.raises(RuntimeError):
        memory_daily.compress_memories("buyer_1", "2026-11-11")
    assert len(store.list_memories("buyer_1", limit=500)) == 21


def test_diary_disabled_by_default_and_enabled(c_store):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    assert store.get_diary_enabled("buyer_1") is False
    store.set_diary_enabled("buyer_1", True)
    assert store.get_diary_enabled("buyer_1") is True
    store.save_app_message("buyer_1", "companion", "user", "今天去爬山了")
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        return "今天和用户聊了爬山，天气不错。"

    diary = memory_daily.generate_diary("buyer_1", today, llm=fake_llm)
    assert diary is not None
    assert "爬山" in diary["content"]
    assert calls
    # 幂等：同一天不会重复生成。
    again = memory_daily.generate_diary("buyer_1", today, llm=fake_llm)
    assert again["diary_id"] == diary["diary_id"]
    assert len(calls) == 1


def test_diary_rejects_pii(c_store):
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    store.set_diary_enabled("buyer_1", True)
    store.save_app_message("buyer_1", "companion", "user", "联系我 13800138000")
    diary = memory_daily.generate_diary(
        "buyer_1",
        today,
        llm=lambda messages: "今天用户留了手机号 13800138000。",
    )
    assert diary is None
