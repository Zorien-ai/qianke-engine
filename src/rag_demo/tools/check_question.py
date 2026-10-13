#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : check_question.py
@Function: 单题调试：跑一条评测题并输出完整过程（路由/SQL/来源/答案）

输出写入 UTF-8 文件而非控制台——Windows 控制台默认 GBK，中文与 emoji 会乱码或直接抛
UnicodeEncodeError，写文件后再查看更可靠。
"""
import argparse
import io
import json
import os

from rag_demo.config import BASE_DIR
from rag_demo.pipeline import answer_question

TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="单题调试")
    parser.add_argument("qid", help="题目 ID，如 OPT-06")
    parser.add_argument("-o", "--output", default="", help="输出文件，默认 check_<ID>.txt")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with open(os.path.join(TESTS_DIR, "eval_questions.json"), encoding="utf-8") as f:
        items = {q["id"]: q for q in json.load(f)}

    if args.qid not in items:
        print(f"未知题目 ID: {args.qid}")
        return
    item = items[args.qid]

    result = answer_question(item["question"])

    lines = [
        f"ID       : {args.qid}",
        f"问题     : {item['question']}",
        f"验收标准 : {item['acceptance']}",
        f"期望来源 : {item['expect_sources']}",
        f"路由     : {result.get('route')}",
        f"SQL      : {result.get('sql', '')}",
        f"rows_count: {result.get('rows_count')}",
        f"实际来源 : {[s['source'] for s in result.get('sources', [])]}",
        "",
        "答案:",
        result.get("answer", ""),
    ]

    out = args.output or os.path.join(BASE_DIR, f"check_{args.qid}.txt")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(str(x) for x in lines))
    print(f"已写入: {out}")


if __name__ == "__main__":
    main()
