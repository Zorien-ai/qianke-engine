#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : answer_guard.py
@Function: 生成后审查——不信任大模型的嘴，但信任代码的手

为什么需要这一层
----------------
预测类问题的**前置**关键词硬拦截已经删掉（原因见 query_processor.py 的说明）：
拿一张词表决定「这个问题能不能答」，换个数据集、换个行业就失效，而且误杀的是
**正常问题**。现在「要不要追加 SQL 路」由规划 LLM 判定，提示词也要求不编造未来值。

但提示词只是约束，不是保证。模型仍然可能张口就是「明年 GMV 将达到 1.2 亿」——
这句话背后没有任何数据支撑，而用户看不出它和「资料里说 X」的区别。
所以补一道**后置**审查：生成完再查，命中就把整段答案换成固定文案。

与前置拦截的关键区别
--------------------
- 前置拦截看「问题里有没有某个词」→ 误杀正常问题；
- 后置审查看「答案里有没有编未来数据」→ 只拦**已经编出来的**答案。
  模型老实说「算不出」时不会被拦：那句话本身是有用的信息
  （2026-10-17 实测它确实会说「资料里没有时间序列，任何具体数字都是编的」）。

启用条件与依据
--------------
- 开关：`RAG_ANSWER_GUARD=0` 关闭（默认开启）。关闭后只剩提示词约束。
- 命中需要**三个条件在同一句里同时成立**，任一不成立就放行：
    1. 问题带未来时点意图（明年 / 下季度 / 未来 …）——不是在问未来，就不查；
    2. 答案某句出现未来断言（预测 / 预计 / 将会 / 将达到 …）；
    3. 同一句给出了具体数字（否则只是一句方向性描述，不构成「编造数据」）。
- 按句判定而不是整段：跨句的历史数字（「2024 年 GMV 是 1200 万元。明年算不出来。」）
  不会被当成未来断言；同一句里「先否认、后给数」也不会被句首的否认放行。
- 例外：该句本身在否认（无法预测 / 算不出 / 没有时间序列 …）→ 放行。
  这道审查要拦的是「假装算出来了」，不是「诚实地拒绝」。
- 依据：2026-10-17 安全防御测试里，模型对「预测明年的 GMV」老实拒答。
  这道审查兜的是「它哪天不老实」的那一次，不属于日常路径——所以宁可条件保守
  （三条件同时满足才动手），也不去扩大拦截面。
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

# 默认开启：这是安全兜底，不该要求部署方先记得打开
ENABLED = os.environ.get("RAG_ANSWER_GUARD", "1") != "0"

# 问题侧：未来时点意图。命中不代表拒绝回答，只是「值得查一下答案有没有编」。
# 收得比较窄：只放明确指向未来的说法，「最近 / 近期」这种时效词不算——
# 它们在问历史数据里的最近一段，答案里有具体数字是正常的。
_QUESTION_FUTURE = (
    "明年", "后年", "下个季度", "下季度", "下个月", "未来", "将来",
    "预测", "预估", "预计", "趋势", "走向", "forecast", "next year",
)

# 答案侧：未来断言。模型编未来数据时几乎必然出现其中之一。
#
# 刻意**不含**单独出现的「预测」：「不构成整体预测依据」「预测价值有限」这类
# 名词用法在诚实回答里很常见，2026-10-17 实测就被它误伤过一次
# （标题句「样本仅 3 人，不构成整体预测依据」被判成在编造未来数据）。
# 真正的编造一定有「明年 / 预计 / 将会」这类指向未来的动词或时间词，不靠「预测」也能抓到。
_ANSWER_CLAIM = (
    "预计", "预估", "将会", "将达到", "有望达到", "有望", "预期",
    "明年", "后年", "下个季度", "下季度", "下个月", "未来", "forecast",
    "projected", "预计达到",
)

