"""Agent Eval runner：加载 20 条 case，真实调用 run_agent 并产出报告。"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from rag_demo.agent.eval.metrics import evaluate_case, summarize
from rag_demo.agent.loop import run_agent
from rag_demo.agent.state import AgentConfig

EvalCase = dict[str, Any]
DEFAULT_CASES = Path(__file__).with_name("cases") / "golden_agent_v1.json"
DEFAULT_OUT = Path("tests/agent_eval_results.json")
DEFAULT_REPORT = Path("tests/agent_eval_report.md")


def load_cases(path: Path | str = DEFAULT_CASES) -> list[EvalCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Agent Eval cases 必须是 JSON 数组")
    ids = [case.get("id") for case in payload]
    if len(ids) != len(set(ids)):
        raise ValueError("Agent Eval case id 必须唯一")
    return payload


def run_case(case: EvalCase) -> dict[str, Any]:
    """执行单条 case；异常也收敛成一条 FAILED 结果，方便报告复盘。"""
    started = time.monotonic()
    dataset = case.get("dataset", "test")
    config = AgentConfig(**(case.get("config") or {
        "max_steps": 6,
        "max_tool_calls": 12,
        "timeout_seconds": 180,
    }))

    try:
        from rag_demo.db.connection import use_dataset

        use_dataset(dataset)
        result = run_agent(case["question"], config=config)
    except Exception as exc:  # noqa: BLE001 - eval 记录异常而不是中断整批
        result = {
            "final_answer": "",
            "status": "FAILED",
            "steps": 0,
            "tool_call_count": 0,
            "tool_calls": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
        result["run_error"] = result.pop("error")

    scored = evaluate_case(case, result)
    scored["elapsed_s"] = round(time.monotonic() - started, 2)
    scored["run_error"] = result.get("run_error")
    return scored


def _write_report(results: list[dict[str, Any]], summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Agent Eval v0.1",
        "",
        f"- 题目数：{summary['total']}",
        f"- 通过：{summary['passed']} / {summary['total']}",
        f"- 通过率：{summary['pass_rate'] * 100:.1f}%",
        f"- 工具召回均值：{summary['tool_recall_avg'] * 100:.1f}%",
        f"- 平均步骤：{summary['avg_steps']:.1f}",
        f"- 平均工具调用：{summary['avg_tool_calls']:.1f}",
        "",
        "## 分类",
        "",
        "| 模块 | 通过 | 总数 | 通过率 |",
        "|---|---:|---:|---:|",
    ]
    for name, row in sorted(summary["modules"].items()):
        lines.append(f"| {name} | {row['passed']} | {row['total']} | {row['pass_rate'] * 100:.1f}% |")

    failed = [r for r in results if not r.get("success")]
    lines.extend(["", f"## 失败用例（{len(failed)}）", ""])
    if not failed:
        lines.append("全部通过。")
    for row in failed:
        lines.append(f"### {row['id']} · {row['question']}")
        lines.append("")
        lines.append(f"- 状态：{row.get('status')}")
        lines.append(f"- 缺少工具：{row.get('missing_tools') or '—'}")
        lines.append(f"- 缺少回答片段：{row.get('missing_required_text') or '—'}")
        lines.append(f"- 实际工具：{row.get('actual_tools') or '—'}")
        if row.get("run_error"):
            lines.append(f"- 运行异常：{row['run_error']}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Eval v0.1：20 条工具/协同 case")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--only", default="", help="逗号分隔的 case id，例如 CALC-01,COL-01")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-pass-rate", type=float, default=0.8)
    parser.add_argument("--validate-only", action="store_true", help="只校验 case，不调用模型")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    if args.only:
        wanted = {part.strip() for part in args.only.split(",") if part.strip()}
        cases = [case for case in cases if case.get("id") in wanted]
    if args.limit > 0:
        cases = cases[: args.limit]

    if args.validate_only:
        print(f"cases={len(cases)} valid")
        return 0

    from rag_demo.generation.generator import API_KEY

    if not API_KEY:
        print("缺少 DEEPSEEK_API_KEY，无法执行真实 Agent Eval")
        return 2

    results = []
    for index, case in enumerate(cases, 1):
        print(f"[{index}/{len(cases)}] {case['id']} {case['question']}")
        result = run_case(case)
        results.append(result)
        print(f"  -> {'PASS' if result['success'] else 'FAIL'} status={result['status']}")

    summary = summarize(results)
    output = {
        "summary": summary,
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_report(results, summary, Path(args.report))

    print(f"pass_rate={summary['pass_rate'] * 100:.1f}%")
    print(f"results={args.out}")
    print(f"report={args.report}")
    return 0 if summary["pass_rate"] >= args.min_pass_rate else 1


__all__ = ["DEFAULT_CASES", "load_cases", "run_case", "main"]
