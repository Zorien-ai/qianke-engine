#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : query_processor.py
@Function: 按需多路 query 处理 + LLM 路由复核

流程图里画了 5 种检索方式，但**不是每个问题都需要全跑一遍**：

    「高价值用户怎么定义的」       -> 直接检索就够了
    「高客单和普通用户的偏好差异」  -> 加一路「子查询分解」
    「用户说优惠券过期了怎么办」    -> 加一路「简化」

所以这里让 LLM **先判断需要哪几路，再只生成那几路**，而不是一律五路。

设计要点：
1. 「直接检索」永远执行 —— 它是兜底，不依赖 LLM 判断成功与否
2. **判断与生成合并为一次调用** —— 若拆成「先判断、再生成」，反而多一次往返
3. 判断失败 / LLM 不可用 -> 自动退化为单路，功能不受影响
4. 变体数有上限（MULTI_QUERY_MAX_VARIANTS），避免模型贪心全选
5. **顺带做路由复核**（2026-10-12 加）：让同一次调用再判一次该不该走 sql / chitchat，
   专治 router.route() 关键词路由的漏判——实测 8 个统计类问题里 4 个没被关键词命中
   而落到 RAG，「哪个城市的人最多」这类口语问法靠规则很难穷举。

   ⚠ 这条兜底的作用范围有限：它只能捞「被判成 RAG 的漏判」。
   被判成 chitchat / sql 的问题根本走不到这里，那类误判只能在 route() 层面修。
