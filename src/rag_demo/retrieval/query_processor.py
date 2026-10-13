#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : query_processor.py
@Function: 多路检索规划 + 路由复核 + SQL 判定

一次 LLM 调用产出三件事：

    1. 路由复核     —— 只分 chitchat / rag，用来捞关键词路由的漏判
    2. 是否需要 SQL —— 决定是否追加一条结构化查询路
    3. 检索变体     —— 需要哪几路资料检索

设计要点：
1. 「直接检索」永远执行 —— 它是兜底，不依赖 LLM 判断成功与否
2. 判断与生成合并为一次调用 —— 拆成「先判断、再生成」反而多一次往返
3. 判断失败 / LLM 不可用 -> 退化为单路，功能不受影响
4. 变体数有上限（MULTI_QUERY_MAX_VARIANTS），避免模型贪心全选
5. **分解出的每个子问题各自成路**（prompt 要求一行一个子问题）。
   若把它们拼成一句话再检索，几个子问题的语义会被平均掉、关键词会互相干扰，
   等于白拆——这是改造前的实际行为。
6. 每条候选回填溯源：原始问题 / 该路实际用的检索式 / 被哪几路命中，
   供生成阶段显式区分资料从哪来。

⚠ 路由复核的作用范围有限：它只能捞「被判成 RAG 的漏判」。
被判成 chitchat 的问题在 router.route() 阶段就分流走了，压根到不了这里。
"""
import logging
import re
from dataclasses import dataclass, field

from rag_demo.config import MULTI_QUERY_MAX_VARIANTS, TOP_K_RRF
from rag_demo.generation.generator import MODEL, client
from rag_demo.prompts import MULTI_QUERY_PROMPT
from rag_demo.retrieval.hybrid_retriever import hybrid_search, rrf_fusion
from rag_demo.tools.router import ROUTE_CHITCHAT, ROUTE_RAG

logger = logging.getLogger(__name__)

# 策略名（与流程图一致）
STRATEGY_DIRECT = "直接检索"
STRATEGY_DECOMPOSE = "子查询分解"
STRATEGY_SIMPLIFY = "复杂问题简化"
STRATEGY_KEYWORDS = "关键词扩写"
STRATEGY_HYDE = "假设答案检索"

# LLM 输出用的短标签 -> 策略名
FIELD_TO_STRATEGY = {
    "分解": STRATEGY_DECOMPOSE,
    "简化": STRATEGY_SIMPLIFY,
    "关键词": STRATEGY_KEYWORDS,
    "假设": STRATEGY_HYDE,
}


@dataclass
class QueryPlan:
    """
    一次 LLM 调用的产出

    route:      复核后的路由（rag / chitchat）。非 rag 时 variants / candidates 无意义
    need_sql:   是否需要追加一条结构化查询路
    variants:   检索变体，元素为 (策略名, 检索式)；「直接检索」必定在首位
    candidates: 检索融合结果，仅 route=rag 且已执行检索时非空
    """
    route: str = ROUTE_RAG
    need_sql: bool = False
    variants: list[tuple[str, str]] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)


def _parse_response(text: str) -> tuple[str, bool, list[tuple[str, str]]]:
    """
    解析 LLM 输出

    返回: (路由, 是否需要 SQL, 额外检索变体列表)

    容错：分隔符可能是 | : ： ｜ 中的任意一种；模型偶尔会加编号或 markdown 符号。
    解析不出来时按「rag + 不需要 SQL」处理——复核只做「有确凿依据才改道」。

    「分解」允许多行，每行独立成为一个变体（这是它与其它策略的唯一结构差异）。
    """
    route = ROUTE_RAG
    need_sql = False
    chosen: list[str] = []
    fields: dict[str, list[str]] = {}

    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*# 0123456789. ").strip()
        if not line:
            continue

        # 路由行
        m = re.match(r"^路由\s*[:：|｜]\s*(.+)$", line)
        if m:
            value = m.group(1).strip().lower()
            if value in (ROUTE_CHITCHAT, ROUTE_RAG):
                route = value
            continue

        # SQL 行
        m = re.match(r"^SQL\s*[:：|｜]\s*(.+)$", line, re.IGNORECASE)
        if m:
            need_sql = m.group(1).strip().lower() in ("需要", "yes", "y", "true", "是")
            continue

        # 策略行
        m = re.match(r"^策略\s*[:：|｜]\s*(.+)$", line)
        if m:
            body = m.group(1).strip()
            if body.lower() not in ("none", "无", "不需要", "直接"):
                chosen = [c.strip() for c in re.split(r"[,，、/]", body) if c.strip()]
            continue

        # 变体行（分解可多行）
        m = re.match(r"^(分解|简化|关键词|假设)\s*[:：|｜]\s*(.+)$", line)
        if m:
            label = m.group(1)
            value = m.group(2).strip()
            # 过滤模型可能写的占位内容
            if value and value not in ("无", "none", "-", "略"):
                fields.setdefault(label, []).append(value)

    # 组装：只采纳「判定需要」且「确实生成了内容」的策略
    extra: list[tuple[str, str]] = []
    for label, strategy in FIELD_TO_STRATEGY.items():
        if label not in chosen:
            continue
        for value in fields.get(label, []):
            extra.append((strategy, value))

    return route, need_sql, extra


def plan_queries(question: str) -> QueryPlan:
    """
    一次 LLM 调用同时拿到「路由复核」「是否需要 SQL」「检索变体」

    变体生成本来就要一次 LLM 往返，顺手让它复核路由、判断 SQL 不增加任何成本——
    这与本模块「判断与生成合并为一次调用」的既有原则一致。

    已知局限：这条兜底只在 ENABLE_MULTI_QUERY=True 时存在。
    关掉后走 hybrid_search，没有这次 LLM 调用，也就没有复核与 SQL 判定。
    """
    variants: list[tuple[str, str]] = [(STRATEGY_DIRECT, question)]

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": MULTI_QUERY_PROMPT.format(question=question)}],
            temperature=0,
        )
        route, need_sql, extra = _parse_response(resp.choices[0].message.content or "")
    except Exception as e:  # LLM 不可用时不影响主流程
        logger.warning("多路规划失败，退化为单路检索: %s", e)
        return QueryPlan(route=ROUTE_RAG, variants=variants)

    variants.extend(extra[:MULTI_QUERY_MAX_VARIANTS])

    if route != ROUTE_RAG:
        logger.info("路由复核改道 -> %s（关键词路由原判 RAG）: %s", route, question)
    else:
        logger.info(
            "多路规划: %s | SQL=%s",
            " | ".join(f"{name}={text[:24]}" for name, text in variants),
            "需要" if need_sql else "不需要",
        )

    return QueryPlan(route=route, need_sql=need_sql, variants=variants)


def build_query_variants(question: str) -> list[tuple[str, str]]:
    """
    兼容旧调用：只要检索变体，忽略路由与 SQL 判定

    tools/ 下的几个评测脚本按这个签名调用，保留以免破坏它们。
    """
    return plan_queries(question).variants


def search_variants(
    variants: list[tuple[str, str]],
    top_k: int = TOP_K_RRF,
    dept: str | None = None,
    keyword_mode: str | None = None,
    origin_query: str | None = None,
) -> list[dict]:
    """
    按变体各自召回后 RRF 融合；只用一路时直接返回，不再融合

    origin_query 会回填到每条候选上，生成阶段据此标注「这条资料是从哪个问题
    找出来的」（原始提问 vs 某条改写），避免 LLM 拿到一份无法溯源的扁平清单。
    """
    result_lists = []
    for strategy, text in variants:
        try:
            hits = hybrid_search(text, top_k=top_k, dept=dept, keyword_mode=keyword_mode)
        except Exception as e:
            logger.warning("策略「%s」检索失败，跳过: %s", strategy, e)
            continue
        if hits:
            for h in hits:
                h["from_query"] = text
                if origin_query:
                    h["origin_query"] = origin_query
                h.setdefault("strategies", []).append(strategy)
            result_lists.append(hits)

    if not result_lists:
        return []
    if len(result_lists) == 1:
        return result_lists[0]

    return rrf_fusion(result_lists, top_n=top_k)


# TODO(perf): [P1] 多路规划那次 LLM 调用仍是主要开销（实测约 6s，占单次问答 31%）。
#             按需生成已能省掉部分变体的检索与生成时间，但 LLM 往返本身无法省。
#             进一步降本方向：改规则扩展 / 换更快的模型。详见 bug/性能隐患台账.md P1
def multi_query_search(
    question: str,
    top_k: int = TOP_K_RRF,
    dept: str | None = None,
    keyword_mode: str | None = None,
) -> QueryPlan:
    """
    多路检索 + RRF 融合（一步到位）

    返回 QueryPlan：调用方应先看 plan.route——若被复核改道成 chitchat，
    说明这个问题本就不该走检索，此时 candidates 为空且**检索已被跳过**（省一次白跑）。
    plan.need_sql 为真时，调用方还需自行追加一条结构化查询路。
    """
    plan = plan_queries(question)

    if plan.route != ROUTE_RAG:
        return plan  # 改道了，candidates 用不上，检索直接省掉

    plan.candidates = search_variants(
        plan.variants, top_k=top_k, dept=dept,
        keyword_mode=keyword_mode, origin_query=question,
    )
    return plan
