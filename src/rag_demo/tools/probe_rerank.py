#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : probe_rerank.py
@Function: 探测 rerank 分数分布，为「wiki 名额阈值」定标
"""
from rag_demo.retrieval.hybrid_retriever import hybrid_search
from rag_demo.retrieval.reranker import rerank

# (ID, query, 期望来源说明)
QUERIES = [
    ("OPT-02", "深圳的钻石会员都是什么特征", "仅 user_profile（wiki 应全无关）"),
    ("CS-04", "钻石会员有什么权益", "tag_definitions.md（知识库实际无此内容）"),
    ("CS-01", "用户说优惠券过期了怎么办", "cs_sop.md（wiki 正相关）"),
    ("OPT-01", "高客单、喜欢美妆的女性用户有哪些", "user_profile + tag_definitions.md"),
    ("DA-01", "哪些标签跟美妆相关", "tag_definitions.md（wiki 正相关）"),
]


def main() -> None:
    print(f"{'query':<28} {'kind':<5} {'score':>9}  source")
    print("-" * 70)

    for qid, q, expect in QUERIES:
        cands = hybrid_search(q, top_k=30)
        reranked = rerank(q, cands, top_k=len(cands))

        wikis = [c for c in reranked if c["source"].endswith(".md")]
        profiles = [c for c in reranked if not c["source"].endswith(".md")]
        wiki_max = max((c["rerank_score"] for c in wikis), default=float("-inf"))
        prof_max = max((c["rerank_score"] for c in profiles), default=float("-inf"))

        print(f"\n### {qid} | {q}")
        print(f"    期望: {expect}")
        print(f"    wiki 候选 {len(wikis)} 条（最高 {wiki_max:.3f}） | profile 候选 {len(profiles)} 条（最高 {prof_max:.3f}）")
        print(f"    wiki 分数: {[round(c['rerank_score'], 2) for c in wikis]}")
        print(f"    top5 明细:")
        for c in reranked[:5]:
            kind = "wiki" if c["source"].endswith(".md") else "prof"
            print(f"      {c['rerank_score']:>8.3f}  [{kind}] {c['source']}")


if __name__ == "__main__":
    main()
