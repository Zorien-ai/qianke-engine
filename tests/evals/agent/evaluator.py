"""Agent Eval evaluator：真实 Agent 轨迹 -> Task / Tool / Recovery 指标。"""
from __future__ import annotations

import json
import os
import re
from typing import Any

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_APPROX_RE = re.compile(
    r"(?:约|大约|预计|预测|估算|估计|推算|大概|接近|左右|约为)"
    r"\s*[^。！？\n]{0,8}?(\d+(?:\.\d+)?)\s*"
    r"(?:人|位|名|%|元|万元|天|倍|次|笔|单|个)"
)
_RESULT_CLAIM_RE = re.compile(
    r"(?:触达|退货率|预测|预计|估算|推算|数量|人数|约为|为)"
    r"\s*[^。！？\n]{0,8}?(\d+(?:\.\d+)?)\s*"
    r"(人|位|名|%|元|万元|天|倍|次|笔|单|个)"
)
_OBSERVED_FACT_RE = re.compile(
    r"(?:当前|目前|现有|快照|截止|已有|全库|总计)"
    r"[^。！？\n]{0,20}?(\d+(?:\.\d+)?)\s*"
    r"(?:人|位|名|%|元|万元|天|倍|次|笔|单|个)"
)


def _observed_fact_numbers(text: str) -> list[str]:
    """事实引用：如“当前钻石会员为 403 人”。"""
    return _OBSERVED_FACT_RE.findall(text or "")


def _numbers(text: str) -> list[str]:
    return _NUMBER_RE.findall(text or "")


def _approximate_numbers(text: str) -> list[str]:
    return _APPROX_RE.findall(text or "")


def _result_claim_numbers(text: str, units: list[str]) -> list[str]:
    wanted = set(units)
    return [
        number
        for number, unit in _RESULT_CLAIM_RE.findall(text or "")
        if unit in wanted
    ]


def _allowed_number(token: str, allowed: list[str]) -> bool:
    """允许 90 命中 90.0 这类格式差异。"""
    if token in allowed:
        return True
    try:
        return any(float(token) == float(item) for item in allowed)
    except (TypeError, ValueError):
        return False


def _json_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def tool_observations(messages: list[Any]) -> list[dict[str, Any]]:
    """从 LangGraph 消息里提取每次工具结果是否成功。"""
    observations: list[dict[str, Any]] = []
    for message in messages or []:
        if getattr(message, "type", "") != "tool":
            continue
        payload = _json_content(getattr(message, "content", None))
        observations.append({
            "name": getattr(message, "name", None) or payload.get("name") or "unknown",
            "ok": bool(payload.get("ok")),
            "error": payload.get("error"),
        })
    return observations


def token_usage(messages: list[Any]) -> dict[str, int | bool]:
    """汇总 LangChain 消息中的 token usage（优先 usage_metadata）。"""
    input_tokens = 0
    output_tokens = 0
    found = False
    for message in messages or []:
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            meta = getattr(message, "response_metadata", None) or {}
            usage = meta.get("token_usage") if isinstance(meta, dict) else None
        if not isinstance(usage, dict):
            continue
        input_tokens += int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        found = True
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "token_usage_found": found,
    }


def estimate_cost(input_tokens: int, output_tokens: int) -> float | None:
    """按可配置单价估算成本；未配置时返回 None，不写死厂商价格。"""
    def _rate(name: str) -> float:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return 0.0
        try:
            return float(raw)
        except ValueError:
            return 0.0

    input_rate = _rate("EVAL_INPUT_COST_PER_1M")
    output_rate = _rate("EVAL_OUTPUT_COST_PER_1M")
    if input_rate == 0.0 and output_rate == 0.0:
        return None
    return round(
        input_tokens / 1_000_000 * input_rate
        + output_tokens / 1_000_000 * output_rate,
        6,
    )


def _keyword_text(text: str) -> str:
    """关键词比较前去掉数字千分位逗号，避免 14555 与 14,555 误判。"""
    return text.replace(",", "").replace("，", "")


