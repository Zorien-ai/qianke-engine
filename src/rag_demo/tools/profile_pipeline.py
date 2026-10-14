#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : profile_pipeline.py
@Function: 拆解一次问答的各环节耗时，定位真实瓶颈

用途：回答「为什么这么慢」这类问题——逐段计时，不靠猜测。

⚠ 性能问题必须先测量再下结论。本项目有过两次教训：按代码结构猜「串行是瓶颈」，
  实测那部分只占 3.8%；按结构猜「五路检索贵」，实测 0.75s。
  结论：任何优化提案前，先跑这个脚本。

链路（与 pipeline 实际执行顺序一致）：
    ① 多路规划   1 次 LLM —— 路由复核 + SQL 判定 + 变体生成，三合一
    ② 各路并行检索 + 各路精排   hybrid_search × N（并行）→ 各路 RRF top30
                                → 各路分来源精排（画像 Top-3 + 文档 Top-2）
    ③ 合并去重   各路 top5 按 id 去重，直接作为候选（无二次融合、无整体终选）
    ④ Text2SQL   1 次 LLM（仅 need_sql 时）
    ⑤ SQL 执行   PostgreSQL
    ⑥ 答案生成   1 次 LLM（流式，计时含全部 chunk）

脚本先预热（加载模型），再跑两轮；**看第二轮**——第一轮含模型加载与 CUDA 首次分配。

用法：
    python src/rag_demo/tools/profile_pipeline.py
    python src/rag_demo/tools/profile_pipeline.py OPT-04      # 指定题目
"""
import json
import os
import sys
import time

from rag_demo.config import BASE_DIR, TOP_K_RRF
from rag_demo.generation.generator import generate_stream
from rag_demo.retrieval.query_processor import (
    STRATEGY_DIRECT,
    plan_queries,
    search_variants,
)
from rag_demo.tools.sql_tool import execute_sql, text2sql, validate_sql

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")


def run_once(qid: str, question: str, label: str) -> dict:
    print(f"\n{'=' * 72}\n【{label}】{qid} | {question}\n{'=' * 72}")
    s = {}

    # ① 多路规划：1 次 LLM 调用同时产出「路由复核 + SQL 判定 + 变体」
    t = time.time()
    plan = plan_queries(question)
    s["plan"] = time.time() - t
    print(f"① 多路规划（1 次 LLM）     : {s['plan']:6.2f}s   "
          f"路由={plan.route}  SQL={plan.need_sql}  变体={len(plan.variants)} 路")
    for name, text in plan.variants:
        print(f"      └ [{name:<8}] {text[:52]}")

    # ② 各路并行检索 + 各路分来源精排 + 合并去重（一次调用内完成）
    trace = []
    t = time.time()
    candidates = search_variants(
        plan.variants, top_k=TOP_K_RRF, origin_query=question, trace_out=trace
    )
    s["search"] = time.time() - t
    hit_total = sum(v["hit_count"] for v in trace)
    kept_total = sum(v.get("kept_count", 0) for v in trace)
    print(f"② 并行检索+各路精排+去重（{len(plan.variants)} 路）: {s['search']:6.2f}s   "
          f"召回 {hit_total} → 各路精排后 {kept_total} → 去重后 {len(candidates)} 条")

    # ⑤⑥ SQL 路：生成 + 执行（仅 need_sql 时）
    sql_result = None
    s["sql_gen"] = s["sql_exec"] = 0.0
    if plan.need_sql:
        t = time.time()
        try:
            sql = text2sql(question)
        except Exception as e:
            sql = ""
            print(f"⑤ Text2SQL 失败: {e}")
        s["sql_gen"] = time.time() - t

        rows, err = [], None
        if sql and validate_sql(sql):
            t = time.time()
            try:
                rows = execute_sql(sql)
            except Exception as e:
                err = str(e)
            s["sql_exec"] = time.time() - t
        sql_result = {"sql": sql, "rows": rows, "error": err}
        print(f"④ Text2SQL（1 次 LLM）    : {s['sql_gen']:6.2f}s")
        print(f"⑤ SQL 执行（DB）          : {s['sql_exec']:6.2f}s   返回 {len(rows)} 行")
    else:
        print("④ Text2SQL                :   ——    （本次不需要 SQL）")

    # ⑦ 答案生成（流式，计时覆盖全部 chunk）
    t = time.time()
    chunks = []
    for delta in generate_stream(question, candidates, sql_result):
        chunks.append(delta)
    s["generate"] = time.time() - t
    answer = "".join(chunks)
    print(f"⑥ 答案生成（1 次 LLM）    : {s['generate']:6.2f}s   答案 {len(answer)} 字")

    s["total"] = sum(s.values())
    llm_total = s["plan"] + s["sql_gen"] + s["generate"]
    print(f"\n   合计 : {s['total']:.2f}s")
    print(f"   其中 LLM 调用 {llm_total:.2f}s（{llm_total / s['total'] * 100:.1f}%）"
          f" | 本地计算（检索+精排+SQL执行）"
          f" {s['total'] - llm_total:.2f}s（{(s['total'] - llm_total) / s['total'] * 100:.1f}%）")
    print(f"   占比 : 规划 {s['plan'] / s['total'] * 100:.1f}% | "
          f"检索+精排+去重 {s['search'] / s['total'] * 100:.1f}% | "
          f"Text2SQL {s['sql_gen'] / s['total'] * 100:.1f}% | "
          f"SQL执行 {s['sql_exec'] / s['total'] * 100:.1f}% | "
          f"生成 {s['generate'] / s['total'] * 100:.1f}%")

    s["answer_len"] = len(answer)
    s["need_sql"] = plan.need_sql
    return s


def main() -> None:
    qid = sys.argv[1] if len(sys.argv) > 1 else "OPT-01"

    with open(os.path.join(TESTS_DIR, "eval_questions.json"), encoding="utf-8") as f:
        items = {q["id"]: q for q in json.load(f)}
    if qid == "CUSTOM" and len(sys.argv) > 2:
        question = sys.argv[2]
    elif qid in items:
        question = items[qid]["question"]
    else:
        print(f"未知题目 ID: {qid}（可用 CUSTOM \"你的问题\" 直接传问题）")
        return

    # 预热：把模型加载、CUDA 首次分配的开销排除在统计之外
    print("[预热] 加载模型与索引...")
    search_variants([(STRATEGY_DIRECT, "预热")], top_k=1)
    print("[预热] 完成")

    run_once(qid, question, "第 1 轮（看数值，不看结论）")
    st = run_once(qid, question, "第 2 轮 ★ 以这轮为准")

    print(f"\n{'=' * 72}")
    print("结论数据（第 2 轮）：")
    rows = [
        ("多路规划（LLM）", st["plan"]),
        ("检索+精排+去重", st["search"]),
        ("Text2SQL（LLM）", st["sql_gen"]),
        ("SQL 执行（DB）", st["sql_exec"]),
        ("答案生成（LLM）", st["generate"]),
    ]
    for name, v in sorted(rows, key=lambda x: -x[1]):
        print(f"  {name:<18} {v:6.2f}s   {v / st['total'] * 100:5.1f}%")
    print(f"  {'合计':<18} {st['total']:6.2f}s")


if __name__ == "__main__":
    main()
