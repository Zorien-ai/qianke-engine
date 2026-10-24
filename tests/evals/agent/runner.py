"""Agent Eval v0.1 Runner：真实运行 20 个 Agent Task 并输出报告。"""
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

DEFAULT_DATASET = "demo"
DEFAULT_OUT = HERE / "results" / "agent_eval_v0.1.json"
DEFAULT_REPORT = HERE / "reports" / "agent_eval_v0.1.md"


def load_tasks(path: Path | str = HERE / "dataset.json") -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list) or len(tasks) != 20:
        raise ValueError(f"期望 20 个 Agent Task，实际 {len(tasks or [])}")
    ids = [task.get("task_id") for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("task_id 必须唯一")
    return tasks


def run_task(task: dict[str, Any], *, dataset: str, config: AgentConfig) -> dict[str, Any]:
    from rag_demo.db.connection import use_dataset

    use_dataset(dataset)
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


def write_report(results: list[dict[str, Any]], summary: dict[str, Any], path: Path, dataset: str) -> None:
    rate = summary["task_success_rate"] * 100
    selection = summary["tool_selection_accuracy"] * 100
    execution = summary["tool_execution_success"] * 100
    recovery = (
        "N/A" if summary["error_recovery"] is None
        else f"{summary['error_recovery'] * 100:.1f}%"
    )
    lines = [
        "# Agent Eval v0.1",
        "",
        f"- 任务数：{summary['total']}",
        f"- 数据集：`{dataset}`",
        f"- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具",
        "",
        "## 核心指标",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| Task Success Rate | **{rate:.1f}%** |",
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
            f"- 期望工具：{row.get('expected_tools')}",
            f"- 实际工具：{row.get('actual_tools')}",
            f"- 缺少工具：{row.get('missing_tools') or '—'}",
            f"- 缺少关键词：{row.get('missing_keywords') or '—'}",
            f"- 最终回答：{str(row.get('final_answer') or '')[:500]}",
            "",
        ])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Eval v0.1（20 个真实任务）")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--cases", default=str(HERE / "dataset.json"))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--only", default="", help="逗号分隔 task_id")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--min-task-success", type=float, default=0.8)
    args = parser.parse_args(argv)

    tasks = load_tasks(args.cases)
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        tasks = [task for task in tasks if task.get("task_id") in wanted]
    if args.limit > 0:
        tasks = tasks[: args.limit]

    if args.validate_only:
        print(f"tasks={len(tasks)} valid")
        return 0

    from rag_demo.generation.generator import API_KEY

    if not API_KEY:
        print("缺少 DEEPSEEK_API_KEY，无法执行真实 Agent Eval")
        return 2

    config = AgentConfig(max_steps=6, max_tool_calls=12, timeout_seconds=180)
    results = []
    for index, task in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] {task['task_id']} {task['question']}")
        scored = run_task(task, dataset=args.dataset, config=config)
        results.append(scored)
        print(
            f"  -> {'PASS' if scored['task_success'] else 'FAIL'} "
            f"status={scored['status']} tools={scored['actual_tools']}"
        )

    summary = evaluator.summarize(results)
    output = {
        "version": "agent-eval-v0.1",
        "dataset": args.dataset,
        "summary": summary,
        "results": results,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(results, summary, Path(args.report), args.dataset)

    print(f"task_success_rate={summary['task_success_rate'] * 100:.1f}%")
    print(f"tool_selection_accuracy={summary['tool_selection_accuracy'] * 100:.1f}%")
    print(f"tool_execution_success={summary['tool_execution_success'] * 100:.1f}%")
    print(f"results={args.out}")
    print(f"report={args.report}")
    return 0 if summary["task_success_rate"] >= args.min_task_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
