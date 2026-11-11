"""每日 C 端记忆压缩、遗忘与日记任务。

建议每天 03:00 Asia/Shanghai 执行：
    python scripts/c_memory_daily.py
    python scripts/c_memory_daily.py --date 2026-11-10
    python scripts/c_memory_daily.py --owner buyer_112

默认处理“昨天”的本地自然日；重复执行是幂等的。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rag_demo.c_end import memory_daily, store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="C 端记忆日任务")
    parser.add_argument("--date", default=None, help="本地自然日 YYYY-MM-DD；默认昨天")
    parser.add_argument("--owner", action="append", default=None, help="只处理指定 owner，可重复")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()

    day = args.date or (datetime.now(memory_daily.LOCAL_TZ).date() - timedelta(days=1)).isoformat()
    if args.owner:
        results = [memory_daily.run_daily(owner, day) for owner in args.owner]
        payload = {"day": day, "owners": len(results), "results": results}
    else:
        payload = memory_daily.run_for_day(day, limit=args.limit)
    print(json.dumps({"ok": not payload.get("failed"), **payload}, ensure_ascii=False, indent=2))
    return 0 if not payload.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
