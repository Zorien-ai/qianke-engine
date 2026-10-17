#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : check_api_options.py
@Function: 验证 Web 端检索选项——/search 召回对比 + /qa 按策略切换

前置：服务已在 127.0.0.1:8000 运行（uvicorn rag_demo.api.main:app --port 8000）
输出写入 api_option_check.txt，避免控制台 GBK 乱码。

用法：
    python src/rag_demo/tools/check_api_options.py
"""
import io
import json
import os
import urllib.request

from rag_demo.config import BASE_DIR
from rag_demo.tools.api_auth import login

BASE_URL = "http://127.0.0.1:8000"
TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")

# M3 起接口需要登录态（/search 还要求 L4）：懒登录一次，复用 Cookie
_opener = None


def _http():
    global _opener
    if _opener is None:
        _opener = login(BASE_URL)
    return _opener


def post(path: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return json.load(_http().open(req, timeout=timeout))


def main() -> None:
    with open(os.path.join(TESTS_DIR, "eval_questions.json"), encoding="utf-8") as f:
        items = {q["id"]: q for q in json.load(f)}

    lines: list[str] = []

    # DA-01 是 A/B 实验里两者分歧最大的一题；MGT-01 是稀疏向量大幅领先的一题
    for qid in ("DA-01", "MGT-01"):
        question = items[qid]["question"]
        lines.append("=" * 72)
        lines.append(f"[{qid}] {question}")
        lines.append("=" * 72)

        r = post("/search", {"question": question, "top_k": 10})
        lines.append("--- /search 召回对比 ---")
        lines.append("BM25   top3: " + str([h["source"] for h in r["bm25"][:3]]))
        lines.append("Sparse top3: " + str([h["source"] for h in r["sparse"][:3]]))
        lines.append(
            f"共同召回 {len(r['both_hit'])} 个 | "
            f"仅 BM25: {r['only_bm25']} | 仅 Sparse: {r['only_sparse']}"
        )
        if r.get("sparse_note"):
            lines.append("注意: " + r["sparse_note"])

        lines.append("")
        lines.append("--- /qa 按策略切换（同一问题） ---")
        for mode in ("bm25", "sparse", "both"):
            try:
                rr = post("/qa", {"question": question, "retriever": mode})
                lines.append(
                    f"  [{mode:6}] route={rr.get('route'):5} "
                    f"来源={[s['source'] for s in rr.get('sources', [])]}"
                )
            except Exception as e:
                lines.append(f"  [{mode:6}] 失败: {e}")
        lines.append("")

    out = os.path.join(BASE_DIR, "api_option_check.txt")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written: {out}")


if __name__ == "__main__":
    main()
