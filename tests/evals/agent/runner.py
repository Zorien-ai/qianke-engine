"""Agent Eval runner：regression 20 条 / benchmark 40 条，真实运行并输出报告。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import evaluator  # noqa: E402
from rag_demo.agent.loop import run_agent  # noqa: E402
from rag_demo.agent.state import AgentConfig  # noqa: E402

SUITES: dict[str, dict[str, Any]] = {
    "regression": {
        "cases": HERE / "regression" / "dataset.v1.json",
        "count": 20,
        "results": HERE / "regression" / "results" / "regression_v1.json",
        "report": HERE / "regression" / "reports" / "regression_v1.md",
    },
    "benchmark": {
        "cases": HERE / "benchmark" / "dataset.v1.json",
        "count": 40,
        "results": HERE / "benchmark" / "results" / "benchmark_v1.json",
        "report": HERE / "benchmark" / "reports" / "benchmark_v1.md",
    },
}
DEFAULT_SUITE = "regression"


def warmup_retrieval() -> None:
    """评测进程启动时串行预热检索模型，避免首个请求撞上半转换的 fp16 模型。"""
    try:
        from rag_demo.retrieval.hybrid_retriever import get_model

        get_model()
    except Exception as exc:  # noqa: BLE001 - 预热失败仍由工具错误正常上报
        print(f"warmup retrieval failed: {type(exc).__name__}: {exc}")


def load_tasks(path: Path | str, expected_count: int | None = None) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("dataset 必须包含非空 tasks 数组")
    if expected_count is not None and len(tasks) != expected_count:
        raise ValueError(f"期望 {expected_count} 个任务，实际 {len(tasks)}")
    ids = [task.get("task_id") for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("task_id 必须唯一")
    return tasks


def run_task(task: dict[str, Any], *, dataset: str, config: AgentConfig) -> dict[str, Any]:
    from rag_demo.db.connection import use_dataset

    task_dataset = task.get("dataset") or dataset
    use_dataset(task_dataset)
    started = time.monotonic()
    try:
        result = run_agent(task["question"], config=config)
    except Exception as exc:  # noqa: BLE001 - 记录错误，继续跑完整个 benchmark
        result = {
            "final_answer": "",
            "status": "FAILED",
            "steps": 0,
            "tool_call_count": 0,
            "tool_calls": [],
            "messages": [],
            "run_error": f"{type(exc).__name__}: {exc}",
        }
    scored = evaluator.evaluate_task(task, result)
    scored["elapsed_s"] = round(time.monotonic() - started, 2)
    return scored


def write_report(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    path: Path,
    *,
    suite: str,
    dataset: str,
) -> None:
    rate = summary["task_success_rate"] * 100
    selection = summary["tool_selection_accuracy"] * 100
    execution = summary["tool_execution_success"] * 100
    recovery = (
        "N/A" if summary["error_recovery"] is None
        else f"{summary['error_recovery'] * 100:.1f}%"
    )
    lines = [
        f"# Agent Eval · {suite}",
        "",
        f"- 任务数：{summary['total']}",
        f"- 数据集：`{dataset}`",
        "- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具",
        "",
        "## 核心指标",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| Task Success Rate（v1 复合口径） | **{rate:.1f}%** |",
        f"| Business Correctness | **{summary['business_correctness_rate'] * 100:.1f}%** |",
        f"| Tool Policy Compliance | **{summary['tool_policy_compliance_rate'] * 100:.1f}%** |",
        f"| Tool Selection Accuracy | **{selection:.1f}%** |",
        f"| Tool Execution Success | **{execution:.1f}%** |",
        f"| Error Recovery | {recovery} |",
        f"| 平均 Steps | {summary['avg_steps']:.2f} |",
        f"| 平均 Tool Calls | {summary['avg_tool_calls']:.2f} |",
        f"| 平均耗时 | {summary['avg_elapsed_s']:.1f}s |",
        "",
        "## 分类结果",
        "",
        "| 分类 | 通过 / 总数 | Task Success |",
        "|---|---:|---:|",
    ]
    for name, row in summary["modules"].items():
        lines.append(
            f"| {name} | {row['passed']} / {row['total']} | "
            f"{row['task_success_rate'] * 100:.1f}% |"
        )

    failed = [r for r in results if not r.get("task_success")]
    lines.extend(["", f"## 未通过任务（{len(failed)}）", ""])
    if not failed:
        lines.append("全部通过。")
    for row in failed:
        lines.extend([
            f"### {row['task_id']} · {row['category']}",
            "",
            f"- 问题：{row['question']}",
            f"- 状态：{row.get('status')}",
            f"- 业务正确性：{'PASS' if row.get('business_correctness') else 'FAIL'}",
            f"- 工具策略：{'PASS' if row.get('tool_policy_compliance') else 'FAIL'}",
            f"- 期望工具：{row.get('expected_tools')}",
            f"- 实际工具：{row.get('actual_tools')}",
            f"- 缺少工具：{row.get('missing_tools') or '—'}",
            f"- 缺少关键词：{row.get('missing_keywords') or '—'}",
            f"- 缺少任一拒答词：{row.get('missing_keywords_any') or '—'}",
            f"- 非法数字：{row.get('disallowed_numbers') or '—'}",
            f"- 人工复核项：{row.get('manual_review') or '—'}",
            f"- 最终回答：{str(row.get('final_answer') or '')[:500]}",
            "",
        ])

    _append_manual_review(lines, results)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _append_manual_review(lines: list[str], results: list[dict[str, Any]]) -> None:
    manual = [r for r in results if r.get("manual_review")]
    lines.extend(["", f"## 人工复核清单（{len(manual)}）", ""])
    if not manual:
        lines.append("无。")
        return
    for row in manual:
        lines.append(f"### {row['task_id']} · {row['category']}")
        lines.append("")
        lines.append(f"- 自动判定：{'PASS' if row.get('task_success') else 'FAIL'}")
        lines.append(f"- 问题：{row.get('question')}")
        lines.append(f"- 最终回答：{str(row.get('final_answer') or '')[:400]}")
        for item in row.get("manual_review") or []:
            lines.append(f"- 复核项：{item}")
        lines.append("")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Eval（regression / benchmark）")
    parser.add_argument("--suite", choices=sorted(SUITES), default=DEFAULT_SUITE)
    parser.add_argument("--dataset", default="")
    parser.add_argument("--cases", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--only", default="", help="逗号分隔 task_id")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--min-task-success", type=float, default=0.8)
    args = parser.parse_args(argv)

    suite = SUITES[args.suite]
    cases_path = Path(args.cases) if args.cases else suite["cases"]
    expected_count = None if args.cases else suite["count"]
    tasks = load_tasks(cases_path, expected_count=expected_count)
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        tasks = [task for task in tasks if task.get("task_id") in wanted]
    if args.limit > 0:
        tasks = tasks[: args.limit]

    if args.validate_only:
        print(f"suite={args.suite} tasks={len(tasks)} valid")
        return 0

    from rag_demo.generation.generator import API_KEY

    if not API_KEY:
        print("缺少 DEEPSEEK_API_KEY，无法执行真实 Agent Eval")
        return 2

    config = AgentConfig(max_steps=6, max_tool_calls=12, timeout_seconds=180)
    warmup_retrieval()
    results = []
    for index, task in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] {task['task_id']} {task['question']}")
        scored = run_task(task, dataset=args.dataset or "demo", config=config)
        results.append(scored)
        print(
            f"  -> {'PASS' if scored['task_success'] else 'FAIL'} "
            f"status={scored['status']} tools={scored['actual_tools']}"
        )

    summary = evaluator.summarize(results)
    output = {
        "version": "agent-eval-v0.1",
        "suite": args.suite,
        "dataset": args.dataset or "demo",
        "summary": summary,
        "results": results,
    }
    out_path = Path(args.out) if args.out else suite["results"]
    report_path = Path(args.report) if args.report else suite["report"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(
        results, summary, report_path,
        suite=args.suite, dataset=args.dataset or "demo",
    )

    print(f"task_success_rate={summary['task_success_rate'] * 100:.1f}%")
    print(f"tool_selection_accuracy={summary['tool_selection_accuracy'] * 100:.1f}%")
    print(f"tool_execution_success={summary['tool_execution_success'] * 100:.1f}%")
    print(f"results={out_path}")
    print(f"report={report_path}")
    return 0 if summary["task_success_rate"] >= args.min_task_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
