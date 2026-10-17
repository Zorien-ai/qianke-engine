#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : check_stream_cache.py
@Function: 验证两项性能优化的实际效果

    1. 流式输出：首字延迟（第一个 delta 到达时间）vs 总耗时
    2. 结果缓存：同一问题第二次提问应接近 0 耗时

前置：服务已在 127.0.0.1:8000 运行
用法：
    python src/rag_demo/tools/check_stream_cache.py
"""
import json
import os
import time
import urllib.request

from rag_demo.config import BASE_DIR
from rag_demo.tools.api_auth import login

BASE = "http://127.0.0.1:8000"
TESTS_DIR = os.path.join(BASE_DIR, "src", "rag_demo", "tests")

# M3 起接口需要登录态：懒登录一次，之后所有请求复用 Cookie
_opener = None


def _http():
    global _opener
    if _opener is None:
        _opener = login(BASE)
    return _opener


def sse_ask(question: str, mode: str = "bm25") -> dict:
    """走流式接口，记录首字延迟与总耗时"""
    payload = json.dumps({"question": question, "retriever": mode}).encode()
    req = urllib.request.Request(
        BASE + "/qa/stream",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    t0 = time.time()
    resp = _http().open(req, timeout=300)

    first_char = None
    answer = ""
    route = None
    cached = False

    for raw in resp:
        line = raw.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        try:
            data = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue

        if data.get("cached"):
            cached = True
        if "route" in data:
            route = data["route"]
        if "delta" in data:
            if first_char is None:
                first_char = time.time() - t0
            answer += data["delta"]

    return {
        "route": route,
        "first_char": first_char if first_char is not None else -1,
        "total": time.time() - t0,
        "answer_len": len(answer),
        "cached": cached,
    }


def main() -> None:
    with open(os.path.join(TESTS_DIR, "eval_questions.json"), encoding="utf-8") as f:
        items = {q["id"]: q for q in json.load(f)}

    # 清缓存，保证第一次是真实生成
    req = urllib.request.Request(BASE + "/admin/clear-cache", data=b"", method="POST")
    urllib.request.urlopen(req, timeout=30)
    print("已清空缓存\n")

    question = items["OPT-01"]["question"]
    print(f"问题：{question}\n")

    r1 = sse_ask(question)
    print("【第 1 次 · 冷生成】")
    print(f"  路由     : {r1['route']}")
    print(f"  首字延迟 : {r1['first_char']:.2f}s")
    print(f"  总耗时   : {r1['total']:.2f}s")
    print(f"  答案字数 : {r1['answer_len']}")
    print(f"  首字占比 : {r1['first_char'] / r1['total'] * 100:.0f}% 的时间在等首字"
          "（其余时间用户在读已出现的文字）")

    print()
    r2 = sse_ask(question)
    print("【第 2 次 · 缓存命中】")
    print(f"  总耗时   : {r2['total']:.3f}s")
    print(f"  缓存标记 : {r2['cached']}")
    print(f"  答案一致 : {r2['answer_len'] == r1['answer_len']}")
    print(f"  加速倍数 : {r1['total'] / max(r2['total'], 0.001):.0f}x")

    # 缓存统计
    stats = json.load(urllib.request.urlopen(BASE + "/cache/stats", timeout=30))
    print(f"\n【缓存统计】{stats}")


if __name__ == "__main__":
    main()
