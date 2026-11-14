"""管理员端 Agent 调用监控 API 的权限与数据边界。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from rag_demo.api import monitor
from rag_demo import ai_monitor


class _AdminMain:
    def _require_system_admin(self):
        return {"id": 1, "username": "admin", "is_system_admin": True}


class _RejectedMain:
    def _require_system_admin(self):
        raise HTTPException(status_code=403, detail="只有系统管理员可以访问")


def test_admin_agent_traces_requires_system_admin(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _RejectedMain())
    with pytest.raises(HTTPException) as exc:
        monitor.admin_agent_traces(range_key="24h")
    assert exc.value.status_code == 403


def test_admin_agent_traces_returns_ai_monitor_payload(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())
    monkeypatch.setattr(
        ai_monitor,
        "agent_traces",
        lambda range_key, **kwargs: {
            "range": range_key,
            "summary": {"requests": 1, "success": 1, "errors": 0},
            "total": 1,
            "items": [{"trace_id": "trace_1", "question": "统计用户数"}],
        },
    )
    data = monitor.admin_agent_traces(range_key="7d", status="success", q="用户")
    assert data["total"] == 1
    assert data["items"][0]["trace_id"] == "trace_1"
    assert data["range"] == "7d"


def test_admin_agent_trace_detail_requires_system_admin(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _RejectedMain())
    with pytest.raises(HTTPException) as exc:
        monitor.admin_agent_trace_detail("trace_1")
    assert exc.value.status_code == 403


def test_admin_agent_trace_detail_returns_trace(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())
    monkeypatch.setattr(
        ai_monitor,
        "trace_detail",
        lambda tenant, trace_id, admin=False: {
            "trace_id": trace_id,
            "meta": {"agent_events": [{"event": "run_started"}]},
        },
    )
    data = monitor.admin_agent_trace_detail("trace_1")
    assert data["trace_id"] == "trace_1"
    assert data["meta"]["agent_events"][0]["event"] == "run_started"


def test_admin_agent_trace_detail_not_found(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())
    monkeypatch.setattr(ai_monitor, "trace_detail", lambda *args, **kwargs: None)
    with pytest.raises(HTTPException) as exc:
        monitor.admin_agent_trace_detail("missing")
    assert exc.value.status_code == 404
