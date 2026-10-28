"""Agent 租户绑定与请求幂等的基础安全测试。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from rag_demo.agent.context import dataset_scope
from rag_demo.agent.execution_store import InMemoryExecutionStore
from rag_demo.agent.service import (
    AgentRequestFailed,
    execute_agent,
    request_fingerprint,
)
from rag_demo.db.connection import current_dataset


def _result(request_id: str, execution_id: str = "exec_test") -> dict:
    return {
        "status": "COMPLETED",
        "final_answer": "ok",
        "request_id": request_id,
        "execution_id": execution_id,
        "parent_execution_id": None,
        "event_trace": [],
        "tool_calls": [],
    }


def test_dataset_scope_switches_and_restores():
    initial = current_dataset()
    with dataset_scope("test"):
        assert current_dataset() == "test"
    assert current_dataset() == initial


def test_execute_agent_runs_inside_dataset_scope():
    store = InMemoryExecutionStore()
    seen: list[str] = []

    def runner(query: str, **kwargs):
        seen.append(current_dataset())
        return _result(kwargs["request_id"])

    result, replay = execute_agent(
        query="统计用户数",
        dataset="test",
        account={"id": 101},
        request_id="req_tenant_001",
        store=store,
        runner=runner,
    )

    assert result["final_answer"] == "ok"
    assert replay is False
    assert seen == ["test"]
    # 执行结束后必须恢复默认上下文，不能把租户泄漏给下一个请求
    assert current_dataset() != "test"


def test_same_request_id_replays_without_rerun():
    store = InMemoryExecutionStore()
    calls: list[str] = []

    def runner(query: str, **kwargs):
        calls.append(kwargs["request_id"])
        return _result(kwargs["request_id"])

    first, first_replay = execute_agent(
        query="统计用户数",
        dataset="test",
        account={"id": 101},
        request_id="req_replay_001",
        store=store,
        runner=runner,
    )
    second, second_replay = execute_agent(
        query="统计用户数",
        dataset="test",
        account={"id": 101},
        request_id="req_replay_001",
        store=store,
        runner=runner,
    )

    assert first_replay is False
    assert second_replay is True
    assert calls == ["req_replay_001"]
    assert second == first


def test_same_request_id_with_different_query_is_rejected():
    store = InMemoryExecutionStore()
    execute_agent(
        query="统计用户数",
        dataset="test",
        account={"id": 101},
        request_id="req_conflict_001",
        store=store,
        runner=lambda query, **kwargs: _result(kwargs["request_id"]),
    )

    with pytest.raises(AgentRequestFailed, match="不同请求"):
        execute_agent(
            query="统计订单数",
            dataset="test",
            account={"id": 101},
            request_id="req_conflict_001",
            store=store,
            runner=lambda query, **kwargs: _result(kwargs["request_id"]),
        )


def test_failed_request_id_is_terminal():
    store = InMemoryExecutionStore()
    scope = "test:101"
    request_id = "req_failed_001"
    request_hash = request_fingerprint("统计用户数")
    assert store.claim(request_id, scope, request_hash).state == "claimed"
    store.fail(request_id, scope, "boom")

    with pytest.raises(AgentRequestFailed, match="boom"):
        execute_agent(
            query="统计用户数",
            dataset="test",
            account={"id": 101},
            request_id=request_id,
            store=store,
            runner=lambda query, **kwargs: _result(kwargs["request_id"]),
        )


def test_runner_exception_marks_request_failed_and_restores_context():
    store = InMemoryExecutionStore()
    initial = current_dataset()

    def broken_runner(query: str, **kwargs):
        raise RuntimeError("llm down")

    with pytest.raises(RuntimeError, match="llm down"):
        execute_agent(
            query="统计用户数",
            dataset="test",
            account={"id": 101},
            request_id="req_runner_fail_001",
            store=store,
            runner=broken_runner,
        )

    assert current_dataset() == initial
    claim = store.claim(
        "req_runner_fail_001",
        "test:101",
        request_fingerprint("统计用户数"),
    )
    assert claim.state == "failed"


def test_memory_claim_is_atomic_under_concurrency():
    store = InMemoryExecutionStore()
    request_hash = request_fingerprint("并发请求")

    def claim_one(_: int) -> str:
        return store.claim("req_concurrent", "test:101", request_hash).state

    with ThreadPoolExecutor(max_workers=8) as pool:
        states = list(pool.map(claim_one, range(8)))

    assert states.count("claimed") == 1
    assert states.count("in_progress") == 7
