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
    payload = json.loads((AGENT_EVAL_DIR / "regression" / "dataset.v1.json").read_text(encoding="utf-8"))
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


def test_benchmark_has_40_tasks_and_expected_distribution():
    payload = json.loads((AGENT_EVAL_DIR / "benchmark" / "dataset.v1.json").read_text(encoding="utf-8"))
    tasks = payload["tasks"]
    assert payload["dataset"] == "demo"
    assert len(tasks) == 40
    counts = {}
    for task in tasks:
        counts[task["category"]] = counts.get(task["category"], 0) + 1
    assert counts == {
        "execute_sql": 10,
        "rag_search": 8,
        "multi_tool": 12,
        "negative": 6,
        "calculator": 4,
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


def test_negative_case_supports_any_refusal_and_number_guard():
    task = {
        "task_id": "neg-x",
        "category": "negative",
        "question": "统计没有的数据",
        "expected_tools": [],
        "expected_keywords_any": ["无法", "没有", "不存在"],
        "must_not_contain_numbers": True,
        "allowed_numbers": ["90"],
        "expected_success": True,
    }
    safe = {
        "status": "COMPLETED",
        "tool_calls": [],
        "messages": [],
        "final_answer": "当前数据没有对应字段，无法给出具体人数，需补充数据。",
    }
    bad = {
        "status": "COMPLETED",
        "tool_calls": [],
        "messages": [],
        "final_answer": "无法精确统计，但按活跃用户推算约 430 人。",
    }
    safe_scored = evaluator.evaluate_task(task, safe)
    bad_scored = evaluator.evaluate_task(task, bad)
    assert safe_scored["task_success"] is True
    assert bad_scored["task_success"] is False
    assert "430" in bad_scored["disallowed_numbers"]


def test_negative_semantic_guard_allows_facts_but_rejects_approx_results():
    task = {
        "task_id": "neg-y",
        "category": "negative",
        "question": "统计触达人数",
        "expected_tools": [],
        "expected_keywords_any": ["无法", "没有", "不存在"],
        "must_not_contain_numbers": True,
        "allowed_numbers": ["8110", "36"],
        "must_not_contain_approx_numbers": True,
        "expected_success": True,
    }
    fact = {
        "status": "COMPLETED",
        "tool_calls": [],
        "messages": [],
        "final_answer": "数据只有 8110 条画像、36 个知识块，没有触达字段，无法统计。",
    }
    fabricated = {
        "status": "COMPLETED",
        "tool_calls": [],
        "messages": [],
        "final_answer": "无法精确统计，估算触达约 36 人。",
    }
    fact_scored = evaluator.evaluate_task(task, fact)
    fabricated_scored = evaluator.evaluate_task(task, fabricated)
    assert fact_scored["task_success"] is True
    assert fabricated_scored["task_success"] is False
    assert "36" in fabricated_scored["approx_numbers"]


def test_negative_result_unit_guard_catches_clear_fabrication():
    task = {
        "task_id": "neg-z",
        "category": "negative",
        "question": "统计触达人数",
        "expected_tools": [],
        "expected_keywords_any": ["无法", "没有", "不存在"],
        "must_not_contain_numbers": True,
        "allowed_numbers": ["8110", "36"],
        "must_not_contain_approx_numbers": True,
        "forbidden_result_units": ["人"],
        "expected_success": True,
    }
    fact = {
        "status": "COMPLETED",
        "tool_calls": [],
        "messages": [],
        "final_answer": "数据只有 8110 位用户的画像，没有触达字段，无法统计。",
    }
    clear_fake = {
        "status": "COMPLETED",
        "tool_calls": [],
        "messages": [],
        "final_answer": "没有触达记录，但触达 8110 人。",
    }
    forecast = {
        "status": "COMPLETED",
        "tool_calls": [],
        "messages": [],
        "final_answer": "无法预测，预计仍为 403 人左右。",
    }
    assert evaluator.evaluate_task(task, fact)["task_success"] is True
    assert evaluator.evaluate_task(task, clear_fake)["task_success"] is False
    assert evaluator.evaluate_task(task, forecast)["task_success"] is False


def test_business_correctness_separates_tool_policy_and_observed_facts():
    task = {
        "task_id": "neg-fact",
        "category": "negative",
        "question": "预测未来人数",
        "expected_tools": [],
        "expected_keywords_any": ["无法", "没有", "不存在"],
        "must_not_contain_approx_numbers": True,
        "forbidden_result_units": ["人"],
        "expected_success": True,
    }
    result = {
        "status": "COMPLETED",
        "tool_calls": [{"name": "execute_sql"}],
        "messages": [],
        "final_answer": "无法预测 2026 年 11 月数量；当前钻石会员为 403 人，仅作事实引用。",
    }
    scored = evaluator.evaluate_task(task, result)
    # 事实引用不再被旧口径误杀；工具策略仍独立判断
    assert scored["task_success"] is True
    assert scored["business_correctness"] is True
    assert scored["tool_policy_compliance"] is True
    assert "403" in scored["observed_fact_numbers"]


def test_business_correctness_can_pass_without_calculator_when_answer_is_right():
    task = {
        "task_id": "multi-ratio",
        "category": "multi_tool",
        "question": "计算占比",
        "expected_tools": ["execute_sql", "calculator"],
        "expected_keywords": ["29.38"],
        "expected_success": True,
    }
    result = {
        "status": "COMPLETED",
        "tool_calls": [{"name": "execute_sql"}],
        "messages": [],
        "final_answer": "沉默客 2383 人，占 29.38%",
    }
    scored = evaluator.evaluate_task(task, result)
    assert scored["task_success"] is False
    assert scored["business_correctness"] is True
    assert scored["tool_policy_compliance"] is False
