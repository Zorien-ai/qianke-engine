#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : router.py
@Function: 入口层意图路由（二分类）——只负责筛掉闲聊

走向只有两条：
    chitchat  闲聊 / 域外问题 -> 直接返回固定回复，不检索、不调模型
    rag       其余全部        -> 进入多路聚合链路

判定器在 2026-10-16 从「关键词规则」换成「BERT 二分类」
---------------------------------------------------------
换的原因（不是"规则不好"，是规则覆盖不住）：
    规则只能拦「句子短 + 含寒暄词」和「域外话题名词 + 疑问形态」这两类。
    而「闰年是怎么回事」「口红哪个色号好看」「你是AI吗」既没有寒暄词，
    也没有命中域外话题表，全被漏判 —— 实测 test 集 135 条闲聊里规则只拦住
    40 条（详见 bug/bert意图路由替换-延迟与准确率对比.md）。
    漏判的闲聊会继续走「多路规划 LLM(3.8s) + 检索(0.5s) + 生成(20.9s)」约 25s，
    为拦一句话付这种代价没有道理。

为什么不是「交给 LLM 判」
    那样闲聊也要付一次模型往返，而「闲聊省掉两次推理」正是这一层存在的理由。
    本地小模型（102M，单条约 13ms）才能同时满足「判得准」和「判得便宜」。

为什么保留规则（且不是死代码）
    1. 模型目录不入库（.gitignore），新环境未训练时自动回退规则，服务不中断
    2. INTENT_ROUTER 可切 "rule" / "hybrid"，规则是回退开关与对照基线
    3. hybrid 模式下规则先短路，能省掉命中的那部分 13ms

