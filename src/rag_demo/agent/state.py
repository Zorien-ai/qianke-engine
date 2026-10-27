"""Agent 状态与运行时配置。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentStatus(str, Enum):
    """Agent 执行状态，供 retry / trace / budget / UI 统一消费。"""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    MAX_STEPS_EXCEEDED = "MAX_STEPS_EXCEEDED"
    MAX_TOOL_CALLS_EXCEEDED = "MAX_TOOL_CALLS_EXCEEDED"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class AgentConfig:
    """真正的 Runtime Config，不再是装饰性参数。"""

    max_steps: int = 5
    max_tool_calls: int = 10
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps 必须 >= 1")
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls 必须 >= 1")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须 > 0")


class AgentState(TypedDict, total=False):
    """LangGraph 对话状态。

    messages: add_messages reducer 负责追加消息。
    step_count / tool_call_count: 步数与工具调用预算。
    status/error: 明确区分 COMPLETED / MAX_STEPS_EXCEEDED / TIMEOUT 等终态。
    """

    messages: Annotated[list, add_messages]
    step_count: int
    tool_call_count: int
    status: str
    error: str | None
    started_at: float
    request_id: str
    execution_id: str
    parent_execution_id: str | None