"""
import logging
import re
from dataclasses import dataclass, field

from rag_demo.config import MULTI_QUERY_MAX_VARIANTS, TOP_K_RRF
from rag_demo.generation.generator import MODEL, client
from rag_demo.prompts import MULTI_QUERY_PROMPT
from rag_demo.retrieval.hybrid_retriever import hybrid_search, rrf_fusion
from rag_demo.tools.router import ROUTE_CHITCHAT, ROUTE_RAG, ROUTE_SQL

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

# 检索策略 + 路由复核的提示词见 rag_demo/prompts.py::MULTI_QUERY_PROMPT


@dataclass
class QueryPlan:
    """
    一次 LLM 调用的产出：路由复核结果 + 检索变体

    route:      复核后的路由（rag / sql / chitchat）。只有 rag 时 variants 才有意义。
    variants:   要跑的检索变体，元素为 (策略名, 检索式)；「直接检索」必定在首位
    candidates: 检索融合结果，仅当 route=rag 且已执行检索时非空
    """
    route: str = ROUTE_RAG
    variants: list[tuple[str, str]] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)


def _parse_response(text: str) -> tuple[str, list[str], dict[str, str]]:
    """
    解析 LLM 输出

    返回: (路由, 选中的短标签列表, {策略名: 检索式})

    容错：分隔符可能是 | : ： ｜ 中的任意一种；模型偶尔会加编号或 markdown 符号。
    路由解析不出来时**默认 rag**——复核只做「有确凿依据才改道」，不做激进改判。
    """
    route = ROUTE_RAG
    chosen: list[str] = []
    generated: dict[str, str] = {}

    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*# 0123456789. ").strip()
        if not line:
            continue

        # 路由行
        m = re.match(r"^路由\s*[:：|｜]\s*(.+)$", line)
        if m:
            value = m.group(1).strip().lower()
            if value in (ROUTE_SQL, ROUTE_CHITCHAT, ROUTE_RAG):
                route = value
            continue

        # 策略行
        m = re.match(r"^策略\s*[:：|｜]\s*(.+)$", line)
        if m:
            body = m.group(1).strip()
            if body.lower() not in ("none", "无", "不需要", "直接"):
                chosen = [c.strip() for c in re.split(r"[,，、/]", body) if c.strip()]
            continue

        # 变体行
        m = re.match(r"^(分解|简化|关键词|假设)\s*[:：|｜]\s*(.+)$", line)
        if m:
            label = m.group(1)
            value = m.group(2).strip()
            # 过滤模型可能写的占位内容
            if value and value not in ("无", "none", "-", "略"):
                generated[FIELD_TO_STRATEGY[label]] = value

    return route, chosen, generated


def plan_queries(question: str) -> QueryPlan:
    """
    一次 LLM 调用同时拿到「路由复核」与「检索变体」

    变体生成本来就要一次 LLM 往返，顺手让它复核路由不增加任何成本——
    这与本模块「判断与生成合并为一次调用」的既有原则一致。

    已知局限：这条兜底只在 ENABLE_MULTI_QUERY=True 时存在。关掉时走 hybrid_search，
    没有这次 LLM 调用，也就没有复核。

    无论路由判成什么，都照常生成变体：变体与路由来自同一次输出，
    多留一份不产生额外开销，也让 build_query_variants 的老调用方不受影响。
    """
    variants: list[tuple[str, str]] = [(STRATEGY_DIRECT, question)]

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": MULTI_QUERY_PROMPT.format(question=question)}],
            temperature=0,
        )
        route, chosen, generated = _parse_response(resp.choices[0].message.content or "")
    except Exception as e:  # LLM 不可用时不影响主流程
        logger.warning("检索策略判断失败，退化为单路检索: %s", e)
        return QueryPlan(route=ROUTE_RAG, variants=variants)

    # 只采纳「判定需要」且「确实生成了内容」的策略
    picked = [
        (strategy, generated[strategy])
        for label, strategy in FIELD_TO_STRATEGY.items()
        if label in chosen and strategy in generated
    ]
    picked = picked[:MULTI_QUERY_MAX_VARIANTS]
    variants.extend(picked)

    if route != ROUTE_RAG:
        logger.info("路由复核改道 -> %s（关键词路由原判 RAG）: %s", route, question)
    else:
        logger.info(
            "检索策略: %s（LLM 判定=%s，实际执行=%s）",
            " | ".join(f"{name}={text[:20]}" for name, text in variants),
            chosen or "无",
            len(variants),
        )

    return QueryPlan(route=route, variants=variants)


def build_query_variants(question: str) -> list[tuple[str, str]]:
    """
    兼容旧调用：只要检索变体，忽略路由复核结果

    tools/ 下的几个评测脚本按这个签名调用，保留以免破坏它们。
    """
    return plan_queries(question).variants


def search_variants(
    variants: list[tuple[str, str]],
    top_k: int = TOP_K_RRF,
    dept: str | None = None,
    keyword_mode: str | None = None,
) -> list[dict]:
    """按变体各自召回后 RRF 融合；只用一路时直接返回，不再融合"""
    result_lists = []
    for strategy, text in variants:
        try:
            hits = hybrid_search(text, top_k=top_k, dept=dept, keyword_mode=keyword_mode)
        except Exception as e:
            logger.warning("策略「%s」检索失败，跳过: %s", strategy, e)
            continue
        if hits:
            for h in hits:
                h.setdefault("strategies", []).append(strategy)
            result_lists.append(hits)

    if not result_lists:
        return []
    if len(result_lists) == 1:
        return result_lists[0]

    return rrf_fusion(result_lists, top_n=top_k)


# TODO(perf): [P1] 变体生成那次 LLM 调用仍是主要开销（实测约 6s，占单次问答 31%）。
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

    返回 QueryPlan：调用方应先看 plan.route——若被复核改道成 sql / chitchat，
    说明这个问题本就不该走 RAG，此时 candidates 为空且**检索已被跳过**（省一次白跑）。
    keyword_mode 透传给底层，用于切换 BM25 / 稀疏向量 / 两者组合。
    """
    plan = plan_queries(question)

    if plan.route != ROUTE_RAG:
        return plan  # 改道了，candidates 用不上，检索直接省掉

    plan.candidates = search_variants(
        plan.variants, top_k=top_k, dept=dept, keyword_mode=keyword_mode
    )
    return plan
