#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : hybrid_retriever.py
@Function: 向量召回 + BM25 关键词召回 + RRF 融合
"""
import logging
import re

import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

from rag_demo.config import (
    DEVICE,
    DTYPE,
    KEYWORD_RETRIEVER,
    MODEL_PATH,
    SEARCH_INDEX_TABLE,
    TOP_K_BM25,
    TOP_K_RRF,
    TOP_K_VECTOR,
)
from rag_demo.db.connection import current_dataset, get_conn

# 稀疏检索依赖 FlagEmbedding；未安装时降级为仅 BM25，不影响主流程
try:
    from rag_demo.retrieval.sparse_retriever import sparse_search
except ImportError:  # pragma: no cover
    sparse_search = None

logger = logging.getLogger(__name__)

jieba.setLogLevel(20)  # 关掉 jieba 初始化日志

# 纯标点/空白 token 过滤器
_PUNCT_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)

# BM25 停用词：画像文本为统一模板，这些词在几乎所有条目中普遍出现，只会引入噪声
STOPWORDS = {
    "用户", "累计", "订单", "总消费", "消费", "平均", "客单价", "偏好",
    "品类", "最近", "一次", "购买", "活跃", "平台", "元", "笔", "在",
    "人", "岁", "的", "了", "为", "：", "，", "。", "（", "）", "｜",
    # 按 jieba 实际切分粒度补的模板碎片（「平均客单价」实际切成「客」+「单价」）
    "总", "客", "单价",
}

# 保留的单字 token：性别单字有检索价值，其余单字多为姓氏/模板碎片噪声
KEEP_SINGLE = {"男", "女"}

# 同义词归一：画像文本写作「女/男」，查询习惯说「女性/男性」
SYNONYMS = {"女性": "女", "男性": "男", "女士": "女", "男士": "男", "妹子": "女"}

# 模型与内存索引进程级常驻；数据库连接统一由 rag_demo.db.connection 管理
_model = None

# BM25 内存索引**按数据集各存一份**（键 = 数据集名，见 config.DATASETS）。
#
# 改造前这里是单个全局变量。分库之后继续共用会出新问题：用户构建完调用
# reload_bm25() 会用**用户库**的语料把 demo 的内存索引顶掉，而 demo 的向量检索
# 仍在查 demo 库——于是「两者组合」变成一半数据来自 demo、一半来自用户数据，
# 且**不报任何错**。这类"静默串数据"正是分库要防的东西，所以内存态必须跟着分。
_bm25: dict[str, "BM25Okapi"] = {}
_bm25_corpus: dict[str, list[dict]] = {}


# TODO(perf): [P3] 模型单例常驻不释放——两个模型约占 6GB 显存的 73%，
#             导致无法与离线实验（如 A/B 脚本）并行运行。需补卸载机制或空闲超时释放。
#             详见 bug/性能隐患台账.md
def get_model():
    global _model
    if _model is None:
        logger.info(f"正在加载 bge-m3 模型（device={DEVICE}, dtype={DTYPE}）...")
        _model = SentenceTransformer(
            str(MODEL_PATH),
            device=DEVICE,
            model_kwargs={"dtype": DTYPE},
        )
    return _model


def _tokenize(text):
    """中文分词（jieba）：同义词归一 -> 过滤空白/标点/停用词/单字碎片"""
    tokens = []
    for tok in jieba.lcut(text or ""):
        tok = SYNONYMS.get(tok, tok)
        if not tok.strip() or _PUNCT_ONLY.match(tok) or tok in STOPWORDS:
            continue
        if len(tok) == 1 and tok not in KEEP_SINGLE:
            continue
        tokens.append(tok)
    return tokens


# TODO(perf): [P5] 全量语料 + 分词结果常驻内存。当前规模（8146 条）无感知，
#             属预防性记录；语料涨到十万级时需考虑分片或持久化倒排。
#             详见 bug/性能隐患台账.md
def _load_bm25_corpus(force=False, dataset: str | None = None):
    """
    从 search_index 表加载语料与分词结果，构建 BM25 索引

    分词结果已由 build_search_index.py 落库，这里直接读回——省掉每次启动
    对 8146 条文本重新 jieba 分词的开销（实测约 6s）。

    与旧实现的差别仅在数据来源：以前是「查源表 + 现场分词」，
    现在是「查索引表，分词结果现成」。语料口径完全一致。

    dataset 不传 = 当前 contextvar 里的数据集；缓存也按它分开存。
    """
    name = dataset or current_dataset()
    if name in _bm25 and not force:
        return

    conn = get_conn(name)
    cur = conn.cursor()
    try:
        cur.execute(
            f"SELECT corpus_id, source, text, bm25_tokens "
            f"FROM {SEARCH_INDEX_TABLE} WHERE bm25_tokens IS NOT NULL"
        )
        rows = cur.fetchall()
    finally:
        conn.rollback()  # 清理查询事务，避免连接停在 idle in transaction
        cur.close()

    if not rows:
        raise RuntimeError(
            f"数据集 {name} 的检索索引表 {SEARCH_INDEX_TABLE} 为空，请先运行 "
            f"python src/rag_demo/tools/build_search_index.py 构建索引"
        )

    _bm25_corpus[name] = [
        {"id": corpus_id, "text": text, "source": source}
        for corpus_id, source, text, _ in rows
    ]
    tokenized = [list(tokens) for _, _, _, tokens in rows]
    _bm25[name] = BM25Okapi(tokenized)

    # 分词结果既然来自库，本函数就不再调用 jieba——但查询侧的 bm25_search 仍要用，
    # 而 jieba 首次调用要加载词典（实测约 1.2s）。这里主动触发一次，
    # 免得这 1.2s 落到第一个用户请求上（改成库内索引后新引入的坑）。
    _tokenize("预热")

    logger.info("BM25 索引加载完成: %d 条（来自 %s 表，数据集 %s）",
                len(_bm25_corpus[name]), SEARCH_INDEX_TABLE, name)


def reload_bm25(dataset: str | None = None):
    """
    强制重建 BM25 内存索引（数据更新后调用）

    dataset 不传 = 当前数据集。**只影响这一个数据集的缓存**，
    动 demo 不会碰到 user 的内存索引（反之亦然）。
    """
    _load_bm25_corpus(force=True, dataset=dataset)


def vector_search(query, top_k=TOP_K_VECTOR, dept=None, sensitivity_max=3):
    """
    向量召回

    读完后**必须回滚事务**：psycopg2 的 cur.close() 并不会结束事务，
    连接会停在 `idle in transaction` 并持续持有 AccessShareLock——
    实测这会阻塞 ingest 侧的 ALTER TABLE / CREATE INDEX，一卡就是几十分钟
    （2026-10-12 数据重导时踩到：一个闲置连接把 wiki_vectors 的排他锁堵死）。
    """
    model = get_model()
    qvec = model.encode(query)
    conn = get_conn()
    cur = conn.cursor()

    try:
        sql = """
            SELECT id, user_id, profile_text, 'user_profile' AS source,
                   1 - (embedding <=> %s::vector) AS score
            FROM user_profile_vectors
            WHERE sensitivity <= %s
        """
        params = [qvec, sensitivity_max]
        if dept:
            sql += " AND dept = %s"
            params.append(dept)
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.extend([qvec, top_k])

        cur.execute(sql, params)
        results = []
        for row in cur.fetchall():
            results.append({
                "id": f"user:{row[1]}",
                "text": row[2],
                "source": row[3],
                "score": float(row[4]),
            })

        # wiki 表（无 dept 过滤，Demo 简化）
        cur.execute("""
            SELECT id, doc_name, chunk_text, 1 - (embedding <=> %s::vector) AS score
            FROM wiki_vectors
            WHERE sensitivity <= %s
            ORDER BY embedding <=> %s::vector LIMIT %s
        """, (qvec, sensitivity_max, qvec, top_k))
        for row in cur.fetchall():
            results.append({
                "id": f"wiki:{row[0]}",
                "text": row[2],
                "source": row[1],
                "score": float(row[3]),
            })
    finally:
        conn.rollback()  # 结束事务，释放 AccessShareLock
        cur.close()

    return results


def bm25_search(query, top_k=TOP_K_BM25):
    """BM25 关键词召回（走当前数据集的内存索引）"""
    name = current_dataset()
    _load_bm25_corpus()
    corpus = _bm25_corpus[name]
    tokenized_query = _tokenize(query)
    scores = _bm25[name].get_scores(tokenized_query)
    top_idx = np.argsort(scores)[::-1][:top_k]
    return [
        {
            "id": corpus[i]["id"],
            "text": corpus[i]["text"],
            "source": corpus[i]["source"],
            "score": float(scores[i]),
        }
        for i in top_idx if scores[i] > 0
    ]


def rrf_fusion(result_lists, k=60, top_n=TOP_K_RRF):
    """
    Reciprocal Rank Fusion

    按 id 去重，名次累加 1/(k+rank+1)——只用名次不用原始分数，
    因为向量相似度、BM25 分、稀疏内积三者的量纲不可比。

    strategies 做**并集**：同一条资料被多路命中时，要把各路的名字都记下来
    （这正是"多路共识"的依据）。此前 item 只在首次出现时保留，
    后面那路的命中记录会被丢掉，导致 strategies 退化成「第一路的名字」。
    """
    fused = {}
    for results in result_lists:
        for rank, item in enumerate(results):
            key = item["id"]
            if key not in fused:
                fused[key] = {
                    "item": item,
                    "rrf_score": 0.0,
                    "strategies": list(item.get("strategies") or []),
                }
            else:
                merged = fused[key]["strategies"]
                for s in item.get("strategies") or []:
                    if s not in merged:
                        merged.append(s)
            fused[key]["rrf_score"] += 1.0 / (k + rank + 1)

    sorted_items = sorted(fused.values(), key=lambda x: -x["rrf_score"])
    return [
        {**x["item"], "rrf_score": x["rrf_score"], "strategies": x["strategies"]}
        for x in sorted_items[:top_n]
    ]


def keyword_search(query, top_k=TOP_K_BM25, mode=None):
    """
    关键词召回——按配置走 BM25 / BGE-M3 稀疏向量 / 两者组合

    两者都产出「词 -> 权重」的稀疏表示，但权重来源不同：
    BM25 数词频（靠 IDF），稀疏向量是模型学出来的。
    A/B 实验显示各有强项（BM25 强在罕见结构词，稀疏向量强在核心实体），
    故做成可切换、可组合，而不是固定死一种。

    参数:
        mode: "bm25" 仅 BM25（默认）
              "sparse" 仅稀疏向量
              "both" 两路都跑后 RRF 融合
    """
    mode = mode or KEYWORD_RETRIEVER

    if mode in ("sparse", "both") and sparse_search is None:
        logger.warning("稀疏检索不可用（FlagEmbedding 未安装），回退为仅 BM25")
        return bm25_search(query, top_k)

    if mode == "sparse":
        return sparse_search(query, top_k)

    if mode == "both":
        bm_hits = bm25_search(query, top_k)
        sp_hits = sparse_search(query, top_k)
        return rrf_fusion([bm_hits, sp_hits], top_n=top_k)

    return bm25_search(query, top_k)


def hybrid_search(query, top_k=TOP_K_RRF, dept=None, keyword_mode=None):
    """
    对外主入口：向量 + 关键词（BM25 / 稀疏 / 组合）+ RRF

    keyword_mode 缺省时读 config.KEYWORD_RETRIEVER；Web 端可按请求覆盖，
    以便同一套服务在不同场景下切换检索策略。
    """
    vec_results = vector_search(query, top_k=TOP_K_VECTOR, dept=dept)
    kw_results = keyword_search(query, top_k=TOP_K_BM25, mode=keyword_mode)
    fused = rrf_fusion([vec_results, kw_results], top_n=top_k)
    return fused
