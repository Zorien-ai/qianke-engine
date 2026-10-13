#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : router.py
@Function: 轻量意图路由——决定问题走哪条链路

三条走向（与流程图一致）：
    chitchat  闲聊 / 域外问题 -> 直接返回固定回复，不检索、不调模型
    sql       聚合统计类问题  -> Text2SQL
    rag       语义检索类问题  -> 混合检索（默认）
"""
import logging
import re

logger = logging.getLogger(__name__)

ROUTE_SQL = "sql"
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

    规则优先：快、免费、可控。宁可漏判（走正常 RAG），也不要误伤真业务问题——
    漏判的代价是浪费一次检索，误伤的代价是把该答的问题拒之门外。

    漏判由 query_processor 的 LLM 路由复核兜底（复用已有调用，零额外成本）。
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


# ---------- 聚合 / 统计类意图 ----------
SQL_KEYWORDS = [
    # 数量类
    "多少", "几个", "几笔", "几家", "几条", "数量", "规模", "总数", "总共", "合计",
    # 排名类
    "排名", "排行", "top", "前几", "前 5", "前5", "前 3", "前3", "前 10", "前10",
    # 分布 / 比例类
    "分布", "占比", "比例", "百分比", "集中", "聚集",
    # 对比类
    "差异", "对比", "相比",
    # 数值统计类
    "平均", "均值", "最高", "最低", "最多", "最少", "最大", "最小",
    "统计", "汇总", "求和", "计数",
    # 口语化比较 / 计数（2026-10-12 补）
    # 实测漏判：「上海和北京的用户哪个多」「用户里买母婴的多不多」都没命中上面的词。
    # 这里只收「几乎只用于聚合」的说法；判别不了的（如「有啥不一样」）不硬塞，
    # 交给 query_processor 的 LLM 复核——规则层宁可漏，也不要误判。
    "哪个多", "哪个少", "谁多", "谁少", "哪边多", "哪边少",
    "多不多", "少不少", "数一下", "算一下", "数数",
]

# 闲聊固定回复见 rag_demo/prompts.py::CHITCHAT_REPLY


def route(question: str) -> str:
    """
    判断问题走向，返回 "chitchat" / "sql" / "rag"

    顺序很重要：先挡闲聊（最省），再判聚合（要 SQL），剩下的走 RAG。
    """
    if not question:
        return ROUTE_RAG

    if is_chitchat(question):
        logger.info("意图路由 -> chitchat: %s", question)
        return ROUTE_CHITCHAT

    q = question.lower()
    for kw in SQL_KEYWORDS:
        if kw in q:
            logger.info("意图路由 -> sql（命中关键词 '%s'）: %s", kw, question)
            return ROUTE_SQL

    logger.info("意图路由 -> rag: %s", question)
    return ROUTE_RAG
