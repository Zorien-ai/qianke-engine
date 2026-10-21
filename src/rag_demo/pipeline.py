#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : pipeline.py
@Function: 统一问答编排入口：二分类路由 -> 多路聚合（检索路 + 可选 SQL 路）-> 生成

链路（与流程图一致）：

    闲聊 / 域外  -> 固定回复（不检索、不调模型）
    其余全部     -> 多路聚合
                    ├─ 检索路 1~N（**并行**检索，各路 RRF 出 top30 后分池取舍：
                    │            画像池跨路合并统一精排取全局 Top-3，
                    │            文档池每路精排各取 Top-2）
                    ├─ 两池结果合并去重（不再二次融合，不按名次重新竞争）
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

from openai import APIError

from rag_demo import answer_guard
from rag_demo.cache import answer_cache
from rag_demo.chitchat import build_reply
from rag_demo.config import ENABLE_MULTI_QUERY, TOP_K_PROFILE, TOP_K_RRF
from rag_demo.db.connection import current_dataset
from rag_demo.generation.generator import generate
from rag_demo.prompts import (
    LLM_UNAVAILABLE_REPLY,
    PREDICTION_BLOCKED_REPLY,
    RETRIEVAL_UNAVAILABLE_REPLY,
)
from rag_demo.retrieval.query_processor import (
    STRATEGY_DIRECT,
    QueryPlan,
    RetrievalUnavailableError,
    multi_query_search,
    search_variants,
)
from rag_demo.tools import sql_tool
from rag_demo.tools.router import ROUTE_CHITCHAT, ROUTE_RAG, route

logger = logging.getLogger(__name__)


def answer_question(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
    use_cache: bool = True,
    profile_limit: int | None = None,
    deep_thinking: bool | None = None,
    memory_context: str | None = None,
    history_key: str = "",
) -> dict:
    """
    统一问答入口（带缓存）

    相比内部实现，返回值多一个 `cached` 字段标明本次是否命中缓存。

    参数:
        keyword_mode:  关键词召回策略 bm25 / sparse / both，缺省读 config
        use_cache:     评测对比不同策略时应传 False，否则会拿到上一次的结果
        profile_limit: 「返回多少个用户」（画像池的全局名额），None = 用 config
                       默认值 TOP_K_PROFILE(3)。由接口层按角色放行后传入
                       （permissions.clamp_top_k）；评测/工具脚本不传即默认行为。
        deep_thinking: 最后一个生成调用是否开启思考模式（None/False = 关，默认）。
                       True = 让模型先推理再作答：实测忠实度 95.7%→100%，
                       代价是慢 5.5 倍、token 7.2 倍（见 tools/ab_deep_thinking.py）。
                       **只作用于生成这一次调用**——规划与 Text2SQL 恒不思考，
                       它们开思考只是白慢，答案质量并不因此提高。
                       它进缓存键：开与不开是两份不同的答案，不能互相命中。

    注意：本函数返回的是**完整结果**，不做任何按角色的裁剪——裁剪统一在
    api 层的 permissions.render() 做。这样评测脚本直接调它拿到的仍是全量字段，
    不会因为加了权限而失能。
    """
    # 数据集必须进键：demo 与 user 是两个库，同一问题答案不同（见 cache.make_key）
    key = answer_cache.make_key(question, dept, keyword_mode, profile_limit, deep_thinking,
                                dataset=current_dataset(), history_key=history_key)

    if use_cache:
        hit = answer_cache.get(key)
        if hit is not None:
            logger.info("缓存命中: %s", (question or "")[:40])
            return {**hit, "cached": True}

    try:
        result = _answer_uncached(question, dept, keyword_mode, profile_limit, deep_thinking,
                                  memory_context=memory_context)
    except APIError as e:
        # LLM 接口故障（超时 / 限流 / 5xx）：不写缓存（恢复后要能正常回答），
        # 返回固定文案 + 独立 route，让用户知道该重试、排查的人知道查 LLM 侧
        logger.error("LLM 服务不可用: %s: %s", type(e).__name__, e)
        return {**_llm_unavailable_result(), "cached": False}

    if use_cache:
        answer_cache.set(key, result)
    return {**result, "cached": False}


