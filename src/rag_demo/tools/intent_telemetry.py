#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : intent_telemetry.py
@Function: 入口意图路由的结构化回流埋点（真实流量 -> 可分析的分布数据）

为什么需要它
------------
「还要不要再补数据」这个问题，只有**线上真实 query 分布**能回答。而真实流量是
无标签的：用户不会告诉你他问的是闲聊还是业务。所以必须先把每次判定记下来，
才能在下游事后补标签、看分布，再决定补什么形态的数据。

在此之前，这条链路只有一个 INFO 日志（"意图路由 -> 多路聚合: xxx"），
只能靠字符串解析，且没有概率、没有耗时，做不了分布分析。

记什么（每行一个 JSON）
-----------------------
    ts            时间（ISO）
    source        api / script / runtime —— 只有 api 才是真实流量
    query         原始问题
    route         最终判定（chitchat / rag）
    mode          bert / hybrid / rule（config.INTENT_ROUTER）
    p_chitchat    P(闲聊)；规则判定时为 null（规则没有概率）
    threshold     当时生效的门槛（配置会变，必须记下来才能复盘）
    latency_ms    本次路由决策耗时（含模型前向）
    event         route（入口判定）/ recheck（下游 LLM 复核改道）

为什么还要记 recheck
--------------------
下游 query_processor 的 LLM 复核会把「判成 RAG」的问题改道成 chitchat——
那是**免费的漏判标签**：模型说业务、LLM 说闲聊，这条就是漏判（既有的 LLM 调用，
不额外花钱，覆盖率 100% 的 RAG 分支）。反过来「判成 chitchat」的没有下游复核，
所以误伤只能靠抽样标注估——两类错误的可得标签成本本来就是不对称的。

⚠ 三条纪律
1. **绝不能影响请求**：所有写入 best-effort，异常只记一次 warning 后自我关闭，
   不抛给调用方。埋点挂了不能连累问答。
2. **不能拖慢请求**：单行 append + 简单锁，不做聚合、不做远程上报。
3. 落盘在 logs/（已在 .gitignore），这是**运行期数据**，不是仓库数据。
"""
import json
import logging
import os
import threading
import time

from rag_demo import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_disabled = False          # 出错后自我关闭，避免每个请求都刷日志
_warned = False
_emitted = 0
_sampled_out = 0

# 调用来源。默认 runtime；api/main.py 启动时置为 "api"，
# 这样离线脚本（bench / smoke）产生的记录不会污染「真实流量」分布。
_source = "runtime"


def set_source(name: str) -> None:
    global _source
    _source = str(name or "runtime")


def get_source() -> str:
    return _source


def _should_sample() -> bool:
    global _sampled_out
    rate = float(getattr(config, "INTENT_TELEMETRY_SAMPLE_RATE", 1.0))
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        _sampled_out += 1
        return False
    # 用秒级时间戳做确定性抖动：不引入 random，避免影响主流程的随机数状态
    import hashlib

    h = hashlib.md5(f"{time.time_ns()}".encode()).digest()
    if (h[0] / 255.0) < rate:
        return True
    _sampled_out += 1
    return False


def record_route(query: str, route: str, mode: str, p_chitchat: float | None,
                 threshold: float | None, latency_ms: float) -> None:
    """记录一次入口路由判定"""
    _write({
        "event": "route",
        "source": _source,
        "query": query,
        "route": route,
        "mode": mode,
        "p_chitchat": None if p_chitchat is None else round(float(p_chitchat), 6),
        "threshold": threshold,
        "latency_ms": round(float(latency_ms), 3),
    })


def record_recheck(query: str, new_route: str, entry_route: str = "rag") -> None:
    """
    记录下游 LLM 复核改道（entry_route=RAG 被改成 chitchat = 一次漏判）

    这条比入口记录更值钱：它带**免费标签**。分析脚本据此统计漏判率，
    不用为「该不该走检索」再花一次标注成本。
    """
    _write({
        "event": "recheck",
        "source": _source,
        "query": query,
        "entry_route": entry_route,
        "new_route": new_route,
    })


def _write(rec: dict) -> None:
    global _disabled, _warned, _emitted
    if _disabled or not getattr(config, "INTENT_TELEMETRY", False):
        return
    try:
        if not _should_sample():
            return
        rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        path = config.INTENT_TELEMETRY_PATH
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with _lock:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
            _emitted += 1
    except Exception as e:  # noqa: BLE001
        # 埋点坏了不能连累问答：关掉自己并留一条线索
        _disabled = True
        if not _warned:
            _warned = True
            logger.warning("意图路由埋点写入失败，本次进程已关闭埋点: %s: %s",
                           type(e).__name__, e)


def stats() -> dict:
    """埋点自身状态（供健康检查 / 排查）"""
    return {
        "enabled": bool(getattr(config, "INTENT_TELEMETRY", False)),
        "disabled_after_error": _disabled,
        "source": _source,
        "emitted": _emitted,
        "sampled_out": _sampled_out,
        "path": config.INTENT_TELEMETRY_PATH,
        "sample_rate": getattr(config, "INTENT_TELEMETRY_SAMPLE_RATE", 1.0),
    }
