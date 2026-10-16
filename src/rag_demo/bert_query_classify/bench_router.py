#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
意图路由方案对比：关键词规则 vs BERT 分类器（准确率 + 延迟）

为什么要在「入口路由」这一层做对比
----------------------------------
入口路由是**每题都要过**的一段代码，所以它的两个代价都必须量出来：
    准确率 —— 判错的方向不对称：把业务判成闲聊 = 拒答真问题（用户直接受损），
              把闲聊判成业务 = 多走一次检索+生成（约 25s 白花，但答得出来）
    延迟   —— 本地推理的固定开销会叠加在**每一个**业务请求上
只报「BERT 更准」不报「贵多少」是半个结论，反之亦然。

三套方案（决策语义一致：命中即 chitchat，不检索、不生成）
----------------------------------------------------------
    rule    关键词规则（改造前的线上逻辑，router.rule_is_chitchat）
    bert    微调 BERT 二分类（p_chitchat >= 阈值）
    hybrid  规则先短路，未命中再交 BERT（省掉命中那部分的 BERT 前向）

数据集（均带真实标签，共 327 条；闲聊 = 正类 = 「该被拦截」）
-------------------------------------------------------------
    test.jsonl                 272 条  与训练同分布（闲聊 135 / 业务 137）
    short_business_test.jsonl   30 条  分布外·极短业务（2~6 字）
    long_business_test.jsonl    25 条  分布外·长句业务（19~22 字）
探针集全是业务，专门检验「误伤」：规则判错这里就是直接拒答真问题。

指标口径
--------
    TP 正确拦截（闲聊被拦下）    FN 漏判（闲聊放进检索链，浪费约 25s）
    FP **误伤**（业务被拦成闲聊，拒答真问题——代价最高）  TN 正确放行

代价换算是估算值，数据来源 bug/10.14/2026-10-14_性能逐模块计时与方案A实验.md：
    LLM 多路规划 3.8s + 本地检索精排 0.5s + LLM 答案生成 20.9s ≈ 25.2s/题

独立运行：
    uv run python src/rag_demo/bert_query_classify/bench_router.py
    uv run python src/rag_demo/bert_query_classify/bench_router.py --device cpu
