#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : router.py
@Function: 轻量意图路由（二分类）——只负责筛掉闲聊

走向只有两条：
    chitchat  闲聊 / 域外问题 -> 直接返回固定回复，不检索、不调模型
    rag       其余全部        -> 进入多路聚合链路

为什么不再判 SQL
----------------
原先这里用 SQL_KEYWORDS 做「闲聊 / 聚合 / 检索」三分类，但关键词判聚合的
漏判率实测达 50%——8 个统计类问法里 4 个没命中（如「上海和北京的用户哪个多」
「用户里买母婴的多不多」）。口语化的聚合问法靠词表覆盖不住，而一旦漏判，
问题就再也进不了 SQL 链路。

现在 SQL 不再是独立分支，而是「多路聚合」里的一路，由 query_processor 的
多路规划统一决定是否追加——那次 LLM 调用本来就存在（用于判断检索路数），
所以追加 SQL 判断不产生额外成本，而且比关键词准得多。

本模块因此收窄为只做一件事：**筛掉闲聊**。这件事必须留在规则层：
一旦交给 LLM，闲聊也要付一次模型往返，「闲聊省掉两次推理」的初衷就没了。
漏判（该拦没拦）由 query_processor 的路由复核兜底，代价可接受。
"""
import logging

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


def is_chitchat(question: str) -> bool:
    """
    判断是否为闲聊 / 域外问题

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


def route(question: str) -> str:
    """
    判断问题走向，返回 "chitchat" / "rag"

    只做二分类：拦掉闲聊，其余一律进入多路聚合链路。
    「是否需要 SQL 路」「需要哪几路检索」都由 query_processor.plan_queries 统一决定。
    """
    if not question:
        return ROUTE_RAG

    if is_chitchat(question):
        logger.info("意图路由 -> chitchat: %s", question)
        return ROUTE_CHITCHAT

    logger.info("意图路由 -> 多路聚合: %s", question)
    return ROUTE_RAG
