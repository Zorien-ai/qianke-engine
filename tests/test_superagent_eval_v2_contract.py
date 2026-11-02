"""Super-agent Eval v2：场景契约与评分器测试（不调真实模型）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from superagent_eval_v2 import CASES, score_case  # noqa: E402


def _fake_result(case):
    if case.get("expect_filtered"):
        return {"status": "FILTERED", "answer": "", "action": {}, "executed": False}
    answer = " ".join(case.get("must_contain") or [])
    if case.get("safety") in {"human_approval", "no_direct_write"}:
        answer += " 需要人工审批，未执行"
    return {
        "status": (case.get("expected_status") or ["DONE"])[0],
        "answer": answer,
        "action": {"action_type": case["expected_action"]} if case.get("expected_action") else {},
        "executed": False,
    }


def test_eval_v2_has_20_plus_cases():
    assert len(CASES) >= 20
    assert len({case["id"] for case in CASES}) == len(CASES)


def test_eval_v2_scorer_all_scenarios():
    failures = []
    for case in CASES:
        score = score_case(case, _fake_result(case))
        if not score.get("passed"):
            failures.append((case["id"], score))
    assert not failures, failures


def test_eval_v2_hallucination_penalty():
    case = next(item for item in CASES if item["id"] == "missing_data")
    score = score_case(
        case,
        {"status": "DONE", "answer": "订单已签收于 2026-10-01，可以退款", "action": {}, "executed": False},
    )
    assert score["total"] < 0.8
