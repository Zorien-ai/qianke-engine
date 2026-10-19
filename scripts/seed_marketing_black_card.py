#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""仅为演示/验收准备黑卡测试数据（demo 数据集）。

这会把 demo 中 3 个北京高价值用户标记为「黑卡」，并把 profile_text 中的
「钻石会员」替换为「黑卡会员」。它是本地演示 fixture，不参与生产部署。
运行：
    uv run python scripts/seed_marketing_black_card.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rag_demo.db.connection import get_conn, reset_dataset, use_dataset  # noqa: E402

TARGET_IDS = ("U8785", "U6103", "U8290")


def main() -> int:
    token = use_dataset("demo")
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """UPDATE user_profile_vectors
               SET member_level = '黑卡',
                   profile_text = replace(replace(profile_text, '钻石会员', '黑卡会员'), '钻石', '黑卡')
               WHERE user_id = ANY(%s) AND city LIKE '北京%%'""",
            (list(TARGET_IDS),),
        )
        if cur.rowcount == 0:
            print("未命中任何北京用户，demo 数据可能未导入。", file=sys.stderr)
            conn.rollback()
            return 1
        conn.commit()
        cur.execute(
            """SELECT user_id, city, member_level, top_category, avg_amount::float8
               FROM user_profile_vectors WHERE user_id = ANY(%s) ORDER BY avg_amount DESC""",
            (list(TARGET_IDS),),
        )
        for row in cur.fetchall():
            print(row)
        print(f"已更新 {cur.rowcount if cur.rowcount >= 0 else len(TARGET_IDS)} 条演示黑卡数据。")
        return 0
    finally:
        try:
            conn.rollback()
            cur.close()
        finally:
            reset_dataset(token)


if __name__ == "__main__":
    raise SystemExit(main())
