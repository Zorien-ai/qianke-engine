#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : check_search_index.py
@Function: 验证落库后的检索索引（search_index 表）

替代此前的 check_sparse_cache.py —— 本地 pkl 缓存机制已废弃，
现在要校验的是数据库里的索引：条数是否齐、两条召回通路是否都还通。

用法：
    uv run python src/rag_demo/tools/check_search_index.py
输出写入 search_index_check.txt，避免控制台 GBK 乱码。
"""
import io
import os
import time

from rag_demo.config import BASE_DIR, KEYWORD_RETRIEVER
from rag_demo.db.connection import close_conn
from rag_demo.db.schema import index_stats
from rag_demo.retrieval.hybrid_retriever import bm25_search, reload_bm25
from rag_demo.retrieval.sparse_retriever import sparse_search

OUT = os.path.join(BASE_DIR, "search_index_check.txt")

PROBES = [
    "钻石会员有什么权益",
    "高客单用户的判定标准",
    "用户投诉物流延迟怎么回复",
]


def main() -> None:
    lines = []
    lines.append("检索索引落库验证（search_index 表）")
    lines.append("=" * 70)

    # ---------- 1. 索引表概况 ----------
    st = index_stats()
    lines.append(f"索引表          : {st['table']}")
    lines.append(f"总条数          : {st['total']}")
    lines.append(f"sparse_weights 缺失: {st['missing_sparse']}")
    lines.append(f"bm25_tokens 缺失   : {st['missing_bm25']}")
    lines.append(f"更新时间        : {st['updated_from']} ~ {st['updated_to']}")
    lines.append(f"来源分布（共 {len(st['by_source'])} 类）:")
    for source, cnt in st["by_source"][:8]:
        lines.append(f"    {source}: {cnt}")
    if len(st["by_source"]) > 8:
        lines.append("    ...")
    lines.append("")

    # ---------- 2. BM25 加载（从库读分词结果 + 建内存索引） ----------
    t = time.time()
    reload_bm25()
    dt_load = time.time() - t
    lines.append(f"BM25 索引加载耗时: {dt_load:.2f}s（含从库读入分词结果）")
    lines.append(f"当前关键词召回模式: {KEYWORD_RETRIEVER}")
    lines.append("")

    # ---------- 3. 两条召回通路对比 ----------
    for q in PROBES:
        lines.append(f"【query】{q}")

        t = time.time()
        bm_hits = bm25_search(q, top_k=5)
        dt_bm = (time.time() - t) * 1000
        lines.append(f"  BM25（{dt_bm:.0f}ms，内存打分）:")
        for h in bm_hits:
            lines.append(f"      {h['score']:>8.4f}  {h['id']}  [{h['source']}]")

        t = time.time()
        sp_hits = sparse_search(q, top_k=5)
        dt_sp = (time.time() - t) * 1000
        lines.append(f"  稀疏向量（{dt_sp:.0f}ms，库内 sparsevec <#>）:")
        for h in sp_hits:
            lines.append(f"      {h['score']:>8.4f}  {h['id']}  [{h['source']}]")

        overlap = {h["id"] for h in bm_hits} & {h["id"] for h in sp_hits}
        lines.append(f"  两路重合 {len(overlap)} / 5 条")
        lines.append("")

    lines.append("=" * 70)
    lines.append("说明：稀疏检索耗时含 query 编码（模型前向），打分本身在库内完成。")

    close_conn()

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
