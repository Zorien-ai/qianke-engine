"""Agent Eval 指标：只做确定性判定，不引入 LLM Judge。

一条 case 的通过条件：
  status 正确
  AND required_tools 全部命中
  AND 最终回答包含所有 final_must_contain
  AND 最终回答不包含任何 final_must_not_contain
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def evaluate_case(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """对一条 Agent 运行结果做确定性评分。"""
    expected = case.get("expected") or {}
    required = set(_as_list(expected.get("required_tools")))
    forbidden = set(_as_list(expected.get("forbidden_tools")))
    must_contain = _as_list(expected.get("final_must_contain"))
    must_not_contain = _as_list(expected.get("final_must_not_contain"))

    actual_tools = [
        str(call.get("name"))
        for call in (result.get("tool_calls") or [])
        if call.get("name")
    ]
    actual_set = set(actual_tools)
    missing_tools = sorted(required - actual_set)
    forbidden_hit = sorted(forbidden & actual_set)

    final = str(result.get("final_answer") or "")
    matched_required = [text for text in must_contain if text in final]
    missing_required = [text for text in must_contain if text not in final]
    hit_forbidden = [text for text in must_not_contain if text in final]

    status_ok = result.get("status") == expected.get("status", "COMPLETED")
    tool_ok = not missing_tools and not forbidden_hit
    final_ok = not missing_required and not hit_forbidden
    success = bool(status_ok and tool_ok and final_ok)

    tool_recall = len(required & actual_set) / len(required) if required else 1.0
    return {
        "id": case.get("id"),
        "module": case.get("module"),
        "question": case.get("question"),
        "success": success,
        "status": result.get("status"),
        "status_ok": status_ok,
        "tool_ok": tool_ok,
        "final_ok": final_ok,
        "required_tools": sorted(required),
        "actual_tools": actual_tools,
        "missing_tools": missing_tools,
        "forbidden_hit": forbidden_hit,
        "tool_recall": tool_recall,
        "must_contain": must_contain,
        "missing_required_text": missing_required,
        "hit_forbidden_text": hit_forbidden,
        "steps": result.get("steps"),
        "tool_call_count": result.get("tool_call_count"),
        "final_answer": final,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """汇总通过率、工具命中和效率。"""
    total = len(results)
    passed = sum(1 for r in results if r.get("success"))
    modules: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0})
    for result in results:
        row = modules[str(result.get("module") or "未分类")]
        row["total"] += 1
        row["passed"] += int(bool(result.get("success")))

    tool_calls = [r.get("tool_call_count") for r in results if isinstance(r.get("tool_call_count"), int)]
    steps = [r.get("steps") for r in results if isinstance(r.get("steps"), int)]
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / total if total else 0.0,
        "tool_recall_avg": (
            sum(r.get("tool_recall", 0.0) for r in results) / total if total else 0.0
        ),
        "avg_tool_calls": sum(tool_calls) / len(tool_calls) if tool_calls else 0.0,
        "avg_steps": sum(steps) / len(steps) if steps else 0.0,
        "modules": {
            name: {
                **row,
                "pass_rate": row["passed"] / row["total"] if row["total"] else 0.0,
            }
            for name, row in modules.items()
        },
    }
