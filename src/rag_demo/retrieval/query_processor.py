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
import contextvars
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from rag_demo.config import (
    MULTI_QUERY_MAX_VARIANTS,
    TOP_K_PROFILE,
    TOP_K_RRF,
    TOP_K_WIKI,
    is_doc_source,
)
from rag_demo.db.schema_facts import get_time_capability
from rag_demo.generation.generator import chat_completion
from rag_demo.prompts import MULTI_QUERY_PROMPT
from rag_demo.retrieval.hybrid_retriever import get_model, hybrid_search
from rag_demo.retrieval.reranker import get_reranker, rerank, rerank_by_source
from rag_demo.tools import intent_telemetry
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

# ==================== 预测类问题：交给提示词 + 数据能力判断 ====================
# 这里原来有一组关键词（明年 / 预测 / 下季度 / 如果…多少）做的硬拦截：
# 命中就关闭 SQL 路，理由是「库内是单时点快照，SUM/AVG 算不出未来值」。
#
# 已删除。两个原因：
#   1. 判断依据写死成「本 demo 库没有时间序列」这个数据现状。换到有日粒度流水的库，
#      这条规则照样拦——属于「demo 规则当系统规则」（见 bug/10.17）。
#   2. 它拦的是「用聚合冒充预测」这个逻辑错误，而那是提示词的职责：
#      MULTI_QUERY_PROMPT 已经注入了当前数据的真实时间能力（get_time_capability），
#      TEXT2SQL_PROMPT 也要求不把 SUM/AVG 起成 predicted_* 别名。
#      用关键词硬兜底会让「能不能答」由一个词表决定，而不是由数据决定。
#
# 代价是判定退回模型（不再有确定性兜底）。可接受：这一层只影响「要不要多查一次」，
# 查错了是答案质量下降，不是系统故障。


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
            messages=[{
                "role": "user",
                # 时间能力从当前数据集采集：写死「只有单时点快照」会让有时间序列的库
                # 也被判成「不需要 SQL」，等于用 demo 的数据属性关掉了真实能力。
                "content": MULTI_QUERY_PROMPT.format(
                    question=question, time_capability=get_time_capability()
                ),
            }],
            temperature=0,
        )
        route, need_sql, extra = _parse_response(resp.choices[0].message.content or "")
    except Exception as e:  # LLM 不可用时不影响主流程
        logger.warning("多路规划失败，退化为单路检索: %s", e)
        return QueryPlan(route=ROUTE_RAG, variants=variants)

    variants.extend(extra[:MULTI_QUERY_MAX_VARIANTS])

    if route != ROUTE_RAG:
        logger.info("路由复核改道 -> %s（入口路由原判 RAG）: %s", route, question)
        # 这是**带免费标签**的一次数据：入口判 RAG、LLM 复核说 chitchat = 一次漏判。
        # 记下来，线上就不必为「该不该走检索」再花一次标注成本。
        intent_telemetry.record_recheck(question, route)
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


def _retrieve_one(
    strategy: str,
    text: str,
    top_k: int,
    dept: str | None,
    keyword_mode: str | None,
    origin_query: str | None,
) -> list[dict]:
    """单路混合检索 + 溯源标注（供线程池并行调用）"""
    hits = hybrid_search(text, top_k=top_k, dept=dept, keyword_mode=keyword_mode)
    for h in hits:
        h["from_query"] = text
        if origin_query:
            h["origin_query"] = origin_query
        h.setdefault("strategies", []).append(strategy)
    return hits


def _offer_to_pool(pool: list[dict], index: dict[str, dict], item: dict) -> bool:
    """
    把一条候选放进池子；池里已有同 id 的，只合并 strategies（多路共识的依据）

    返回是否**新增**（False = 重复命中，已并入既有那条的 strategies）。

    共识标记必须保留到统一精排之后：它决定「这条资料是被几路独立召回的」，
    去重时丢掉就再也补不回来（而候选本身在池里只有一份）。
    """
    cid = item["id"]
    existing = index.get(cid)
    if existing is not None:
        for s in item.get("strategies") or []:
            if s not in existing.setdefault("strategies", []):
                existing["strategies"].append(s)
        return False
    index[cid] = item
    pool.append(item)
    return True


