"""认证/监控 PG 配置必须动态读取环境变量，不能缓存导入时端口。"""
from __future__ import annotations

from rag_demo import ai_monitor, auth


def test_current_pg_config_reads_env(monkeypatch):
    monkeypatch.setenv("RAG_AUTH_PG_HOST", "127.0.0.1")
    monkeypatch.setenv("RAG_AUTH_PG_PORT", "15432")
    monkeypatch.setenv("RAG_AUTH_PG_DB", "rag_auth")
    cfg = auth.current_pg_config()
    assert cfg["host"] == "127.0.0.1"
    assert cfg["port"] == 15432
    assert cfg["dbname"] == "rag_auth"


def test_ai_monitor_connect_uses_current_config(monkeypatch):
    captured = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(ai_monitor.psycopg2, "connect", fake_connect)
    monkeypatch.setenv("RAG_AUTH_PG_PORT", "15432")
    ai_monitor._connect()
    assert captured["port"] == 15432
