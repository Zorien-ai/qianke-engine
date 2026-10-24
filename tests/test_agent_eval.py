# -*- coding: utf-8 -*-
"""Agent Eval 纯指标与用例集合测试（不调真实 LLM / 数据库）。"""
from pathlib import Path

import pytest

from rag_demo.agent.eval.metrics import evaluate_case, summarize
from rag_demo.agent.eval.runner import DEFAULT_CASES, load_cases


def test_golden_set_has_20_cases_and_expected_distribution():
    cases = load_cases(DEFAULT_CASES)
    assert len(cases) == 20
    counts = {}
    for case in cases:
        counts[case["module"]] = counts.get(case["module"], 0) + 1
    assert counts == {
        "calculator": 5,
        "rag_search": 5,
        "execute_sql": 5,
        "collaboration": 5,
    }
    assert len({case["id"] for case in cases}) == 20


def test_case_pass_requires_tool_status_and_final_checks():
    case = {
        "id": "x",
        "module": "calculator",
        "question": "1+1",
        "expected": {
            "status": "COMPLETED",
            "required_tools": ["calculator"],
            "final_must_contain": ["2"],
        },
    }
    good = evaluate_case(case, {
        "status": "COMPLETED",
        "tool_calls": [{"name": "calculator", "args": {"expression": "1+1"}}],
        "final_answer": "结果是 2",
        "steps": 1,
        "tool_call_count": 1,
    })
    assert good["success"] is True
    assert good["tool_recall"] == 1.0

    no_tool = evaluate_case(case, {
        "status": "COMPLETED",
        "tool_calls": [],
        "final_answer": "结果是 2",
    })
    assert no_tool["success"] is False
    assert no_tool["missing_tools"] == ["calculator"]

    wrong_final = evaluate_case(case, {
        "status": "COMPLETED",
        "tool_calls": [{"name": "calculator"}],
        "final_answer": "不知道",
    })
    assert wrong_final["success"] is False


def test_summarize_groups_modules_and_rates():
    results = [
        {"module": "calculator", "success": True, "tool_recall": 1.0, "steps": 2, "tool_call_count": 1},
        {"module": "calculator", "success": False, "tool_recall": 0.0, "steps": 1, "tool_call_count": 0},
        {"module": "rag_search", "success": True, "tool_recall": 1.0, "steps": 2, "tool_call_count": 1},
    ]
    summary = summarize(results)
    assert summary["total"] == 3
    assert summary["passed"] == 2
    assert summary["pass_rate"] == pytest.approx(2 / 3)
    assert summary["modules"]["calculator"]["passed"] == 1
    assert summary["modules"]["calculator"]["pass_rate"] == 0.5
