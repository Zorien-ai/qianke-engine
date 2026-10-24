# -*- coding: utf-8 -*-
"""Agent 架构、Tool Contract 与 LangGraph 路由单测（不调真实 LLM / 数据库）。"""
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage

from rag_demo.agent import loop
from rag_demo.agent.registry import get_tool_contracts, get_tool_schemas, get_tools
from rag_demo.agent.state import AgentConfig, AgentState, AgentStatus
from rag_demo.agent.tool import ToolResult
from rag_demo.agent.tools.calculator import calculator
from rag_demo.agent.tools.rag import rag_search
from rag_demo.agent.tools.sql import execute_sql
from rag_demo.tools.sql_tool import _json_value


def test_tool_result_contract():
    success = ToolResult.success(expression="1+1", result=2).dump()
    assert success["ok"] is True
    assert success["data"]["result"] == 2
    assert success["expression"] == "1+1"

    failure = ToolResult.failure("DIVISION_BY_ZERO", "division by zero").dump()
    assert failure["ok"] is False
    assert failure["error"] == {"code": "DIVISION_BY_ZERO", "message": "division by zero"}


def test_registry_exposes_tools_and_json_schemas():
    assert [t.name for t in get_tools()] == ["rag_search", "execute_sql", "calculator"]
    schemas = get_tool_schemas()
    assert set(schemas) == {"rag_search", "execute_sql", "calculator"}
    assert schemas["calculator"]["properties"]["expression"]["type"] == "string"
    assert schemas["rag_search"]["properties"]["top_k"]["default"] == 5
    assert schemas["execute_sql"]["properties"]["sql"]["type"] == "string"
    assert set(get_tool_contracts()) == {"rag_search", "execute_sql", "calculator"}


def test_tool_contract_invoke_accepts_json_arguments():
    contracts = get_tool_contracts()
    result = contracts["calculator"].invoke({"expression": "10/4"})
    assert result["ok"] is True
    assert result["result"] == 2.5

    bad = contracts["calculator"].invoke({"unknown": 1})
    assert bad["ok"] is False
    assert bad["error"]["code"] == "INVALID_ARGUMENTS"


def test_calculator_json_contract_and_safe_ast():
    result = calculator.invoke({"expression": "(156000 - 128000) / 128000 * 100"})
    assert result["ok"] is True
    assert result["result"] == 21.875
    assert result["data"]["result"] == 21.875

    bad = calculator.invoke({"expression": "__import__('os').getcwd()"})
    assert bad["ok"] is False
    assert bad["error"]["code"] == "INVALID_EXPRESSION"

    div0 = calculator.invoke({"expression": "1/0"})
    assert div0["ok"] is False
    assert div0["error"]["code"] == "DIVISION_BY_ZERO"


def test_sql_contract_success_and_error(monkeypatch):
    from rag_demo.tools import sql_tool

    monkeypatch.setattr(
        sql_tool,
        "execute_sql_dict",
        lambda sql: {
            "sql": sql,
            "columns": ["count"],
            "rows": [{"count": 128}],
            "row_count": 1,
            "error": None,
        },
    )
    result = execute_sql.invoke({"sql": "SELECT COUNT(*) AS count FROM user_profile_vectors LIMIT 1"})
    assert result["ok"] is True
    assert result["columns"] == ["count"]
    assert result["rows"] == [{"count": 128}]
    assert result["row_count"] == 1

    # psycopg2 的 Decimal 必须转成 JSON number，不能把 Decimal repr 传给 LLM
    assert _json_value(Decimal("1159.50")) == 1159.5

    monkeypatch.setattr(
        sql_tool,
        "execute_sql_dict",
        lambda sql: {
            "sql": sql,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": {
                "code": "SQL_VALIDATION_ERROR",
                "message": "SQL 校验失败：仅允许 SELECT/WITH",
            },
        },
    )
    bad = execute_sql.invoke({"sql": "DELETE FROM user_profile_vectors"})
    assert bad["ok"] is False
    assert bad["error"]["code"] == "SQL_VALIDATION_ERROR"


def test_sql_bottom_returns_structured_error_without_string_matching():
    from rag_demo.tools.sql_tool import execute_sql_dict

    result = execute_sql_dict("DELETE FROM user_profile_vectors")
    assert result["error"] == {
        "code": "SQL_VALIDATION_ERROR",
        "message": "SQL 校验失败：仅允许 SELECT/WITH、必须带 LIMIT、仅白名单表",
    }


