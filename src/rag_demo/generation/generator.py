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
from rag_demo.db.schema_facts import get_sql_schema
from rag_demo.prompts import RAG_ANSWER_PROMPT, SQL_SUMMARY_PROMPT

# ================= 配置区 =================
API_KEY = os.getenv("DEEPSEEK_API_KEY")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

client = OpenAI(api_key=API_KEY or "EMPTY", base_url=BASE_URL)
# 提示词统一在 rag_demo/prompts.py 维护
# ==========================================


def chat_completion(messages, model=None, temperature=0.0, stream=False,
                    deep_thinking: bool | None = None, feature: str = "llm", **kwargs):
    """
    统一的 LLM 调用入口

    **所有模块都应走这里**，而不是各自 `client.chat.completions.create(...)`。
    公共参数（当前是思考模式）集中一处控制——麻烦的从来不是参数写错，
    而是散在 4 个调用点、改的时候漏掉一个，表现为「有的路快有的路慢」。

    deep_thinking：**本次调用**是否启用思考模式
        None  -> 跟随全局 ENABLE_THINKING（缺省关闭），调用行为与改造前一致
        True  -> 强制开启（模型先输出推理过程再给答案：更慢更贵，推理不进答案）
        False -> 强制关闭（即使全局开着，也能单独关掉这一次）

    为什么需要「按次」而不只是全局开关：思考模式的代价是实测慢 63%、token 涨 3.4 倍，
    值不值得只有**最后一个生成调用**说了算——规划、Text2SQL 那些中间调用开思考
    只是白白变慢，答案质量并不会因此提高。全局开关做不到这个区分。

    优先级：调用方显式传入 > 全局 ENABLE_THINKING。全局关时用 setdefault，
    保证调用方通过 extra_body 自己塞的 thinking 仍然优先（便于单点实验）。
    """
    extra = dict(kwargs.pop("extra_body", None) or {})
    if deep_thinking is not None:
        extra["thinking"] = {"type": "enabled" if deep_thinking else "disabled"}
    elif not ENABLE_THINKING:
        extra.setdefault("thinking", {"type": "disabled"})
    resp = client.chat.completions.create(
        model=model or MODEL,
        messages=messages,
        temperature=temperature,
        stream=stream,
        extra_body=extra or None,
        **kwargs,
    )
    # 非流式调用在这里统一记账；流式 usage 在最后一个 chunk，由 generate_events 负责。
    if not stream:
        try:
            from rag_demo import ai_monitor

            ai_monitor.record_llm_usage(
                model=model or MODEL,
                usage=usage_of(resp),
                feature=feature,
            )
        except Exception:  # noqa: BLE001 监控失败不能影响 LLM 调用
            pass
    return resp


def usage_of(resp) -> dict:
    """
    提取 token 用量（含 reasoning 明细）

    思考模式的开销全在 completion_tokens 里、却**不进答案**——不看 reasoning_tokens
    就分不清「答案写长了」和「预算被推理吃掉了」（实测开启时 reasoning 占 completion 的 75%）。
    字段缺失时直接不返回该键，避免上游把 None 当成 0 统计。
    """
    u = getattr(resp, "usage", None)
    if u is None:
        return {}
    out = {
        "prompt_tokens": getattr(u, "prompt_tokens", None),
        "completion_tokens": getattr(u, "completion_tokens", None),
        "total_tokens": getattr(u, "total_tokens", None),
    }
    details = getattr(u, "completion_tokens_details", None)
    if details is not None:
        out["reasoning_tokens"] = getattr(details, "reasoning_tokens", None)
    return {k: v for k, v in out.items() if v is not None}


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
            # 与 pipeline.prepare 保持同构：非流式/流式两条路的 sources 字段必须一致，
            # 否则同一条资料在两种接口下展示的东西不同，排查时非常误导
            "expand_scope": c.get("expand_scope", ""),
            "parent_key": c.get("parent_key", ""),
            "images": c.get("images", []),
        }
        for i, c in enumerate(candidates, 1)
    ]


def generate(query, candidates, sql_result=None, model=MODEL, deep_thinking=None):
    """
    非流式生成。deep_thinking 见 chat_completion——这是「最后一个 LLM」的开关，
    只有这一次调用该不该慢下来多想，由它决定。

    返回值多一个 usage（token 用量，含 reasoning 明细），供 A/B 与前端核算成本；
    API 层不会透出它（permissions.render 只复制白名单字段）。
    """
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
        deep_thinking=deep_thinking,
        feature="answer",
    )
    answer = resp.choices[0].message.content
    return {"answer": answer, "sources": _build_sources(candidates), "usage": usage_of(resp)}


# ---------- 流式事件类型 ----------
# 推理段与答案段必须分成两个通道：混成一条字符串流也能拼出全文，
# 但前端没法把思维链单独折叠展示，也没法在「只有推理、还没有答案」的阶段
# 给出正确的等待提示（那时它会误以为在正常生成）。
EVENT_REASONING = "reasoning"
EVENT_ANSWER = "answer"


