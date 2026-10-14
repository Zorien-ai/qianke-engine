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

from rag_demo.config import MULTI_QUERY_MAX_VARIANTS, PER_ROUTE_TOPK, TOP_K_RRF
from rag_demo.generation.generator import chat_completion
from rag_demo.prompts import MULTI_QUERY_PROMPT
from rag_demo.retrieval.hybrid_retriever import hybrid_search, rrf_fusion
from rag_demo.retrieval.reranker import rerank
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

# ==================== 预测类问题的规则拦截 ====================
# 为什么需要：SQL 判定是 LLM 给出的「软约束」，它可能把「预测明年 GMV」判成需要 SQL。
# 但库内只有 2024-12-30 的单时点静态快照，没有时间序列，SUM / AVG 只能重述历史、
# 算不出未来值 —— 最终会产出一个「有来源标记、无实际依据」的数字（EDGE-02 实测）。
# 这里做一次硬复核，不依赖模型是否守规矩。
#
# 误伤控制：**只在 need_sql 已为真时才复核**。即它不会改变「本来就不需要 SQL」的问题
# （业务知识类，如「明年会员等级会不会调整」），只否决「既要算数 + 又是未来时点」这个
# 交集 —— 而这个交集恰好就是 SQL 必然答不好的那批。
# 局限：仍是关键词匹配，措辞绕开这些词就无法命中；详见 bug 文档「局限性」。

FUTURE_TIME_MARKERS = (
    "明年", "后年", "下一年", "次年",
    "下个月", "下个季度", "下季度", "下一季度",
    "未来", "将来",
)

PREDICTIVE_ACTION_MARKERS = (
    "预测", "预估", "预计", "推算", "推演", "展望",
    "会增长", "会减少", "会下降", "会达到", "会突破", "会变成",
)

# 反事实推演：「如果……多少 / 涨降 / 达到」（如「不发券 GMV 会少多少」）
# 不要求出现「会」字——「会员」「优惠」都含「会」，加这个词会引入大量假阳性
_COUNTERFACTUAL_RE = re.compile(
    r"如果.{0,30}?(多少|金额|GMV|占比|比例|数量|人数|涨|降|增|减|达到|变化)"
)


def looks_predictive(question: str) -> bool:
    """
    问题是否属于「预测 / 未来时点 / 反事实推演」——SQL 路无法回答的那一类

    只做否定性判断（用于关闭 SQL 路），不参与路由：
    命中也只是「不给数字」，问题仍会走 RAG 检索，不会被拦成闲聊。
    """
    q = question or ""
    if any(m in q for m in FUTURE_TIME_MARKERS):
        return True
    if any(m in q for m in PREDICTIVE_ACTION_MARKERS):
        return True
    return bool(_COUNTERFACTUAL_RE.search(q))


