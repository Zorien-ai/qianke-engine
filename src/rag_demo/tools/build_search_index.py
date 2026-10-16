#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : build_search_index.py
@Function: 构建检索索引表 search_index（BM25 分词结果 + BGE-M3 稀疏权重）

取代此前的本地 pkl 缓存：
  - BM25 分词结果落库，服务启动时读回内存即可，免去重新 jieba 分词
  - 稀疏权重以 pgvector sparsevec 落库，检索可直接在库内完成

语料口径与 sparse_retriever._build_corpus 保持一致（画像表 + 文档表），
保证落库前后检索结果可比。

写入策略：先算完再「TRUNCATE + 批量 INSERT」，整个过程在同一事务内，
构建失败会回滚保留旧索引，不会出现空表窗口。

用法：
    uv run python src/rag_demo/tools/build_search_index.py
"""
import io
import logging
import os
import time

from psycopg2.extras import execute_values

from rag_demo.config import BASE_DIR, DEFAULT_DATASET, SEARCH_INDEX_TABLE, SPARSE_VEC_DIM
from rag_demo.db.connection import (
    close_conn,
    get_conn,
    require_write_scope,
    writes_to,
)
from rag_demo.db.schema import (
    FRESH,
    current_fingerprint,
    ensure_schema,
    index_freshness,
    write_fingerprint,
)
from rag_demo.retrieval.hybrid_retriever import _tokenize
from rag_demo.retrieval.sparse_retriever import encode_sparse, weights_to_sparsevec

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

BATCH = 256
OUT = os.path.join(BASE_DIR, "build_search_index.txt")


def load_corpus() -> list[dict]:
    """语料 = 画像文本 + 知识库分块，与 sparse_retriever._build_corpus 同源"""
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


def main() -> None:
    # 写操作守卫：本脚本会 TRUNCATE search_index，属于破坏性写操作，必须由入口显式
    # 声明目标数据集（见文件末尾的 __main__）。import 后直接调 main() 会当场抛
    # UnsafeWriteError——索引表与源表同库这件事，靠「声明」保证，不靠调用方记得。
    require_write_scope("build_search_index")

    lines = ["检索索引构建（search_index）", "=" * 70]
    t_all = time.time()

    ensure_schema()

    corpus = load_corpus()
    logger.info("语料条数: %d", len(corpus))
    lines.append(f"语料条数: {len(corpus)}")

    # ---------- 1. jieba 分词（BM25 用） ----------
    t = time.time()
    tokenized = [_tokenize(c["text"]) for c in corpus]
    dt_tokenize = time.time() - t
    logger.info("jieba 分词完成: %.2fs", dt_tokenize)
    lines.append(f"jieba 分词耗时: {dt_tokenize:.2f}s")

    # ---------- 2. BGE-M3 稀疏编码 ----------
    t = time.time()
    weights_list = encode_sparse([c["text"] for c in corpus])
    dt_encode = time.time() - t
    logger.info("稀疏编码完成: %.2fs", dt_encode)
    lines.append(f"稀疏编码耗时: {dt_encode:.2f}s")

    # ---------- 3. 落库（同一事务：先清空再批量写入） ----------
    rows = [
        (
            c["id"],
            c["source"],
            c["text"],
            tokens,
            weights_to_sparsevec(weights, SPARSE_VEC_DIM),
        )
        for c, tokens, weights in zip(corpus, tokenized, weights_list)
    ]

    # 本次构建对应的语料指纹：落库后据此判断「索引是否落后于源表」。
    # 在开写事务之前取，避免在事务里再开一条连接读源表。
    fingerprint = current_fingerprint()

    conn = get_conn()
    cur = conn.cursor()

    t = time.time()
    cur.execute(f"TRUNCATE {SEARCH_INDEX_TABLE}")
    for i in range(0, len(rows), BATCH):
        execute_values(
            cur,
            f"""INSERT INTO {SEARCH_INDEX_TABLE}
                (corpus_id, source, text, bm25_tokens, sparse_weights)
                VALUES %s""",
            rows[i:i + BATCH],
            template="(%s, %s, %s, %s, %s::sparsevec)",
        )
    # 指纹与索引行**同一事务**提交：写指纹失败就整体回滚，
    # 不留「行在、指纹没写」的中间态（那会让下次检查误报 unknown）
    write_fingerprint(cur, fingerprint)
    conn.commit()
    dt_db = time.time() - t
    logger.info("写入完成: %.2fs（%d 行）", dt_db, len(rows))
    lines.append(f"写库耗时: {dt_db:.2f}s（{len(rows)} 行）")

    # ---------- 4. 回读校验 ----------
    cur.execute(f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE}")
    total = cur.fetchone()[0]
    cur.execute(
        f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE} WHERE sparse_weights IS NULL"
    )
    missing_sparse = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE} WHERE bm25_tokens IS NULL")
    missing_bm25 = cur.fetchone()[0]
    cur.execute(
        f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE} WHERE array_length(bm25_tokens, 1) = 0"
    )
    empty_tokens = cur.fetchone()[0]
    conn.rollback()

    lines.append(f"回读条数: {total}")
    lines.append(f"sparse_weights 缺失: {missing_sparse}")
    lines.append(f"bm25_tokens 缺失: {missing_bm25}")
    lines.append(f"bm25_tokens 为空数组: {empty_tokens}")

    # ---------- 4.5 新鲜度自检：刚写入的指纹应立刻与源表一致 ----------
    # 不一致说明构建期间源表被改了（并发重导），本次索引可能已经落后
    fresh = index_freshness()
    lines.append(f"索引新鲜度: {fresh['status']}（{fresh['reason']}）")
    logger.info("索引新鲜度: %s（%s）", fresh["status"], fresh["reason"])

    # ---------- 5. 稀疏检索自测（确认库内算子可用） ----------
    probe = corpus[0]["text"][:20]
    probe_vec = weights_to_sparsevec(encode_sparse([probe])[0], SPARSE_VEC_DIM)
    cur.execute(
        f"""SELECT corpus_id, sparse_weights <#> %s::sparsevec AS neg_ip
            FROM {SEARCH_INDEX_TABLE}
            WHERE sparse_weights IS NOT NULL
            ORDER BY sparse_weights <#> %s::sparsevec
            LIMIT 3""",
        (probe_vec, probe_vec),
    )
    probe_rows = cur.fetchall()
    conn.rollback()
    lines.append(f"库内稀疏检索自测（query={probe!r}）:")
    for cid, neg_ip in probe_rows:
        lines.append(f"    {cid}  score={-float(neg_ip):.4f}")

    lines.append(f"总耗时: {time.time() - t_all:.2f}s")

    cur.close()
    close_conn()

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written: {OUT}")
    for line in lines:
        print(line)

    # 自检没过就返回非零：本脚本是**显式**执行的，失败要让调用方（CI / 人）
    # 立刻知道，而不是只在日志里留一行
    if fresh["status"] != FRESH:
        logger.error("索引自检未通过：%s", fresh["reason"])
        raise SystemExit(1)


if __name__ == "__main__":
    # 显式声明写作用域：脚本入口写 demo 库（与改造前行为一致）。
    # 作用域会同时设置当前数据集，因此语料读取（user_profile_vectors / wiki_vectors）
    # 与索引写入落在同一个库上——索引一旦与源表不同库，检索结果是错的且不报错。
    with writes_to(DEFAULT_DATASET):
        main()
