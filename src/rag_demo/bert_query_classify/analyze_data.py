#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 1：BERT 意图分类数据 —— 分析与清洗

输入：data/1.jsonl              （原始数据，只读不修改）
输出：data/cleaned.jsonl        （清洗后数据）
      outputs/data_analysis/class_distribution.png
      outputs/data_analysis/length_distribution.png
      outputs/data_analysis/duplicate_top10.png
      outputs/data_analysis/analysis_report.json

独立运行：uv run python src/rag_demo/bert_query_classify/analyze_data.py
"""
import json
import os
from collections import Counter

import matplotlib.pyplot as plt
import numpy as np

# ---------------- 路径 ----------------
BASE = os.path.dirname(os.path.abspath(__file__))
SRC_JSONL = os.path.join(BASE, "data", "1.jsonl")
CLEAN_JSONL = os.path.join(BASE, "data", "cleaned.jsonl")
OUT_DIR = os.path.join(BASE, "outputs", "data_analysis")
REPORT_JSON = os.path.join(OUT_DIR, "analysis_report.json")

LABELS = ["CHITCHAT", "BUSINESS"]
LABEL_MAP = {"CHITCHAT": 0, "BUSINESS": 1}
MIN_LEN, MAX_LEN = 2, 100

# 中文字体
plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False


def load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def pct(n: int, total: int) -> str:
    return f"{n / total * 100:.2f}%" if total else "0.00%"


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    raw = load_jsonl(SRC_JSONL)
    total = len(raw)
    print("=" * 78)
    print("步骤 1：数据分析与清洗")
    print("=" * 78)
    print(f"原始数据：{SRC_JSONL}")
    print(f"总样本数：{total}")

    # ---------- 1. 基本统计 ----------
    print("\n" + "-" * 78)
    print("【1. 基本统计】")
    print("-" * 78)

    label_cnt = Counter(r.get("label") for r in raw)
    print("类别分布：")
    for lb in LABELS:
        c = label_cnt.get(lb, 0)
        print(f"  {lb:10s} {c:5d}  ({pct(c, total)})")
    other = {k: v for k, v in label_cnt.items() if k not in LABELS}
    if other:
        print(f"  非法标签   {sum(other.values()):5d}  ({pct(sum(other.values()), total)})  {other}")

    lengths = [len(str(r.get("query", ""))) for r in raw]
    arr = np.asarray(lengths, dtype=float)
    len_stats = {
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "mean": float(np.mean(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
    }
    print("\n文本长度分布（字符数）：")
    print(f"  min={len_stats['min']:.0f}  max={len_stats['max']:.0f}  "
          f"mean={len_stats['mean']:.2f}  p50={len_stats['p50']:.0f}  "
          f"p95={len_stats['p95']:.0f}  p99={len_stats['p99']:.0f}")

    per_label_len = {}
    for lb in LABELS:
        sub = [len(str(r.get("query", ""))) for r in raw if r.get("label") == lb]
        if sub:
            per_label_len[lb] = {
                "count": len(sub),
                "mean": float(np.mean(sub)),
                "max": float(np.max(sub)),
                "p95": float(np.percentile(sub, 95)),
            }
            d = per_label_len[lb]
            print(f"  {lb:10s} n={d['count']:5d}  mean={d['mean']:6.2f}  "
                  f"max={d['max']:5.0f}  p95={d['p95']:5.0f}")

    # ---------- 2. 数据质量检查 ----------
    print("\n" + "-" * 78)
    print("【2. 数据质量检查】")
    print("-" * 78)

    queries = [str(r.get("query", "")) for r in raw]
    query_cnt = Counter(queries)
    dup_items = [(q, c) for q, c in query_cnt.most_common() if c > 1]
    dup_extra = sum(c - 1 for _, c in dup_items)
    print(f"完全重复：{len(dup_items)} 个重复 query，多出 {dup_extra} 条"
          f"（去重后 {len(query_cnt)} 条，去重率 {pct(dup_extra, total)}）")

    # 同一 query 冲突标签
    q2labels: dict[str, set] = {}
    for r in raw:
        q2labels.setdefault(str(r.get("query", "")), set()).add(r.get("label"))
    conflicts = {q: sorted(v) for q, v in q2labels.items() if len(v) > 1}
    print(f"标签冲突（同一 query 多个标签）：{len(conflicts)} 个")
    if conflicts:
        for q, v in list(conflicts.items())[:5]:
            print(f"    {q!r} -> {v}")

    blank = [q for q in queries if not q.strip()]
    none_q = [r for r in raw if r.get("query") is None]
    print(f"空值 query：{len(none_q)} 条；空白字符 query：{len(blank)} 条")

    print(f"标签合法性：{'通过（仅 CHITCHAT / BUSINESS）' if not other else '存在非法标签 ' + str(other)}")

    too_short = [q for q in queries if len(str(q)) < MIN_LEN]
    too_long = [q for q in queries if len(str(q)) > MAX_LEN]
    print(f"长度异常：< {MIN_LEN} 字 {len(too_short)} 条；> {MAX_LEN} 字 {len(too_long)} 条")
    for q in too_long[:5]:
        print(f"    [{len(q)}] {q[:60]}...")

    if dup_items:
        print(f"\n重复样本 Top 10：")
        for q, c in dup_items[:10]:
            print(f"    x{c:<4d} {q}")

    # ---------- 3. 可视化 ----------
    print("\n" + "-" * 78)
    print("【3. 可视化输出】")
    print("-" * 78)

    # 3.1 类别分布柱状图
    fig, ax = plt.subplots(figsize=(12, 6))
    counts = [label_cnt.get(lb, 0) for lb in LABELS]
    bars = ax.bar(LABELS, counts, color=["#4C9BE8", "#F2994A"], width=0.5)
    for b, c in zip(bars, counts):
        ax.text(b.get_x() + b.get_width() / 2, c, f"{c}\n({pct(c, total)})",
                ha="center", va="bottom", fontsize=11)
    ax.set_title(f"类别分布（总样本 {total}）", fontsize=14)
    ax.set_ylabel("样本数")
    ax.set_ylim(0, max(counts) * 1.25 if counts else 1)
    ax.grid(axis="y", alpha=0.3)
    p1 = os.path.join(OUT_DIR, "class_distribution.png")
    fig.savefig(p1, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3.2 文本长度分布直方图（按类别分色）
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    bins = np.arange(0, min(max(lengths) + 2, 120), 2)
    for lb, color in zip(LABELS, ["#4C9BE8", "#F2994A"]):
        sub = [len(str(r.get("query", ""))) for r in raw if r.get("label") == lb]
        axes[0].hist(sub, bins=bins, alpha=0.6, label=f"{lb} (n={len(sub)})", color=color)
    axes[0].set_title("文本长度分布（按类别）", fontsize=13)
    axes[0].set_xlabel("字符数")
    axes[0].set_ylabel("样本数")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    axes[1].hist(lengths, bins=bins, color="#6FCF97", alpha=0.85)
    for v, name, c in ((len_stats["mean"], "mean", "red"), (len_stats["p95"], "p95", "purple")):
        axes[1].axvline(v, ls="--", lw=1.5, color=c, label=f"{name}={v:.0f}")
    axes[1].set_title("文本长度分布（整体）", fontsize=13)
    axes[1].set_xlabel("字符数")
    axes[1].set_ylabel("样本数")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    fig.suptitle("文本长度分布统计", fontsize=14)
    p2 = os.path.join(OUT_DIR, "length_distribution.png")
    fig.savefig(p2, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3.3 重复样本 Top 10
    top10 = dup_items[:10]
    p3 = os.path.join(OUT_DIR, "duplicate_top10.png")
    if top10:
        qs = [q if len(q) <= 14 else q[:14] + "…" for q, _ in top10][::-1]
        cs = [c for _, c in top10][::-1]
        fig, ax = plt.subplots(figsize=(12, 6))
        bars = ax.barh(qs, cs, color="#EB5757", alpha=0.85)
        for b, c in zip(bars, cs):
            ax.text(c, b.get_y() + b.get_height() / 2, f" {c}", va="center", fontsize=10)
        ax.set_title("重复样本 Top 10", fontsize=14)
        ax.set_xlabel("出现次数")
        ax.grid(axis="x", alpha=0.3)
        fig.savefig(p3, dpi=150, bbox_inches="tight")
        plt.close(fig)
    else:
        print("  无重复样本，跳过 duplicate_top10.png")

    for p in (p1, p2, p3):
        if os.path.exists(p):
            print(f"  {p}")

    # ---------- 4. 数据清洗 ----------
    print("\n" + "-" * 78)
    print("【4. 数据清洗】")
    print("-" * 78)

    seen: set[str] = set()
    cleaned, drop = [], Counter()
    for r in raw:
        lb, q = r.get("label"), r.get("query")
        if lb not in LABEL_MAP:
            drop["label 非法"] += 1
            continue
        if q is None:
            drop["query 为空值"] += 1
            continue
        q = str(q).strip()
        if not q:
            drop["query 为空白"] += 1
            continue
        q = " ".join(q.split())
        if len(q) < MIN_LEN:
            drop[f"长度 < {MIN_LEN}"] += 1
            continue
        if len(q) > MAX_LEN:
            drop[f"长度 > {MAX_LEN}"] += 1
            continue
        if q in seen:
            drop["完全重复"] += 1
            continue
        seen.add(q)
        cleaned.append({"query": q, "label": lb})

    for k, v in drop.items():
        print(f"  剔除 {k}：{v} 条")

    with open(CLEAN_JSONL, "w", encoding="utf-8") as f:
        for r in cleaned:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    cl_cnt = Counter(r["label"] for r in cleaned)
    cl_len = [len(r["query"]) for r in cleaned]
    print(f"\n清洗后：{len(cleaned)} 条（原始 {total}，剔除 {total - len(cleaned)}，"
          f"保留率 {pct(len(cleaned), total)}）")
    for lb in LABELS:
        c = cl_cnt.get(lb, 0)
        print(f"  {lb:10s} {c:5d}  ({pct(c, len(cleaned))})")
    print(f"  长度：min={min(cl_len)} max={max(cl_len)} mean={np.mean(cl_len):.2f} "
          f"p50={np.percentile(cl_len, 50):.0f} p95={np.percentile(cl_len, 95):.0f}")
    ratio = cl_cnt.get("BUSINESS", 0) / max(cl_cnt.get("CHITCHAT", 1), 1)
    print(f"  类别比 CHITCHAT:BUSINESS = 1 : {ratio:.3f}（越接近 1 越均衡）")
    print(f"\n清洗结果已写入：{CLEAN_JSONL}")

    report = {
        "source": SRC_JSONL,
        "total_raw": total,
        "label_counts_raw": dict(label_cnt),
        "length_stats_raw": len_stats,
        "per_label_length": per_label_len,
        "duplicate": {
            "dup_query_kinds": len(dup_items),
            "dup_extra_rows": dup_extra,
            "unique_queries": len(query_cnt),
            "label_conflicts": len(conflicts),
        },
        "blank_queries": len(blank),
        "null_queries": len(none_q),
        "invalid_labels": other,
        "abnormal_length": {"lt_min": len(too_short), "gt_max": len(too_long)},
        "top10_duplicates": [{"query": q, "count": c} for q, c in top10],
        "drop_reasons": dict(drop),
        "cleaned": {
            "path": CLEAN_JSONL,
            "total": len(cleaned),
            "label_counts": dict(cl_cnt),
            "length": {
                "min": min(cl_len), "max": max(cl_len),
                "mean": float(np.mean(cl_len)),
                "p50": float(np.percentile(cl_len, 50)),
                "p95": float(np.percentile(cl_len, 95)),
            },
        },
        "figures": [p for p in (p1, p2, p3) if os.path.exists(p)],
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"分析报告已写入：{REPORT_JSON}")
    print("=" * 78)


if __name__ == "__main__":
    main()