def _dedupe_wikis_by_doc(items: list[dict]) -> list[dict]:
    """
    文档池再收敛一次：同一个**回填单元**只留分数最高的那条（strategies 取并集）

    为什么 id 级去重不够
    -------------------
    wiki 的 id 是 **chunk 级**的，而两条改写式命中的常常是同一篇文档的**不同分块**。
    父块回填会把它们各自展开成同一份正文——此时两条**正文一字不差、来源名也相同**，
    却因 id 不同而各占一个名额，白占额度、白烧 token，前端还会出现两个内容完全
    一样的 `[来源N]`。（EDGE-02 实测：`analysis_report_template.md` 重复出现两条。）

    去重键 = `parent_key`（章节级回填）或 `source`（整篇回填/未回填）：
    章节级下同一篇文档的**不同章节**是两份不同的资料，不能按 source 合并。

    只对文档池调用，**不能用于画像池**：所有画像的 source 都是 `user_profile`，
    按 source 收敛会把 3 个用户并成 1 个。
    """
    by_unit: dict[str, dict] = {}
    for c in items:
        key = c.get("parent_key") or c["source"]
        prev = by_unit.get(key)
        if prev is None:
            by_unit[key] = c
            continue
        # 分数高的那条留在原位（正文 / id / from_query 都用它），低的只贡献 strategies
        winner, loser = (
            (c, prev) if c.get("rerank_score", 0) > prev.get("rerank_score", 0) else (prev, c)
        )
        for s in loser.get("strategies") or []:
            if s not in winner.setdefault("strategies", []):
                winner["strategies"].append(s)
        by_unit[key] = winner
    return list(by_unit.values())


