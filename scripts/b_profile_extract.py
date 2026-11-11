"""扫描 30 分钟无消息的 C 买家 ↔ 商家店宠会话，抽取并保存 B 端会话画像。

建议每分钟执行；任务幂等，重复扫描不会重复生成画像。
    python scripts/b_profile_extract.py
    python scripts/b_profile_extract.py --owner buyer_112
    python scripts/b_profile_extract.py --limit 200
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rag_demo.c_end import chat_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="B 端会话画像抽取")
    parser.add_argument("--owner", action="append", default=None, help="只处理指定买家，可重复")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    if args.owner:
        results = [
            chat_profile.extract_for_owner(owner)
            for owner in args.owner
        ]
        payload = {"owners": len(results), "results": results}
    else:
        payload = chat_profile.run_idle_profiles(limit=args.limit)
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