def evaluate_task(task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """评价单个任务。"""
    expected = [str(x) for x in (task.get("expected_tools") or [])]
    expected_set = set(expected)
    required = task.get("required_tools")
    required = [str(x) for x in required] if required is not None else list(expected)
    optional = [str(x) for x in (task.get("optional_tools") or [])]
    forbidden = [str(x) for x in (task.get("forbidden_tools") or [])]
    required_set = set(required)
    forbidden_set = set(forbidden)
    actual_calls = [
        str(call.get("name"))
        for call in (result.get("tool_calls") or [])
        if call.get("name")
    ]
    actual_set = set(actual_calls)
    missing_tools = sorted(expected_set - actual_set)
    missing_required_tools = sorted(required_set - actual_set)
    forbidden_tools_hit = sorted(forbidden_set & actual_set)
    tool_selection_ok = not missing_tools
    tool_policy_ok = not missing_required_tools and not forbidden_tools_hit
    tool_recall = len(expected_set & actual_set) / len(expected_set) if expected_set else 1.0

    final = str(result.get("final_answer") or "")
    final_keyword_text = _keyword_text(final)
    keywords = [str(x) for x in (task.get("expected_keywords") or [])]
    missing_keywords = [
        word for word in keywords if _keyword_text(word) not in final_keyword_text
    ]
    keywords_any = [str(x) for x in (task.get("expected_keywords_any") or [])]
    hit_any = [word for word in keywords_any if _keyword_text(word) in final_keyword_text]
    missing_any = [] if not keywords_any or hit_any else keywords_any
    disallowed_numbers: list[str] = []
    if task.get("must_not_contain_numbers"):
        allowed_numbers = [str(x) for x in (task.get("allowed_numbers") or [])]
        disallowed_numbers = [
            token for token in _numbers(final) if not _allowed_number(token, allowed_numbers)
        ]
    approx_numbers: list[str] = []
    if task.get("must_not_contain_approx_numbers"):
        # 语义护栏：允许引用事实数字，但禁止“约/预计/估算 + 数字”的结果型表达。
        approx_numbers = _approximate_numbers(final)
        for token in approx_numbers:
            if token not in disallowed_numbers:
                disallowed_numbers.append(token)

    result_claim_numbers: list[str] = []
    forbidden_units = [str(x) for x in (task.get("forbidden_result_units") or [])]
    if forbidden_units:
        result_claim_numbers = _result_claim_numbers(final, forbidden_units)
        for token in result_claim_numbers:
            if token not in disallowed_numbers:
                disallowed_numbers.append(token)

    observed_fact_numbers = _observed_fact_numbers(final)
    for token in (task.get("observed_fact_numbers") or []):
        token = str(token)
        if token not in observed_fact_numbers:
            observed_fact_numbers.append(token)
    fact_aware_disallowed = [
        token for token in disallowed_numbers
        if token not in observed_fact_numbers
    ]
    final_ok = not missing_keywords and not missing_any and not fact_aware_disallowed
    business_disallowed = fact_aware_disallowed
    business_final_ok = not missing_keywords and not missing_any and not business_disallowed

    observations = tool_observations(result.get("messages") or [])
    usage = token_usage(result.get("messages") or [])
    executed = [item for item in observations if item.get("ok") is not None]
    executed_ok = [item for item in observations if item.get("ok")]
    tool_errors = [item for item in observations if not item.get("ok")]
    tool_execution_ok = (
        len(executed_ok) / len(executed) if executed else (1.0 if not actual_calls else 0.0)
    )

    status = result.get("status")
    status_ok = status == "COMPLETED"
    task_success = bool(
        task.get("expected_success", True)
        and status_ok
        and tool_selection_ok
        and final_ok
    )
    business_correctness = bool(
        task.get("expected_success", True)
        and status_ok
        and business_final_ok
    )
    tool_policy_compliance = bool(tool_policy_ok)
    error_recovered = bool(tool_errors and task_success)

    return {
        "task_id": task.get("task_id"),
        "category": task.get("category"),
        "question": task.get("question"),
        "request_id": result.get("request_id"),
        "execution_id": result.get("execution_id"),
        "parent_execution_id": result.get("parent_execution_id"),
        "event_trace": result.get("event_trace") or [],
        "status": status,
        "status_ok": status_ok,
        "task_success": task_success,
        "business_correctness": business_correctness,
        "tool_policy_compliance": tool_policy_compliance,
        "expected_tools": expected,
        "required_tools": required,
        "optional_tools": optional,
        "forbidden_tools": forbidden,
        "actual_tools": actual_calls,
        "missing_tools": missing_tools,
        "missing_required_tools": missing_required_tools,
        "forbidden_tools_hit": forbidden_tools_hit,
        "tool_selection_ok": tool_selection_ok,
        "tool_policy_ok": tool_policy_ok,
        "tool_recall": tool_recall,
        "expected_keywords": keywords,
        "expected_keywords_any": keywords_any,
        "missing_keywords": missing_keywords,
        "missing_keywords_any": missing_any,
        "must_not_contain_numbers": bool(task.get("must_not_contain_numbers")),
        "allowed_numbers": [str(x) for x in (task.get("allowed_numbers") or [])],
        "disallowed_numbers": disallowed_numbers,
        "business_disallowed_numbers": business_disallowed,
        "observed_fact_numbers": observed_fact_numbers,
        "approx_numbers": approx_numbers,
        "result_claim_numbers": result_claim_numbers,
        "must_not_contain_approx_numbers": bool(task.get("must_not_contain_approx_numbers")),
        "forbidden_result_units": [str(x) for x in (task.get("forbidden_result_units") or [])],
        "final_ok": final_ok,
        "manual_review": list(task.get("manual_review") or []),
        "tool_results": observations,
        "tool_execution_ok": tool_execution_ok,
        "tool_errors": tool_errors,
        "error_recovered": error_recovered,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "token_usage_found": usage["token_usage_found"],
        "steps": result.get("steps"),
        "tool_call_count": result.get("tool_call_count"),
        "elapsed_s": result.get("elapsed_s"),
        "final_answer": final,
        "run_error": result.get("run_error"),
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.get("task_success"))
    business_passed = sum(1 for r in results if r.get("business_correctness"))
    policy_passed = sum(1 for r in results if r.get("tool_policy_compliance"))
    tool_selection_passed = sum(1 for r in results if r.get("tool_selection_ok"))
    observations = [
        item
        for r in results
        for item in (r.get("tool_results") or [])
    ]
    executed_errors = [
        item
        for r in results
        for item in (r.get("tool_errors") or [])
    ]
    error_cases = [r for r in results if r.get("tool_errors")]
    recovered_cases = [r for r in error_cases if r.get("error_recovered")]

    steps = [r.get("steps") for r in results if isinstance(r.get("steps"), int)]
    calls = [r.get("tool_call_count") for r in results if isinstance(r.get("tool_call_count"), int)]
    elapsed = [r.get("elapsed_s") for r in results if isinstance(r.get("elapsed_s"), (int, float))]
    input_tokens = sum(int(r.get("input_tokens") or 0) for r in results)
    output_tokens = sum(int(r.get("output_tokens") or 0) for r in results)
    token_tasks = sum(1 for r in results if r.get("token_usage_found"))
    estimated_cost = estimate_cost(input_tokens, output_tokens)

    modules: dict[str, dict[str, Any]] = {}
    for r in results:
        row = modules.setdefault(
            str(r.get("category") or "未分类"),
            {"total": 0, "passed": 0, "business_passed": 0, "policy_passed": 0},
        )
        row["total"] += 1
        row["passed"] += int(bool(r.get("task_success")))
        row["business_passed"] += int(bool(r.get("business_correctness")))
        row["policy_passed"] += int(bool(r.get("tool_policy_compliance")))

    return {
        "total": total,
        "passed": passed,
        "task_success_rate": passed / total if total else 0.0,
        "business_correctness_rate": business_passed / total if total else 0.0,
        "tool_policy_compliance_rate": policy_passed / total if total else 0.0,
        "tool_selection_accuracy": tool_selection_passed / total if total else 0.0,
        "tool_execution_success": (
            sum(1 for item in observations if item.get("ok")) / len(observations)
            if observations else 0.0
        ),
        "error_recovery": (
            len(recovered_cases) / len(error_cases) if error_cases else None
        ),
        "error_cases": len(error_cases),
        "tool_error_count": len(executed_errors),
        "avg_steps": sum(steps) / len(steps) if steps else 0.0,
        "avg_tool_calls": sum(calls) / len(calls) if calls else 0.0,
        "avg_elapsed_s": sum(elapsed) / len(elapsed) if elapsed else 0.0,
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "avg_tokens_per_task": (input_tokens + output_tokens) / total if total else 0.0,
        "token_usage_tasks": token_tasks,
        "estimated_cost": estimated_cost,
        "cost_configured": estimated_cost is not None,
        "modules": {
            name: {
                **row,
                "task_success_rate": row["passed"] / row["total"] if row["total"] else 0.0,
                "business_correctness_rate": row["business_passed"] / row["total"] if row["total"] else 0.0,
                "tool_policy_compliance_rate": row["policy_passed"] / row["total"] if row["total"] else 0.0,
            }
            for name, row in sorted(modules.items())
        },
    }
