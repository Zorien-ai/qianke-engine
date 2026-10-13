#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : test_sql_tool.py
@Function: Text2SQL 专项测试（Phase 4 验收用）
"""
import logging
import sys

from rag_demo.tools.sql_tool import query

# 部分终端是 GBK，无法编码的字符用 ? 替代，避免直接崩溃
sys.stdout.reconfigure(errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

QUESTIONS = [
    "一共有多少用户",
    "客单价最高的 5 个用户",
    "美妆用户的平均客单价是多少",
    "深圳有多少女性用户",
    "用户最多的前 5 个城市",
]


def main() -> None:
    for q in QUESTIONS:
        r = query(q)
        print("=" * 62)
        print(f"问题: {q}")
        print(f"SQL : {r['sql']}")
        if r["error"]:
            print(f"错误: {r['error']}")
        else:
            print(f"结果({len(r['rows'])} 行):")
            for row in r["rows"][:10]:
                print(f"    {row}")
    print("=" * 62)


if __name__ == "__main__":
    main()
