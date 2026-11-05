"""控制面 PostgreSQL 观察器：定期记录 /ready、队列、工作项与审批计数。

用法：
    python scripts/observe_control_pg.py --once
    python scripts/observe_control_pg.py --duration 60 --interval 10
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _metric_value(text: str, name: str, label: str | None = None) -> float | None:
    for line in text.splitlines():
        if not line.startswith(name):
            continue
        if label and label not in line:
            continue
        try:
            return float(line.rsplit(" ", 1)[-1])
        except ValueError:
            continue
    return None


def sample(api: str) -> dict:
    ready_status, ready_body = _get(f"{api}/ready")
    metrics_status, metrics = _get(f"{api}/metrics")
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "ready_status": ready_status,
        "ready": ready_body[:500],
        "metrics_status": metrics_status,
        "queue_done": _metric_value(metrics, "qianke_queue_jobs", 'status="done"'),
        "queue_pending": _metric_value(metrics, "qianke_queue_jobs", 'status="pending"'),
        "queue_dead": _metric_value(metrics, "qianke_queue_jobs", 'status="dead"'),
        "work_items_waiting_approval": _metric_value(
            metrics, "qianke_work_items", 'status="waiting_approval"'
        ),
        "work_items_stuck": _metric_value(metrics, "qianke_work_items", 'status="stuck"'),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8080")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--out", default="logs/control_pg_observation.jsonl")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(1, args.duration)
    samples = 0
    with out.open("a", encoding="utf-8") as handle:
        while True:
            row = sample(args.api)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            samples += 1
            print(json.dumps(row, ensure_ascii=False))
            if args.once or time.monotonic() >= deadline:
                break
            time.sleep(max(1, args.interval))
    print(f"samples={samples} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
