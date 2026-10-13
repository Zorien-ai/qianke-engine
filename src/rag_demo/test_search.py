#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : test_search.py
@Function: 验证混合检索 + 精排效果（不调 LLM）
"""
from rag_demo.retrieval.hybrid_retriever import bm25_search, hybrid_search, vector_search
from rag_demo.retrieval.reranker import rerank

q = "高客单、喜欢美妆的女性用户"

print(f"查询：{q}\n")

vec = vector_search(q, top_k=20)
bm = bm25_search(q, top_k=20)
print(f"向量召回 {len(vec)} 条 / BM25 召回 {len(bm)} 条")

print("\n--- BM25 单独 Top-5 ---")
for i, c in enumerate(bm[:5], 1):
    print(f"[{i}] {c['source']}  bm25={c['score']:.4f}  {c['text'][:60]}...")

cands = hybrid_search(q, top_k=20)
print(f"\n--- RRF 融合 Top-10（共 {len(cands)} 条）---")
for i, c in enumerate(cands[:10], 1):
    print(f"[{i}] {c['source']}  RRF={c.get('rrf_score', 0):.4f}  {c['text'][:60]}...")

top5 = rerank(q, cands, top_k=5)
print("\n--- 精排后 Top-5 ---")
for i, c in enumerate(top5, 1):
    print(f"[{i}] 来源: {c['source']}  RRF: {c.get('rrf_score', 0):.4f}  Rerank: {c.get('rerank_score', 0):.4f}")
    print(f"    {c['text'][:100]}...")
