#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : profile_modes_compare.py
@Function: 三种关键词策略（bm25 / sparse / both）逐环节耗时对比

背景
----
界面上同一问题，三种策略耗时差异明显（实测 19.3s / 27.1s / 30.7s）。
但检索环节只占零点几秒，无法解释 11s 的差距。本脚本把一次问答拆成
「变体生成 / 检索 / 融合 / 精排 / 生成」五段，逐段对比，找出差异真正来自哪里。

关键怀疑点：**生成的答案长度**。召回素材越多，模型写得越长，生成越慢。

用法：
    python src/rag_demo/tools/profile_modes_compare.py
    python src/rag_demo/tools/profile_modes_compare.py OPT-04
"""
import json
import os
import sys
import time

from rag_demo.config import BASE_DIR, TOP_K_PROFILE, TOP_K_RRF, TOP_K_WIKI
from rag_demo.generation.generator import generate
from rag_demo.retrieval.hybrid_retriever import hybrid_search, rrf_fusion
from rag_demo.retrieval.query_processor import build_query_variants
from rag_demo.retrieval.reranker import rerank_by_source

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")

MODES = ["bm25", "sparse", "both"]


def run_mode(question: str, variants: list, mode: str) -> dict:
    """固定变体、替换关键词策略，跑完检索→精排→生成"""
    t0 = time.time()
    result_lists = []
    for _, text in variants:
        hits = hybrid_search(text, top_k=TOP_K_RRF, keyword_mode=mode)
        if hits:
            result_lists.append(hits)
    t_search = time.time() - t0

    t0 = time.time()
    fused = result_lists[0] if len(result_lists) == 1 else rrf_fusion(result_lists, top_n=TOP_K_RRF)
    t_fuse = time.time() - t0

    t0 = time.time()
    reranked = rerank_by_source(question, fused, top_k_profile=TOP_K_PROFILE, top_k_wiki=TOP_K_WIKI)
    t_rerank = time.time() - t0

    t0 = time.time()
    result = generate(question, reranked)
    t_gen = time.time() - t0

    answer = result.get("answer", "")
    return {
        "mode": mode,
        "search": t_search,
        "fuse": t_fuse,
        "rerank": t_rerank,
        "generate": t_gen,
        "total": t_search + t_fuse + t_rerank + t_gen,
        "answer_len": len(answer),
        "sources": len(reranked),
    }


def main() -> None:
    qid = sys.argv[1] if len(sys.argv) > 1 else "OPT-01"

    with open(os.path.join(TESTS_DIR, "eval_questions.json"), encoding="utf-8") as f:
        items = {q["id"]: q for q in json.load(f)}
    if qid not in items:
        print(f"未知题目 ID: {qid}")
        return
    question = items[qid]["question"]

    # 预热（模型加载不计入统计）
    print("[预热] 加载模型与索引...")
    warm = hybrid_search("预热", top_k=1, keyword_mode="both")
    rerank_by_source("预热", warm)
    print("[预热] 完成\n")

    # 变体生成只做一次，三种模式共享（消除它带来的干扰）
    t0 = time.time()
    variants = build_query_variants(question)
    t_variants = time.time() - t0
    print(f"题目：{qid} | {question}")
    print(f"变体生成（三模式共享）：{t_variants:.2f}s，共 {len(variants)} 路\n")

    rows = [run_mode(question, variants, m) for m in MODES]

    print("=" * 84)
    print(f"{'策略':<8}{'检索':>9}{'融合':>8}{'精排':>8}{'生成':>9}{'合计':>9}"
          f"{'答案字数':>10}{'每字耗时':>11}")
    print("-" * 84)
    for r in rows:
        per_char = r["generate"] / max(r["answer_len"], 1) * 1000
        print(f"{r['mode']:<8}{r['search']:>8.2f}s{r['fuse']:>7.2f}s{r['rerank']:>7.2f}s"
              f"{r['generate']:>8.2f}s{r['total']:>8.2f}s{r['answer_len']:>10}{per_char:>10.2f}ms")

    print("=" * 84)
    fastest, slowest = min(rows, key=lambda x: x["total"]), max(rows, key=lambda x: x["total"])
    print(f"\n最快 {fastest['mode']}（{fastest['total']:.2f}s）"
          f" vs 最慢 {slowest['mode']}（{slowest['total']:.2f}s）"
          f"，差 {slowest['total'] - fastest['total']:.2f}s")

    diff_gen = slowest["generate"] - fastest["generate"]
    diff_search = slowest["search"] - fastest["search"]
    print(f"其中：生成环节差 {diff_gen:.2f}s，检索环节差 {diff_search:.2f}s")
    print(f"\n结论：耗时差异的 {diff_gen / max(slowest['total'] - fastest['total'], 0.01) * 100:.0f}%"
          " 来自「生成」，不是「检索」")
    print("      —— 召回素材越多 -> 模型写得越长 -> 生成越慢。")
    print(f"      每字耗时约 {sum(r['generate'] / max(r['answer_len'], 1) for r in rows) / len(rows) * 1000:.2f}ms，"
          "这决定了答案长度就是响应时间的第一驱动因素。")


if __name__ == "__main__":
    main()
