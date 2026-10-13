#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""临时脚本：校验统一后的提示词占位符可正常填充"""
from rag_demo.prompts import (
    CHITCHAT_REPLY,
    MULTI_QUERY_PROMPT,
    RAG_ANSWER_PROMPT,
    SQL_SCHEMA,
    SQL_SUMMARY_PROMPT,
    TEXT2SQL_PROMPT,
)

# 逐个 .format()，占位符不匹配会直接抛 KeyError/IndexError
rendered = {
    "RAG_ANSWER_PROMPT": RAG_ANSWER_PROMPT.format(context="【资料】", question="【问题】"),
    "SQL_SUMMARY_PROMPT": SQL_SUMMARY_PROMPT.format(
        schema=SQL_SCHEMA, question="【问题】", sql="SELECT 1", row_count=0, rows="（空结果）"
    ),
    "TEXT2SQL_PROMPT": TEXT2SQL_PROMPT.format(schema=SQL_SCHEMA, question="【问题】"),
    "MULTI_QUERY_PROMPT": MULTI_QUERY_PROMPT.format(question="【问题】"),
}

print("=== 占位符填充校验 ===")
for name, text in rendered.items():
    print(f"[OK] {name:22s} 渲染后 {len(text):5d} 字")
    assert "【问题】" in text or name == "RAG_ANSWER_PROMPT", name

print()
print("=== 素材/文案长度 ===")
print(f"SQL_SCHEMA      {len(SQL_SCHEMA):5d} 字")
print(f"CHITCHAT_REPLY  {len(CHITCHAT_REPLY):5d} 字")

print()
print("=== 关键内容抽查（确认搬家未丢字）===")
checks = [
    ("RAG 引用要求", "每个关键结论后面标注 [来源N]", RAG_ANSWER_PROMPT),
    ("SQL 写操作禁令", "禁止 UPDATE / DELETE / INSERT / ALTER / DROP", TEXT2SQL_PROMPT),
    ("总结空结果处理", "数据里本来就没有这一类", SQL_SUMMARY_PROMPT),
    ("路由保守原则", "拿不准一律写 rag", MULTI_QUERY_PROMPT),
    ("schema 枚举", "钻石 / 黄金 / 白银 / 普通", SQL_SCHEMA),
    ("文案引导语", "换个相关的问题试试", CHITCHAT_REPLY),
]
for label, needle, hay in checks:
    print(f"[{'OK ' if needle in hay else 'MISS'}] {label}")

print()
print("=== 提示词总数 ===")
import rag_demo.prompts as p
names = [n for n in dir(p) if not n.startswith("_") and n.isupper()]
print(names)
