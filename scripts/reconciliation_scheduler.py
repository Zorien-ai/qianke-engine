"""定时对账 worker：只检查并留痕，不自动修改订单。

用法：
    python scripts/reconciliation_scheduler.py --interval 1800
    python scripts/reconciliation_scheduler.py --once

Windows 任务计划程序可直接调用 --once，或常驻运行本脚本。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rag_demo.c_end import store  # noqa: E402


def _setup_logging() -> None:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(logs / "reconciliation_scheduler.log", encoding="utf-8"),
        ],
    )


def run_once(limit: int = 200) -> dict:
    report = store.run_reconciliation("SCHEDULED", limit=limit)
    logging.info(
        "reconciliation run_id=%s ok=%s checked=%s legacy=%s issues=%s",
        report["run_id"],
        report["ok"],
        report["checked"],
        report["legacy"],
        report["issue_count"],
    )
    if report["issue_count"]:
        logging.warning("reconciliation issues: %s", json.dumps(report["issues"], ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Qianke C/merchant order reconciliation worker")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("QIANKE_RECONCILE_INTERVAL_SECONDS", "1800")),
        help="seconds between runs (default 1800)",
    )
    parser.add_argument("--limit", type=int, default=200, help="max orders per run")
    parser.add_argument("--once", action="store_true", help="run once and exit")
    args = parser.parse_args()
    if args.interval < 10:
        parser.error("--interval must be >= 10 seconds")
    _setup_logging()
    if args.once:
        run_once(args.limit)
        return 0
    logging.info("reconciliation scheduler started interval=%ss limit=%s", args.interval, args.limit)
    while True:
        try:
            run_once(args.limit)
        except Exception:  # noqa: BLE001 - 单次失败不能杀 worker
            logging.exception("reconciliation run failed")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
