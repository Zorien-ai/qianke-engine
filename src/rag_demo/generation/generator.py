#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : generator.py
@Function: 带引用要求的 Prompt 构造 + LLM 调用（DeepSeek / OpenAI 兼容接口）
"""
import os
from openai import OpenAI

from rag_demo.config import (
    CONTEXT_INCLUDE_SQL_TEXT,
    ENABLE_THINKING,
    SQL_CELL_MAX_CHARS,
    SQL_ROWS_MAX,
)
from rag_demo.prompts import RAG_ANSWER_PROMPT, SQL_SUMMARY_PROMPT

# ================= 配置区 =================
API_KEY = os.getenv("DEEPSEEK_API_KEY")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

client = OpenAI(api_key=API_KEY or "EMPTY", base_url=BASE_URL)
# 提示词统一在 rag_demo/prompts.py 维护
# ==========================================


def chat_completion(messages, model=None, temperature=0.0, stream=False, **kwargs):
    """
    统一的 LLM 调用入口

    **所有模块都应走这里**，而不是各自 `client.chat.completions.create(...)`。
    公共参数（当前是思考模式）集中一处控制——麻烦的从来不是参数写错，
    而是散在 4 个调用点、改的时候漏掉一个，表现为「有的路快有的路慢」。

    extra_body 允许调用方追加自己的参数，思考模式开关会合并进去；
    调用方已显式指定的 thinking 优先（便于单点实验）。
    """
    extra = dict(kwargs.pop("extra_body", None) or {})
    if not ENABLE_THINKING:
        extra.setdefault("thinking", {"type": "disabled"})
    return client.chat.completions.create(
        model=model or MODEL,
        messages=messages,
        temperature=temperature,
        stream=stream,
        extra_body=extra or None,
        **kwargs,
    )


def build_context(candidates, sql_result=None):
    """
    把检索资料与结构化查询结果拼成 LLM 的 context

    分两段输出，因为二者性质不同：
        [检索资料]        —— 「找到的文本」，需要归纳、可以有推断
        [结构化查询结果]  —— 「算出来的数」，必须原样引用、不能归纳
    混在一起写，模型容易把统计数字当成文本一起"总结"掉。

    每条资料带溯源：从哪个问题找出来的（原始 / 改写）、走的是哪几路。
    没有溯源的话，LLM 只看到一份扁平清单，无法判断某条资料对应提问的哪一部分。
    """
    parts = []

    if candidates:
        lines = ["[检索资料]"]
        for i, c in enumerate(candidates, 1):
            origin = c.get("origin_query") or ""
            from_q = c.get("from_query") or ""
            ways = "、".join(c.get("strategies") or [])

            tags = []
            if origin:
                tags.append(f"原问题: {origin}")
            if from_q and from_q != origin:
                tags.append(f"改写: {from_q}")
            if ways:
                tags.append(f"路径: {ways}")

            head = f"[资料{i}] ({c.get('source', '')})"
            if tags:
                head += "（" + " | ".join(tags) + "）"
            lines.append(f"{head}\n{c['text']}")
        parts.append("\n".join(lines))

    if sql_result and sql_result.get("rows"):
        rows = sql_result["rows"]
        # 单元格逐个截断：一格可能是整段画像文本或十几个字段，原样塞进去很占地方
        rows_text = "\n".join(
            " | ".join(str(v)[:SQL_CELL_MAX_CHARS] for v in r)
            for r in rows[:SQL_ROWS_MAX]
        )
        head = "[结构化查询结果]"
        if CONTEXT_INCLUDE_SQL_TEXT:
            # 默认不放 SQL 原文：模型需要的是「结果」，不是「查询怎么写」。
            # 复杂 SQL 常有 5 个 CTE、50 行，实测占 OPT-05 的 context 1503 字中的大头。
            head += f"\n{sql_result.get('sql', '')}"
        shown = min(len(rows), SQL_ROWS_MAX)
        parts.append(f"{head}\n（共 {len(rows)} 行，下列 {shown} 行）\n{rows_text}")

    return "\n\n".join(parts)


def _build_sources(candidates):
    """候选 → 对外的 sources 列表（带溯源，便于前端/排查）"""
    return [
        {
            "index": i,
            "source": c["source"],
            # 与 pipeline.prepare 保持同一长度，否则非流式与流式两条路的
            # 来源内容长度会不一致（都是「来源」，长度却不同，很容易被当成 bug）
            "text": c["text"][:400],
            "origin_query": c.get("origin_query", ""),
            "from_query": c.get("from_query", ""),
            "strategies": c.get("strategies", []),
        }
        for i, c in enumerate(candidates, 1)
    ]


def generate(query, candidates, sql_result=None, model=MODEL):
    has_sql = bool(sql_result and sql_result.get("rows"))

    if not candidates and not has_sql:
        return {"answer": "根据现有资料无法确定。", "sources": []}

    if not API_KEY:
        raise RuntimeError(
            "未配置 DEEPSEEK_API_KEY 环境变量，无法调用大模型。"
            "请先设置：set DEEPSEEK_API_KEY=sk-xxxx"
        )

    context = build_context(candidates, sql_result)
    prompt = RAG_ANSWER_PROMPT.format(context=context, question=query)
    resp = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=0.3,
    )
    answer = resp.choices[0].message.content
    return {"answer": answer, "sources": _build_sources(candidates)}


# ---------- Text2SQL 结果自然语言化 ----------
# 提示词见 rag_demo/prompts.py::SQL_SUMMARY_PROMPT


# TODO(perf): [P4] schema 每次无条件注入（约 500 字 / prompt），
#             但只有「结果 0 行」时才真正需要枚举信息。可改为按需注入。
#             注意：这是修 OPT-06 时引入的必要代价，属可优化点而非缺陷。
#             详见 bug/性能隐患台账.md
def generate_stream(query, candidates, sql_result=None, model=MODEL):
    """
    流式生成：逐段产出文本片段

    与 generate() 相比只多一个 stream=True。**总耗时几乎不变**，但
    首字延迟从「整段答案生成完」提前到「第一个 token 到达」——
    用户从「盯着转圈十几秒」变成「几秒后文字开始逐字出现」。

    产出的是字符串片段（delta），调用方负责拼接与推送。
    """
    has_sql = bool(sql_result and sql_result.get("rows"))
    if not candidates and not has_sql:
        yield "根据现有资料无法确定。"
        return

    context = build_context(candidates, sql_result)
    prompt = RAG_ANSWER_PROMPT.format(context=context, question=query)
    stream = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=0.3,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def llm_summarize(question: str, sql_result: dict, schema: str = "") -> str:
    """
    把 Text2SQL 的查询结果转成自然语言回答

    参数:
        question:   用户原始问题
        sql_result: sql_tool.query() 的返回值 {"sql", "rows", "error"}
        schema:     表结构说明（含字段取值范围）

                    必须传入，否则 0 行结果无法解释——LLM 不知道枚举有哪些，
                    只能笼统地说"没有符合条件的记录"。典型场景 OPT-06：
                    问「母婴偏好用户」，而 top_category 枚举里根本没有"母婴"，
                    用户无法区分这是「数据缺失」还是「查询写错了」。

    返回:
        自然语言回答字符串
    """
    if sql_result.get("error"):
        return f"查询未能完成：{sql_result['error']}"

    rows = sql_result.get("rows", [])
    rows_text = "\n".join(str(r) for r in rows[:50]) or "（空结果）"

    prompt = SQL_SUMMARY_PROMPT.format(
        schema=schema or "（未提供）",
        question=question,
        sql=sql_result.get("sql", ""),
        row_count=len(rows),
        rows=rows_text,
    )
    resp = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content
