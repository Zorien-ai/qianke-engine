"""店宠 WebSocket 重试 E2E：同一 client_message_id 只触发一次 social.send_message。

用 FastAPI TestClient 的 WebSocket 通道驱动真实的 `/api/c/ws/chat/{friend_id}` 路由，
auth 与店宠 Agent 用 monkeypatch 替换（不改生产 auth），验证：

- 同 ID 重发：第二次回放缓存，social.send_message 只调用一次；
- 同 ID 不同内容：返回 IDEMPOTENCY_CONFLICT，不重复执行；
- 非法 client_message_id：返回结构化错误；
- 不带 client_message_id：保持旧行为（每次执行）。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from rag_demo import auth
from rag_demo.api import c_end
from rag_demo.c_end import idempotency, store

_SESSION = "ws-e2e-session"


@pytest.fixture()
def ws_env(tmp_path, monkeypatch):
    """独立 SQLite + 测试专用会话解析 + 可计数的 fake 店宠。"""
    monkeypatch.setenv("QIANKE_C_END_DB", str(tmp_path / "c_end_ws.sqlite"))
    monkeypatch.setattr(store, "_DB_PATH", None)
    store.init()
    idempotency.init()

    def fake_resolve_session(token):
        if token == _SESSION:
            return {"id": 7, "status": auth.STATUS_ACTIVE, "is_demo": False}
        return None

    # 只替换测试进程里的函数，不改生产 auth 代码。
    monkeypatch.setattr(auth, "resolve_session", fake_resolve_session)

    calls: list[dict] = []

    def fake_send(buyer_id, friend_id, content, **kwargs):
        calls.append({"buyer_id": buyer_id, "friend_id": friend_id, "content": content})
        return {
            "message": {"content": content, "sender_id": buyer_id},
            "reply": {"sender_id": friend_id, "content": "喵~ 收到", "metadata": {}},
            "companion_message": None,
        }

    monkeypatch.setattr(c_end.social, "send_message", fake_send)

    app = FastAPI()
    app.include_router(c_end.router)
    with TestClient(app) as client:
        # 会话 Cookie 放在 client 实例上（避免每次请求传 cookies 的弃用路径）。
        client.cookies.set(auth.SESSION_COOKIE, _SESSION)
        yield client, calls


def _connect(client):
    return client.websocket_connect("/api/c/ws/chat/store_demo")


def test_ws_resend_same_client_message_id_only_calls_social_once(ws_env):
    """同一 client_message_id 通过 WebSocket 重发：只执行一次，第二次回放。"""
    client, calls = ws_env

    with _connect(client) as websocket:
        websocket.send_json(
            {"content": "@店宠 今天有活动吗", "client_message_id": "cmsg_ws_e2e_0001"}
        )
        first = websocket.receive_json()
        websocket.send_json(
            {"content": "@店宠 今天有活动吗", "client_message_id": "cmsg_ws_e2e_0001"}
        )
        second = websocket.receive_json()

    assert first["type"] == "chat"
    # 首次响应不带回放标记，第二次显式标记 idempotent_replay
    assert first.get("idempotent_replay") is not True
    assert second["type"] == "chat"
    assert second.get("idempotent_replay") is True
    assert second["reply"]["content"] == first["reply"]["content"] == "喵~ 收到"
    assert len(calls) == 1
    assert calls[0]["buyer_id"] == "buyer_7"
    assert calls[0]["friend_id"] == "store_demo"


def test_ws_same_client_message_id_different_content_conflicts(ws_env):
    """同 ID 换内容不执行第二次，返回结构化 IDEMPOTENCY_CONFLICT。"""
    client, calls = ws_env

    with _connect(client) as websocket:
        websocket.send_json(
            {"content": "@店宠 活动", "client_message_id": "cmsg_ws_e2e_0002"}
        )
        first = websocket.receive_json()
        websocket.send_json(
            {"content": "@店宠 退款", "client_message_id": "cmsg_ws_e2e_0002"}
        )
        second = websocket.receive_json()

    assert first["type"] == "chat"
    assert second["type"] == "error"
    assert second["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert len(calls) == 1


def test_ws_rejects_invalid_client_message_id(ws_env):
    """非法 client_message_id 不触达店宠 Agent，返回结构化错误。"""
    client, calls = ws_env

    with _connect(client) as websocket:
        websocket.send_json({"content": "hi", "client_message_id": "bad id!"})
        error = websocket.receive_json()

    assert error["type"] == "error"
    assert error["error"]["code"] == "INVALID_CLIENT_MESSAGE_ID"
    assert calls == []


def test_ws_without_client_message_id_keeps_legacy_behavior(ws_env):
    """不传 client_message_id 时保持旧行为：每条消息都执行（不做幂等）。"""
    client, calls = ws_env

    with _connect(client) as websocket:
        websocket.send_json({"content": "@店宠 第一条"})
        first = websocket.receive_json()
        websocket.send_json({"content": "@店宠 第二条"})
        second = websocket.receive_json()

    assert first["type"] == "chat" and second["type"] == "chat"
    assert first.get("idempotent_replay") is None
    assert second.get("idempotent_replay") is None
    assert len(calls) == 2


def test_ws_rejects_unauthenticated_connection(ws_env):
    """没有有效会话 Cookie 时连接被关闭（1008），不会执行店宠 Agent。"""
    client, calls = ws_env
    client.cookies.clear()

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/c/ws/chat/store_demo"):
            pass

    assert calls == []
