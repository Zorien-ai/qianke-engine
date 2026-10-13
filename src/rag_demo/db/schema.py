#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : schema.py
@Function: 检索索引表 search_index 的建表与状态查询

为什么单独建表，而不是往 user_profile_vectors / wiki_vectors 加列：
  bm25_tokens 与 sparse_weights 都是**派生数据**，随时可由源表重建。
  独立存放的好处是——不会被 ingest 脚本的 TRUNCATE 连带清掉，
  且可单独重建、单独监控，源表保持"业务数据"的纯粹语义。

稀疏权重用 pgvector 原生 sparsevec 类型（而非 JSONB），
这样稀疏检索能直接在库内完成，不必把 8146 条权重拉进内存。
"""
import logging

from rag_demo.config import SEARCH_INDEX_TABLE, SPARSE_VEC_DIM
from rag_demo.db.connection import get_conn

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {SEARCH_INDEX_TABLE} (
    corpus_id       VARCHAR(64)  PRIMARY KEY,
    source          VARCHAR(128) NOT NULL,
    text            TEXT         NOT NULL,
    bm25_tokens     TEXT[],
    sparse_weights  sparsevec({SPARSE_VEC_DIM}),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
)
"""

CREATE_INDEX_SQL = [
    f"CREATE INDEX IF NOT EXISTS idx_{SEARCH_INDEX_TABLE}_source "
    f"ON {SEARCH_INDEX_TABLE} (source)",
]

# 运行期是否用 HNSW 近邻索引加速稀疏检索。
# 当前语料 8146 条，精确全表扫描已足够快；HNSW 是近似算法，
# 会带来「检索结果与精确内积不一致」的风险，故默认不建，留待规模上去再启用。
ENABLE_SPARSE_HNSW = False

HNSW_SQL = (
    f"CREATE INDEX IF NOT EXISTS idx_{SEARCH_INDEX_TABLE}_sparse "
    f"ON {SEARCH_INDEX_TABLE} USING hnsw (sparse_weights sparsevec_ip_ops)"
)


def ensure_schema() -> None:
    """
    幂等建表 + 建索引，**立即提交**

    必须提交，不能把 DDL 留在事务里：get_conn() 每次探活都会 rollback
    未提交事务，后续任何一次取连接都会把建表悄悄冲掉（已实际踩过）。
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(CREATE_TABLE_SQL)
        for sql in CREATE_INDEX_SQL:
            cur.execute(sql)
        if ENABLE_SPARSE_HNSW:
            cur.execute(HNSW_SQL)
        conn.commit()
        logger.info("检索索引表 %s 已就绪", SEARCH_INDEX_TABLE)
    finally:
        cur.close()


def index_stats() -> dict:
    """索引表概况：条数 / 来源分布 / 更新时间 / 缺失列统计"""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE}")
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT source, COUNT(*) FROM {SEARCH_INDEX_TABLE} "
            f"GROUP BY source ORDER BY COUNT(*) DESC"
        )
        by_source = cur.fetchall()

        cur.execute(f"SELECT MIN(updated_at), MAX(updated_at) FROM {SEARCH_INDEX_TABLE}")
        updated_from, updated_to = cur.fetchone()

        cur.execute(
            f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE} WHERE sparse_weights IS NULL"
        )
        missing_sparse = cur.fetchone()[0]

        cur.execute(
            f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE} WHERE bm25_tokens IS NULL"
        )
        missing_bm25 = cur.fetchone()[0]
    finally:
        conn.rollback()
        cur.close()

    return {
        "table": SEARCH_INDEX_TABLE,
        "total": total,
        "by_source": by_source,
        "updated_from": updated_from,
        "updated_to": updated_to,
        "missing_sparse": missing_sparse,
        "missing_bm25": missing_bm25,
    }
