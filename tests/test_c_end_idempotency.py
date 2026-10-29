"""C 端客户端消息幂等：claim / replay / conflict / release。"""
from __future__ import annotations

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
