#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : profile_pipeline.py
@Function: 拆解一次问答的各环节耗时，定位真实瓶颈

用途：回答「五路检索为什么慢」这类问题——逐段计时，不靠猜测。
      脚本会先预热（加载模型），再跑两轮；**看第二轮的数值**，第一轮含有
      模型加载与 CUDA 首次分配的开销。

用法：
    python src/rag_demo/tools/profile_pipeline.py
    python src/rag_demo/tools/profile_pipeline.py OPT-04     # 指定题目
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


def run_once(qid: str, question: str, label: str) -> dict:
    print(f"\n{'=' * 68}\n【{label}】{qid} | {question}\n{'=' * 68}")

    # ① 变体生成：1 次 LLM 调用出 4 个变体
    t = time.time()
    variants = build_query_variants(question)
    t_variants = time.time() - t
    print(f"① 变体生成（1 次 LLM 调用）  : {t_variants:6.2f}s   产出 {len(variants)} 路")

    # ② 各路检索：逐个跑，单独计时
    all_hits = []
    t_search_total = 0.0
    for name, text in variants:
        t = time.time()
        hits = hybrid_search(text, top_k=TOP_K_RRF)
        dt = time.time() - t
        t_search_total += dt
        all_hits.append(hits)
        print(f"     检索[{name:<8}]      : {dt:6.2f}s   命中 {len(hits):>3} 条")

    print(f"② 检索合计（串行累加）       : {t_search_total:6.2f}s")

    # ③ RRF 融合
    t = time.time()
    fused = rrf_fusion(all_hits, top_n=TOP_K_RRF)
    t_fuse = time.time() - t
    print(f"③ RRF 融合                   : {t_fuse:6.2f}s   候选 {len(fused)} 条")

    # ④ 分来源精排（含 Parent Document 扩展）
    t = time.time()
    reranked = rerank_by_source(question, fused, top_k_profile=TOP_K_PROFILE, top_k_wiki=TOP_K_WIKI)
    t_rerank = time.time() - t
    print(f"④ 精排 + 文档扩展            : {t_rerank:6.2f}s   保留 {len(reranked)} 条")

    # ⑤ LLM 生成
    t = time.time()
    result = generate(question, reranked)
    t_gen = time.time() - t
    answer = result.get("answer", "")
    print(f"⑤ LLM 生成                   : {t_gen:6.2f}s   答案 {len(answer)} 字")

    total = t_variants + t_search_total + t_fuse + t_rerank + t_gen
    print(f"\n   合计 : {total:.2f}s")
    print(f"   占比 : 变体生成 {t_variants / total * 100:4.1f}% | "
          f"检索 {t_search_total / total * 100:4.1f}% | "
          f"融合 {t_fuse / total * 100:4.1f}% | "
          f"精排 {t_rerank / total * 100:4.1f}% | "
          f"生成 {t_gen / total * 100:4.1f}%")

    return {
        "variants": t_variants,
        "search": t_search_total,
        "fuse": t_fuse,
        "rerank": t_rerank,
        "generate": t_gen,
        "total": total,
        "answer_len": len(answer),
    }


def main() -> None:
    qid = sys.argv[1] if len(sys.argv) > 1 else "OPT-01"

    with open(os.path.join(TESTS_DIR, "eval_questions.json"), encoding="utf-8") as f:
        items = {q["id"]: q for q in json.load(f)}
    if qid not in items:
        print(f"未知题目 ID: {qid}")
        return
    question = items[qid]["question"]

    # 预热：把模型加载、CUDA 首次分配的开销排除在统计之外
    print("[预热] 加载模型与索引...")
    warm = hybrid_search("预热", top_k=1)
    rerank_by_source("预热", warm)
    print("[预热] 完成")

    run_once(qid, question, "第 1 轮（看数值，不看结论）")
    stats = run_once(qid, question, "第 2 轮 ★ 以这轮为准")

    print(f"\n{'=' * 68}")
    print("结论数据（第 2 轮）：")
    print(f"  五路检索本身只占 {stats['search']:.2f}s（{stats['search'] / stats['total'] * 100:.1f}%）")
    print(f"  变体生成占       {stats['variants']:.2f}s（{stats['variants'] / stats['total'] * 100:.1f}%）")
    print(f"  LLM 生成占       {stats['generate']:.2f}s（{stats['generate'] / stats['total'] * 100:.1f}%）")


if __name__ == "__main__":
    main()
