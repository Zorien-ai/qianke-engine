"""B 端会话画像常驻扫描器：每 60 秒检查一次 30 分钟空闲会话。

本地演示：
    python scripts/b_profile_worker.py
    python scripts/b_profile_worker.py --interval 120

生产建议交给 systemd / 容器常驻进程；单次扫描器见 b_profile_extract.py。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rag_demo.c_end import chat_profile  # noqa: E402

logger = logging.getLogger("b_profile_worker")


def main() -> int:
    parser = argparse.ArgumentParser(description="B 端会话画像常驻扫描")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(ROOT / "logs" / "b_profile_worker.log", encoding="utf-8")],
    )
    while True:
        try:
            result = chat_profile.run_idle_profiles(limit=args.limit)
            logger.info("profile_scan %s", json.dumps({k: result[k] for k in ("checked", "ok", "skipped")}, ensure_ascii=False))
        except Exception:  # noqa: BLE001 - 单轮失败不退出常驻进程
            logger.exception("profile_scan_failed")
        if args.once:
            return 0
        time.sleep(max(10, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