"""
import argparse
import json
import os
import statistics
import time
from datetime import datetime

import torch

from rag_demo import config
from rag_demo.tools import router
from rag_demo.tools import bert_intent

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT_JSON = os.path.join(BASE, "outputs", "router_compare.json")

CHITCHAT = "CHITCHAT"
BUSINESS = "BUSINESS"

DATASETS = [
    ("test", "test.jsonl", "与训练同分布"),
    ("short_probe", "short_business_test.jsonl", "分布外·极短业务 2~6 字"),
    ("long_probe", "long_business_test.jsonl", "分布外·长句业务 19~22 字"),
]

# 门槛扫描：看「误伤」与「漏判」怎么随门槛此消彼长，据此定 config 里的默认值
THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99]

# 代价换算常数（§模块文档已注明出处）
COST_LLM_PLAN_SEC = 3.8
COST_RETRIEVAL_SEC = 0.5
COST_GENERATION_SEC = 20.9
COST_PER_MISS_SEC = COST_LLM_PLAN_SEC + COST_RETRIEVAL_SEC + COST_GENERATION_SEC

WARMUP = 10


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_items() -> list[dict]:
    items: list[dict] = []
    for group, filename, desc in DATASETS:
        rows = load_jsonl(os.path.join(DATA, filename))
        for r in rows:
            items.append({"query": r["query"], "label": r["label"],
                          "group": group, "group_desc": desc})
    return items


def metrics(labels: list[str], preds: list[bool]) -> dict:
    """
    以「判定为闲聊」为正类统计

    FP 单独命名 misblock（误伤/误拦）：它不是"又一个错误"，而是最贵的那种，
    报告里必须一眼看到，不能被 accuracy 平均掉。
    """
    tp = sum(1 for lab, p in zip(labels, preds) if lab == CHITCHAT and p)
    fn = sum(1 for lab, p in zip(labels, preds) if lab == CHITCHAT and not p)
    fp = sum(1 for lab, p in zip(labels, preds) if lab == BUSINESS and p)
    tn = sum(1 for lab, p in zip(labels, preds) if lab == BUSINESS and not p)
    n = len(labels)
    n_chitchat, n_business = tp + fn, fp + tn
    accuracy = (tp + tn) / n if n else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / n_chitchat if n_chitchat else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "n": n,
        "n_chitchat": n_chitchat,
        "n_business": n_business,
        "tp_caught": tp,
        "fn_missed": fn,
        "fp_misblock": fp,
        "tn_passed": tn,
        "accuracy": round(accuracy, 4),
        "precision_chitchat": round(precision, 4),
        "recall_chitchat": round(recall, 4),
        "f1_chitchat": round(f1, 4),
        "misblock_rate_on_business": round(fp / n_business, 4) if n_business else 0.0,
        "miss_rate_on_chitchat": round(fn / n_chitchat, 4) if n_chitchat else 0.0,
    }


def group_metrics(items: list[dict], preds: list[bool]) -> dict:
    out = {}
    for group, _, _ in DATASETS:
        idx = [i for i, it in enumerate(items) if it["group"] == group]
        out[group] = metrics([items[i]["label"] for i in idx], [preds[i] for i in idx])
    return out


def _sync() -> None:
    """CUDA 是异步执行：不同步会把「提交内核」的时间当成「算完」的时间"""
    if torch.cuda.is_available() and str(config.DEVICE).startswith("cuda"):
        torch.cuda.synchronize()


def time_single_calls(decide, queries: list[str], passes: int = 1) -> list[float]:
    """按真实请求形态逐条调用并计时（毫秒）"""
    lat: list[float] = []
    for _ in range(passes):
        for q in queries:
            _sync()
            t0 = time.perf_counter()
            decide(q)
            _sync()
            lat.append((time.perf_counter() - t0) * 1000)
    return lat


def latency_stats(lat: list[float]) -> dict:
    ordered = sorted(lat)
    def pick(p):  # 最近秩分位数，样本少时不插值，避免给出不存在的"精确值"
        return ordered[min(len(ordered) - 1, int(len(ordered) * p))]
    return {
        "calls": len(lat),
        "mean_ms": round(statistics.fmean(lat), 4),
        "p50_ms": round(pick(0.5), 4),
        "p95_ms": round(pick(0.95), 4),
        "max_ms": round(max(lat), 4),
        "total_ms": round(sum(lat), 2),
    }


def build_report(items: list[dict], probs: list[float], args) -> dict:
    queries = [it["query"] for it in items]
    labels = [it["label"] for it in items]
    threshold = config.INTENT_CHITCHAT_THRESHOLD

    # ---------- 判定（准确率用） ----------
    rule_preds = [router.rule_is_chitchat(q) for q in queries]
    bert_preds = [p >= threshold for p in probs]
    hybrid_preds = [r or b for r, b in zip(rule_preds, bert_preds)]

    # ---------- 延迟（单条逐次调用，生产形态） ----------
    def _rule(q):
        router.rule_is_chitchat(q)

    def _bert(q):
        bert_intent.chitchat_prob(q)

    def _hybrid(q):
        if not router.rule_is_chitchat(q):
            bert_intent.chitchat_prob(q)

    for q in queries[:WARMUP]:  # 预热：首次调用含 CUDA 上下文初始化
        _bert(q)

    lat_rule = time_single_calls(_rule, queries, passes=args.rule_passes)
    # BERT 多跑几遍：单遍 327 个样本的均值会被 GPU 时钟/调度抖动带偏
    # （实测两次运行相差约 2ms，相对 16ms 是 12%），p50 比 mean 稳。
    lat_bert = time_single_calls(_bert, queries, passes=args.bert_passes)
    lat_hybrid = time_single_calls(_hybrid, queries, passes=args.bert_passes)

    # 批量吞吐（离线 / 批处理场景的参考值，不是线上形态）
    _sync()
    t0 = time.perf_counter()
    bert_intent.predict(queries, batch_size=32)
    _sync()
    batch_ms = (time.perf_counter() - t0) * 1000

    variants = {
        "rule": {"desc": "关键词规则（改造前）", "metrics": metrics(labels, rule_preds),
                 "latency_single": latency_stats(lat_rule)},
        "bert": {"desc": f"BERT 二分类（阈值 {threshold}）",
                 "metrics": metrics(labels, bert_preds),
                 "latency_single": latency_stats(lat_bert)},
        "hybrid": {"desc": f"规则短路 + BERT 兜底（阈值 {threshold}）",
                   "metrics": metrics(labels, hybrid_preds),
                   "latency_single": latency_stats(lat_hybrid)},
    }
    for name, preds in {"rule": rule_preds, "bert": bert_preds,
                        "hybrid": hybrid_preds}.items():
        variants[name]["by_group"] = group_metrics(items, preds)

    # ---------- 门槛扫描 ----------
    sweep = []
    for th in THRESHOLDS:
        preds = [p >= th for p in probs]
        m = metrics(labels, preds)
        m["threshold"] = th
        m["by_group"] = group_metrics(items, preds)
        sweep.append(m)

    # ---------- 规则侧缺口：规则漏掉的闲聊，BERT 补回来多少 ----------
    rule_missed_idx = [i for i, (lab, p) in enumerate(zip(labels, rule_preds))
                       if lab == CHITCHAT and not p]
    rule_misblock_idx = [i for i, (lab, p) in enumerate(zip(labels, rule_preds))
                         if lab == BUSINESS and p]
    recovered = [i for i in rule_missed_idx if probs[i] >= threshold]

    rule_m = variants["rule"]["metrics"]
    bert_m = variants["bert"]["metrics"]

    # ---------- BERT 自身错误归因 + 风险边界 ----------
    # 「误伤」的 2 条是什么样的？「漏判」的 p 是多少？门槛再抬还有没有余地？
    # 这些必须落进结果文件：只看汇总数字无法判断门槛该往哪调。
    # 注意这里用的是 **BERT 的判定**，与上面 rule_* 是两套账，不能混。
    misblock = sorted(
        ({"query": queries[i], "group": items[i]["group"], "p_chitchat": round(probs[i], 4)}
         for i in range(len(items))
         if labels[i] == BUSINESS and bert_preds[i]),
        key=lambda d: -d["p_chitchat"],
    )
    missed = sorted(
        ({"query": queries[i], "group": items[i]["group"], "p_chitchat": round(probs[i], 4)}
         for i in range(len(items))
         if labels[i] == CHITCHAT and not bert_preds[i]),
        key=lambda d: -d["p_chitchat"],
    )
    # 业务侧「最像闲聊」的前几条：它们与门槛之间的距离就是误伤余量，
    # 余量为负说明已经有业务样本越过门槛（就是上面误伤那几条）。
    business_risk = sorted(
        ({"query": it["query"], "group": it["group"], "p_chitchat": round(p, 4)}
         for it, p in zip(items, probs) if it["label"] == BUSINESS),
        key=lambda d: -d["p_chitchat"],
    )[:8]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "device": config.DEVICE,
        "dtype": str(config.DTYPE),
        "threshold": threshold,
        "intent_router_config": config.INTENT_ROUTER,
        "model_load": bert_intent.load_info(),
        "dataset": {
            "total": len(items),
            "chitchat": sum(1 for l in labels if l == CHITCHAT),
            "business": sum(1 for l in labels if l == BUSINESS),
            "groups": {g: sum(1 for it in items if it["group"] == g) for g, _, _ in DATASETS},
        },
        "variants": variants,
        "threshold_sweep": sweep,
        "batch32": {
            "total_ms": round(batch_ms, 2),
            "per_item_ms": round(batch_ms / len(queries), 4),
        },
        "rule_gap_analysis": {
            "rule_missed_chitchat": len(rule_missed_idx),
            "bert_recovered_at_threshold": len(recovered),
            "bert_recovered_ratio": (
                round(len(recovered) / len(rule_missed_idx), 4) if rule_missed_idx else None
            ),
            "rule_misblocked_business": len(rule_misblock_idx),
            "rule_misblocked_samples": [queries[i] for i in rule_misblock_idx][:10],
        },
        "error_attribution": {
            "bert_misblock": misblock,
            "bert_missed": missed,
            "business_risk_top": business_risk,
            # 业务侧最高 p_chitchat 与门槛的距离：越小说明门槛越贴边
            "risk_margin": round(threshold - business_risk[0]["p_chitchat"], 4)
            if business_risk else None,
        },
        "cost_model": {
            "sec_per_miss": COST_PER_MISS_SEC,
            "rule_wasted_sec": round(rule_m["fn_missed"] * COST_PER_MISS_SEC, 1),
            "bert_wasted_sec": round(bert_m["fn_missed"] * COST_PER_MISS_SEC, 1),
            "saved_sec": round((rule_m["fn_missed"] - bert_m["fn_missed"]) * COST_PER_MISS_SEC, 1),
            "rule_misblock_count": rule_m["fp_misblock"],
            "bert_misblock_count": bert_m["fp_misblock"],
        },
    }


def print_report(rep: dict) -> None:
    line = "=" * 92
    print(line)
    print("意图路由方案对比：关键词规则 vs BERT 分类器（准确率 + 延迟）")
    print(line)
    ds = rep["dataset"]
    print(f"数据集 {ds['total']} 条（闲聊 {ds['chitchat']} / 业务 {ds['business']}）"
          f" device={rep['device']} dtype={rep['dtype']}")
    print(f"门槛 {rep['threshold']} | INTENT_ROUTER={rep['intent_router_config']} | "
          f"模型加载 {rep['model_load'].get('load_sec')}s")

    print("\n【总览】延迟以 p50 为主口径（均值受 GPU 抖动影响，p95 看长尾）")
    print(f"  {'方案':<8}{'准确率':>9}{'召回(闲聊)':>11}{'精确(闲聊)':>11}"
          f"{'误伤业务':>9}{'漏判闲聊':>9}{'p50 ms':>10}{'均值ms':>10}{'p95 ms':>9}")
    for name in ("rule", "bert", "hybrid"):
        v = rep["variants"][name]
        m, lat = v["metrics"], v["latency_single"]
        print(f"  {name:<8}{m['accuracy']:>9.4f}{m['recall_chitchat']:>11.4f}"
              f"{m['precision_chitchat']:>11.4f}{m['fp_misblock']:>9}{m['fn_missed']:>9}"
              f"{lat['p50_ms']:>10.4f}{lat['mean_ms']:>10.4f}{lat['p95_ms']:>9.4f}")

    print("\n【分组明细】误伤 / 漏判（误伤 = 业务被拦成闲聊 = 拒答）")
    print(f"  {'组':<13}{'n':>5}" + "".join(f"{v:>22}" for v in ("rule", "bert", "hybrid")))
    for group, _, desc in DATASETS:
        row = f"  {group:<13}{rep['dataset']['groups'][group]:>5}"
        for name in ("rule", "bert", "hybrid"):
            g = rep["variants"][name]["by_group"][group]
            cell = f"误伤{g['fp_misblock']} 漏判{g['fn_missed']}"
            row += f"{cell:>22}"
        print(row)
        print(f"  {'':<13}{'':<5}{desc}")

    print("\n【门槛扫描】BERT（误伤随门槛下降，漏判随门槛上升）")
    print(f"  {'阈值':>6}{'准确率':>9}{'误伤':>7}{'漏判':>7}{'正确拦截':>9}{'误伤率':>9}{'漏判率':>9}")
    for s in rep["threshold_sweep"]:
        print(f"  {s['threshold']:>6}{s['accuracy']:>9.4f}{s['fp_misblock']:>7}"
              f"{s['fn_missed']:>7}{s['tp_caught']:>9}"
              f"{s['misblock_rate_on_business']:>9.4f}{s['miss_rate_on_chitchat']:>9.4f}")

    gap, cost, bat = rep["rule_gap_analysis"], rep["cost_model"], rep["batch32"]
    print("\n【规则漏判的闲聊，BERT 补回来多少】")
    print(f"  规则漏判闲聊 {gap['rule_missed_chitchat']} 条；"
          f"其中 BERT 在阈值 {rep['threshold']} 下拦回 {gap['bert_recovered_at_threshold']} 条"
          f"（{gap['bert_recovered_ratio']}）")
    print(f"  规则误伤业务 {gap['rule_misblocked_business']} 条"
          f"{'：' + str(gap['rule_misblocked_samples']) if gap['rule_misblocked_samples'] else ''}")

    ea = rep["error_attribution"]

    def _dump(title, rows, limit=10):
        print(f"  {title}")
        for d in rows[:limit]:
            print(f"    {d['group']:<12} p_chitchat={d['p_chitchat']:<8} {d['query']}")
        if len(rows) > limit:
            print(f"    ...（共 {len(rows)} 条）")
        if not rows:
            print("    （无）")

    print("\n【错误归因】")
    _dump("BERT 误伤（业务被拦 = 拒答，最贵的一种错）:", ea["bert_misblock"])
    _dump("BERT 漏判（闲聊进链路，浪费 25.2s，但答得出来）:", ea["bert_missed"])
    print(f"  业务侧最像闲聊的样本（门槛 {rep['threshold']}，余量 "
          f"{ea['risk_margin']}；余量为负 = 已有业务样本越过门槛）:")
    for d in ea["business_risk_top"][:6]:
        print(f"    {d['group']:<12} p_chitchat={d['p_chitchat']:<8} {d['query']}")

    print("\n【代价换算】漏判每题浪费 "
          f"{cost['sec_per_miss']}s（LLM 规划 + 检索 + 生成）")
    print(f"  规则: 漏判 {rep['variants']['rule']['metrics']['fn_missed']} 条 "
          f"-> 浪费 {cost['rule_wasted_sec']}s")
    print(f"  BERT: 漏判 {rep['variants']['bert']['metrics']['fn_missed']} 条 "
          f"-> 浪费 {cost['bert_wasted_sec']}s；误伤 {cost['bert_misblock_count']} 条（拒答）")
    print(f"  省下 {cost['saved_sec']}s（{rep['dataset']['total']} 条上的合计）")
    print(f"  BERT 单条 {rep['variants']['bert']['latency_single']['p50_ms']}ms（p50），"
          f"相对 25.2s 链路占 "
          f"{rep['variants']['bert']['latency_single']['p50_ms'] / (COST_PER_MISS_SEC * 1000) * 100:.3f}%")

    print(f"\n【批量吞吐参考】batch32 共 {bat['total_ms']}ms，"
          f"单条 {bat['per_item_ms']}ms（离线场景，线上是单条形式）")
    print(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="意图路由方案对比（规则 vs BERT）")
    parser.add_argument("--device", choices=["cuda", "cpu"], default=None,
                        help="覆盖 config.DEVICE（用于对比同机 CPU/GPU 延迟）")
    parser.add_argument("--rule-passes", type=int, default=10,
                        help="规则方案重复遍数（规则是微秒级，单遍测不准）")
    parser.add_argument("--bert-passes", type=int, default=3,
                        help="BERT 方案重复遍数（GPU 抖动大，多遍取分位数更稳）")
    parser.add_argument("--out", default=OUT_JSON)
    args = parser.parse_args()

    if args.device:
        config.DEVICE = args.device
        config.DTYPE = torch.float16 if args.device == "cuda" else torch.float32

    items = load_items()
    queries = [it["query"] for it in items]

    if not bert_intent.preload():
        print(f"[fatal] BERT 意图模型不可用，无法对比: {bert_intent.load_info().get('error')}")
        print("        请先跑 train.py 生成 models/bert-intent（或检查 INTENT_MODEL_PATH）")
        raise SystemExit(1)

    probs = [r["p_chitchat"] for r in bert_intent.predict(queries, batch_size=32)]

    rep = build_report(items, probs, args)
    rep["model_load"] = bert_intent.load_info()

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)

    print_report(rep)
    print(f"结果已写入：{args.out}")


if __name__ == "__main__":
    main()
