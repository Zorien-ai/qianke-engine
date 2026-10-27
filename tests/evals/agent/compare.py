"""对比两个 Agent Eval baseline（默认读取 baselines/<version>.json）。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BASELINES = HERE / "baselines"

METRICS = [
    ("task_success_rate", "Task Success", "pct"),
    ("business_correctness_rate", "Business Correctness", "pct"),
    ("tool_policy_compliance_rate", "Tool Policy", "pct"),
    ("tool_selection_accuracy", "Tool Selection", "pct"),
    ("tool_execution_success", "Tool Execution", "pct"),
    ("error_recovery", "Error Recovery", "pct"),
    ("avg_steps", "Avg Steps", "num"),
    ("avg_tool_calls", "Avg Tool Calls", "num"),
    ("avg_elapsed_s", "Avg Latency", "sec"),
    ("total_tokens", "Total Tokens", "int"),
    ("avg_tokens_per_task", "Avg Tokens", "int"),
    ("estimated_cost", "Estimated Cost", "cost"),
]


def resolve(path: str) -> Path:
    p = Path(path)
    if p.exists():
        return p
    candidate = BASELINES / f"{path}.json"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"baseline not found: {path}")


def load(path: str) -> dict[str, Any]:
    return json.loads(resolve(path).read_text(encoding="utf-8"))


def _summary(baseline: dict[str, Any]) -> dict[str, Any]:
    # baseline 顶层是 regression / benchmark；优先对比 benchmark
    return baseline.get("benchmark", {}).get("summary", {})


def fmt(value: Any, kind: str) -> str:
    if value is None:
        return "N/A"
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "sec":
        return f"{value:.1f}s"
    if kind == "cost":
        return f"${value:.4f}"
    if kind == "int":
        return f"{value:,.0f}"
    return f"{value:.2f}"


def delta(old: Any, new: Any, kind: str) -> str:
    if old is None or new is None:
        return "—"
    diff = new - old
    if kind == "pct":
        return f"{diff * 100:+.1f}pp"
    if kind == "sec":
        return f"{diff:+.1f}s"
    if kind == "cost":
        return f"{diff:+.4f}"
    if kind == "int":
        return f"{diff:+,.0f}"
    return f"{diff:+.2f}"


def compare(old: dict[str, Any], new: dict[str, Any]) -> str:
    old_sum = _summary(old)
    new_sum = _summary(new)
    rows = [
        "| 指标 | " + str(old.get("version", "old")) + " | "
        + str(new.get("version", "new")) + " | Δ |",
        "|---|---:|---:|---:|",
    ]
    for key, label, kind in METRICS:
        rows.append(
            f"| {label} | {fmt(old_sum.get(key), kind)} | "
            f"{fmt(new_sum.get(key), kind)} | "
            f"{delta(old_sum.get(key), new_sum.get(key), kind)} |"
        )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="对比两个 Agent Eval baseline")
    parser.add_argument("old", help="旧版本，如 v1.8.1 或 json 路径")
    parser.add_argument("new", help="新版本，如 v1.8.2 或 json 路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON 差值")
    args = parser.parse_args(argv)
    old, new = load(args.old), load(args.new)
    if args.json:
        print(json.dumps({"old": old.get("version"), "new": new.get("version"),
                          "old_summary": _summary(old), "new_summary": _summary(new)},
                         ensure_ascii=False, indent=2))
    else:
        print(compare(old, new))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
