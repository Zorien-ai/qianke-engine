"""Phase C：数据集评测的纯判定边界。"""
from __future__ import annotations

from rag_demo.agent_eval_store import _score_case


def test_score_case_passes_completed_with_keywords_and_tools():
    case = {"expected_keywords": ["8110"], "expected_tools": ["execute_sql"]}
    result = {
        "status": "COMPLETED",
        "final_answer": "共 8110 名用户",
        "tool_calls": [{"name": "execute_sql", "args": {}}],
    }
    passed, score = _score_case(case, result)
    assert passed is True
    assert score == 1.0


def test_score_case_rejects_missing_keyword():
    case = {"expected_keywords": ["8110"], "expected_tools": []}
    result = {"status": "COMPLETED", "final_answer": "无法统计", "tool_calls": []}
    passed, score = _score_case(case, result)
    assert passed is False
    assert score == 0.0


def test_score_case_rejects_missing_expected_tool():
    case = {"expected_keywords": [], "expected_tools": ["execute_sql"]}
    result = {"status": "COMPLETED", "final_answer": "ok", "tool_calls": [{"name": "rag_search"}]}
    passed, score = _score_case(case, result)
    assert passed is False
    assert score == 0.0


def test_score_case_rejects_failed_status():
    case = {"expected_keywords": [], "expected_tools": []}
    result = {"status": "FAILED", "final_answer": "ok", "tool_calls": []}
    passed, score = _score_case(case, result)
    assert passed is False
    assert score == 0.0