def search_variants(
    variants: list[tuple[str, str]],
    top_k: int = TOP_K_RRF,
    dept: str | None = None,
    keyword_mode: str | None = None,
    origin_query: str | None = None,
    trace_out: list[dict] | None = None,
    top_k_profile: int = TOP_K_PROFILE,
) -> list[dict]:
    """
    各路**并行**检索 → 画像池跨路合并统一精排 / 文档池各路分池精排 → 合并去重

    链路（与设计约定一致）：
        每条改写 query 独立走 hybrid_search（向量 top20 + BM25 top20 → RRF → top30）；
        画像池：把所有路召回的画像候选**合并到一起、统一精排取全局 Top-K**（默认 3）；
        文档池：**每路各自精排取 Top-M**（默认 2，含相关度阈值过滤与父块全文扩展）；
        两池结果合并、按 id 去重后直接作为候选，**不再做第二次融合**。

    为什么两个池的取舍方式不一样（这是本函数最容易被改错的地方）
    --------------------------------------------------------
    两个池要的东西不同，所以不能套用同一套合并策略：

      画像池要的是「**全局最相关的 N 个用户**」——候选之间是**竞争**关系。
        多路只是召回手段，同一个用户在几条改写式下都命中，只会重复占名额。
        分路各取 3 个再合并，等于让「弱路的第 1 名」和「强路的第 1 名」并列：
        3 路就能交回 9 条画像，而其中大部分是各路的凑数项。
      文档池要的是「**覆盖**」——不同改写式（尤其子问题分解）命中的业务规则
        常常是不同文件。分路保名额才能保证「每个子问题的口径都进上下文」；
        若也合并成一个大池统一精排，名额会被其中一路的文档整片占满，
        另一个子问题对应的口径直接消失。

    一句话：**画像求相关性（跨路统一竞争），文档求覆盖度（分路各自保名额）。**

    为什么画像池的统一精排用「原问题」打分：
        改写式是为召回而生成的近似表达，拿它当相关性基准等于用手段去评判目的。
        统一精排时用**用户真正问的那句**（origin_query；缺省取首路检索式，
        即「直接检索」的原句）给所有候选打分，跨路候选才在同一把尺子上比较。

    为什么各路之间不再 RRF：不再按名次融合让它们重新竞争——弱路的第 5 名
    仅凭名次就能挤掉强路的第 1 名。合并去重只解决「同一条被多路选中」，
    不改变各池的选择结果。

    top_k_profile 是**画像池的全局名额**（不是每路名额）——接口层的
    「返回多少个用户」调的就是它；评测 / 工具脚本不传，用 config 默认值。

    单路时本函数与改造前完全等价：只有一路时「跨路合并」等于「本路候选」，
    画像仍是该路精排取 Top-K，不引入任何行为变化。

    为什么精排串行、检索并行：检索是 DB + BM25，线程池并发安全且收益直接；
    精排是 GPU 前向，多线程同时 predict 同一 CrossEncoder 会争抢 CUDA，
    串行执行（每路 30 条约 0.1s）没有感知成本。

    origin_query 会回填到每条候选上，生成阶段据此标注「这条资料是从哪个问题
    找出来的」（原始提问 vs 某条改写），避免 LLM 拿到一份无法溯源的扁平清单。

    trace_out 传入列表时，每路的摘要会追加进去（策略名 / 检索式 / 召回数 /
    该路画像入池数 / 该路保留的文档数 / 来源），供前端展示检索过程；不传则不留痕。
    """
    if not variants:
        return []

    # 预热两个模型：确保在进入线程池之前都已加载完。
    # get_reranker / get_model 都是「无锁的懒加载」——线程池里第一次多路检索会
    # 让多个线程同时看到 `_model is None`，于是各自构造一个 SentenceTransformer。
    #
    # 这里的代价**不是慢一点，而是报错**：某个线程会拿到正在转 fp16 的模型，
    # 抛 "expected scalar type Half but found Float"，该路被当作「检索失败」静默跳过。
    # 表现是「明明规划了 3 路，trace 里只有 2 路」（2026-10-15 实测撞到 3 次，
    # 全部发生在进程冷启动后的第一个多路问题上）。
    #
    # 生产不受影响（api/main.py 的 lifespan 启动时已 get_model()），
    # 但评测脚本、tools 下的脚本都没有这个保护。
    get_reranker()
    get_model()

    # ① 各路并行检索
    #
    # ⚠ 提交时必须**把当前上下文拷一份带进去**。concurrent.futures 的线程**不继承
    # contextvar**，也就是说这些检索线程会拿到默认值——而「当前数据集」正是靠
    # contextvar 传的（见 db/connection.py）。不拷，所有检索都会安静地打到默认数据集
    # （demo）上：/qa 上看不出任何异常（它本来就查 demo），但向导切到 user/test 之后
    # 会「用别人的数据回答我的问题」，且没有任何报错。2026-10-17 实测踩到。
    #
    # 必须**逐任务** copy：一个 Context 不能被两个线程同时进入，
    # 共用一份会让第二路直接抛 RuntimeError。
    per_variant_hits: dict[tuple[str, str], list[dict]] = {}
    errors: dict[tuple[str, str], str] = {}
    with ThreadPoolExecutor(max_workers=len(variants)) as pool:
        futures = {
            pool.submit(
                contextvars.copy_context().run,
                _retrieve_one, strategy, text, top_k, dept, keyword_mode, origin_query,
            ): (strategy, text)
            for strategy, text in variants
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                per_variant_hits[key] = fut.result()
            except Exception as e:
                logger.warning("策略「%s」检索失败，跳过: %s", key[0], e)
                errors[key] = str(e)

    # ② 分池取舍：画像**只入池不淘汰**（跨路合并后统一精排），
    #    文档**本路精排取 Top-M**（分路保覆盖）
    profile_pool: list[dict] = []
    pool_index: dict[str, dict] = {}
    wiki_kept: list[dict] = []
    for strategy, text in variants:
        key = (strategy, text)
        if key in errors:
            if trace_out is not None:
                trace_out.append({
                    "strategy": strategy, "query": text,
                    "hit_count": 0, "profile_candidates": 0,
                    "kept_count": 0, "sources": [], "error": errors[key],
                })
            continue
        hits = per_variant_hits.get(key) or []

        # 画像：本路**不做取舍**，全部入池，等所有路收完再统一精排。
        # 同一条被多路命中只占一个池内名额（strategies 合并，留下共识依据）
        profiles_in_route = 0
        for c in hits:
            if not is_doc_source(c["source"]):
                if _offer_to_pool(profile_pool, pool_index, c):
                    profiles_in_route += 1

        # 文档：**保持每路分池精排**（相关度阈值过滤 + 父块全文扩展都在这里做）。
        # 精排失败不按「跳过该路」处理——精排是整个链路的基础能力，
        # 它挂了应该整体暴露，而不是静默退化成一个只有部分资料的回答
        wikis_in_route = [c for c in hits if is_doc_source(c["source"])]
        kept = (
            rerank_by_source(text, wikis_in_route, top_k_wiki=TOP_K_WIKI)
            if wikis_in_route else []
        )
        kept_in_route = 0
        for c in kept:
            # 跨路去重：同一篇文档被两路同时选中时只留一份
            if _offer_to_pool(wiki_kept, pool_index, c):
                kept_in_route += 1

        if trace_out is not None:
            trace_out.append({
                "strategy": strategy,
                "query": text,
                "hit_count": len(hits),
                # 该路给画像池送了几个候选（不在本路淘汰）、本路文档留了几条
                "profile_candidates": profiles_in_route,
                "kept_count": kept_in_route,
                "sources": [h["source"] for h in kept[:8]],
            })

    # ③ 画像池统一精排：用**原问题**给跨路候选打分，取全局 Top-K。
    #    缺省取首路检索式——首路恒为「直接检索」，它的检索式就是原问题
    rerank_query = origin_query or variants[0][1]
    kept_profiles = (
        rerank(rerank_query, profile_pool, top_k=top_k_profile) if profile_pool else []
    )

    # 文档池按文档名再收敛一次：同一篇被两路命中不同 chunk 时，id 不同、
    # 展开父块后正文却完全相同，只按 id 去重会留下重复占位
    wiki_kept = _dedupe_wikis_by_doc(wiki_kept)

    # 画像在前、文档在后：两池分数出自**不同 query**，横向比大小没有意义，
    # 不再按分数混排（那等于拿两把尺子量出来的数排序）
    merged: list[dict] = kept_profiles + wiki_kept

    if not merged:
        # 注意区分两种「空」：
        #   全部路都抛异常  -> 检索不可用，必须让上层知道（否则被当成「资料缺失」）
        #   全部路都无命中  -> 正常的空结果，按「资料里没有」处理
        if trace_out and len(trace_out) == len(variants) and all(v.get("error") for v in trace_out):
            raise RetrievalUnavailableError(
                f"全部 {len(variants)} 路检索均失败：{trace_out[0].get('error')}"
            )
        return []
    return merged


# TODO(perf): [P1] 多路规划那次 LLM 调用仍是主要开销（实测约 6s，占单次问答 31%）。
#             按需生成已能省掉部分变体的检索与生成时间，但 LLM 往返本身无法省。
#             进一步降本方向：改规则扩展 / 换更快的模型。详见 bug/性能隐患台账.md P1
def multi_query_search(
    question: str,
    top_k: int = TOP_K_RRF,
    dept: str | None = None,
    keyword_mode: str | None = None,
    top_k_profile: int = TOP_K_PROFILE,
) -> QueryPlan:
    """
    多路并行检索 + 分池取舍（画像跨路统一精排 / 文档各路保名额）+ 合并去重

    返回 QueryPlan：调用方应先看 plan.route——若被复核改道成 chitchat，
    说明这个问题本就不该走检索，此时 candidates 为空且**检索已被跳过**（省一次白跑）。
    plan.need_sql 为真时，调用方还需自行追加一条结构化查询路。

    top_k_profile 是画像池的**全局**名额，透传给 search_variants；接口层的
    「返回多少个用户」就是它。
    """
    plan = plan_queries(question)

    if plan.route != ROUTE_RAG:
        return plan  # 改道了，candidates 用不上，检索直接省掉

    per_variant: list[dict] = []
    plan.candidates = search_variants(
        plan.variants, top_k=top_k, dept=dept,
        keyword_mode=keyword_mode, origin_query=question,
        trace_out=per_variant, top_k_profile=top_k_profile,
    )
    plan.trace = {
        # 原问题一起带走：前端要对照「原问题 vs 改写后的检索式」才看得出改写做了什么
        "question": question,
        "need_sql": plan.need_sql,
        "variants": per_variant,
        # 合并去重后的候选总数（不是各路之和——同一条被多路选中只算一份）
        "fused_count": len(plan.candidates),
        # 两个池的名额口径**不同**，字段名必须分开，否则前端会当成同一套配额：
        # profile_pool  = 画像池全局名额（跨路合并统一精排后取 K）
        # wiki_per_route = 文档池每路名额（分路各自保覆盖）
        # （改造前是 kept_per_route={"profile","wiki"}，那是「每路各自」的配额）
        "limits": {"profile_pool": top_k_profile, "wiki_per_route": TOP_K_WIKI},
        # 画像池入池总数（跨路去重后、精排前）：前端展示「N 条画像候选 → 精排取 K」
        "profile_pool_count": sum(v.get("profile_candidates", 0) for v in per_variant),
        # 文档池被「同文档收敛」丢掉的重复杂数（同一篇被多路命中不同 chunk）。
        # 正常情况为 0 或 1；持续 >0 说明多路改写撞到同一篇文档，属正常现象，
        # 留个数是为了排查时能看出「到底丢了几条」，而不是只能怀疑
        "wiki_doc_dedup": (
            sum(v.get("kept_count", 0) for v in per_variant)
            - sum(1 for c in plan.candidates if is_doc_source(c["source"]))
        ),
    }
    return plan
