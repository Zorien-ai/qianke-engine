#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : ab_sparse_vs_bm25.py
@Function: A/B 实验——BM25 关键词召回 vs BGE-M3 原生稀疏向量（在线链路版）

背景
----
当前混合检索的「关键词那一路」用的是 BM25（jieba 分词 + 停用词 + 同义词归一）。
但 bge-m3 模型本身就能输出稀疏向量（learned sparse），理论上语义对齐更好。
两条路到底谁强？跑实验对比，不靠感觉。

改版说明（2026-10-14）
--------------------
本脚本此前自己维护一套稀疏向量：用 BGEM3FlagModel 给 8146 条语料现算权重、
pickle 落盘到 sparse_cache.pkl，再用 Python 双重循环逐条算内积。

问题是**它测的不是线上那条路**——线上走的是 sparse_retriever.sparse_search()，
索引存在 search_index 表、打分交给 pgvector 的 sparsevec（P7 的改造结果）。
自维护那套在 P7 之后已经没人用了，跑出来的结论对线上没有约束力。

现在直接调用两个**线上函数**：
    bm25_search()    —— hybrid_retriever：读 search_index.bm25_tokens，内存 BM25 打分
    sparse_search()  —— sparse_retriever：读 search_index.sparse_weights，库内 sparsevec 打分

顺带删掉的东西：本地 pkl 缓存、全量语料编码（约 27s）、约 120 行自维护索引代码。
而且两者读的是同一张表，语料口径天然一致，不会再出现「两套语料比来比去」。

做法
----
1. 先确认 search_index 表里 BM25 分词与稀疏权重都存在（缺稀疏索引就没法比）
2. 对评测集每道题，两条路各召回 top-K
3. 看「期望来源」有没有被召回到、排在第几名

为什么用「期望来源命中」当指标
----------------------------
每道评测题都标了 expect_sources（该看哪个文档/画像表）。
命中 = 该召回的料送到了；名次 = 送得够不够靠前（越靠前，后面精排压力越小）。
这是个能客观量化、又不需要人工打分的指标。

用法
----
    uv run python src/rag_demo/tools/ab_sparse_vs_bm25.py
    可选参数：--topk 20

局限（读数前必须先知道）
----------------------
只测「召回」这一环，不含精排与生成。后面还有 bge-reranker 分池精排
（画像 Top-3 / 文档 Top-2），**前 20 名内的名次差基本会被精排纠正**，
所以本实验的「名次」差异不能直接等同于最终答案质量差异。
"""
import argparse
import json
import logging
import os
import time

from rag_demo.config import BASE_DIR, SEARCH_INDEX_TABLE
from rag_demo.db.connection import get_conn
from rag_demo.retrieval.hybrid_retriever import bm25_search, reload_bm25
from rag_demo.retrieval.sparse_retriever import prewarm, sparse_search

logging.basicConfig(level=logging.WARNING)

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")


def check_index() -> tuple[int, int, int]:
    """
    确认索引表里两种索引都在

    返回 (总数, 有 bm25_tokens 的条数, 有 sparse_weights 的条数)。
    稀疏索引缺失时实验无从谈起——与其跑出一堆「稀疏没命中」的假结论，
    不如直接报错，这种静默降级之前吃过亏。
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT COUNT(*), COUNT(bm25_tokens), COUNT(sparse_weights) "
            f"FROM {SEARCH_INDEX_TABLE}"
        )
        return cur.fetchone()
    finally:
        conn.rollback()
        cur.close()


