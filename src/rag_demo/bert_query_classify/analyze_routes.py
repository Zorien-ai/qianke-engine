#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
入口路由的真实流量分布分析：用线上 query 分布决定「还要不要再补数据」

为什么要有这个脚本
------------------
补数据的依据不该是「我构造了个例，模型答错了」（那是**个例驱动**），
而该是「真实流量里有多大比例落在模型不稳的区间」（**分布驱动**）。
两者的区别很实际：个例可以被一条样本修好，分布问题得改数据构成。

两种数据来源
------------
1. **结构化回流**（推荐，线上跑起来就有）
   `logs/intent_routes.jsonl`，由 tools/intent_telemetry.py 写入：
   每行带 query / route / p_chitchat / threshold / latency_ms / source。
   只有 source="api" 的记录才算真实流量。

2. **旧文本日志回流**（`--backfill`）
   改造前的日志只有一行文本（"意图路由 -> 多路聚合: xxx"），没有概率。
   本脚本能把这类日志解析成真实 query 清单，再用**当前模型**离线补算 p_chitchat。
   这样即使线上还没跑起来，也能先把「真实分布」这一栏填上——
   但要清楚它测的是"当时被问过什么"，不是"当时模型怎么判"。

真实流量的两个固有难点（脚本里的对应处理）
------------------------------------------
a. **没有标签**。用户不会标注自己是闲聊还是业务。所以：
   - 漏判有**免费标签**：下游 LLM 复核改道（recheck 事件）就是"入口说业务、
     LLM 说闲聊"，覆盖率 100% 的 RAG 分支，零额外成本；
   - 误伤没有免费标签（被判 chitchat 的问题不会再进 LLM），
     只能**分层抽样 + LLM 标注**（`--label`），要花钱，所以按档抽样而不是全量。
   - ⚠ LLM 标注是**代理标注**，与 recheck 同源（同模型家族）→ 有同向偏差，
     它能发现"明显错判"，不能当作人工金标准。
b. **重复率高**。真实流量里同一句话被问 18 次很常见，按请求数算分布会被
   高频问题主导。所以本脚本同时给「按请求」和「按去重 query」两种口径。

决策门槛（写死在脚本里，避免对着数字拍脑袋）
--------------------------------------------
    n_api < 200 或 distinct < 50   -> 样本不足，**不产出补充决策**（只出分布画像）
    误伤 > 0                       -> 优先补：按长度/字符形态归类误伤样本
    漏判率 > 5%                    -> 先考虑调门槛（漏判有下游兜底，代价低）
    模糊带(p∈[0.5,0.9))占比 > 5%   -> 该区间样本不足，需补"模糊带"样本

输出：outputs/route_distribution.json（+ 控制台报告）
独立运行：
    uv run python src/rag_demo/bert_query_classify/analyze_routes.py
    uv run python src/rag_demo/bert_query_classify/analyze_routes.py --backfill "logs/rag_demo.log*"
    uv run python src/rag_demo/bert_query_classify/analyze_routes.py --label --per-stratum 10
