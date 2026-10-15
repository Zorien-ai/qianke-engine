#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : preflight.py
@Function: 评测脚本开跑前的环境预检（LLM API / 检索链路）

为什么需要
----------
2026-10-14/15 连续踩了两次同一个坑：DeepSeek API 出故障期间启动评测，
结果——

    * 忠实度首跑：串行调用都连续 APITimeoutError，3 题全失败
    * RAGAS 首跑：批量评测里大批样本失败，而 raise_exceptions=False
      把它们**静默记成 NaN**，均值照样算得出来——看着像「指标算不出来」，
      实际是 API 挂了。跑完 20 分钟才发现，数据全废。

预检把这类成本挡在开跑前：探测几次 LLM 调用，不通就立刻退出，
不要带着坏状态跑完全程。

局限
----
预检只保证「开跑这一刻 API 是通的」。跑十几分钟的批量评测中途 API 再挂，
仍要靠**跑完后的 NaN 检查**兜底（见 eval_ragas.py 的检查），两者配合。
"""
import sys
import time

from rag_demo.generation import generator

# 判定「API 不可用」的连续失败次数：偶发一次超时不算挂（网络抖动常见），
# 连续失败才说明是真故障
REQUIRED_OK = 2
MAX_ATTEMPTS = 4
RETRY_SLEEP = 3


def _probe(timeout: int):
    """
    发一次最小请求探测 API。

    不经过 chat_completion 的 kwargs 通道——`max_retries` 是 **client 级**
    参数，openai 3.26 的 create() 直接传会 TypeError（实测踩过）。
    用 client.with_options() 做 per-call 覆盖，SDK 内部重试关掉，
    重试策略由本模块自己控制。
    """
    client = generator.client.with_options(max_retries=0, timeout=timeout)
    return client.chat.completions.create(
        model=generator.MODEL,
        messages=[{"role": "user", "content": "只回答两个字：正常"}],
        temperature=0.0,
        extra_body={"thinking": {"type": "disabled"}} if not generator.ENABLE_THINKING else None,
    )


def check_api(verbose: bool = True, timeout: int = 20) -> bool:
    """
    探测 LLM API 是否可用。可用返回 True，不可用返回 False。

    不抛异常——预检失败是「环境就绪度」问题，让调用方决定怎么退出。

    timeout 必须短（默认 20s）：API 挂起时 openai 客户端默认等 600s，
    4 次尝试会拖 40 分钟，预检反而成了新的等待源。短超时下
    最坏耗时 ≈ MAX_ATTEMPTS × timeout + 重试间隔。
    """
    ok = 0
    last_err = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = _probe(timeout)
            if resp.choices and resp.choices[0].message.content:
                ok += 1
                if verbose:
                    print(f"[预检] LLM API 第 {attempt} 次探测正常")
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:160]}"
            if verbose:
                print(f"[预检] LLM API 第 {attempt} 次探测失败：{last_err}")
        if ok >= REQUIRED_OK:
            return True
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_SLEEP)
    if verbose:
        print(f"[预检] LLM API 不可用（{MAX_ATTEMPTS} 次尝试仅 {ok} 次成功）")
        print("        最近错误：" + (last_err or "未知"))
        print("        此时启动评测只会得到残缺结果，先确认 API 状态再跑。")
    return False


def main() -> None:
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ok = check_api()
    print(f"\n结论: {'可用，可以跑评测' if ok else '不可用，不要启动评测'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
