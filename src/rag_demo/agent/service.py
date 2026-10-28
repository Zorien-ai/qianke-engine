"""Agent 请求执行服务：租户上下文 + 请求幂等 + Runtime 调用。"""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Callable

from rag_demo.agent.context import dataset_scope
from rag_demo.agent.execution_store import ClaimResult, ExecutionStore, get_execution_store
from rag_demo.agent.loop import run_agent_with_retry

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def request_fingerprint(query: str, parent_execution_id: str | None = None) -> str:
    payload = f"{query.strip()}\n{parent_execution_id or ''}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class AgentRequestInProgress(RuntimeError):
    def __init__(self, execution_id: str | None = None) -> None:
        super().__init__("同一个 request_id 正在执行中，请勿重复提交")
        self.execution_id = execution_id


class AgentRequestFailed(RuntimeError):
    pass


def normalize_request_id(value: str | None) -> str:
    if value is None:
        return f"req_{uuid.uuid4().hex[:16]}"
    value = value.strip()
    if not value:
        return f"req_{uuid.uuid4().hex[:16]}"
    if not _REQUEST_ID_RE.fullmatch(value):
        raise ValueError("request_id 只允许 1-128 位字母、数字、下划线或短横线")
    return value


def agent_scope(dataset: str, account: dict[str, Any] | None) -> str:
    """幂等作用域：同一数据集 + 同一账号才共享 request_id。"""
    principal = account.get("id") if account else "offline"
    return f"{dataset}:{principal}"


def execute_agent(
    *,
    query: str,
    dataset: str,
    request_id: str | None,
    parent_execution_id: str | None = None,
    account: dict[str, Any] | None = None,
    store: ExecutionStore | None = None,
    runner: Callable[..., dict[str, Any]] | None = None,
    runner_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """执行一次 Agent 请求。

    Returns:
        (result, idempotent_replay)
    """
    request_id = normalize_request_id(request_id)
    scope = agent_scope(dataset, account)
    fingerprint = request_fingerprint(query, parent_execution_id)
    store = store or get_execution_store()
    runner = runner or run_agent_with_retry
    runner_kwargs = dict(runner_kwargs or {})

    claim: ClaimResult = store.claim(request_id, scope, fingerprint)
    if claim.state == "completed":
        if claim.response is None:
            raise AgentRequestFailed("已完成记录缺少响应")
        return claim.response, True
    if claim.state == "conflict":
        raise AgentRequestFailed("同一个 request_id 已用于不同请求，请更换 request_id")
    if claim.state == "in_progress":
        raise AgentRequestInProgress(claim.execution_id)
    if claim.state == "failed":
        raise AgentRequestFailed(claim.error or "该 request_id 已执行失败，请更换 request_id 重试")

    try:
        with dataset_scope(dataset):
            result = runner(
                query,
                request_id=request_id,
                parent_execution_id=parent_execution_id,
                **runner_kwargs,
            )
    except Exception as exc:
        store.fail(request_id, scope, f"{type(exc).__name__}: {exc}")
        raise

    if not isinstance(result, dict):
        store.fail(request_id, scope, "Agent 返回结果不是 dict")
        raise RuntimeError("Agent 返回结果格式错误")
    execution_id = str(result.get("execution_id") or "")
    store.complete(request_id, scope, execution_id, result)
    return result, False
