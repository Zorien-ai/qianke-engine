"""C 端消费者注册 / 验证码登录测试。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_demo import auth
from rag_demo.api import c_auth
from rag_demo.c_end import consumer_auth


@pytest.fixture()
def sms_env(monkeypatch):
    consumer_auth.reset_for_tests()
    monkeypatch.setattr(consumer_auth, "_DEV_MODE", True)
    monkeypatch.setattr(consumer_auth, "_DEV_CODE", "654321")
    yield
    consumer_auth.reset_for_tests()


@pytest.fixture()
def client(monkeypatch):
    account = {
        "id": 9001,
        "username": "c_13800138000",
        "display_name": "小鱼用户",
        "account_type": auth.ACCOUNT_CONSUMER,
        "role": "buyer",
        "status": auth.STATUS_ACTIVE,
        "status_label": "正常",
        "is_system_admin": False,
        "is_enterprise_admin": False,
        "is_demo": False,
        "enterprise_id": None,
    }
    monkeypatch.setattr(auth, "create_consumer", lambda *args, **kwargs: account)
    monkeypatch.setattr(auth, "find_user_by_login", lambda account_id: account)
    monkeypatch.setattr(auth, "create_session", lambda user_id, ttl=None: "test-session-token")
    monkeypatch.setattr(auth, "resolve_session", lambda token: account)
    app = FastAPI()
    app.include_router(c_auth.router)
    return TestClient(app)


def test_sms_code_dev_flow_and_one_time_use(sms_env):
    result = consumer_auth.send_code("13800138000", client_ip="127.0.0.1")
    assert result["dev_mode"] is True
    assert result["dev_code"] == "654321"
    assert consumer_auth.verify_code("13800138000", "000000") is False
    assert consumer_auth.verify_code("13800138000", "654321") is True
    # 一次性：同一验证码不能复用
    assert consumer_auth.verify_code("13800138000", "654321") is False


def test_sms_code_has_cooldown(sms_env):
    consumer_auth.send_code("13800138000")
    with pytest.raises(ValueError, match="频繁"):
        consumer_auth.send_code("13800138000")


def test_sms_code_rejects_invalid_phone(sms_env):
    with pytest.raises(ValueError, match="11 位"):
        consumer_auth.send_code("123")
    with pytest.raises(ValueError, match="11 位"):
        consumer_auth.send_code("12800138000")


def test_register_sets_session_cookie(client, sms_env):
    consumer_auth.send_code("13800138000")
    response = client.post(
        "/api/c/auth/register",
        json={
            "phone": "13800138000",
            "code": "654321",
            "nickname": "小鱼用户",
            "password": "password123",
            "agree_terms": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["account"]["account_type"] == "consumer"
    assert auth.SESSION_COOKIE in response.headers.get("set-cookie", "")


def test_register_requires_terms_and_valid_code(client):
    response = client.post(
        "/api/c/auth/register",
        json={
            "phone": "13800138000",
            "code": "654321",
            "nickname": "小鱼用户",
            "password": "password123",
            "agree_terms": False,
        },
    )
    assert response.status_code == 400
    assert "同意" in response.json()["detail"]


def test_code_login_rejects_bad_code(client, sms_env):
    response = client.post(
        "/api/c/auth/login/code",
        json={"phone": "13800138000", "code": "000000"},
    )
    assert response.status_code == 400


def test_code_login_succeeds_with_verified_code(client, sms_env):
    consumer_auth.send_code("13800138000")
    response = client.post(
        "/api/c/auth/login/code",
        json={"phone": "13800138000", "code": "654321"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["account"]["username"] == "c_13800138000"


def test_production_mode_without_provider_fails_and_clears_code(sms_env, monkeypatch):
    monkeypatch.setattr(consumer_auth, "_DEV_MODE", False)
    monkeypatch.setenv("QIANKE_SMS_PROVIDER", "")
    with pytest.raises(RuntimeError, match="供应商未配置"):
        consumer_auth.send_code("13800138000")
    assert consumer_auth.verify_code("13800138000", "654321") is False