def test_rag_contract_has_results_and_no_final_answer(monkeypatch):
    import rag_demo.retrieval.hybrid_retriever as hybrid

    monkeypatch.setattr(
        hybrid,
        "hybrid_search",
        lambda query, top_k=5: [
            {"id": "doc-1", "text": "黑卡会员定义", "score": 0.91, "source": "运营SOP.md"},
        ],
    )
    result = rag_search.invoke({"query": "黑卡会员定义", "top_k": 3})
    assert result["ok"] is True
    assert result["query"] == "黑卡会员定义"
    assert result["results"][0] == {
        "content": "黑卡会员定义",
        "score": 0.91,
        "source": "运营SOP.md",
    }
    assert "answer" not in result


def test_state_contract_and_graph_shape():
    graph = loop.build_graph(AgentConfig(max_steps=3)).get_graph()
    assert {"chatbot", "tools"} <= set(graph.nodes)
    assert any(e.source == "chatbot" and e.target == "tools" for e in graph.edges)
    assert any(e.source == "tools" and e.target == "chatbot" for e in graph.edges)
    assert AgentState.__annotations__["messages"]
    assert AgentState.__annotations__["step_count"]
    assert AgentState.__annotations__["status"]
    assert AgentState.__annotations__["tool_call_count"]


def test_agent_config_validation():
    with pytest.raises(ValueError, match="max_steps"):
        AgentConfig(max_steps=0)
    with pytest.raises(ValueError, match="max_tool_calls"):
        AgentConfig(max_tool_calls=0)
    with pytest.raises(ValueError, match="timeout_seconds"):
        AgentConfig(timeout_seconds=0)


def test_should_continue_routes_tool_calls_and_stops_on_terminal():
    tool_call = {"name": "calculator", "args": {"expression": "1+1"}, "id": "c1", "type": "tool_call"}
    state = {
        "messages": [AIMessage(content="", tool_calls=[tool_call])],
        "status": AgentStatus.RUNNING.value,
    }
    assert loop.should_continue(state) == "tools"

    state["status"] = AgentStatus.MAX_STEPS_EXCEEDED.value
    assert loop.should_continue(state) == "__end__"


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return self._responses.pop(0)


def _tool_call_message():
    return AIMessage(content="", tool_calls=[{
        "name": "calculator",
        "args": {"expression": "2+3"},
        "id": "call_1",
        "type": "tool_call",
    }])


def test_run_agent_uses_config_and_completes(monkeypatch):
    fake = _FakeLLM([_tool_call_message(), AIMessage(content="结果是 5")])
    monkeypatch.setattr(loop, "get_llm", lambda: fake)
    monkeypatch.setattr(loop, "build_system_prompt", lambda: "sys")

    result = loop.run_agent("2+3 等于多少？", config=AgentConfig(max_steps=4))

    assert result["status"] == AgentStatus.COMPLETED.value
    assert result["final_answer"] == "结果是 5"
    assert result["steps"] == 2
    assert result["tool_call_count"] == 1
    assert fake.calls == 2


def test_run_agent_max_steps_is_configurable(monkeypatch):
    fake = _FakeLLM([_tool_call_message(), _tool_call_message(), _tool_call_message()])
    monkeypatch.setattr(loop, "get_llm", lambda: fake)
    monkeypatch.setattr(loop, "build_system_prompt", lambda: "sys")

    result = loop.run_agent("一直算", config=AgentConfig(max_steps=1))

    assert result["status"] == AgentStatus.MAX_STEPS_EXCEEDED.value
    assert "最大推理步数" in result["final_answer"]
    assert fake.calls == 1


def test_run_agent_max_tool_calls_status(monkeypatch):
    fake = _FakeLLM([_tool_call_message(), _tool_call_message()])
    monkeypatch.setattr(loop, "get_llm", lambda: fake)
    monkeypatch.setattr(loop, "build_system_prompt", lambda: "sys")

    result = loop.run_agent("一直算", config=AgentConfig(max_steps=5, max_tool_calls=1))

    assert result["status"] == AgentStatus.MAX_TOOL_CALLS_EXCEEDED.value
    assert "最大工具调用次数" in result["final_answer"]
    assert fake.calls == 1
