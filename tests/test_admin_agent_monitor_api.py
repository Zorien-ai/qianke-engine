"""管理员端 Agent 调用监控 API 的权限与数据边界。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from rag_demo.api import monitor
from rag_demo import agent_eval_store, ai_monitor


class _AdminMain:
    def _require_system_admin(self):
        return {"id": 1, "username": "admin", "is_system_admin": True}

    def _agent_dataset(self, account=None):
        return "test"


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


def test_admin_agent_trace_tags_updates(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())
    monkeypatch.setattr(
        ai_monitor,
        "set_agent_trace_tags",
        lambda trace_id, tags, actor="": ["回归", "慢查询"],
    )
    data = monitor.admin_agent_trace_tags(
        "trace_1",
        monitor.AgentTraceTagsIn(tags=["回归", "慢查询"]),
    )
    assert data["trace_id"] == "trace_1"
    assert data["tags"] == ["回归", "慢查询"]


def test_admin_agent_trace_tags_not_found(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())
    monkeypatch.setattr(ai_monitor, "set_agent_trace_tags", lambda *args, **kwargs: None)
    with pytest.raises(HTTPException) as exc:
        monitor.admin_agent_trace_tags("missing", monitor.AgentTraceTagsIn(tags=["x"]))
    assert exc.value.status_code == 404


def test_admin_agent_trace_feedback_updates(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())
    monkeypatch.setattr(
        ai_monitor,
        "set_agent_trace_feedback",
        lambda trace_id, **kwargs: 5,
    )
    data = monitor.admin_agent_trace_feedback(
        "trace_1",
        monitor.AgentTraceFeedbackIn(score=5, comment="口径清楚"),
    )
    assert data["feedback_score"] == 5
    assert data["comment"] == "口径清楚"


def test_admin_agent_trace_feedback_validation_error(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())

    def _raise(*args, **kwargs):
        raise ValueError("评分必须在 1-5 之间")

    monkeypatch.setattr(ai_monitor, "set_agent_trace_feedback", _raise)
    with pytest.raises(HTTPException) as exc:
        monitor.admin_agent_trace_feedback(
            "trace_1",
            monitor.AgentTraceFeedbackIn(score=9),
        )
    assert exc.value.status_code == 400


def test_admin_agent_trace_feedback_not_found(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())
    monkeypatch.setattr(ai_monitor, "set_agent_trace_feedback", lambda *args, **kwargs: None)
    with pytest.raises(HTTPException) as exc:
        monitor.admin_agent_trace_feedback(
            "missing",
            monitor.AgentTraceFeedbackIn(score=5),
        )
    assert exc.value.status_code == 404


def test_admin_agent_datasets_requires_system_admin(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _RejectedMain())
    with pytest.raises(HTTPException) as exc:
        monitor.admin_agent_datasets()
    assert exc.value.status_code == 403


def test_admin_agent_dataset_create(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())
    monkeypatch.setattr(
        agent_eval_store,
        "create_dataset",
        lambda *args, **kwargs: {"dataset_id": "ds_1", "name": "回归集", "cases": []},
    )
    data = monitor.admin_agent_dataset_create(
        monitor.AgentDatasetIn(name="回归集", trace_ids=["trace_1"])
    )
    assert data["dataset_id"] == "ds_1"


def test_admin_agent_experiment_create_starts_background(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _AdminMain())
    monkeypatch.setattr(
        agent_eval_store,
        "create_experiment",
        lambda *args, **kwargs: {"experiment_id": "exp_1", "status": "QUEUED"},
    )
    started = {}

    class _Thread:
        def __init__(self, target, args, daemon, name):
            started["target"] = target
            started["args"] = args

        def start(self):
            started["started"] = True

    monkeypatch.setattr(monitor.threading, "Thread", _Thread)
    data = monitor.admin_agent_experiment_create(monitor.AgentExperimentIn(dataset_id="ds_1"))
    assert data["experiment_id"] == "exp_1"
    assert started["started"] is True
    assert started["args"][0] == "exp_1"


def test_admin_agent_experiments_requires_system_admin(monkeypatch):
    monkeypatch.setattr(monitor, "_main", lambda: _RejectedMain())
    with pytest.raises(HTTPException) as exc:
        monitor.admin_agent_experiments()
    assert exc.value.status_code == 403
