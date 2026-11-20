"""C 端会话结束后的记忆复盘任务。

建议每 10 分钟跑一次（Asia/Shanghai）：
    python scripts/c_memory_review.py
    python scripts/c_memory_review.py --owner buyer_112
    python scripts/c_memory_review.py --now 2026-11-20T21:00:00+08:00

只处理已空闲会话，只创建 PENDING_CONFIRMATION 候选，不直接写 ACTIVE。
需要 QIANKE_C_MEMORY_WRITE_MODE=candidate。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rag_demo.c_end import memory_review  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="C 端会话记忆复盘（候选模式）")
    parser.add_argument("--owner", action="append", default=None, help="只处理指定 owner，可重复")
    parser.add_argument("--now", default=None, help="ISO 时间，默认当前时间")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--watch", action="store_true", help="常驻轮询，默认每 300 秒一次")
    parser.add_argument("--interval", type=int, default=300, help="--watch 的轮询秒数")
    args = parser.parse_args()

    while True:
        now = datetime.fromisoformat(args.now) if args.now else None
        payload = memory_review.review_all(now=now, owners=args.owner, limit=args.limit)
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2), flush=True)
        if not args.watch:
            return 0
        time.sleep(max(30, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