def rank_of_expect(hits: list[dict], expect: set[str]) -> int:
    """期望来源在命中列表里的最好名次（1 起；没命中返回 0）"""
    for rank, h in enumerate(hits, 1):
        if h["source"] in expect:
            return rank
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="BM25 vs BGE-M3 稀疏向量 A/B（在线链路）")
    parser.add_argument("--topk", type=int, default=20, help="每路召回数量")
    args = parser.parse_args()

    # ---------- 索引 ----------
    total, bm25_n, sparse_n = check_index()
    print(f"[索引] {SEARCH_INDEX_TABLE}: 共 {total} 条"
          f" | bm25_tokens {bm25_n} | sparse_weights {sparse_n}")
    if not sparse_n:
        raise SystemExit(
            f"索引表 {SEARCH_INDEX_TABLE} 里没有 sparse_weights，稀疏检索无从比对。\n"
            f"请先运行：uv run python src/rag_demo/tools/build_search_index.py"
        )
    if bm25_n != sparse_n:
        print(f"[警告] 两种索引覆盖条数不一致（{bm25_n} vs {sparse_n}），结果不可比")

    reload_bm25()
    print("[BM25] 索引就绪（来自 search_index）")

    # 预热稀疏模型：不预热的话，首次调用会把约 4s 的模型加载算进第一条的耗时，
    # 23 条平均下来凭空多出约 170ms——「稀疏慢」会因此被高估。
    prewarm()
    print("[Sparse] 模型就绪")

    # ---------- 评测题 ----------
    with open(os.path.join(TESTS_DIR, "eval_questions.json"), encoding="utf-8") as f:
        questions = json.load(f)
    # 只取有期望来源的题（缺口题 expect 为空，不参与命中率统计）
    questions = [q for q in questions if q.get("expect_sources")]

    print(f"\n[评测] 参与对比的问题：{len(questions)} 条\n")
    print("=" * 100)

    rows = []
    for q in questions:
        question = q["question"]
        expect = set(q["expect_sources"])

        # BM25（在线：hybrid_retriever.bm25_search）
        t0 = time.time()
        bm_hits = bm25_search(question, top_k=args.topk)
        bm_ms = (time.time() - t0) * 1000
        bm_rank = rank_of_expect(bm_hits, expect)

        # 稀疏（在线：sparse_retriever.sparse_search，含 query 编码）
        t0 = time.time()
        sp_hits = sparse_search(question, top_k=args.topk)
        sp_ms = (time.time() - t0) * 1000
        sp_rank = rank_of_expect(sp_hits, expect)

        rows.append({
            "id": q["id"], "question": question, "expect": sorted(expect),
            "bm_rank": bm_rank, "sp_rank": sp_rank,
            "bm_ms": bm_ms, "sp_ms": sp_ms,
            "bm_top": [h["source"] for h in bm_hits[:3]],
            "sp_top": [h["source"] for h in sp_hits[:3]],
        })
        print(f"{q['id']:<9} 期望={','.join(sorted(expect)):<38} "
              f"BM25 名次={bm_rank:<3} Sparse 名次={sp_rank:<3}")

    # ---------- 汇总 ----------
    def hit_rate(key):
        return sum(1 for r in rows if r[key] > 0)

    def avg_rank(key):
        ranks = [r[key] for r in rows if r[key] > 0]
        return sum(ranks) / len(ranks) if ranks else 0

    n = len(rows)
    print("=" * 100)
    print(f"\n【命中率】top-{args.topk} 内是否召回期望来源")
    print(f"  BM25   : {hit_rate('bm_rank')}/{n} = {hit_rate('bm_rank') / n * 100:.1f}%")
    print(f"  Sparse : {hit_rate('sp_rank')}/{n} = {hit_rate('sp_rank') / n * 100:.1f}%")

    print(f"\n【平均名次】命中时的平均排名（越小越好）")
    print(f"  BM25   : {avg_rank('bm_rank'):.1f}")
    print(f"  Sparse : {avg_rank('sp_rank'):.1f}")

    print(f"\n【查询耗时】单次检索平均")
    print(f"  BM25   : {sum(r['bm_ms'] for r in rows) / n:.1f} ms（内存索引，不含编码）")
    print(f"  Sparse : {sum(r['sp_ms'] for r in rows) / n:.1f} ms（库内打分，含 query 编码）")

    # 逐题差异
    print(f"\n【谁更好】逐题对比")
    only_bm = [r["id"] for r in rows if r["bm_rank"] > 0 and r["sp_rank"] == 0]
    only_sp = [r["id"] for r in rows if r["sp_rank"] > 0 and r["bm_rank"] == 0]
    both = [r for r in rows if r["bm_rank"] > 0 and r["sp_rank"] > 0]
    bm_better = [r["id"] for r in both if r["bm_rank"] < r["sp_rank"]]
    sp_better = [r["id"] for r in both if r["sp_rank"] < r["bm_rank"]]

    print(f"  只有 BM25 命中 : {only_bm or '无'}")
    print(f"  只有 Sparse 命中: {only_sp or '无'}")
    print(f"  都命中时 BM25 更靠前 : {bm_better or '无'}")
    print(f"  都命中时 Sparse 更靠前: {sp_better or '无'}")

    out_path = os.path.join(BASE_DIR, "ab_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"\n[输出] 逐题明细已写入 {out_path}")


if __name__ == "__main__":
    main()
