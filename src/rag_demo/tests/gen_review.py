#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : gen_review.py
@Function: 把评测结果导出成人工评分清单（Markdown），便于逐条打分
"""
import argparse
import json
import os

from rag_demo.config import BASE_DIR

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成人工评分清单")
    parser.add_argument("result_file", help="评测结果 json（文件名或绝对路径）")
    parser.add_argument("-o", "--output", default="", help="输出路径，默认 <结果名>_review.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    path = args.result_file
    if not os.path.isabs(path):
        path = os.path.join(TESTS_DIR, path)
    with open(path, "r", encoding="utf-8") as f:
        results = json.load(f)

    out = args.output or os.path.splitext(path)[0] + "_review.md"

    auto_pass = sum(1 for r in results if r.get("passed") is True)
    undecided = sum(1 for r in results if r.get("passed") is None)

    lines = [
        f"# 人工评分清单",
        "",
        f"- 结果文件: `{os.path.basename(path)}`",
        f"- 自动判定通过: **{auto_pass}/{len(results)}**",
        f"- 需人工判定（负样本）: {undecided} 条",
        "",
        "> 评分：`1` = 通过（答案正确、无误导、来源可靠），`0` = 不通过。",
        "> 可直接在下方 `manual_score = ___` 处填写，改完告诉我，我写回 json 并算通过率。",
        "",
    ]

    for i, r in enumerate(results, 1):
        lines += [
            "---",
            "",
            f"## [{i}] {r.get('id')} | {r.get('question')}",
            "",
            f"- **板块**: {r.get('module')}",
            f"- **路由**: `{r.get('route')}`",
            f"- **自动判定**: `{r.get('passed')}`",
            f"- **期望来源**: `{r.get('expect_sources')}`",
            f"- **实际来源**: `{r.get('actual_sources')}`",
            f"- **耗时**: {r.get('elapsed_sec')}s",
            f"- **验收标准**: {r.get('acceptance')}",
        ]
        if r.get("route") == "sql":
            lines += [
                f"- **SQL**: `{(r.get('sql') or '').strip()}`",
                f"- **rows_count**: {r.get('rows_count')}",
            ]
        lines += [
            "",
            "**答案**：",
            "",
            (r.get("answer") or "（空）").strip(),
            "",
            "**评分**: `manual_score = ___`　`note = ___`",
            "",
        ]

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"清单已生成: {out}")
    print(f"共 {len(results)} 条 | 自动判定通过 {auto_pass} | 待人工 {undecided}")


if __name__ == "__main__":
    main()