def generate_events(query, candidates, sql_result=None, model=MODEL, deep_thinking=None):
    """
    流式生成（带类型的事件流）：yield (kind, text)，kind ∈ {EVENT_REASONING, EVENT_ANSWER}

    为什么需要这个函数：开启思考模式时，推理过程**先于**答案逐段下发，且走的是
    delta 的另一个字段（reasoning_content）。实测两者不交叠——问一个两步心算题，
    前 46 个 chunk 全是 reasoning_content，之后才切到 content。所以这里按字段分流。

    不开启思考时只产生 EVENT_ANSWER，与 generate_stream 完全等价。

    ⚠️ 推理**语言不稳定**：同一个中文问题，实测有时全程英文（两步心算题）、
    有时全程中文（数据统计题）。展示时不要按某一种语言的排版/标点做假设，
    更不要把它当成「答案的草稿」去解析引用——推理不进答案、也不参与 [来源N]。
    """
    has_sql = bool(sql_result and sql_result.get("rows"))
    if not candidates and not has_sql:
        yield EVENT_ANSWER, "根据现有资料无法确定。"
        return

    context = build_context(candidates, sql_result)
    prompt = RAG_ANSWER_PROMPT.format(context=context, question=query)
    stream_kwargs = dict(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=0.3,
        stream=True,
        deep_thinking=deep_thinking,
        feature="answer",
    )
    try:
        stream = chat_completion(**stream_kwargs, stream_options={"include_usage": True})
    except Exception:  # noqa: BLE001 兼容不支持 stream_options 的兼容端点
        stream = chat_completion(**stream_kwargs)
    last_usage = None
    try:
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                last_usage = usage_of(chunk)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # 两个字段都取：思考模式下推理先到，漏掉任一个都会丢内容
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield EVENT_REASONING, reasoning
            if delta.content:
                yield EVENT_ANSWER, delta.content
    finally:
        if last_usage:
            try:
                from rag_demo import ai_monitor

                ai_monitor.record_llm_usage(
                    model=model or MODEL,
                    usage=last_usage,
                    feature="answer",
                )
            except Exception:  # noqa: BLE001
                pass


# ---------- Text2SQL 结果自然语言化 ----------
# 提示词见 rag_demo/prompts.py::SQL_SUMMARY_PROMPT


# TODO(perf): [P4] schema 每次无条件注入（约 500 字 / prompt），
#             但只有「结果 0 行」时才真正需要枚举信息。可改为按需注入。
#             注意：这是修 OPT-06 时引入的必要代价，属可优化点而非缺陷。
#             详见 bug/性能隐患台账.md
def generate_stream(query, candidates, sql_result=None, model=MODEL, deep_thinking=None):
    """
    流式生成：逐段产出文本片段

    与 generate() 相比只多一个 stream=True。**总耗时几乎不变**，但
    首字延迟从「整段答案生成完」提前到「第一个 token 到达」——
    用户从「盯着转圈十几秒」变成「几秒后文字开始逐字出现」。

    产出的是字符串片段（delta），调用方负责拼接与推送。

    ⚠️ 开启 deep_thinking 时首字延迟会大幅劣化：流在**推理跑完、开始吐答案**
    之前一直是空的（推理走另一个字段，本函数把它丢掉了）。也就是说思考模式下
    「流式」只是不用等全部答案，仍要等全部推理——想看推理过程要改用
    `generate_events`，否则用户看到的是「点了深度思考之后卡住不动」。
    """
    for kind, text in generate_events(
        query, candidates, sql_result=sql_result, model=model, deep_thinking=deep_thinking
    ):
        if kind == EVENT_ANSWER:
            yield text


def llm_summarize(question: str, sql_result: dict, schema: str = "") -> str:
    """
    把 Text2SQL 的查询结果转成自然语言回答

    参数:
        question:   用户原始问题
        sql_result: sql_tool.query() 的返回值 {"sql", "rows", "error"}
        schema:     表结构说明（含字段取值范围）。不传则自动从当前数据集采集。

                    必须有，否则 0 行结果无法解释——LLM 不知道枚举有哪些，
                    只能笼统地说"没有符合条件的记录"。典型场景 OPT-06：
                    问「母婴偏好用户」，而 top_category 枚举里根本没有"母婴"，
                    用户无法区分这是「数据缺失」还是「查询写错了」。
                    注意这里要的是**当前数据集**的枚举，不能是写死的 demo 枚举。

    返回:
        自然语言回答字符串
    """
    if sql_result.get("error"):
        return f"查询未能完成：{sql_result['error']}"

    rows = sql_result.get("rows", [])
    rows_text = "\n".join(str(r) for r in rows[:50]) or "（空结果）"

    prompt = SQL_SUMMARY_PROMPT.format(
        schema=schema or get_sql_schema(),
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
