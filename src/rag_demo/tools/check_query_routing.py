#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : check_query_routing.py
@Function: 检查「按需多路」的策略判断是否合理

只跑判断环节（build_query_variants），不跑检索与生成——所以很快（每次约 3~6s）。

关注点：LLM 会不会「贪心全选」，或者「偷懒全不选」。
理想表现是：简单问题 1 路，复杂问题 2~3 路。

输出写入 query_routing_check.txt，避免 Windows 控制台 GBK 编码乱码。

用法：
    python src/rag_demo/tools/check_query_routing.py
"""
import io
import json
import os
import time

from rag_demo.config import BASE_DIR
from rag_demo.retrieval.query_processor import build_query_variants

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")

# (题号, 该题的特征, 期望的合理路数)
CASES = [
    ("OPT-03", "简短、单一意图、术语明确", "1 路（只直接检索）"),
    ("OPT-01", "三个限定条件叠加", "2~3 路（可能加分解或关键词）"),
    ("CS-05", "口语化场景描述", "2~3 路（可能加简化）"),
    ("MGT-02", "含特定标签名", "2~3 路（可能加关键词）"),
    ("DA-01", "含『标签』这类结构词", "2~3 路（可能加关键词）"),
    ("EDGE-03", "关联/相似查询", "2~3 路（可能加分解）"),
]


def main() -> None:
    with open(os.path.join(TESTS_DIR, "eval_questions.json"), encoding="utf-8") as f:
        items = {q["id"]: q for q in json.load(f)}

    lines: list[str] = []
    stat: dict[int, int] = {}

    for qid, feature, expect in CASES:
        question = items[qid]["question"]
        t0 = time.time()
        variants = build_query_variants(question)
        dt = time.time() - t0

        n = len(variants)
        stat[n] = stat.get(n, 0) + 1

        lines.append(f"[{qid}] {question}")
        lines.append(f"    特征    : {feature}")
        lines.append(f"    期望    : {expect}")
        lines.append(f"    实际    : {n} 路，判断耗时 {dt:.1f}s")
        for name, text in variants:
            lines.append(f"              · {name}: {text[:56]}")
        lines.append("")

    lines.append("=" * 72)
    lines.append("路数分布：")
    for k in sorted(stat):
        lines.append(f"    {k} 路 × {stat[k]} 题")
    total_cases = len(CASES)
    extra = sum((k - 1) * v for k, v in stat.items())
    avg = 1 + extra / total_cases
    lines.append(f"    平均路数：{avg:.2f}（全跑是 5.00）")

    out = os.path.join(BASE_DIR, "query_routing_check.txt")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written: {out}")


if __name__ == "__main__":
    main()
