# -*- coding: utf-8 -*-
"""Agent 架构、Tool Contract 与 LangGraph 路由单测（不调真实 LLM / 数据库）。"""
from langchain_core.messages import AIMessage

from rag_demo.agent import loop
from rag_demo.agent.registry import get_tool_contracts, get_tool_schemas, get_tools
from rag_demo.agent.state import AgentState
from rag_demo.agent.tool import ToolResult
from rag_demo.agent.tools.calculator import calculator
from rag_demo.agent.tools.rag import rag_search
from rag_demo.agent.tools.sql import execute_sql
from rag_demo.tools.sql_tool import _json_value
from decimal import Decimal


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
            "error": "SQL 校验失败：仅允许 SELECT/WITH",
        },
    )
    bad = execute_sql.invoke({"sql": "DELETE FROM user_profile_vectors"})
    assert bad["ok"] is False
    assert bad["error"]["code"] == "SQL_VALIDATION_ERROR"


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
    graph = loop.build_graph().get_graph()
    assert {"chatbot", "tools"} <= set(graph.nodes)
    assert any(e.source == "chatbot" and e.target == "tools" for e in graph.edges)
    assert any(e.source == "tools" and e.target == "chatbot" for e in graph.edges)
    assert AgentState.__annotations__["messages"]
    assert AgentState.__annotations__["step_count"]


def test_should_continue_routes_tool_calls_and_stops_at_max():
    tool_call = {"name": "calculator", "args": {"expression": "1+1"}, "id": "c1", "type": "tool_call"}
    state = {
        "messages": [AIMessage(content="", tool_calls=[tool_call])],
        "step_count": 1,
    }
    assert loop.should_continue(state) == "tools"

    state["step_count"] = loop.MAX_STEPS
    assert loop.should_continue(state) == "__end__"
