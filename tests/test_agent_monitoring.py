"""本地 LangSmith 中台：execute_agent 的监控埋点边界。"""
from __future__ import annotations

import pytest

from rag_demo import ai_monitor
from rag_demo.agent.execution_store import InMemoryExecutionStore
from rag_demo.agent.service import execute_agent


def _result(request_id: str) -> dict:
    return {
        "status": "COMPLETED",
        "final_answer": "ok",
        "request_id": request_id,
        "execution_id": "exec_monitor_test",
        "event_trace": [{"event": "run_started", "timestamp": 1.0}],
        "tool_calls": [{"name": "execute_sql"}],
        "steps": 2,
        "tool_call_count": 1,
        "total_tokens": 12,
    }


def test_execute_agent_records_local_monitor_trace(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(
        ai_monitor,
        "begin_trace",
        lambda entrypoint, account=None: (
            calls.setdefault("begin", (entrypoint, account)) and "trace_monitor_test"
        ),
    )
    monkeypatch.setattr(
        ai_monitor,
        "record_trace_usage",
        lambda trace_id, **kwargs: calls.setdefault("usage", (trace_id, kwargs)),
    )
    monkeypatch.setattr(
        ai_monitor,
        "finish_trace",
        lambda **kwargs: calls.setdefault("finish", kwargs),
    )

    def runner(query: str, **kwargs):
        return _result(kwargs["request_id"])

    result, replay = execute_agent(
        query="统计用户数",
        dataset="test",
        account={"id": 101, "username": "monitor_test"},
        request_id="req_monitor_001",
        store=InMemoryExecutionStore(),
        runner=runner,
    )

    assert replay is False
    assert result["final_answer"] == "ok"
    assert calls["begin"][0] == "agent.execute"
    trace_id, usage = calls["usage"]
    assert trace_id == "trace_monitor_test"
    assert usage["total_tokens"] == 12
    finished = calls["finish"]
    assert finished["status"] == "success"
    assert finished["meta"]["question"] == "统计用户数"
    assert finished["meta"]["request_id"] == "req_monitor_001"
    assert finished["meta"]["execution_id"] == "exec_monitor_test"
    assert finished["meta"]["agent_events"][0]["event"] == "run_started"


def test_execute_agent_records_failed_trace(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(
        ai_monitor,
        "begin_trace",
        lambda entrypoint, account=None: "trace_failed_test",
    )
    monkeypatch.setattr(
        ai_monitor,
        "record_trace_usage",
        lambda trace_id, **kwargs: None,
    )
    monkeypatch.setattr(
        ai_monitor,
        "finish_trace",
        lambda **kwargs: calls.setdefault("finish", kwargs),
    )

    def runner(query: str, **kwargs):
        raise RuntimeError("llm unavailable")

    with pytest.raises(RuntimeError, match="llm unavailable"):
        execute_agent(
            query="统计用户数",
            dataset="test",
            account={"id": 101},
            request_id="req_monitor_failed",
            store=InMemoryExecutionStore(),
            runner=runner,
        )

    assert calls["finish"]["status"] == "error"
    assert "llm unavailable" in calls["finish"]["meta"]["error"]
