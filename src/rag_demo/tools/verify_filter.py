#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : verify_filter.py
@Function: 验证 wiki 名额过滤（问题 5）改动前后的来源差异
"""
import json
import os

from rag_demo.config import BASE_DIR
from rag_demo.pipeline import answer_question

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")
IDS = ["OPT-02", "CS-04", "OPT-01", "DA-01", "CS-01", "CS-02"]


def main() -> None:
    with open(os.path.join(TESTS_DIR, "eval_questions.json"), encoding="utf-8") as f:
        questions = {q["id"]: q for q in json.load(f)}
    with open(os.path.join(TESTS_DIR, "eval_results_gpu_v2_2026-10-11.json"), encoding="utf-8") as f:
        old = {r["id"]: r.get("actual_sources", []) for r in json.load(f)}

    for qid in IDS:
        item = questions[qid]
        r = answer_question(item["question"])
        after = [s["source"] for s in r["sources"]]
        before = old.get(qid, [])
        flag = "  <-- 变化" if before != after else ""
        print(f"\n### {qid}  {item['question']}")
        print(f"    before: {before}")
        print(f"    after : {after}{flag}")
        print(f"    wiki 条数: {sum(1 for s in before if s.endswith('.md'))} -> {sum(1 for s in after if s.endswith('.md'))}")


if __name__ == "__main__":
    main()