def _chitchat_result() -> dict:
    """
    闲聊 / 域外：不检索、不调模型，直接给拒答引导

    文案不是常量：能力清单固定，示例问句按当前数据集生成（见 chitchat.build_reply）。
    """
    return {"answer": build_reply(), "sources": [], "route": ROUTE_CHITCHAT}


# 第三种 route：既不是正常回答（rag），也不是闲聊（chitchat），而是检索基础设施挂了。
# 单独标记出来，调用方（前端 / 评测脚本）才能区分「答不出」和「服务坏了」。
ROUTE_ERROR = "error"


def _unavailable_result() -> dict:
    """
    检索基础设施不可用（数据库连不上、索引表缺失等）

    刻意用独立文案与 route：若沿用「根据现有资料无法确定」，
    排查的人会去查知识库、调检索参数——而真正的问题只是数据库没启动。
    """
    return {"answer": RETRIEVAL_UNAVAILABLE_REPLY, "sources": [], "route": ROUTE_ERROR}


# 第三种 route：LLM 服务不可用（API 故障 / 超时 / 限流）。
# 与检索不可用分开标记：两者的排查方向完全相反——一个查数据库，
# 一个查 LLM 接口。混成一个 route 会把排查带到错误的方向。
ROUTE_LLM_ERROR = "llm_error"


def _llm_unavailable_result() -> dict:
    """
    LLM 接口不可用时的兜底（2026-10-14/15 DeepSeek API 故障期间实测：
    用户看到的是「APITimeoutError」，既不知是服务挂了也不知该重试）
    """
    return {"answer": LLM_UNAVAILABLE_REPLY, "sources": [], "route": ROUTE_LLM_ERROR}


def _run_sql(question: str) -> dict:
    """执行 SQL 路（多路规划判定需要时才会调到这里）"""
    logger.info("追加 SQL 路: %s", question)
    return sql_tool.query(question)


def brief_rows(rows: list[tuple], limit: int = 20) -> list[list[str]]:
    """
    SQL 结果行摘要（供前端展示原始数字）

    最多 limit 行、每格截断——结果可能有 50 行 × 十余列，原样返回会让响应体失控。
    前端只用来「看见具体数字」，不是拿去做计算。
    """
    return [[str(v)[:60] for v in r] for r in rows[:limit]]


