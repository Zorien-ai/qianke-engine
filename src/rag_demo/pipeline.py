#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : pipeline.py
@Function: 统一问答编排入口：二分类路由 -> 多路聚合（检索路 + 可选 SQL 路）-> 生成

链路（与流程图一致）：

    闲聊 / 域外  -> 固定回复（不检索、不调模型）
    其余全部     -> 多路聚合
                     ├─ 检索路 1~N（各自召回后 RRF 融合、分来源精排）
                     ├─ SQL 路（多路规划判定需要时才追加）
                     └─ 聚合后**一次**生成

为什么 SQL 不再是独立分支
------------------------
改造前是「闲聊 / SQL / RAG」三选一的互斥分流，靠关键词判聚合类问题，
实测漏判率 50%（8 个统计问法里 4 个没命中）。漏判后问题再也进不了 SQL 链路。

现在 SQL 变成多路里的一路，由 query_processor 的多路规划统一决定是否追加——
那次 LLM 调用本来就要做（判断检索路数），所以这个判定是免费的，而且比关键词准。

`/qa` 接口与评测脚本共用同一实现，避免逻辑漂移。

性能说明
--------
一次问答 9~17s，其中 **92~96% 花在 LLM 生成**（实测见
tools/profile_modes_compare.py：检索仅 0.35~0.51s、精排 0.15~0.32s）。
所以这里对**完整结果**做缓存，重复提问可直接命中；
再配合流式输出降低首字延迟，是收益最大的两个方向。
"""
import logging

from rag_demo.cache import answer_cache
from rag_demo.config import ENABLE_MULTI_QUERY, TOP_K_PROFILE, TOP_K_RRF, TOP_K_WIKI
from rag_demo.generation.generator import generate
from rag_demo.prompts import CHITCHAT_REPLY
from rag_demo.retrieval.hybrid_retriever import hybrid_search
from rag_demo.retrieval.query_processor import QueryPlan, multi_query_search
from rag_demo.retrieval.reranker import rerank_by_source
from rag_demo.tools import sql_tool
from rag_demo.tools.router import ROUTE_CHITCHAT, ROUTE_RAG, route

logger = logging.getLogger(__name__)


def answer_question(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
    use_cache: bool = True,
) -> dict:
    """
    统一问答入口（带缓存）

    相比内部实现，返回值多一个 `cached` 字段标明本次是否命中缓存。

    参数:
        keyword_mode: 关键词召回策略 bm25 / sparse / both，缺省读 config
        use_cache:    评测对比不同策略时应传 False，否则会拿到上一次的结果
    """
    key = answer_cache.make_key(question, dept, keyword_mode)

    if use_cache:
        hit = answer_cache.get(key)
        if hit is not None:
            logger.info("缓存命中: %s", (question or "")[:40])
            return {**hit, "cached": True}

    result = _answer_uncached(question, dept, keyword_mode)

    if use_cache:
        answer_cache.set(key, result)
    return {**result, "cached": False}


def _chitchat_result() -> dict:
    """闲聊 / 域外：固定回复，不检索、不调模型"""
    return {"answer": CHITCHAT_REPLY, "sources": [], "route": ROUTE_CHITCHAT}


def _run_sql(question: str) -> dict:
    """执行 SQL 路（多路规划判定需要时才会调到这里）"""
    logger.info("追加 SQL 路: %s", question)
    return sql_tool.query(question)


def _plan_and_retrieve(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
) -> QueryPlan:
    """
    多路规划 + 检索路执行

    返回的 QueryPlan 中：
        route     可能被 LLM 复核改道成 chitchat（捞关键词路由的漏判）
        need_sql  是否需要再追加一条结构化查询路
        candidates 已融合的检索候选（带溯源字段）

    关闭 ENABLE_MULTI_QUERY 时没有那次 LLM 调用，退化为单路检索、无 SQL 判定
    —— 这是该开关的固有代价，不是缺陷。
    """
    if not ENABLE_MULTI_QUERY:
        return QueryPlan(
            route=ROUTE_RAG,
            candidates=hybrid_search(
                question, top_k=TOP_K_RRF, dept=dept, keyword_mode=keyword_mode
            ),
        )

    return multi_query_search(
        question, top_k=TOP_K_RRF, dept=dept, keyword_mode=keyword_mode
    )


def _answer_uncached(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
) -> dict:
    """
    实际问答流程

    二分类路由 -> 多路聚合。返回:
        闲聊: {"answer", "sources": [], "route": "chitchat"}
        其余: {"answer", "sources", "route": "rag"}
              命中 SQL 路时额外带 "sql" / "rows_count"
    """
    if route(question) == ROUTE_CHITCHAT:
        return _chitchat_result()

    plan = _plan_and_retrieve(question, dept, keyword_mode)

    if plan.route == ROUTE_CHITCHAT:
        logger.info("路由复核改道 -> chitchat: %s", question)
        return _chitchat_result()

    # SQL 路：与检索路并行产出，最终一起进 context
    sql_result = _run_sql(question) if plan.need_sql else None

    reranked = rerank_by_source(
        question, plan.candidates, top_k_profile=TOP_K_PROFILE, top_k_wiki=TOP_K_WIKI
    )
    result = generate(question, reranked, sql_result=sql_result)
    result["route"] = ROUTE_RAG

    if sql_result is not None:
        result["sql"] = sql_result.get("sql", "")
        result["rows_count"] = len(sql_result.get("rows", []))
    return result


def prepare(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
) -> dict:
    """
    问答前置阶段：路由 + 多路检索 + 精排 + （按需）SQL（**不含生成**）

    供流式接口使用——先同步做完检索拿到上下文，再交给 LLM 逐字生成。
    这样前置阶段（约 3~6s）与生成阶段可以分开观测。

    返回:
        {"route": "chitchat", "answer": ..., "sources": []}      闲聊：直接给答案
        {"route": "rag", "candidates": [...], "sql_result": ..., "sources": [...]}
                                                                  其余：交给 generate_stream
    """
    if route(question) == ROUTE_CHITCHAT:
        return {"route": ROUTE_CHITCHAT, "answer": CHITCHAT_REPLY, "sources": []}

    plan = _plan_and_retrieve(question, dept, keyword_mode)

    if plan.route == ROUTE_CHITCHAT:
        logger.info("路由复核改道 -> chitchat: %s", question)
        return {"route": ROUTE_CHITCHAT, "answer": CHITCHAT_REPLY, "sources": []}

    sql_result = _run_sql(question) if plan.need_sql else None

    reranked = rerank_by_source(
        question, plan.candidates, top_k_profile=TOP_K_PROFILE, top_k_wiki=TOP_K_WIKI
    )
    return {
        "route": ROUTE_RAG,
        "candidates": reranked,
        "sql_result": sql_result,
        "sources": [
            {
                "index": i,
                "source": c["source"],
                "text": c["text"][:100],
                "origin_query": c.get("origin_query", ""),
                "from_query": c.get("from_query", ""),
                "strategies": c.get("strategies", []),
            }
            for i, c in enumerate(reranked, 1)
        ],
    }
