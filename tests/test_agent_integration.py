# -*- coding: utf-8 -*-
"""真实 Agent 集成测试。

与单测不同：这里不 mock LLM、不 mock ToolNode，直接跑真实 DeepSeek + 本地 test 数据集。
没有 DEEPSEEK_API_KEY / 数据库时自动 skip，避免 CI 无凭证时误红。

本地执行：
    DEEPSEEK_API_KEY=... pytest -m integration tests/test_agent_integration.py -q
"""
from __future__ import annotations

import os

import pytest

from rag_demo.agent.loop import run_agent
from rag_demo.agent.state import AgentConfig, AgentStatus

pytestmark = pytest.mark.integration


def _require_real_env():
    if not os.getenv("DEEPSEEK_API_KEY"):
        pytest.skip("缺少 DEEPSEEK_API_KEY，跳过真实 Agent 集成测试")
    try:
        from rag_demo.db.connection import get_conn, use_dataset

        use_dataset("test")
        conn = get_conn()
        conn.rollback()
    except Exception as exc:  # noqa: BLE001 - 数据库不可用就 skip
        pytest.skip(f"本地 test 数据库不可用，跳过集成测试：{type(exc).__name__}: {exc}")


@pytest.mark.integration
def test_real_agent_runs_sql_and_calculator_end_to_end():
    """真实模型 + 真实 LangGraph + 真实 SQL/RAG/Calculator 工具。"""
    _require_real_env()

    result = run_agent(
        "查上海黑卡流失用户数量并计算占比",
        config=AgentConfig(max_steps=6, max_tool_calls=12, timeout_seconds=180),
    )

    assert result["status"] == AgentStatus.COMPLETED.value, result
    names = [call["name"] for call in result["tool_calls"]]
    assert "execute_sql" in names, names
    assert "calculator" in names, names
    assert result["final_answer"]
    assert "上海" in result["final_answer"]
