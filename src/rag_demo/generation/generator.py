#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : generator.py
@Function: 带引用要求的 Prompt 构造 + LLM 调用（DeepSeek / OpenAI 兼容接口）
"""
import os
from openai import OpenAI

from rag_demo.prompts import RAG_ANSWER_PROMPT, SQL_SUMMARY_PROMPT

# ================= 配置区 =================
API_KEY = os.getenv("DEEPSEEK_API_KEY")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

client = OpenAI(api_key=API_KEY or "EMPTY", base_url=BASE_URL)
# 提示词统一在 rag_demo/prompts.py 维护
# ==========================================


def build_context(candidates):
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(f"[来源{i}] ({c['source']}) {c['text']}")
    return "\n".join(lines)


def generate(query, candidates, model=MODEL):
    if not candidates:
        return {"answer": "根据现有资料无法确定。", "sources": []}

    if not API_KEY:
        raise RuntimeError(
            "未配置 DEEPSEEK_API_KEY 环境变量，无法调用大模型。"
            "请先设置：set DEEPSEEK_API_KEY=sk-xxxx"
        )

    context = build_context(candidates)
    prompt = RAG_ANSWER_PROMPT.format(context=context, question=query)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    answer = resp.choices[0].message.content
    sources = [
        {"index": i, "source": c["source"], "text": c["text"][:100]}
        for i, c in enumerate(candidates, 1)
    ]
    return {"answer": answer, "sources": sources}


# ---------- Text2SQL 结果自然语言化 ----------
# 提示词见 rag_demo/prompts.py::SQL_SUMMARY_PROMPT


# TODO(perf): [P4] schema 每次无条件注入（约 500 字 / prompt），
#             但只有「结果 0 行」时才真正需要枚举信息。可改为按需注入。
#             注意：这是修 OPT-06 时引入的必要代价，属可优化点而非缺陷。
#             详见 bug/性能隐患台账.md
def generate_stream(query, candidates, model=MODEL):
    """
    流式生成：逐段产出文本片段

    与 generate() 相比只多一个 stream=True。**总耗时几乎不变**，但
    首字延迟从「整段答案生成完」提前到「第一个 token 到达」——
    用户从「盯着转圈十几秒」变成「几秒后文字开始逐字出现」。

    产出的是字符串片段（delta），调用方负责拼接与推送。
    """
    if not candidates:
        yield "根据现有资料无法确定。"
        return

    context = build_context(candidates)
    prompt = RAG_ANSWER_PROMPT.format(context=context, question=query)
    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
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
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content