漏判仍然由 query_processor 的路由复核兜底（复用已有 LLM 调用，零额外成本）。
但要注意方向性：那次复核只能在「已判 RAG」的分支里改道成闲聊，也就是**只能捞漏判、
捞不回误伤**。所以门槛宁可偏高——把业务问题误判成闲聊是拒答真问题，
比多走一次检索严重得多（见 config.INTENT_CHITCHAT_THRESHOLD）。
"""
import logging
import time

from rag_demo import config
from rag_demo.tools import bert_intent, intent_telemetry

logger = logging.getLogger(__name__)

ROUTE_RAG = "rag"
ROUTE_CHITCHAT = "chitchat"

# ---------- 寒暄 / 致谢 / 元问题 ----------
# 命中即视为闲聊，直接返回固定回复，省掉两次模型推理
CHITCHAT_KEYWORDS = [
    "你好", "您好", "哈喽", "哈啰", "在吗", "在不在", "在么", "在嘛",
    "hi", "hello", "hey",
    "谢谢", "感谢", "多谢", "辛苦了", "再见", "拜拜", "晚安",
    "早安", "早上好", "中午好", "下午好", "晚上好",
    "哈哈", "嘻嘻", "嘿嘿",
    "你是谁", "你叫什么", "你是什么", "介绍一下你", "你会什么", "你能做什么",
    "讲个笑话", "说个笑话", "讲个故事", "讲个段子", "唱首歌", "随便聊聊", "无聊",
    "写首诗", "作首诗", "翻译一下",
]

# ---------- 明确的域外话题 ----------
# 这些话题与用户画像 / 标签口径 / 运营客服知识库完全无关，但用户确实会问。
# 用「话题名词 + 疑问形态」双重条件，避免误伤（例如「天气」不该拦「天气对销量的影响」这类真业务问题
# 目前知识库里也没有，但保留窄口径更安全）。
OFFTOPIC_TOPICS = [
    "天气", "气温", "下雨", "股票", "基金", "彩票", "新闻", "汇率",
    "油价", "菜价", "星座", "算命", "游戏", "电影", "音乐", "旅游攻略",
]
OFFTOPIC_QUESTION_HINTS = [
    "怎么样", "如何", "多少", "是什么", "好不好", "会不会", "有没有",
    "吗", "呢", "?", "？", "几", "哪天", "什么时候",
]


# 寒暄关键词只在「短句」里才判闲聊。
#
# 原先这里没有长度限制，只要句子里出现「你好」就整句判闲聊——实测
# 「你好，我想问问高价值用户怎么定义」被拦掉，真问题直接拒答。
# 这类误判的代价（该答的答不了）远大于漏判（浪费一次检索），所以必须设上限。
CHITCHAT_MAX_LEN = 12


# ---------- 业务词兜底：优先级高于 BERT / 规则 ----------
# 实测 BERT 会把「很能花钱的女生都有谁」判成闲聊（P(闲聊) ≥ 阈值）。这类问题含明确业务词，
# 只是表达比较口语化；拒答真业务问题比漏拦闲聊代价大得多。命中业务信号时直接判 rag
# （via=business_guard），不调模型；寒暄/域外短句（你好、今天天气怎么样）不含这些词，
# 仍会按原逻辑被拦掉。
BUSINESS_SIGNALS = [
    "消费", "花钱", "下单", "购买", "订单", "客单", "金额", "用户", "画像", "会员",
    "标签", "偏好", "品类", "商品", "年龄", "性别", "女生", "男生", "女性", "男性",
    "城市", "地区", "运营", "营销", "召回", "流失", "沉默", "活跃", "销售", "客服",
    "权益", "统计", "占比", "分布", "排名", "人数", "规模", "美妆", "推荐", "sop",
    "流程", "规则", "分群", "高价值", "高客单", "低客单", "复购", "转化",
]


def has_business_signal(question: str) -> bool:
    """问题里是否出现明确的业务信号词（用于兜住口语化业务问题）。"""
    q = (question or "").strip().lower()
    return any(word in q for word in BUSINESS_SIGNALS)


def rule_is_chitchat(question: str) -> bool:
    """
    关键词规则判定（改造前的线上逻辑，现在是回退与对照基线）

    规则优先：快、免费、可控。宁可漏判（走正常链路），也不要误伤真业务问题——
    漏判的代价是浪费一次检索，误伤的代价是把该答的问题拒之门外。

    漏判由 query_processor 的路由复核兜底（复用已有 LLM 调用，零额外成本）。
    """
    if not question:
        return False

    q = question.strip().lower()

    # 寒暄 / 致谢 / 元问题：仅限短句——长句里的「你好」多半是正式提问的开场
    if len(q) <= CHITCHAT_MAX_LEN and any(kw in q for kw in CHITCHAT_KEYWORDS):
        return True

    # 域外话题：名词 + 疑问形态同时出现才拦
    if any(t in q for t in OFFTOPIC_TOPICS) and any(h in q for h in OFFTOPIC_QUESTION_HINTS):
        return True

    return False


def decide(question: str) -> tuple[bool, float | None, str]:
    """
    一次判定，返回 (是否闲聊, P(闲聊), 判定来源)

    判定来源 via：
        rule          配置强制走规则（INTENT_ROUTER="rule"）或 hybrid 下规则短路
        bert          模型判定
        business_guard 命中业务词，强制判 rag（优先于规则/模型，避免口语化业务问题被误杀）
        rule_fallback 模型不可用（目录缺失 / 加载失败 / 推理异常）回退规则

    为什么要把 via 带出来：埋点必须能区分「模型判的」和「规则兜的」。
    混在一起统计会把模型能力算错——规则回退期间的真实流量不代表模型水平。
    """
    if not question:
        return False, None, "rule"

    # 业务词优先级最高：BERT 对口语化业务问句会误判闲聊，这里直接判 rag。
    if has_business_signal(question):
        return False, None, "business_guard"

    mode = config.INTENT_ROUTER

    if mode == "rule":
        return rule_is_chitchat(question), None, "rule"

    if mode == "hybrid" and rule_is_chitchat(question):
        # 规则已命中，省掉这次 BERT 前向（约 13ms）
        return True, None, "rule"

    try:
        prob = bert_intent.chitchat_prob(question)
    except Exception as e:  # noqa: BLE001
        logger.warning("意图分类推理失败，本次回退关键词规则: %s: %s", type(e).__name__, e)
        prob = None

    if prob is None:
        return rule_is_chitchat(question), None, "rule_fallback"

    return prob >= config.INTENT_CHITCHAT_THRESHOLD, prob, "bert"


def is_chitchat(question: str) -> bool:
    """
    按 config.INTENT_ROUTER 选择判定器（bert / hybrid / rule）

    BERT 不可用（模型缺失、加载失败、推理异常）时一律回退规则：
    闲聊判定是优化项，不该成为服务可用性的依赖。
    """
    if not question:
        return False
    return decide(question)[0]


def route(question: str) -> str:
    """
    判断问题走向，返回 "chitchat" / "rag"（并落一条回流埋点）

    只做二分类：拦掉闲聊，其余一律进入多路聚合链路。
    「是否需要 SQL 路」「需要哪几路检索」都由 query_processor.plan_queries 统一决定。

    埋点在这层做（不是 pipeline 层）：这里才有 P(闲聊)、门槛和判定耗时，
    而 P(闲聊) 正是后续决定「门槛要不要调、数据要不要补」的唯一依据。
    """
    if not question:
        return ROUTE_RAG

    t0 = time.perf_counter()
    hit, prob, via = decide(question)
    latency_ms = (time.perf_counter() - t0) * 1000
    result = ROUTE_CHITCHAT if hit else ROUTE_RAG

    # best-effort：埋点自己吞异常，绝不因它让请求失败
    intent_telemetry.record_route(
        query=question, route=result, mode=config.INTENT_ROUTER,
        p_chitchat=prob, threshold=config.INTENT_CHITCHAT_THRESHOLD,
        latency_ms=latency_ms,
    )

    logger.info(
        "意图路由(%s/%s, p=%.4f, %.1fms) -> %s: %s",
        config.INTENT_ROUTER, via,
        -1.0 if prob is None else prob, latency_ms,
        "chitchat" if hit else "多路聚合", question,
    )
    return result