# 答案侧：明确的否认。命中就放行——「算不出来」正是我们想要的回答。
_ANSWER_DENIAL = (
    "无法预测", "不能预测", "不做预测", "不支持预测", "无法预估", "无法推算",
    "算不出", "算不出来", "不能推算", "无法给出", "无法判断", "没有办法预测",
    "没有时间序列", "没有历史", "缺少时间序列", "资料里没有", "资料中没有",
    "无法可靠预测", "不能可靠预测", "不具备预测",
)

# 具体数字分两类，阈值不同的原因：金额/比例本身就是「编出来的结论」，
# 而人数/单量在诚实回答里常常只是**样本量**（「样本仅 3 人」）。
# 所以计数类要求 3 位数以上才算「编造规模」，个位数/两位数一律放行。
_NUMBER_MONEY_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:万亿|亿|万|千|百|元|块|%|％|倍)",
)
_NUMBER_COUNT_RE = re.compile(
    r"\d{3,}(?:\.\d+)?\s*(?:人|单|件|个)",
)


def _number_in(sentence: str) -> str | None:
    m = _NUMBER_MONEY_RE.search(sentence) or _NUMBER_COUNT_RE.search(sentence)
    return m.group(0) if m else None

# 按句判定，而不是整段判定。两个理由（都是实测能碰到的形态）：
#   1. 「2024 年 GMV 是 1200 万元。明年这个数算不出来。」——整段判定会把
#      跨句的历史数字当成未来断言，误杀一条诚实回答；
#   2. 「明年无法预测，据推测大约 1.2 亿。」——整段判定又会被句首的「无法预测」
#      放行，漏掉同一句里编出来的数字。
# 句内同时出现 未来断言 + 数字 + 否认 时按「保留」处理：那是模型在自我限定，
# 不是假装算出来了。
_SENTENCE_SPLIT = re.compile(r"[。；;！!？?\n]+")


def _hits(text: str, words: tuple[str, ...]) -> str | None:
    low = (text or "").lower()
    for w in words:
        if w.lower() in low:
            return w
    return None


def _find_fabricated(text: str) -> tuple[str, str, str] | None:
    """返回第一句「既做未来断言、又给出数字、且没在同一句里否认」的 (句子, 断言词, 数字)"""
    for raw in _SENTENCE_SPLIT.split(text):
        sentence = raw.strip()
        if not sentence:
            continue
        claim = _hits(sentence, _ANSWER_CLAIM)
        if claim is None:
            continue
        if _hits(sentence, _ANSWER_DENIAL) is not None:
            continue  # 这句在自我限定（算不出 / 资料里没有），不算编造
        number = _number_in(sentence)
        if number is None:
            continue  # 只给了方向没给数字，不构成「编造数据」
        return sentence, claim, number
    return None


def inspect(question: str, answer: str) -> dict | None:
    """
    审查一条已生成的答案

    返回 None = 放行；返回 dict = 命中的规则（调用方据此替换答案并留痕）。
    """
    if not ENABLED:
        return None
    text = (answer or "").strip()
    if not text:
        return None  # 空答案不归这里管（生成侧会走 LLM_UNAVAILABLE_REPLY）

    q_hit = _hits(question, _QUESTION_FUTURE)
    if q_hit is None:
        return None  # 问题不是在问未来：历史事实类答案原样放行

    found = _find_fabricated(text)
    if found is None:
        return None  # 模型老实说算不出，或只给了方向没给数字：保留原文

    sentence, claim, number = found
    logger.warning(
        "答案后置审查命中：问题含「%s」，答案句含「%s」并给出数字「%s」：%s",
        q_hit, claim, number, sentence[:80],
    )
    return {
        "rule": "prediction_claim",
        "question_signal": q_hit,
        "answer_signal": claim,
        "number": number,
        "sentence": sentence[:120],
    }


def summarize(guard: dict | None) -> str:
    """给日志/接口用的一句话摘要（不含答案正文，避免二次泄露）"""
    if not guard:
        return "-"
    return f"{guard.get('rule')}({guard.get('question_signal')}/{guard.get('answer_signal')}/{guard.get('number')})"