def load_user_cards(candidates: list[dict], limit: int = 30) -> list[dict]:
    """把本轮被检索到的画像候选补齐成结构化用户卡片。

    画像候选的 id 形如 `user:U1234`，但 profile_text 只是给模型看的拼接文本；
    前端要卡片需要结构化字段，因此按候选顺序回库补一次（只查被命中的少量 ID）。
    """
    user_ids = []
    for c in candidates or []:
        cid = str(c.get("id") or "")
        if c.get("source") != "user_profile" or not cid.startswith("user:"):
            continue
        uid = cid.split(":", 1)[1].strip()
        if uid and uid not in user_ids:
            user_ids.append(uid)
        if len(user_ids) >= limit:
            break
    if not user_ids:
        return []

    from rag_demo.db.connection import get_conn

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT user_id, age, gender, city, member_level, order_count,
                      total_amount, avg_amount, top_category, days_since_last_buy, platforms
               FROM user_profile_vectors WHERE user_id = ANY(%s)""",
            (user_ids,),
        )
        rows = {row[0]: row for row in cur.fetchall()}
    finally:
        conn.rollback()  # 只读查询，及时结束事务释放锁
        cur.close()

    cards = []
    for uid in user_ids:
        row = rows.get(uid)
        if not row:
            continue
        cards.append({
            "user_id": row[0],
            "age": row[1],
            "gender": row[2],
            "city": row[3],
            "member_level": row[4],
            "order_count": int(row[5] or 0),
            "total_amount": float(row[6] or 0),
            "avg_amount": float(row[7] or 0),
            "top_category": row[8],
            "days_since_last_buy": row[9],
            "platforms": row[10],
        })
    return cards


def _plan_and_retrieve(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
    profile_limit: int | None = None,
) -> QueryPlan:
    """
    多路规划 + 检索路执行

    返回的 QueryPlan 中：
        route     可能被 LLM 复核改道成 chitchat（捞关键词路由的漏判）
        need_sql  是否需要再追加一条结构化查询路
        candidates 各路并行检索 + 分池取舍 + 合并去重后的候选（带溯源字段）

    profile_limit 是「返回多少个用户」——画像池的**全局名额**，None 用 config
    默认值。它必须在检索阶段就生效（画像池统一精排时取 Top-k），而不是取完再截：
    候选池的取舍口径本身就该由这个数决定，事后再砍等于「先按 3 个挑完再扔」。

    关闭 ENABLE_MULTI_QUERY 时没有那次 LLM 调用，退化为单路检索、无 SQL 判定
    ——这是该开关的固有代价，不是缺陷。单路同样走「RRF top30 → 分池取舍」，
    且与改造前的分路精排**完全等价**（只有一路时「跨路合并」就是本路候选）。
    """
    top_k_profile = profile_limit or TOP_K_PROFILE

    if not ENABLE_MULTI_QUERY:
        return QueryPlan(
            route=ROUTE_RAG,
            candidates=search_variants(
                [(STRATEGY_DIRECT, question)], top_k=TOP_K_RRF,
                dept=dept, keyword_mode=keyword_mode,
                top_k_profile=top_k_profile,
            ),
        )

    return multi_query_search(
        question, top_k=TOP_K_RRF, dept=dept, keyword_mode=keyword_mode,
        top_k_profile=top_k_profile,
    )


def _answer_uncached(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
    profile_limit: int | None = None,
    deep_thinking: bool | None = None,
    memory_context: str | None = None,
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

    try:
        plan = _plan_and_retrieve(question, dept, keyword_mode, profile_limit)
    except RetrievalUnavailableError as e:
        # 数据库挂了不能伪装成「资料里没有」——明确报「服务不可用」
        logger.error("检索不可用: %s", e)
        return _unavailable_result()

    if plan.route == ROUTE_CHITCHAT:
        logger.info("路由复核改道 -> chitchat: %s", question)
        return _chitchat_result()

    # 「返回多少个用户」不在这里截断：画像池的全局名额在检索阶段
    # （search_variants 统一精排取 Top-k）就已生效，拿到的已是最终份数。
    # 事后再截一次不但多余，还会让「候选池按 3 个挑」和「展现 3 个」变成两套口径
    candidates = plan.candidates

    # SQL 路：与检索路并行产出，最终一起进 context
    sql_result = _run_sql(question) if plan.need_sql else None

    # 检索路已在 multi_query_search 内完成「各路 RRF top30 → 分池取舍 → 合并去重」，
    # 这里直接进生成，不再做整体终选（否则等于三层精排）
    result = generate(question, candidates, sql_result=sql_result, deep_thinking=deep_thinking,
                      memory_context=memory_context)
    result["route"] = ROUTE_RAG
    result["user_cards"] = load_user_cards(candidates)

    # 生成后审查：提示词只是约束，模型仍可能替数据说话（「明年 GMV 将达到 1.2 亿」）。
    # 命中就把整段答案换成固定文案——为什么是「后置审查」而不是前置拦截，
    # 以及命中条件/开关的取舍，见 answer_guard.py 模块开头。
    guard = answer_guard.inspect(question, result.get("answer", ""))
    if guard:
        logger.warning("答案被后置审查替换：%s", answer_guard.summarize(guard))
        result["answer"] = PREDICTION_BLOCKED_REPLY
        result["guard"] = guard

    if sql_result is not None:
        result["sql"] = sql_result.get("sql", "")
        result["rows_count"] = len(sql_result.get("rows", []))
        result["sql_rows"] = brief_rows(sql_result.get("rows", []))
        result["sql_error"] = sql_result.get("error")

    # 检索过程留痕（哪几路、每路召回了什么、融合后剩多少），供前端展示
    result["trace"] = plan.trace
    return result


def prepare(
    question: str,
    dept: str | None = None,
    keyword_mode: str | None = None,
    profile_limit: int | None = None,
) -> dict:
    """
    问答前置阶段：路由 + 多路检索 + 精排 + （按需）SQL（**不含生成**）

    供流式接口使用——先同步做完检索拿到上下文，再交给 LLM 逐字生成。
    这样前置阶段（约 3~6s）与生成阶段可以分开观测。

    返回:
        {"route": "chitchat", "answer": ..., "sources": []}      闲聊：直接给答案
        {"route": "rag", "candidates": [...], "sql_result": ...,
         "sources": [...], "trace": {...}}
            其余：交给 generate_stream
            trace 是检索过程留痕（每路的策略/检索式/命中数、融合后数量、
            LLM 的 SQL 判定结果），供前端把中间步骤展示出来
    """
    if route(question) == ROUTE_CHITCHAT:
        return {"route": ROUTE_CHITCHAT, "answer": build_reply(), "sources": []}

    try:
        plan = _plan_and_retrieve(question, dept, keyword_mode, profile_limit)
    except RetrievalUnavailableError as e:
        logger.error("检索不可用: %s", e)
        return {
            "route": ROUTE_ERROR,
            "answer": RETRIEVAL_UNAVAILABLE_REPLY,
            "sources": [],
            "candidates": [],
            "sql_result": None,
            "trace": {},
        }

    if plan.route == ROUTE_CHITCHAT:
        logger.info("路由复核改道 -> chitchat: %s", question)
        return {"route": ROUTE_CHITCHAT, "answer": build_reply(), "sources": []}

    # candidates 已是最终份数（画像池名额在检索阶段就已生效），
    # 下方 sources 与它用的是**同一份**结果——不会出现
    # 「答案里提到 5 个用户，来源列里却有 9 条」的不一致
    candidates = plan.candidates

    sql_result = _run_sql(question) if plan.need_sql else None

    # candidates 已是「各路 RRF top30 → 各路分来源精排 → 合并去重」的结果，
    # 直接透传给生成层，不再做整体终选（否则等于三层精排）
    return {
        "route": ROUTE_RAG,
        "candidates": candidates,
        "sql_result": sql_result,
        "trace": plan.trace,
        "user_cards": load_user_cards(candidates),
        "sources": [
            {
                "index": i,
                "source": c["source"],
                # 400 字：要让人看清「这段资料到底说了什么」，100 字只够认个标题。
                # wiki 做过全文扩展的最长 1200 字，这里截断后仍能看出主体内容。
                "text": c["text"][:400],
                "origin_query": c.get("origin_query", ""),
                "from_query": c.get("from_query", ""),
                "strategies": c.get("strategies", []),
                # 精排分数与回填范围——它们决定了这条资料凭什么占住名额
                "rerank_score": round(float(c.get("rerank_score", 0)), 4),
                "expanded": bool(c.get("expanded", False)),
                "expand_scope": c.get("expand_scope", ""),
                "parent_key": c.get("parent_key", ""),
                # 图片只带 key / 外链，**不带签名 URL**：sources 会进 answer_cache，
                # 签名地址存进去（TTL 1 小时）命中缓存就是死链。签名在
                # permissions._render_source 每次响应时现做。
                "images": c.get("images", []),
            }
            for i, c in enumerate(candidates, 1)
        ],
    }
