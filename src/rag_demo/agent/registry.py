"""工具注册表：LangChain Tools + JSON Tool Contract 双入口。"""
from __future__ import annotations

from typing import Any, Iterable

from rag_demo.agent.tool import Tool
from rag_demo.agent.tools.action import prepare_followup_task
from rag_demo.agent.tools.calculator import _calculator_adapter, calculator
from rag_demo.agent.tools.rag import _rag_adapter, rag_search
from rag_demo.agent.tools.sql import _sql_adapter, execute_sql


def get_tools(allowed_tools: Iterable[str] | None = None) -> list[Any]:
    """返回绑定给 LangGraph chatbot 的 LangChain Tools（ToolNode 使用）。

    allowed_tools 非 None 时只暴露白名单内的 Tool；执行前的二次校验在 chatbot 节点。
    """
    tools = [rag_search, execute_sql, calculator, prepare_followup_task]
    if allowed_tools is None:
        return tools
    allowed = set(allowed_tools)
    return [tool for tool in tools if tool.name in allowed]


def get_tool_contracts() -> dict[str, Tool]:
    """返回与框架无关的 Tool Contract（JSON Schema + invoke），MCP 可直接复用。"""
    return {
        "rag_search": Tool(
            name=rag_search.name,
            description=rag_search.description,
            input_schema=rag_search.args_schema.model_json_schema(),
            fn=_rag_adapter,
        ),
        "execute_sql": Tool(
            name=execute_sql.name,
            description=execute_sql.description,
            input_schema=execute_sql.args_schema.model_json_schema(),
            fn=_sql_adapter,
        ),
        "calculator": Tool(
            name=calculator.name,
            description=calculator.description,
            input_schema=calculator.args_schema.model_json_schema(),
            fn=_calculator_adapter,
        ),
        "prepare_followup_task": Tool(
            name=prepare_followup_task.name,
            description=prepare_followup_task.description,
            input_schema=prepare_followup_task.args_schema.model_json_schema(),
            fn=lambda **kwargs: prepare_followup_task.invoke(kwargs),
        ),
    }


def get_tool_schemas() -> dict[str, dict[str, Any]]:
    """给前端/MCP/文档使用的 JSON Schema 清单。"""
    return {name: tool.input_schema for name, tool in get_tool_contracts().items()}


__all__ = ["get_tools", "get_tool_contracts", "get_tool_schemas"]
