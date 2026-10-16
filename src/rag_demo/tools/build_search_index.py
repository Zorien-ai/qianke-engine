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
from typing import Callable

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

# 进度/阶段回调的签名与 ingest_data、ingest_docs 保持一致，构建任务用同一套接
ProgressFn = Callable[[int, int, str], None]   # (已完成, 总数, 阶段说明)
PhaseFn = Callable[[str, dict], None]          # (阶段名, 该阶段的真实数量)


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


def build_index(
    progress: ProgressFn | None = None,
    on_phase: PhaseFn | None = None,
) -> dict:
    """
    重建当前数据集的检索索引 —— **服务路径与脚本路径共用这一份**

    与 main() 分开的理由（不是洁癖，三条都是事故）：
        main() 末尾会 close_conn()——在服务里会把别的线程正在用的连接一起关掉；
        会把报告写进仓库根目录（脚本产物不该由服务产生）；
        自检不过时 raise SystemExit——那不是 HTTP 错误码，会直接打死工作线程。
    所以这里只「干活」，报告与退出码留给 main()。

    ⚠ 要求调用方已在 writes_to(...) 作用域内（本函数自己也会再校验一次，
    这样「import 后直接调用」同样当场抛 UnsafeWriteError，而不是先 TRUNCATE 再说）。

    进度分四段（语料 → 分词 → 稀疏编码 → 落库），前三段内部没有可切分的循环
    （一次全量），所以用 on_phase 报「做完了、多少条」；落库段按批回调 progress。
    """
    require_write_scope("build_search_index")

    timings: dict[str, float] = {}
    t_all = time.time()

    ensure_schema()

    t = time.time()
    corpus = load_corpus()
    timings["corpus"] = time.time() - t
    logger.info("语料条数: %d", len(corpus))
    if on_phase:
        on_phase("corpus_done", {"rows": len(corpus)})

    # ---------- 1. jieba 分词（BM25 用） ----------
    t = time.time()
    tokenized = [_tokenize(c["text"]) for c in corpus]
    timings["tokenize"] = time.time() - t
    logger.info("jieba 分词完成: %.2fs", timings["tokenize"])
    if on_phase:
        on_phase("tokenize_done", {"rows": len(corpus)})

    # ---------- 2. BGE-M3 稀疏编码 ----------
    t = time.time()
    weights_list = encode_sparse([c["text"] for c in corpus])
    timings["encode"] = time.time() - t
    logger.info("稀疏编码完成: %.2fs", timings["encode"])
    if on_phase:
        on_phase("encode_done", {"rows": len(corpus)})

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
        if progress:
            progress(min(i + BATCH, len(rows)), len(rows), "写入检索索引")
    # 指纹与索引行**同一事务**提交：写指纹失败就整体回滚，
    # 不留「行在、指纹没写」的中间态（那会让下次检查误报 unknown）
    write_fingerprint(cur, fingerprint)
    conn.commit()
    timings["db"] = time.time() - t
    logger.info("写入完成: %.2fs（%d 行）", timings["db"], len(rows))

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

    # ---------- 5. 稀疏检索自测（确认库内算子可用） ----------
    probe = corpus[0]["text"][:20] if corpus else ""
    probe_rows: list[tuple] = []
    if probe:
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

    # ---------- 6. 新鲜度自检：刚写入的指纹应立刻与源表一致 ----------
    # 不一致说明构建期间源表被改了（并发重导），本次索引可能已经落后
    fresh = index_freshness()
    logger.info("索引新鲜度: %s（%s）", fresh["status"], fresh["reason"])

    cur.close()
    timings["total"] = time.time() - t_all
    return {
        "corpus": len(corpus),
        "total": total,
        "missing_sparse": missing_sparse,
        "missing_bm25": missing_bm25,
        "empty_tokens": empty_tokens,
        "fresh": fresh,
        "probe": probe,
        "probe_rows": probe_rows,
        "timings": timings,
    }


def main() -> None:
    """脚本入口：只负责「报告 + 退出码」，干活在 build_index"""
    stats = build_index()
    tm = stats["timings"]

    lines = ["检索索引构建（search_index）", "=" * 70]
    lines.append(f"语料条数: {stats['corpus']}")
    lines.append(f"jieba 分词耗时: {tm['tokenize']:.2f}s")
    lines.append(f"稀疏编码耗时: {tm['encode']:.2f}s")
    lines.append(f"写库耗时: {tm['db']:.2f}s（{stats['total']} 行）")
    lines.append(f"回读条数: {stats['total']}")
    lines.append(f"sparse_weights 缺失: {stats['missing_sparse']}")
    lines.append(f"bm25_tokens 缺失: {stats['missing_bm25']}")
    lines.append(f"bm25_tokens 为空数组: {stats['empty_tokens']}")
    lines.append(f"索引新鲜度: {stats['fresh']['status']}（{stats['fresh']['reason']}）")
    lines.append(f"库内稀疏检索自测（query={stats['probe']!r}）:")
    for cid, neg_ip in stats["probe_rows"]:
        lines.append(f"    {cid}  score={-float(neg_ip):.4f}")
    lines.append(f"总耗时: {tm['total']:.2f}s")

    close_conn()

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written: {OUT}")
    for line in lines:
        print(line)

    # 自检没过就返回非零：本脚本是**显式**执行的，失败要让调用方（CI / 人）
    # 立刻知道，而不是只在日志里留一行
    if stats["fresh"]["status"] != FRESH:
        logger.error("索引自检未通过：%s", stats["fresh"]["reason"])
        raise SystemExit(1)


if __name__ == "__main__":
    # 显式声明写作用域：脚本入口写 demo 库（与改造前行为一致）。
    # 作用域会同时设置当前数据集，因此语料读取（user_profile_vectors / wiki_vectors）
    # 与索引写入落在同一个库上——索引一旦与源表不同库，检索结果是错的且不报错。
    with writes_to(DEFAULT_DATASET):
        main()
