#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : sparse_retriever.py
@Function: BGE-M3 原生稀疏向量检索（库内检索版）

与 BM25 的关系
--------------
两者都产出「词 -> 权重」的稀疏表示，区别在权重从哪来：

    BM25      数词频，按词的罕见程度（IDF）加权 —— 不需要模型，纯统计
    稀疏向量   权重由 bge-m3 训练学出来 —— 需要一次模型前向

A/B 实验（见 bug/10.11/2026-10-11_BM25对BGE-M3稀疏向量实验.md）显示各有强项：

    BM25     强在罕见结构词（「标签」），弱在泛词干扰（「规模」）、空词白给权重（「本周」）
    稀疏向量  强在核心实体（「高价值」），弱在漏掉结构词、被语义强词带偏（「美妆」）

所以两者不做「二选一」，而是做成可切换、可组合的选项（见 config.KEYWORD_RETRIEVER）。

存储与检索
----------
索引以 pgvector 的 sparsevec 类型存在 search_index 表，打分用 `<#>`（负内积）
直接在库内完成，替代此前的「本地 pkl + Python 全量遍历」：

    旧：8146 条权重常驻内存，每次查询用 Python 双重循环逐条算内积（热态约 70ms）
    新：索引留在库里，查询只需编码一次 query，打分交给 pgvector

收益：内存占用归零、多实例天然共享同一份索引、一致性由数据库保证
     （不再依赖内容指纹去猜缓存是否过期）。
代价：索引更新必须重跑 tools/build_search_index.py，没有「下次加载自动失效」了。
"""
import logging
import threading

from rag_demo.config import MODEL_PATH, SEARCH_INDEX_TABLE, SPARSE_VEC_DIM, TOP_K_BM25
from rag_demo.db.connection import get_conn

logger = logging.getLogger(__name__)

_model = None

# 模型初始化加锁做双重检查：服务启动时的预热线程与首个请求可能同时触发加载，
# 不加锁会各加载一遍——既浪费显存、争抢 GPU，请求也照样慢（这个问题真实发生过）。
_model_lock = threading.Lock()


def get_sparse_model():
    """加载 BGEM3FlagModel（单例，首次约 4s）"""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # 可能已被其它线程加载完成
                from FlagEmbedding import BGEM3FlagModel

                logger.info("正在加载 bge-m3 稀疏向量模型（use_fp16=True）...")
                _model = BGEM3FlagModel(str(MODEL_PATH), use_fp16=True)
    return _model


def encode_sparse(texts: list[str], batch_size: int = 64) -> list[dict]:
    """把文本编码成稀疏权重：[{token_id: weight}, ...]"""
    model = get_sparse_model()
    out = model.encode(
        texts,
        batch_size=batch_size,
        max_length=512,
        return_dense=False,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    return out["lexical_weights"]


def weights_to_sparsevec(weights: dict, dim: int = SPARSE_VEC_DIM) -> str:
    """
    把 {token_id: weight} 转成 pgvector sparsevec 的文本字面量

    格式：'{4:0.2246,1062:0.154}/250002'

    下标直接用 token_id——查询与文档走同一映射，只要两侧一致即可对齐
    （实测 token_id 最小为 4，不会踩到 sparsevec 从 1 开始的下标约定）。
    """
    if not weights:
        return f"{{}}/{dim}"
    body = ",".join(f"{int(k)}:{float(v):.6g}" for k, v in weights.items())
    return f"{{{body}}}/{dim}"


def sparse_search(query: str, top_k: int = TOP_K_BM25) -> list[dict]:
    """
    稀疏向量召回（库内计算）

    pgvector 的 `<#>` 返回**负内积**，升序即内积降序，故取负还原成相似度。
    返回结构与 bm25_search 完全一致，便于上层直接互换或融合。

    只保留内积 > 0 的候选，与旧实现的 `if scores[i] > 0` 口径一致。
    """
    q_weights = encode_sparse([query])[0]
    if not q_weights:
        return []

    q_vec = weights_to_sparsevec(q_weights)

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""SELECT corpus_id, source, text,
                       sparse_weights <#> %s::sparsevec AS neg_ip
                FROM {SEARCH_INDEX_TABLE}
                WHERE sparse_weights IS NOT NULL
                ORDER BY sparse_weights <#> %s::sparsevec
                LIMIT %s""",
            (q_vec, q_vec, top_k),
        )
        rows = cur.fetchall()
    except Exception as e:
        # 索引表可能还没建：给一句可操作的提示，而不是把 psycopg 堆栈抛给调用方
        raise RuntimeError(
            f"稀疏检索失败（索引表 {SEARCH_INDEX_TABLE}）: {e}；"
            f"请先运行 tools/build_search_index.py 构建索引"
        ) from e
    finally:
        conn.rollback()  # 清理查询事务，避免连接停在 idle in transaction
        cur.close()

    results = []
    for corpus_id, source, text, neg_ip in rows:
        score = -float(neg_ip)
        if score > 0:
            results.append({
                "id": corpus_id,
                "text": text,
                "source": source,
                "score": score,
            })
    return results


def prewarm() -> None:
    """预热稀疏模型（索引在库内无需预热，模型首次加载约 4s）"""
    get_sparse_model()
