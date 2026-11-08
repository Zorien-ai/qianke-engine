"""汇总控制面 PG 观察脚本输出，生成可用率/队列/缺口报告。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def _parse_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def summarize(rows: list[dict], *, required_seconds: int = 86400) -> dict:
    points = []
    for row in rows:
        try:
            points.append((_parse_at(row["at"]), row))
        except (KeyError, TypeError, ValueError):
            continue
    if not points:
        return {"verdict": "NO_DATA", "samples": 0}
    points.sort(key=lambda item: item[0])
    first_at, last_at = points[0][0], points[-1][0]
    duration = max(0.0, (last_at - first_at).total_seconds())
    ready_ok = sum(1 for _, row in points if int(row.get("ready_status") or 0) == 200)
    metrics_ok = sum(1 for _, row in points if int(row.get("metrics_status") or 0) == 200)
    gaps = [
        round((points[i][0] - points[i - 1][0]).total_seconds(), 1)
        for i in range(1, len(points))
        if (points[i][0] - points[i - 1][0]).total_seconds() > 180
    ]

    def values(key: str) -> list[float]:
        return [float(row[key]) for _, row in points if row.get(key) is not None]

    queue_done = values("queue_done")
    pending = values("queue_pending")
    dead = values("queue_dead")
    waiting = values("work_items_waiting_approval")
    stuck = values("work_items_stuck")
    failures = len(points) - ready_ok
    if failures:
        verdict = "FAIL"
    elif duration < required_seconds:
        verdict = "IN_PROGRESS"
    else:
        verdict = "PASS"
    return {
        "verdict": verdict,
        "samples": len(points),
        "first_at": first_at.isoformat(),
        "last_at": last_at.isoformat(),
        "duration_seconds": round(duration, 1),
        "required_seconds": required_seconds,
        "ready_ok": ready_ok,
        "ready_fail": failures,
        "ready_rate": round(ready_ok / len(points), 4),
        "metrics_ok": metrics_ok,
        "gaps_over_180s": gaps,
        "queue_done_last": queue_done[-1] if queue_done else None,
        "queue_done_delta": round(queue_done[-1] - queue_done[0], 1) if len(queue_done) > 1 else 0,
        "queue_pending_max": max(pending) if pending else None,
        "queue_dead_max": max(dead) if dead else None,
        "waiting_approval_max": max(waiting) if waiting else None,
        "stuck_max": max(stuck) if stuck else None,
    }


def load(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--required-hours", type=float, default=24)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    files = args.file or ["logs/control_pg_observation_final.jsonl"]
    rows: list[dict] = []
    for name in files:
        path = Path(name)
        if path.exists():
            rows.extend(load(path))
    result = summarize(rows, required_seconds=int(args.required_hours * 3600))
    result["files"] = files
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] in {"PASS", "IN_PROGRESS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
