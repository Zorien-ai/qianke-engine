"""Super-agent 独立 Worker 进程。

用法：
    python scripts/sa_worker.py

API 侧配置：
    QIANKE_SUPERAGENT_QUEUE_DISPATCHER=0
    QIANKE_QUEUE_BACKEND=postgres   # 可选；默认 sqlite

Worker 侧同一套环境变量；进程只消费队列，不暴露 HTTP。
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rag_demo.superagent import runtime  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("QIANKE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s",
    )
    stop = threading.Event()

    def _stop(signum, _frame):
        logger.info("收到信号 %s，准备退出 Worker", signum)
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    runtime.run_worker_loop(poll_seconds=float(os.environ.get("QIANKE_SA_WORKER_POLL", "2")), stop_event=stop)
    logger.info("Super-agent Worker 已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
