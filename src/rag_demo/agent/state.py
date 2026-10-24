"""Agent 状态定义。"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """LangGraph 对话状态。

    messages: LangGraph 的 add_messages reducer 负责追加/覆盖消息。
    step_count: 防止工具循环失控，最大 5 步。
    """

    messages: Annotated[list, add_messages]
    step_count: int
