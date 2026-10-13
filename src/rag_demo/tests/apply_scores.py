#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : apply_scores.py
@Function: 从人工评分清单（review.md）解析 manual_score 并回填到评测结果 json
"""
import argparse
import json
import os
import re
from collections import defaultdict

from rag_demo.config import BASE_DIR

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")

# 匹配 `manual_score = _1__` / `manual_score = __0_` 等带下划线占位的写法。
# 注意：[^0-9] 会匹配换行符，必须排除 \n，否则说明行会向后吞到第一条评分
SCORE_RE = re.compile(r"manual_score\s*=\s*[^\d\n]*([01])[^\d\n]*")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填人工评分")
    parser.add_argument("review_file", help="评分清单 md（文件名或绝对路径）")
    parser.add_argument("result_file", help="评测结果 json（文件名或绝对路径）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    def _resolve(p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(TESTS_DIR, p)

    review_path = _resolve(args.review_file)
    result_path = _resolve(args.result_file)

    with open(review_path, "r", encoding="utf-8") as f:
        scores = [int(x) for x in SCORE_RE.findall(f.read())]

    with open(result_path, "r", encoding="utf-8") as f:
        results = json.load(f)

    if len(scores) != len(results):
        print(f"[中止] 清单解析到 {len(scores)} 个评分，结果有 {len(results)} 条，请检查是否有条目漏填")
        return

    for r, s in zip(results, scores):
        r["manual_score"] = s

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    passed = sum(1 for r in results if r.get("manual_score") == 1)
    print(f"已回填 {len(scores)} 条评分 -> {os.path.basename(result_path)}")
    print(f"人工评分通过: {passed}/{len(results)} = {passed / len(results) * 100:.1f}%")

    # 自动判定 vs 人工评分差异（用于校准自动指标）
    diffs = []
    for r in results:
        auto, manual = r.get("passed"), r.get("manual_score")
        if manual is not None and auto is not None and int(auto) != manual:
            diffs.append(r)
    print(f"\n自动判定与人工不一致: {len(diffs)} 条")
    for r in diffs:
        print(
            f"  {r['id']} | route={r.get('route')} | 自动={r.get('passed')} 人工={r.get('manual_score')}"
            f" | 期望={r.get('expect_sources')} 实际={r.get('actual_sources')}"
        )

    # 分板块通过率
    by_module = defaultdict(lambda: {"total": 0, "pass": 0})
    for r in results:
        m = r.get("module", "unknown")
        by_module[m]["total"] += 1
        by_module[m]["pass"] += r.get("manual_score") or 0
    print("\n=== 分板块通过率（人工评分） ===")
    for m, s in by_module.items():
        print(f"{m}: {s['pass']}/{s['total']}")


if __name__ == "__main__":
    main()
