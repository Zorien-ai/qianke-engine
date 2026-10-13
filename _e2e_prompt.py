#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""临时脚本：提示词统一后三条链路的端到端验证"""
import io
import os
import time

from rag_demo.config import BASE_DIR
from rag_demo.pipeline import answer_question

CASES = [
    ("你好", "chitchat", "CHITCHAT_REPLY"),
    ("有多少美妆用户", "sql", "TEXT2SQL_PROMPT + SQL_SUMMARY_PROMPT"),
    ("钻石会员有什么权益", "rag", "RAG_ANSWER_PROMPT"),
]

lines = []
for q, expect_route, uses in CASES:
    t = time.time()
    r = answer_question(q, use_cache=False)
    dt = time.time() - t
    route = r.get("route")
    ok = "OK  " if route == expect_route else "MISS"
    lines.append("=" * 72)
    lines.append(f"{ok} query={q}")
    lines.append(f"     route={route}（期望 {expect_route}）  用到: {uses}   {dt:.1f}s")
    if r.get("sql"):
        lines.append(f"     sql={r['sql'][:70]}")
    lines.append(f"     answer={(r.get('answer') or '')[:110]}")

with io.open(os.path.join(BASE_DIR, "_e2e_prompt.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("written: _e2e_prompt.txt")
