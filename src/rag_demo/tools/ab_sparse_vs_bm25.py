#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : ab_sparse_vs_bm25.py
@Function: A/B 实验——BM25 关键词召回 vs BGE-M3 原生稀疏向量

背景
----
当前混合检索的「关键词那一路」用的是 BM25（jieba 分词 + 停用词 + 同义词归一）。
但 bge-m3 模型本身就能输出稀疏向量（learned sparse），理论上语义对齐更好。
两条路到底谁强？跑实验对比，不靠感觉。

做法
----
1. 把全部语料（画像 N 条 + 知识库分块 M 条）分别建两套索引
2. 对评测集每道题，各召回 top-K
3. 看「期望来源」有没有被召回到、排在第几名

为什么用「期望来源命中」当指标
----------------------------
每道评测题都标了 expect_sources（该看哪个文档/画像表）。
命中 = 该召回的料送到了；名次 = 送得够不够靠前（越靠前，后面精排压力越小）。
这是个能客观量化、又不需要人工打分的指标。

用法
----
    python src/rag_demo/tools/ab_sparse_vs_bm25.py
    可选参数：--topk 20 --limit 0（0 表示全部语料）
"""
import argparse
import json
import logging
import os
import pickle
import time

import numpy as np

from rag_demo.config import BASE_DIR, MODEL_PATH
from rag_demo.db.connection import get_conn
from rag_demo.retrieval.hybrid_retriever import _tokenize, reload_bm25, bm25_search

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")
CACHE_PATH = os.path.join(BASE_DIR, "sparse_cache.pkl")


def load_corpus():
    """从库里拉全部语料，与 BM25 语料保持一致（画像 + 文档分块）"""
    conn = get_conn()
    cur = conn.cursor()

    corpus = []
    cur.execute("SELECT user_id, profile_text FROM user_profile_vectors")
    for uid, text in cur.fetchall():
        corpus.append({"id": f"user:{uid}", "text": text, "source": "user_profile"})

    cur.execute("SELECT id, doc_name, chunk_text FROM wiki_vectors")
    for cid, doc, text in cur.fetchall():
        corpus.append({"id": f"wiki:{cid}", "text": text, "source": doc})

    cur.close()
    return corpus


def build_sparse_index(corpus, batch_size=64, force=False):
    """
    用 BGEM3FlagModel 给全部语料算稀疏权重

    结果缓存到磁盘——8110 条编码要几分钟，重复实验不该重复付这个代价。
    """
    if os.path.exists(CACHE_PATH) and not force:
        with open(CACHE_PATH, "rb") as f:
            cached = pickle.load(f)
        if len(cached) == len(corpus):
            print(f"[缓存] 复用稀疏向量索引（{len(cached)} 条）")
            return cached

    from FlagEmbedding import BGEM3FlagModel

    print(f"[编码] 正在用 bge-m3 计算稀疏向量（{len(corpus)} 条）...")
    model = BGEM3FlagModel(str(MODEL_PATH), use_fp16=True)

    texts = [c["text"] for c in corpus]
    t0 = time.time()
    output = model.encode(
        texts,
        batch_size=batch_size,
        max_length=512,
        return_dense=False,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    elapsed = time.time() - t0
    weights = output["lexical_weights"]

    print(f"[编码] 完成，耗时 {elapsed:.1f}s（{elapsed / max(len(texts), 1) * 1000:.1f} ms/条）")

    with open(CACHE_PATH, "wb") as f:
        pickle.dump(weights, f)
    return weights


def sparse_scores(query_weights: dict, corpus_weights: list) -> np.ndarray:
    """
    稀疏向量打分：查询与文档的 token 权重内积

    稀疏向量长这样 {token_id: weight}，只有几百个非零项——
    这也是它「稀疏」的含义：不用给整个词表都存一个数。
    """
    scores = np.zeros(len(corpus_weights), dtype=np.float32)
    for i, doc_w in enumerate(corpus_weights):
        s = 0.0
        for token, w in query_weights.items():
            dw = doc_w.get(token)
            if dw:
                s += w * dw
        scores[i] = s
    return scores


def rank_of_expect(hits: list[dict], expect: set[str]) -> int:
    """期望来源在命中列表里的最好名次（1 起；没命中返回 0）"""
    for rank, h in enumerate(hits, 1):
        if h["source"] in expect:
            return rank
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="BM25 vs BGE-M3 稀疏向量 A/B")
    parser.add_argument("--topk", type=int, default=20, help="每路召回数量")
    parser.add_argument("--force", action="store_true", help="强制重算稀疏向量缓存")
    args = parser.parse_args()

    # ---------- 语料 ----------
    corpus = load_corpus()
    print(f"[语料] 共 {len(corpus)} 条"
          f"（画像 {sum(1 for c in corpus if c['source'] == 'user_profile')}，"
          f"文档分块 {sum(1 for c in corpus if c['source'] != 'user_profile')}）")

    # ---------- BM25 ----------
    reload_bm25()
    print("[BM25] 索引就绪")

    # ---------- Sparse ----------
    sparse_corpus = build_sparse_index(corpus, force=args.force)

    from FlagEmbedding import BGEM3FlagModel
    model = BGEM3FlagModel(str(MODEL_PATH), use_fp16=True)

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

        # BM25
        t0 = time.time()
        bm_hits = bm25_search(question, top_k=args.topk)
        bm_ms = (time.time() - t0) * 1000
        bm_rank = rank_of_expect(bm_hits, expect)

        # Sparse
        t0 = time.time()
        q_out = model.encode([question], return_dense=False, return_sparse=True,
                             return_colbert_vecs=False)
        q_w = q_out["lexical_weights"][0]
        scores = sparse_scores(q_w, sparse_corpus)
        top_idx = np.argsort(scores)[::-1][: args.topk]
        sp_hits = [{"id": corpus[i]["id"], "source": corpus[i]["source"],
                    "score": float(scores[i])} for i in top_idx if scores[i] > 0]
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
    print(f"  Sparse : {sum(r['sp_ms'] for r in rows) / n:.1f} ms（含 query 编码）")

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