"""
import argparse
import glob
import json
import os
import re
import statistics
import time
from collections import Counter
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(BASE)))
OUT_DIR = os.path.join(BASE, "outputs")
REPORT_JSON = os.path.join(OUT_DIR, "route_distribution.json")
LABEL_CACHE = os.path.join(OUT_DIR, "route_labels.jsonl")
TELEMETRY_DEFAULT = os.path.join(REPO, "logs", "intent_routes.jsonl")

# 模糊带 / 分档
BUCKETS = [(0.0, 0.1), (0.1, 0.3), (0.3, 0.5), (0.5, 0.7),
           (0.7, 0.9), (0.9, 0.99), (0.99, 1.01)]
AMBIGUOUS_LO, AMBIGUOUS_HI = 0.5, 0.9

# 决策门槛（改这里就是改决策规则，别在报告里临时拍）
MIN_REQUESTS = 200
MIN_DISTINCT = 50
MISS_RATE_ALERT = 0.05
AMBIGUOUS_SHARE_ALERT = 0.05

# 旧日志里的路由行（改造前格式）："... | 意图路由 -> 多路聚合: 查询"
LOG_ROUTE_RE = re.compile(r"意图路由\s*->\s*(chitchat|多路聚合)\s*[:：]\s*(.+?)\s*$")
LOG_RECHECK_RE = re.compile(r"路由复核改道\s*->\s*(\w+).*?[:：]\s*(.+?)\s*$")


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_telemetry(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_backfill(patterns: list[str]) -> list[dict]:
    """
    从改造前的文本日志里捞出真实 query

    只认路由行（每条真实请求必有一行）。p_chitchat 留空，稍后由当前模型离线补算——
    注意这不是"当时模型的判定"，改造前那层是关键词规则，压根没有概率。
    """
    recs: list[dict] = []
    files: list[str] = []
    for p in patterns:
        files.extend(glob.glob(p) if any(ch in p for ch in "*?[") else [p])
    for path in sorted(set(files)):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = LOG_ROUTE_RE.search(line)
                if m:
                    kind, query = m.group(1), m.group(2)
                    recs.append({
                        "event": "route",
                        "source": "backfill-log",
                        "ts": line[:19].replace(" ", "T"),
                        "query": query,
                        "route": "chitchat" if kind == "chitchat" else "rag",
                        "mode": "rule(改造前)",
                        "p_chitchat": None,
                        "threshold": None,
                        "latency_ms": None,
                        "backfilled": True,
                        "log_file": os.path.basename(path),
                    })
                    continue
                m = LOG_RECHECK_RE.search(line)
                if m:
                    recs.append({
                        "event": "recheck",
                        "source": "backfill-log",
                        "ts": line[:19].replace(" ", "T"),
                        "query": m.group(2),
                        "entry_route": "rag",
                        "new_route": m.group(1),
                        "backfilled": True,
                        "log_file": os.path.basename(path),
                    })
    return recs


def fill_missing_probs(recs: list[dict]) -> int:
    """
    给没有 p_chitchat 的记录用**当前模型**离线补算（旧日志回流需要）

    补算值标记 p_chitchat_source="offline_model"，与线上实时判定区分开：
    前者回答"这些 query 在今天的模型眼里长什么样"，不能当历史判定用。
    """
    todo = [r for r in recs if r.get("event") == "route" and r.get("p_chitchat") is None]
    if not todo:
        return 0
    from rag_demo.tools import bert_intent

    if not bert_intent.preload():
        print("[warn] 意图模型不可用，无法为回流日志补算 p_chitchat（跳过）")
        return 0
    probs = bert_intent.predict([r["query"] for r in todo], batch_size=32)
    if probs is None:
        return 0
    for r, p in zip(todo, probs):
        r["p_chitchat"] = round(p["p_chitchat"], 6)
        r["p_chitchat_source"] = "offline_model"
    return len(todo)


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def bucket_of(p: float) -> str:
    for lo, hi in BUCKETS:
        if lo <= p < hi:
            return f"{lo:.2f}-{min(hi, 1.0):.2f}"
    return "?"


def pct(k: int, n: int) -> str:
    return f"{k}/{n} = {k / n * 100:.1f}%" if n else "0/0"


def analyze(routes: list[dict], rechecks: list[dict]) -> dict:
    n = len(routes)
    queries = [r["query"] for r in routes]
    uniq = sorted(set(queries))
    by_route = Counter(r["route"] for r in routes)
    # 去重口径：同一 query 的路由取第一次出现（同模型同门槛下判定一致）
    first = {}
    for r in routes:
        first.setdefault(r["query"], r)
    by_route_uniq = Counter(r["route"] for r in first.values())

    with_p = [r for r in routes if r.get("p_chitchat") is not None]
    p_values = [r["p_chitchat"] for r in with_p]

    buckets = {}
    for r in with_p:
        buckets.setdefault(bucket_of(r["p_chitchat"]), []).append(r)
    bucket_rows = []
    for lo, hi in BUCKETS:
        key = f"{lo:.2f}-{min(hi, 1.0):.2f}"
        rows = buckets.get(key, [])
        blocked = sum(1 for r in rows if r["route"] == "chitchat")
        uniq_q = {r["query"] for r in rows}
        uniq_blocked = sum(1 for r in first.values()
                           if first[r["query"]] is r and r["query"] in uniq_q
                           and r["route"] == "chitchat")
        bucket_rows.append({
            "bucket": key, "n": len(rows),
            "share_of_requests": round(len(rows) / n, 4) if n else 0.0,
            "blocked_as_chitchat": blocked,
            "n_distinct": len(uniq_q),
            "blocked_distinct": uniq_blocked,
        })

    ambiguous = [r for r in with_p if AMBIGUOUS_LO <= r["p_chitchat"] < AMBIGUOUS_HI]
    lat = [r["latency_ms"] for r in routes if r.get("latency_ms") is not None]
    lat_stats = None
    if lat:
        ordered = sorted(lat)
        pick = lambda p: ordered[min(len(ordered) - 1, int(len(ordered) * p))]  # noqa: E731
        lat_stats = {"n": len(lat), "mean_ms": round(statistics.fmean(lat), 3),
                     "p50_ms": round(pick(0.5), 3), "p95_ms": round(pick(0.95), 3),
                     "max_ms": round(max(lat), 3)}

    # 漏判：recheck 把 RAG 改道成 chitchat（免费标签）
    rag_n = by_route.get("rag", 0)
    miss_n = len(rechecks)
    # 模糊带样本的特征画像（决定「补什么形态」时看它）
    amb_by_len = Counter()
    for r in ambiguous:
        L = len(r["query"])
        amb_by_len["1-3" if L <= 3 else "4-6" if L <= 6 else
                   "7-12" if L <= 12 else "13-20" if L <= 20 else "21+"] += 1

    return {
        "n_requests": n,
        "n_distinct": len(uniq),
        "time_range": [routes[0]["ts"] if routes else None,
                       routes[-1]["ts"] if routes else None],
        "sources": dict(Counter(r.get("source") for r in routes)),
        "modes": dict(Counter(r.get("mode") for r in routes)),
        "route_by_request": dict(by_route),
        "route_by_distinct": dict(by_route_uniq),
        "blocked_share_requests": round(by_route.get("chitchat", 0) / n, 4) if n else 0.0,
        "blocked_share_distinct": (
            round(by_route_uniq.get("chitchat", 0) / len(uniq), 4) if uniq else 0.0),
        "p_chitchat_coverage": round(len(with_p) / n, 4) if n else 0.0,
        "p_chitchat_stats": ({
            "mean": round(statistics.fmean(p_values), 4),
            "min": min(p_values), "max": max(p_values),
            "median": round(statistics.median(p_values), 4),
        } if p_values else None),
        "buckets": bucket_rows,
        "ambiguous_band": {
            "range": [AMBIGUOUS_LO, AMBIGUOUS_HI],
            "n": len(ambiguous),
            "share": round(len(ambiguous) / n, 4) if n else 0.0,
            "by_length": dict(amb_by_len),
            "samples": [{"query": r["query"], "p_chitchat": r["p_chitchat"]}
                        for r in sorted(ambiguous, key=lambda x: -x["p_chitchat"])[:15]],
        },
        "router_latency": lat_stats,
        "recheck_miss": {
            "n": miss_n,
            "rate_on_rag": round(miss_n / rag_n, 4) if rag_n else None,
            "samples": [{"query": r["query"], "new_route": r.get("new_route")}
                        for r in rechecks[:15]],
        },
        "top_queries": [{"query": q, "count": c} for q, c in
                        Counter(queries).most_common(10)],
    }


def decide(rep: dict) -> dict:
    """按写死的门槛给出「要不要补、补什么」，样本不足就明说样本不足"""
    n, uniq = rep["n_requests"], rep["n_distinct"]
    actions = []
    sufficient = n >= MIN_REQUESTS and uniq >= MIN_DISTINCT
    if not sufficient:
        actions.append({
            "priority": "blocked",
            "action": "样本不足，不产出补充决策",
            "why": f"真实请求 {n} 条 / 去重 {uniq} 条，门槛是 ≥{MIN_REQUESTS} / ≥{MIN_DISTINCT}。"
                   f"继续用构造个例驱动补数据会引入采样偏差——等真实流量积累。",
        })
    amb = rep["ambiguous_band"]["share"]
    if sufficient and amb > AMBIGUOUS_SHARE_ALERT:
        actions.append({
            "priority": "P1",
            "action": f"补「模糊带」样本（p∈[{AMBIGUOUS_LO},{AMBIGUOUS_HI}) 占 {amb:.1%}）",
            "why": "这些 query 模型自己也不确定，是最容易在线上翻转的一批；"
                   "按 by_length 画像决定补哪个长度档。",
        })
    miss_rate = rep["recheck_miss"]["rate_on_rag"]
    if sufficient and miss_rate is not None and miss_rate > MISS_RATE_ALERT:
        actions.append({
            "priority": "P1",
            "action": f"漏判率超阈值（{miss_rate:.1%} > {MISS_RATE_ALERT:.0%}）-> 先调门槛",
            "why": "漏判有下游 LLM 复核兜底，代价是多走一次检索；"
                   "调低门槛比补数据见效快。",
        })
    if sufficient and not actions:
        actions.append({
            "priority": "P3",
            "action": "暂不补数据",
            "why": "样本量达标且未触发任何阈值：模糊带占比、漏判率都在可接受范围。",
        })
    return {"sufficient": sufficient, "thresholds": {
        "min_requests": MIN_REQUESTS, "min_distinct": MIN_DISTINCT,
        "miss_rate_alert": MISS_RATE_ALERT,
        "ambiguous_share_alert": AMBIGUOUS_SHARE_ALERT,
    }, "actions": actions}


# ---------------------------------------------------------------------------
# 分层抽样 + LLM 标注（可选，花钱）
# ---------------------------------------------------------------------------
def load_label_cache() -> dict:
    cache = {}
    for r in load_telemetry(LABEL_CACHE):
        cache[r["query"]] = r
    return cache


def sample_for_label(routes: list[dict], per_stratum: int) -> list[dict]:
    """按 p_chitchat 档位分层抽样：每档最多 per_stratum 条去重 query"""
    first = {}
    for r in routes:
        if r.get("p_chitchat") is not None:
            first.setdefault(r["query"], r)
    strata: dict[str, list[dict]] = {}
    for r in first.values():
        strata.setdefault(bucket_of(r["p_chitchat"]), []).append(r)
    picked = []
    for key in sorted(strata):
        rows = sorted(strata[key], key=lambda x: -x["p_chitchat"])[:per_stratum]
        picked.extend(rows)
    return picked


LABEL_PROMPT = """你是电商运营数据平台的意图判别器。用户会向平台提问，你要判断这个问题属于哪一类。

