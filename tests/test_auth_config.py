"""auth PostgreSQL 配置加载回归测试。"""
from __future__ import annotations

from rag_demo import auth


def test_auth_pg_config_prefers_auth_password(monkeypatch):
    monkeypatch.setenv("RAG_AUTH_PG_PASSWORD", "auth-secret")
    monkeypatch.setenv("RAG_PG_PASSWORD", "main-secret")
    config = auth._current_pg_config()
    assert config["password"] == "auth-secret"
    assert config["dbname"] == "rag_auth"


def test_auth_pg_config_falls_back_to_main_password(monkeypatch):
    monkeypatch.delenv("RAG_AUTH_PG_PASSWORD", raising=False)
    monkeypatch.setenv("RAG_PG_PASSWORD", "main-secret")
    config = auth._current_pg_config()
    assert config["password"] == "main-secret"
