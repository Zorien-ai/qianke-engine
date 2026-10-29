"""C 端客户端消息幂等：claim / replay / conflict / release / TTL 清理。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from rag_demo.c_end import idempotency, store


@pytest.fixture()
def c_idem(tmp_path, monkeypatch):
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    idempotency.init()
    return idempotency


def _fp(c_idem, text="你好", thread=None):
    return c_idem.fingerprint(text, thread)


def _backdate(c_idem, client_id, owner_id, endpoint, *, created_at, updated_at):
    """把幂等记录的时间拨到过去，模拟 TTL 过期。"""
    conn = sqlite3.connect(str(store._db_path()))
    try:
        conn.execute(
            "UPDATE c_client_request SET created_at = ?, updated_at = ? "
            "WHERE client_id = ? AND owner_id = ? AND endpoint = ?",
            (created_at, updated_at, client_id, owner_id, endpoint),
        )
        conn.commit()
    finally:
        conn.close()


def _row_count(c_idem) -> int:
    conn = sqlite3.connect(str(store._db_path()))
    try:
        return conn.execute("SELECT COUNT(*) FROM c_client_request").fetchone()[0]
    finally:
        conn.close()


def _old_iso(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def test_claim_complete_replay(c_idem):
    fp = _fp(c_idem)
    first = c_idem.claim(client_id="cmsg_12345678", owner_id="buyer_1", endpoint="c_agent_run", request_fingerprint=fp)
    assert first["state"] == "claimed"
    c_idem.complete(
        client_id="cmsg_12345678",
        owner_id="buyer_1",
        endpoint="c_agent_run",
        response={"reply": "已收到"},
    )
    second = c_idem.claim(client_id="cmsg_12345678", owner_id="buyer_1", endpoint="c_agent_run", request_fingerprint=fp)
    assert second["state"] == "replay"
    assert second["response"]["reply"] == "已收到"


def test_same_id_different_message_conflicts(c_idem):
    c_idem.claim(
        client_id="cmsg_87654321",
        owner_id="buyer_1",
        endpoint="c_agent_run",
        request_fingerprint=_fp(c_idem, "你好"),
    )
    with pytest.raises(c_idem.IdempotencyConflict):
        c_idem.claim(
            client_id="cmsg_87654321",
            owner_id="buyer_1",
            endpoint="c_agent_run",
            request_fingerprint=_fp(c_idem, "换一个问题"),
        )


def test_release_allows_retry(c_idem):
    fp = _fp(c_idem, "重试消息")
    c_idem.claim(client_id="cmsg_retry_01", owner_id="buyer_1", endpoint="c_agent_run", request_fingerprint=fp)
    c_idem.release(client_id="cmsg_retry_01", owner_id="buyer_1", endpoint="c_agent_run")
    again = c_idem.claim(client_id="cmsg_retry_01", owner_id="buyer_1", endpoint="c_agent_run", request_fingerprint=fp)
    assert again["state"] == "claimed"


def test_default_ttl_is_seven_days_and_env_override(c_idem, monkeypatch):
    monkeypatch.delenv(c_idem.TTL_ENV, raising=False)
    assert c_idem.DEFAULT_TTL_SECONDS == 7 * 24 * 3600
    assert c_idem._ttl_seconds() == c_idem.DEFAULT_TTL_SECONDS

    monkeypatch.setenv(c_idem.TTL_ENV, "60")
    assert c_idem._ttl_seconds() == 60

    # 非法/非正数环境变量回退默认值
    monkeypatch.setenv(c_idem.TTL_ENV, "not-a-number")
    assert c_idem._ttl_seconds() == c_idem.DEFAULT_TTL_SECONDS
    monkeypatch.setenv(c_idem.TTL_ENV, "0")
    assert c_idem._ttl_seconds() == c_idem.DEFAULT_TTL_SECONDS

    # 显式参数优先于环境变量
    assert c_idem._ttl_seconds(120) == 120


def test_prune_removes_expired_completed_and_stale_in_progress(c_idem):
    """过期 COMPLETED 与超时 IN_PROGRESS 被删；新鲜记录保持 replay/in_progress。"""
    # 过期 COMPLETED
    c_idem.claim(
        client_id="cmsg_old_done", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=_fp(c_idem, "old done"),
    )
    c_idem.complete(
        client_id="cmsg_old_done", owner_id="buyer_1", endpoint="c_agent_run",
        response={"reply": "旧响应"},
    )
    # 过期 IN_PROGRESS（进程崩溃遗留执行权）
    c_idem.claim(
        client_id="cmsg_old_progress", owner_id="buyer_1", endpoint="c_store_send",
        request_fingerprint=_fp(c_idem, "old progress"),
    )
    # 新鲜 COMPLETED
    c_idem.claim(
        client_id="cmsg_new_done", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=_fp(c_idem, "new done"),
    )
    c_idem.complete(
        client_id="cmsg_new_done", owner_id="buyer_1", endpoint="c_agent_run",
        response={"reply": "新响应"},
    )
    # 新鲜 IN_PROGRESS
    c_idem.claim(
        client_id="cmsg_new_progress", owner_id="buyer_1", endpoint="c_store_send",
        request_fingerprint=_fp(c_idem, "new progress"),
    )
    assert _row_count(c_idem) == 4

    old = _old_iso(hours=2)
    _backdate(c_idem, "cmsg_old_done", "buyer_1", "c_agent_run", created_at=old, updated_at=old)
    _backdate(c_idem, "cmsg_old_progress", "buyer_1", "c_store_send", created_at=old, updated_at=old)

    deleted = c_idem.prune(max_age_seconds=3600)
    assert deleted == 2
    assert _row_count(c_idem) == 2

    # 新鲜 COMPLETED 仍回放缓存
    replay = c_idem.claim(
        client_id="cmsg_new_done", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=_fp(c_idem, "new done"),
    )
    assert replay["state"] == "replay"
    assert replay["response"]["reply"] == "新响应"
    # 新鲜 IN_PROGRESS 仍占执行权
    assert c_idem.claim(
        client_id="cmsg_new_progress", owner_id="buyer_1", endpoint="c_store_send",
        request_fingerprint=_fp(c_idem, "new progress"),
    )["state"] == "in_progress"

    # 过期记录被删后，同 ID 可以重新 claim（TTL 到期即允许重新执行）
    assert c_idem.claim(
        client_id="cmsg_old_done", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=_fp(c_idem, "old done"),
    )["state"] == "claimed"


def test_prune_does_not_remove_fresh_replay(c_idem):
    """默认 TTL 下刚完成的记录不会被清理，replay 仍然命中。"""
    fp = _fp(c_idem, "刚刚完成")
    c_idem.claim(
        client_id="cmsg_fresh_01", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=fp,
    )
    c_idem.complete(
        client_id="cmsg_fresh_01", owner_id="buyer_1", endpoint="c_agent_run",
        response={"reply": "缓存响应"},
    )
    assert c_idem.prune() == 0
    replay = c_idem.claim(
        client_id="cmsg_fresh_01", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=fp,
    )
    assert replay["state"] == "replay"
    assert replay["response"]["reply"] == "缓存响应"


def test_prune_uses_env_ttl(c_idem, monkeypatch):
    """QIANKE_C_IDEMPOTENCY_TTL_SECONDS 控制 prune 的过期阈值。"""
    fp = _fp(c_idem, "环境变量 TTL")
    c_idem.claim(
        client_id="cmsg_env_01", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=fp,
    )
    c_idem.complete(
        client_id="cmsg_env_01", owner_id="buyer_1", endpoint="c_agent_run",
        response={"reply": "ok"},
    )
    old = _old_iso(hours=2)
    _backdate(c_idem, "cmsg_env_01", "buyer_1", "c_agent_run", created_at=old, updated_at=old)

    # TTL = 1 天：2 小时前的记录未过期
    monkeypatch.setenv(c_idem.TTL_ENV, str(24 * 3600))
    assert c_idem.prune() == 0
    assert c_idem.claim(
        client_id="cmsg_env_01", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=fp,
    )["state"] == "replay"

    # TTL = 60 秒：同一记录过期被清理
    monkeypatch.setenv(c_idem.TTL_ENV, "60")
    assert c_idem.prune() == 1


def test_auto_prune_runs_on_claim(c_idem, monkeypatch):
    """claim 会自动触发清理（本测试把节流间隔设为 0）。"""
    monkeypatch.setattr(c_idem, "_PRUNE_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(c_idem, "_last_prune_at", float("-inf"))

    fp = _fp(c_idem, "自动清理旧记录")
    c_idem.claim(
        client_id="cmsg_auto_old", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=fp,
    )
    c_idem.complete(
        client_id="cmsg_auto_old", owner_id="buyer_1", endpoint="c_agent_run",
        response={"reply": "old"},
    )
    old = _old_iso(hours=2)
    _backdate(c_idem, "cmsg_auto_old", "buyer_1", "c_agent_run", created_at=old, updated_at=old)

    # 新请求触发自动 prune（默认 TTL 7 天不会删 2 小时前记录，这里用环境变量收紧）
    monkeypatch.setenv(c_idem.TTL_ENV, "60")
    result = c_idem.claim(
        client_id="cmsg_auto_new", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=_fp(c_idem, "新请求"),
    )
    assert result["state"] == "claimed"
    assert _row_count(c_idem) == 1
    assert c_idem.claim(
        client_id="cmsg_auto_old", owner_id="buyer_1", endpoint="c_agent_run",
        request_fingerprint=fp,
    )["state"] == "claimed"