- CHITCHAT：闲聊、寒暄、致谢、元问题（问你是谁/能做什么）、通用常识问题（闰年是怎么回事、
  怎么做菜）、与平台数据无关的话题。
- BUSINESS：任何需要用平台的用户画像 / 标签口径 / 运营知识库来回答的问题，
  包括极短的口语化缩写（如「客单价」「看下GMV」「U2765」「日活」）。

只输出一个词：CHITCHAT 或 BUSINESS，不要任何解释。

用户问题：{question}"""


def label_with_llm(rows: list[dict], cache: dict) -> tuple[dict, dict]:
    """
    LLM 分层标注（代理标签）

    返回 (labels, stats)。已有缓存的不重复调用——标注要花钱，断点续跑是刚需。
    """
    from rag_demo.generation.generator import chat_completion

    todo = [r for r in rows if r["query"] not in cache]
    stats = {"cached": len(rows) - len(todo), "called": 0, "failed": 0}
    if not todo:
        return cache, stats

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(LABEL_CACHE, "a", encoding="utf-8") as f:
        for r in todo:
            q = r["query"]
            try:
                resp = chat_completion(
                    messages=[{"role": "user",
                               "content": LABEL_PROMPT.format(question=q)}],
                    temperature=0,
                )
                text = (resp.choices[0].message.content or "").strip().upper()
                label = "CHITCHAT" if "CHITCHAT" in text else (
                    "BUSINESS" if "BUSINESS" in text else "UNKNOWN")
            except Exception as e:  # noqa: BLE001
                print(f"[warn] 标注失败（跳过）: {q!r}: {type(e).__name__}: {e}")
                stats["failed"] += 1
                continue
            rec = {"query": q, "label": label, "p_chitchat": r["p_chitchat"],
                   "route": r["route"], "labeled_at": datetime.now().isoformat(timespec="seconds"),
                   "labeler": "llm-proxy"}
            cache[q] = rec
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            stats["called"] += 1
            time.sleep(0.2)
    return cache, stats


def label_report(rows: list[dict], cache: dict) -> dict:
    """用代理标签算路由准确率 / 误伤 / 漏判"""
    labeled = [cache[r["query"]] for r in rows if r["query"] in cache]
    if not labeled:
        return {}
    tp = fp = fn = tn = 0
    mis = []
    for r in labeled:
        true_c = r["label"] == "CHITCHAT"
        pred_c = r["route"] == "chitchat"
        if true_c and pred_c:
            tp += 1
        elif true_c and not pred_c:
            fn += 1
            mis.append({"kind": "漏判", **r})
        elif not true_c and pred_c:
            fp += 1
            mis.append({"kind": "误伤(拒答)", **r})
        else:
            tn += 1
    n = len(labeled)
    return {
        "n_labeled": n, "tp": tp, "fp_misblock": fp, "fn_missed": fn, "tn": tn,
        "accuracy": round((tp + tn) / n, 4),
        "labeler": "llm-proxy（同源于 recheck 的模型家族，有同向偏差）",
        "samples_needing_data": sorted(
            mis, key=lambda x: (x["kind"], -x["p_chitchat"]))[:20],
    }


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def print_report(rep: dict, dec: dict, lab: dict, label_stats: dict) -> None:
    line = "=" * 88
    print(line)
    print("入口路由 · 真实流量分布分析（分布驱动，而不是个例驱动）")
    print(line)
    print(f"请求 {rep['n_requests']} 条 / 去重 {rep['n_distinct']} 条    "
          f"时间范围 {rep['time_range'][0]} ~ {rep['time_range'][1]}")
    print(f"来源 {rep['sources']}    判定器 {rep['modes']}")

    print("\n【1】路由分布")
    print(f"  按请求：{rep['route_by_request']}  被拦成闲聊 "
          f"{rep['blocked_share_requests']:.1%}")
    print(f"  按去重：{rep['route_by_distinct']}  被拦成闲聊 "
          f"{rep['blocked_share_distinct']:.1%}")
    print("  两种口径都要看：真实流量重复率很高，按请求算会被高频问题主导")

    print("\n【2】P(闲聊) 分档（分布驱动的核心：看真实 query 落在哪）")
    print(f"  概率覆盖率 {rep['p_chitchat_coverage']:.1%}"
          f"（旧日志回流 + 离线补算的记录也算在内）")
    print(f"  {'档位':<12}{'请求数':>8}{'占比':>9}{'判为闲聊':>10}{'去重数':>8}")
    for b in rep["buckets"]:
        print(f"  {b['bucket']:<12}{b['n']:>8}{b['share_of_requests']:>8.1%}"
              f"{b['blocked_as_chitchat']:>10}{b['n_distinct']:>8}")
    if rep["p_chitchat_stats"]:
        s = rep["p_chitchat_stats"]
        print(f"  均值 {s['mean']}  中位 {s['median']}  范围 [{s['min']}, {s['max']}]")

    amb = rep["ambiguous_band"]
    print(f"\n【3】模糊带 p∈[{amb['range'][0]},{amb['range'][1]}) —— 最该关注的一批")
    print(f"  {pct(amb['n'], rep['n_requests'])}    长度画像 {amb['by_length']}")
    for s in amb["samples"][:8]:
        print(f"    p={s['p_chitchat']:<8} {s['query']}")

    if rep["router_latency"]:
        L = rep["router_latency"]
        print(f"\n【4】路由决策耗时（本地判定段）n={L['n']}  "
              f"p50 {L['p50_ms']}ms  p95 {L['p95_ms']}ms  max {L['max_ms']}ms")

    rk = rep["recheck_miss"]
    print(f"\n【5】漏判（免费标签：下游 LLM 复核改道）{rk['n']} 条，"
          f"占 RAG 分支 {rk['rate_on_rag'] if rk['rate_on_rag'] is not None else '—'}")
    for s in rk["samples"][:8]:
        print(f"    {s['query']}")

    if lab:
        print(f"\n【6】代理标注（LLM 分层抽样，{label_stats}）")
        print(f"  标注 {lab['n_labeled']} 条：准确率 {lab['accuracy']:.4f}  "
              f"误伤 {lab['fp_misblock']} / 漏判 {lab['fn_missed']}")
        for s in lab["samples_needing_data"][:10]:
            print(f"    [{s['kind']:<9}] p={s['p_chitchat']:<8} route={s['route']:<9} "
                  f"{s['query']}")

    print(f"\n【7】决策（门槛写死在脚本里，样本不足就明说）")
    print(f"  样本充足：{'是' if dec['sufficient'] else '否'}   "
          f"门槛 {dec['thresholds']}")
    for a in dec["actions"]:
        print(f"  [{a['priority']}] {a['action']}")
        print(f"      {a['why']}")
    print(line)


def main() -> None:
    ap = argparse.ArgumentParser(description="入口路由的真实流量分布分析")
    ap.add_argument("--input", default=TELEMETRY_DEFAULT,
                    help="结构化回流 JSONL（默认 logs/intent_routes.jsonl）")
    ap.add_argument("--backfill", nargs="*", default=[],
                    help="旧文本日志（支持通配符），解析出真实 query 并用当前模型补算 P(闲聊)")
    ap.add_argument("--source", default="all",
                    help="只统计某一来源：all / api（真实线上流量）/ backfill-log（旧日志回流）"
                         "/ replay（入口函数级回放）等，见报告里的 sources 字段")
    ap.add_argument("--label", action="store_true", help="对分层抽样调用 LLM 打代理标签（花钱）")
    ap.add_argument("--per-stratum", type=int, default=10, help="每个概率档抽样条数（去重后）")
    ap.add_argument("--out", default=REPORT_JSON)
    args = ap.parse_args()

    recs = load_telemetry(args.input)
    if recs:
        print(f"结构化回流：{args.input}  {len(recs)} 条")
    else:
        print(f"结构化回流：{args.input} 不存在或为空"
              f"（正常——埋点是本次新加的，线上跑起来后才会积累）")

    if args.backfill:
        bf = load_backfill(args.backfill)
        print(f"旧日志回流：{args.backfill}  {len(bf)} 条")
        recs.extend(bf)

    if args.source != "all":
        recs = [r for r in recs if r.get("source") == args.source]
        print(f"按来源过滤 source={args.source} -> {len(recs)} 条")

    routes = [r for r in recs if r.get("event") == "route"]
    rechecks = [r for r in recs if r.get("event") == "recheck"]
    if not routes:
        print("\n没有可分析的请求记录。两种补数据方式：")
        print("  1) 让服务跑起来（uvicorn）并接受真实请求，埋点会自动记录到 "
              "logs/intent_routes.jsonl")
        print("  2) 用 --backfill 解析历史日志："
              "analyze_routes.py --backfill \"logs/rag_demo.log*\"")
        raise SystemExit(0)

    filled = fill_missing_probs(routes)
    if filled:
        print(f"离线补算 P(闲聊)：{filled} 条（标注 p_chitchat_source=offline_model）")
    routes.sort(key=lambda r: r.get("ts") or "")

    rep = analyze(routes, rechecks)
    dec = decide(rep)

    lab, label_stats = {}, {}
    if args.label:
        cache = load_label_cache()
        sample = sample_for_label(routes, args.per_stratum)
        print(f"\n分层抽样 {len(sample)} 条去重 query 送 LLM 标注"
              f"（每档上限 {args.per_stratum}，已有缓存 {len(cache)} 条）")
        cache, label_stats = label_with_llm(sample, cache)
        lab = label_report(sample, cache)

    rep["decision"] = dec
    rep["proxy_labeling"] = lab or None
    rep["label_stats"] = label_stats or None
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)

    print_report(rep, dec, lab, label_stats)
    print(f"结果已写入：{args.out}")


if __name__ == "__main__":
    main()