class RetrievalUnavailableError(RuntimeError):
    """
    检索基础设施不可用（数据库连不上、索引表缺失等）

    必须与「检索成功但无命中」严格区分：
        本异常   = 系统故障（如 PostgreSQL 没启动）
        返回空   = 资料里确实没有

    不区分的话，上层拿到空 candidates 会输出「根据现有资料无法确定」——
    把系统故障伪装成知识库缺失，排查时会被带到完全错误的方向
    （2026-10-14 实际踩过：PG 停了，先怀疑的是提示词改动）。
    """


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
    # 检索过程留痕：供前端展示「走了哪几路、每路召回了什么、融合后剩多少」。
    # 只存摘要（策略名 / 检索式 / 命中数 / 前几条来源），**不存全文**——
    # 多路 × top30 全带上会让响应体失控。
    trace: dict = field(default_factory=dict)
    # LLM 判了「需要 SQL」但被预测类规则否决——单独记着，否则前端看到
    # need_sql=False 会以为模型没判出来，看不出是复核拦下的。
    sql_blocked: bool = False


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
        resp = chat_completion(
            messages=[{"role": "user", "content": MULTI_QUERY_PROMPT.format(question=question)}],
            temperature=0,
        )
        route, need_sql, extra = _parse_response(resp.choices[0].message.content or "")
    except Exception as e:  # LLM 不可用时不影响主流程
        logger.warning("多路规划失败，退化为单路检索: %s", e)
        return QueryPlan(route=ROUTE_RAG, variants=variants)

    variants.extend(extra[:MULTI_QUERY_MAX_VARIANTS])

    # SQL 判定复核：LLM 判「需要」但问题属预测类 -> 关闭 SQL 路（硬兜底，
    # 与上面的路由复核并列；提示词是软约束，这里不依赖模型守不守规矩）
    sql_blocked = False
    if need_sql and looks_predictive(question):
        logger.info("SQL 判定复核：问题属预测类，关闭 SQL 路 -> %s", question)
        need_sql = False
        sql_blocked = True

    if route != ROUTE_RAG:
        logger.info("路由复核改道 -> %s（关键词路由原判 RAG）: %s", route, question)
    else:
        logger.info(
            "多路规划: %s | SQL=%s",
            " | ".join(f"{name}={text[:24]}" for name, text in variants),
            "需要" if need_sql else "不需要",
        )

    return QueryPlan(route=route, need_sql=need_sql, variants=variants,
                     sql_blocked=sql_blocked)


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
    per_route_topk: int = PER_ROUTE_TOPK,
    trace_out: list[dict] | None = None,
) -> list[dict]:
    """
    按变体各自召回、**各自精排**后 RRF 融合；只用一路时直接返回，不再融合

    为什么先精排再聚合（而不是融合后再精排）：
    各路召回分数的量纲不可比（向量相似度 / BM25 分 / 稀疏内积），且不同检索式
    的头部质量差异很大。混在一起融合时，弱路的第 30 名仅凭名次就能挤掉强路的
    第 2 名，而精排发生在融合之后、候选已被挤掉，救不回来。
    先用**该路检索式**做 Cross-Encoder 精排砍到 per_route_topk 条——
    各路只把头部交出来，再按名次 RRF 融合。终选入上下文时仍会按原问题
    再做一次分来源精排（pipeline.rerank_by_source），两层各司其职。

    origin_query 会回填到每条候选上，生成阶段据此标注「这条资料是从哪个问题
    找出来的」（原始提问 vs 某条改写），避免 LLM 拿到一份无法溯源的扁平清单。

    trace_out 传入列表时，每路的摘要会追加进去（策略名 / 检索式 / 召回数 /
    精排后保留数 / 前几条来源），供前端展示检索过程；不传则不留痕。
    """
    result_lists = []
    for strategy, text in variants:
        try:
            hits = hybrid_search(text, top_k=top_k, dept=dept, keyword_mode=keyword_mode)
        except Exception as e:
            logger.warning("策略「%s」检索失败，跳过: %s", strategy, e)
            if trace_out is not None:
                trace_out.append({
                    "strategy": strategy, "query": text,
                    "hit_count": 0, "kept_count": 0, "sources": [], "error": str(e),
                })
            continue
        hit_count = len(hits)
        if hits:
            for h in hits:
                h["from_query"] = text
                if origin_query:
                    h["origin_query"] = origin_query
                h.setdefault("strategies", []).append(strategy)
            # 每路先精排：用该路检索式给本路候选打分，只留头部进融合。
            # 精排失败不按「跳过该路」处理——与改造前 rerank_by_source 失败的
            # 语义保持一致：精排是整个链路的基础能力，它挂了应该整体暴露，
            # 而不是静默退化成一个只有部分资料的回答。
            hits = rerank(text, hits, top_k=per_route_topk)
            result_lists.append(hits)
        if trace_out is not None:
            trace_out.append({
                "strategy": strategy,
                "query": text,
                "hit_count": hit_count,
                "kept_count": len(hits),
                "sources": [h["source"] for h in hits[:8]],
            })

    if not result_lists:
        # 注意区分两种「空」：
        #   全部路都抛异常  -> 检索不可用，必须让上层知道（否则被当成「资料缺失」）
        #   全部路都无命中  -> 正常的空结果，按「资料里没有」处理
        if trace_out and len(trace_out) == len(variants) and all(v.get("error") for v in trace_out):
            raise RetrievalUnavailableError(
                f"全部 {len(variants)} 路检索均失败：{trace_out[0].get('error')}"
            )
        return []
    if len(result_lists) == 1:
        return result_lists[0]

    # 融合不再截到 top_k（30）：每路已精排到 per_route_topk 条，
    # 总量 ≤ 路数 × per_route_topk，全部保留交给终选
    return rrf_fusion(result_lists, top_n=len(result_lists) * per_route_topk)


# TODO(perf): [P1] 多路规划那次 LLM 调用仍是主要开销（实测约 6s，占单次问答 31%）。
#             按需生成已能省掉部分变体的检索与生成时间，但 LLM 往返本身无法省。
#             进一步降本方向：改规则扩展 / 换更快的模型。详见 bug/性能隐患台账.md P1
def multi_query_search(
    question: str,
    top_k: int = TOP_K_RRF,
    dept: str | None = None,
    keyword_mode: str | None = None,
    per_route_topk: int = PER_ROUTE_TOPK,
) -> QueryPlan:
    """
    多路检索（各路先精排）+ RRF 融合（一步到位）

    返回 QueryPlan：调用方应先看 plan.route——若被复核改道成 chitchat，
    说明这个问题本就不该走检索，此时 candidates 为空且**检索已被跳过**（省一次白跑）。
    plan.need_sql 为真时，调用方还需自行追加一条结构化查询路。
    """
    plan = plan_queries(question)

    if plan.route != ROUTE_RAG:
        return plan  # 改道了，candidates 用不上，检索直接省掉

    per_variant: list[dict] = []
    plan.candidates = search_variants(
        plan.variants, top_k=top_k, dept=dept,
        keyword_mode=keyword_mode, origin_query=question,
        per_route_topk=per_route_topk,
        trace_out=per_variant,
    )
    plan.trace = {
        # 原问题一起带走：前端要对照「原问题 vs 改写后的检索式」才看得出改写做了什么
        "question": question,
        "need_sql": plan.need_sql,
        "sql_blocked": plan.sql_blocked,
        "variants": per_variant,
        "fused_count": len(plan.candidates),
        # 每路精排后保留数：前端据此展示「召回 30 -> 精排 5」的收敛过程
        "per_route_topk": per_route_topk,
    }
    return plan
