# -*- coding: utf-8 -*-
"""Agent Eval evaluator 单测：不调真实模型。"""
import json
import sys
from pathlib import Path

from langchain_core.messages import ToolMessage

AGENT_EVAL_DIR = Path(__file__).parent / "evals" / "agent"
if str(AGENT_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_EVAL_DIR))

import evaluator  # noqa: E402


def test_dataset_uses_demo_and_has_20_tasks():
    payload = json.loads((AGENT_EVAL_DIR / "dataset.json").read_text(encoding="utf-8"))
    assert payload["dataset"] == "demo"
    assert len(payload["tasks"]) == 20
    counts = {}
    for task in payload["tasks"]:
        counts[task["category"]] = counts.get(task["category"], 0) + 1
    assert counts == {
        "calculator": 5,
        "execute_sql": 5,
        "rag_search": 5,
        "multi_tool": 5,
    }


def _tool_message(name: str, ok: bool, error=None):
    payload = {"ok": ok}
    if error:
        payload["error"] = error
    return ToolMessage(content=json.dumps(payload), name=name, tool_call_id="c1")


def test_evaluate_task_success_and_tool_metrics():
    task = {
        "task_id": "t1",
        "category": "multi_tool",
        "question": "q",
        "expected_tools": ["execute_sql", "calculator"],
        "expected_keywords": ["100"],
        "expected_success": True,
    }
    result = {
        "status": "COMPLETED",
        "tool_calls": [
            {"name": "execute_sql", "args": {}},
            {"name": "calculator", "args": {}},
        ],
        "messages": [
            _tool_message("execute_sql", True),
            _tool_message("calculator", True),
        ],
        "final_answer": "占比 100%",
        "steps": 3,
        "tool_call_count": 2,
    }
    scored = evaluator.evaluate_task(task, result)
    assert scored["task_success"] is True
    assert scored["tool_selection_ok"] is True
    assert scored["tool_execution_ok"] == 1.0
    assert scored["final_ok"] is True


def test_evaluate_task_fails_when_required_tool_missing():
    task = {
        "task_id": "t2",
        "category": "sql",
        "question": "q",
        "expected_tools": ["execute_sql"],
        "expected_keywords": ["3"],
        "expected_success": True,
    }
    result = {
        "status": "COMPLETED",
        "tool_calls": [],
        "messages": [],
        "final_answer": "3",
    }
    scored = evaluator.evaluate_task(task, result)
    assert scored["task_success"] is False
    assert scored["missing_tools"] == ["execute_sql"]


def test_error_recovery_only_counts_error_cases():
    task = {
        "task_id": "t3",
        "category": "sql",
        "question": "q",
        "expected_tools": ["execute_sql"],
        "expected_keywords": ["3"],
        "expected_success": True,
    }
    result = {
        "status": "COMPLETED",
        "tool_calls": [{"name": "execute_sql"}, {"name": "execute_sql"}],
        "messages": [
            _tool_message("execute_sql", False, {"code": "SQL_EXECUTION_ERROR"}),
            _tool_message("execute_sql", True),
        ],
        "final_answer": "3",
        "steps": 3,
        "tool_call_count": 2,
    }
    scored = evaluator.evaluate_task(task, result)
    assert scored["error_recovered"] is True
    summary = evaluator.summarize([scored])
    assert summary["error_recovery"] == 1.0
    assert summary["error_cases"] == 1
