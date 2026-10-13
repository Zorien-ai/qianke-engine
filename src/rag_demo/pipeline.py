#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : pipeline.py
@Function: 统一问答编排入口：意图路由 -> 闲聊 / Text2SQL / RAG
           /qa 接口与评测脚本共用同一实现，避免逻辑漂移

           RAG 分支内还有一层 LLM 路由复核，用于捞回关键词路由（router.route）的漏判，
           详见 _retrieve 与 query_processor.plan_queries

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
from rag_demo.generation.generator import generate, llm_summarize
from rag_demo.prompts import CHITCHAT_REPLY, SQL_SCHEMA
from rag_demo.retrieval.hybrid_retriever import hybrid_search
from rag_demo.retrieval.query_processor import multi_query_search
from rag_demo.retrieval.reranker import rerank_by_source
from rag_demo.tools import sql_tool
from rag_demo.tools.router import (
    ROUTE_CHITCHAT,
    ROUTE_RAG,
    ROUTE_SQL,
    route,
)

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


def _sql_result(question: str) -> dict:
    """聚合统计：Text2SQL —— 生成 → 安全校验 → 执行 → 自然语言化"""
    sql_result = sql_tool.query(question)
    return {
        "answer": llm_summarize(question, sql_result, schema=SQL_SCHEMA),
        "sources": [{
            "index": 1,
            "source": "sql",
            "text": sql_result.get("sql", ""),
        }],
        "sql": sql_result.get("sql", ""),
        "rows_count": len(sql_result.get("rows", [])),
        "route": ROUTE_SQL,
    }


def _prepare_sql(question: str) -> dict:
    """流式接口用：SQL 的前置阶段（结果集交给 llm_summarize）"""
    sql_result = sql_tool.query(question)
    return {
        "route": ROUTE_SQL,
        "sql_result": sql_result,
        "sources": [{"index": 1, "source": "sql", "text": sql_result.get("sql", "")}],
    }


def _retrieve(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
) -> tuple[str, list[dict]]:
    """
    RAG 检索阶段，返回 (最终路由, 候选列表)

    这里会顺带做一次 **LLM 路由复核**（复用变体生成的那次调用，零额外成本）：
    router.route() 是纯关键词规则，统计类问题只要没命中 SQL_KEYWORDS 就会落到 RAG
    ——实测 8 个统计类问法漏判 4 个。复核能在同一轮把它们捞回 SQL 或闲聊。

    注意复核的边界：只可能把「rag」改成别的——被判成 sql / chitchat 的问题
    在 route() 阶段就分流走了，压根到不了这里。
    """
    if not ENABLE_MULTI_QUERY:
        # 没有变体生成那次 LLM 调用，也就没有顺带的复核机会
        return ROUTE_RAG, hybrid_search(
            question, top_k=TOP_K_RRF, dept=dept, keyword_mode=keyword_mode
        )

    plan = multi_query_search(
        question, top_k=TOP_K_RRF, dept=dept, keyword_mode=keyword_mode
    )
    return plan.route, plan.candidates


def _answer_uncached(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
) -> dict:
    """
    实际问答流程

    三条链路（与流程图一致）：
        闲聊 / 域外 -> 固定回复（不检索、不调模型）
        聚合统计    -> Text2SQL
        语义检索    -> 按需多路 query + 混合检索 + 分来源精排（默认）

    后两条之间还有一层兜底：RAG 检索时会用 LLM 复核一次路由，
    捞回被关键词规则漏判的统计类问题（详见 _retrieve）。

    返回:
        闲聊: {"answer", "sources": [], "route": "chitchat"}
        RAG : {"answer", "sources", "route": "rag"}
        SQL : {"answer", "sources", "sql", "rows_count", "route": "sql"}
    """
    route_result = route(question)

    if route_result == ROUTE_CHITCHAT:
        return _chitchat_result()

    if route_result == ROUTE_SQL:
        return _sql_result(question)

    # 关键词路由判成 RAG，但可能是漏判——检索阶段顺带复核
    final_route, candidates = _retrieve(question, dept, keyword_mode)

    if final_route == ROUTE_SQL:
        logger.info("路由复核改道 -> sql: %s", question)
        return _sql_result(question)

    if final_route == ROUTE_CHITCHAT:
        logger.info("路由复核改道 -> chitchat: %s", question)
        return _chitchat_result()

    reranked = rerank_by_source(
        question, candidates, top_k_profile=TOP_K_PROFILE, top_k_wiki=TOP_K_WIKI
    )
    result = generate(question, reranked)
    result["route"] = ROUTE_RAG
    return result


def prepare(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
) -> dict:
    """
    问答前置阶段：路由 + 检索 + 精排（**不含生成**）

    供流式接口使用——先同步做完检索拿到上下文，再交给 LLM 逐字生成。
    这样前置阶段（约 3~6s）与生成阶段可以分开观测。

    与 _answer_uncached 一样会做 LLM 路由复核，所以返回的 route 可能与
    route(question) 的结果不同（关键词漏判被复核改道）。

    返回:
        {"route": "chitchat", "answer": ..., "sources": []}          闲聊：直接给答案
        {"route": "sql", "sql_result": ..., "sources": [...]}        SQL：交给 llm_summarize
        {"route": "rag", "candidates": [...], "sources": [...]}      RAG：交给 generate_stream
    """
    route_result = route(question)

    if route_result == ROUTE_CHITCHAT:
        return {"route": ROUTE_CHITCHAT, "answer": CHITCHAT_REPLY, "sources": []}

    if route_result == ROUTE_SQL:
        return _prepare_sql(question)

    final_route, candidates = _retrieve(question, dept, keyword_mode)

    if final_route == ROUTE_SQL:
        logger.info("路由复核改道 -> sql: %s", question)
        return _prepare_sql(question)

    if final_route == ROUTE_CHITCHAT:
        logger.info("路由复核改道 -> chitchat: %s", question)
        return {"route": ROUTE_CHITCHAT, "answer": CHITCHAT_REPLY, "sources": []}

    reranked = rerank_by_source(
        question, candidates, top_k_profile=TOP_K_PROFILE, top_k_wiki=TOP_K_WIKI
    )
    return {
        "route": ROUTE_RAG,
        "candidates": reranked,
        "sources": [
            {"index": i, "source": c["source"], "text": c["text"][:100]}
            for i, c in enumerate(reranked, 1)
        ],
    }
