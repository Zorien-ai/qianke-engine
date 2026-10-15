#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 1：BERT 意图分类数据 —— 分析与清洗

输入：data/1.jsonl                          （原始数据，只读不修改）
      data/chitchat_generated.jsonl         （步骤 2.1 长句闲聊，存在则合并）
      data/chitchat_medium_generated.jsonl  （步骤 2.7 中段闲聊，存在则合并）
      data/business_generated.jsonl         （步骤 2.7 短/中长/长句业务，存在则合并）
输出：data/cleaned.jsonl                    （清洗后数据）
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
DATA_DIR = os.path.join(BASE, "data")
SRC_JSONL = os.path.join(DATA_DIR, "1.jsonl")
CLEAN_JSONL = os.path.join(DATA_DIR, "cleaned.jsonl")
OUT_DIR = os.path.join(BASE, "outputs", "data_analysis")
REPORT_JSON = os.path.join(OUT_DIR, "analysis_report.json")

# 补充数据（按顺序合并，文件不存在则跳过）
EXTRA_FILES = [
    ("chitchat_generated.jsonl", "长句闲聊 步骤2.1"),
    ("chitchat_medium_generated.jsonl", "中段闲聊 步骤2.7"),
    ("business_generated.jsonl", "短/中长/长句业务 步骤2.7"),
]

LABELS = ["CHITCHAT", "BUSINESS"]
LABEL_MAP = {"CHITCHAT": 0, "BUSINESS": 1}
# 只截上限。**下限不剔除**：线上真实存在「好 / 赞 / 在」这类单字 query，
# 且把它们留在 CHITCHAT 里能削弱「短 = 闲聊」的伪关联（CHITCHAT 也可以是短的）。
MAX_LEN = 100
SHORT_LEN = 2      # 仅用于统计口径，不做删除

# 长度对称性检查用的分桶
BUCKETS = [(1, 3), (4, 6), (7, 9), (10, 12), (13, 15), (16, 18), (19, 24), (25, 40)]

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


def length_symmetry(rows: list[dict]) -> dict:
    """
    长度对称性检查 —— 「模型会不会走长度捷径」的体检表

    判定标准（任一不满足即认为存在长度捷径）：
      1. 没有任何长度桶被单一类别垄断：每桶少数类占比 >= 20%
      2. 两类最大长度差 <= 3 字
      3. 两类平均长度差 <= 1.5 字

    为什么要在训练前卡这个：偏置是「数据里长度和标签共变」造成的，
    模型只是忠实地学到了它。补数据只能从数据侧解决，事后加 class_weight、
    调阈值都治不了——所以这一项必须在上训练之前过。
    """
    lens = {lb: [len(r["query"]) for r in rows if r["label"] == lb] for lb in LABELS}
    buckets, worst = [], 1.0
    for lo, hi in BUCKETS:
        ch = sum(1 for v in lens["CHITCHAT"] if lo <= v <= hi)
        bu = sum(1 for v in lens["BUSINESS"] if lo <= v <= hi)
        tot = ch + bu
        minority = (min(ch, bu) / tot) if tot else 0.0
        worst = min(worst, minority) if tot else worst
        buckets.append({"range": f"{lo}-{hi}", "chitchat": ch, "business": bu,
                        "minority_share": round(minority, 4),
                        "empty": tot == 0,
                        # 空桶（两类都没有样本）不构成捷径，不能算不合格
                        "pass": True if tot == 0 else bool(minority >= 0.2)})
    max_diff = abs(max(lens["CHITCHAT"]) - max(lens["BUSINESS"]))
    mean_diff = abs(
        sum(lens["CHITCHAT"]) / max(len(lens["CHITCHAT"]), 1)
        - sum(lens["BUSINESS"]) / max(len(lens["BUSINESS"]), 1)
    )
    ok = worst >= 0.2 and max_diff <= 3 and mean_diff <= 1.5
    return {
        "buckets": buckets,
        "worst_minority_share": round(worst, 4),
        "max_len_diff": max_diff,
        "mean_len_diff": round(mean_diff, 3),
        "max_len": {lb: max(lens[lb]) for lb in LABELS},
        "mean_len": {lb: round(sum(lens[lb]) / max(len(lens[lb]), 1), 2) for lb in LABELS},
        "no_length_shortcut": ok,
    }


def pct(n: int, total: int) -> str:
    return f"{n / total * 100:.2f}%" if total else "0.00%"


PUNCT = set(" \t\r\n？?！!。.，,~～、；;：:「」“”\"'•·…—_-=+*/\\|@#$%^&()[]{}<>《》【】")
# 去重键：抹掉空白与标点。"你好" 与 "你好？"、'U2765 是什么用户' 与
# 'U2765是什么用户' 本质是同一条样本，按原文去重会漏掉它们（跨集泄漏的来源）。
def dedupe_key(s) -> str:
    return "".join(ch for ch in str(s) if ch not in PUNCT)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 78)
    print("步骤 1：数据分析与清洗")
    print("=" * 78)
    raw = load_jsonl(SRC_JSONL)
    n_src = len(raw)
    print(f"原始数据：{SRC_JSONL}  {n_src} 条")
    extra_info = {}
    for fname, desc in EXTRA_FILES:
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            continue
        rows = load_jsonl(path)
        extra_info[fname] = len(rows)
        raw = raw + rows
        print(f"补充数据：{fname}  {len(rows)} 条（{desc}）")
    total = len(raw)
    print(f"合并后总样本数：{total}")

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

    # 长度区间重叠：补长句闲聊后要盯住「长 = 闲聊」这个反向偏置
    bu_max = max((len(str(r.get("query", ""))) for r in raw if r.get("label") == "BUSINESS"),
                 default=0)
    ch_over = [len(str(r.get("query", ""))) for r in raw
               if r.get("label") == "CHITCHAT" and len(str(r.get("query", ""))) > bu_max]
    print(f"  长度区间重叠：BUSINESS 最长 {bu_max} 字；CHITCHAT 超出该长度的有 "
          f"{len(ch_over)} 条 -> {'存在「长 = 闲聊」反向偏置风险' if ch_over else '无反向偏置'}")

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

    key_cnt = Counter(dedupe_key(q) for q in queries)
    norm_dup_extra = sum(c - 1 for k, c in key_cnt.items() if c > 1)
    punct_dup_extra = max(key_cnt.get("", 0) - 1, 0)
    print(f"归一化重复（抹掉标点/空格后同形）：多出 {norm_dup_extra} 条"
          f"（其中纯标点变体 {punct_dup_extra} 条，其余是真实标点/空格变体）")

    n_punct = sum(1 for q in queries if dedupe_key(q) == "")
    print(f"纯标点 / 无实义 query：{n_punct} 条（去重后 {len({q for q in queries if dedupe_key(q) == ''})} 条）"
          f" -> 剔除（无意图可言，且标点变体本身就是跨集重复源）")

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

    too_short = [q for q in queries if len(str(q)) < SHORT_LEN]
    too_long = [q for q in queries if len(str(q)) > MAX_LEN]
    print(f"长度异常：> {MAX_LEN} 字 {len(too_long)} 条（剔除）")
    print(f"           < {SHORT_LEN} 字 {len(too_short)} 条（**保留**，作为长度锚点，不删）")
    if too_short:
        print(f"           短样本：{' / '.join(sorted(set(too_short)))}")
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
        if len(q) > MAX_LEN:
            drop[f"长度 > {MAX_LEN}"] += 1
            continue
        key = dedupe_key(q)
        if key == "":
            drop["纯标点/无实义"] += 1
            continue
        if key in seen:
            drop["重复（含标点/空格变体）"] += 1
            continue
        seen.add(key)
        cleaned.append({"query": q, "label": lb})

    for k, v in drop.items():
        print(f"  剔除 {k}：{v} 条")

    with open(CLEAN_JSONL, "w", encoding="utf-8") as f:
        for r in cleaned:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    cl_cnt = Counter(r["label"] for r in cleaned)
    cl_len = [len(r["query"]) for r in cleaned]
    print(f"\n清洗后：{len(cleaned)} 条（合并原始 {total}，剔除 {total - len(cleaned)}，"
          f"保留率 {pct(len(cleaned), total)}）")
    for lb in LABELS:
        c = cl_cnt.get(lb, 0)
        sub = [len(r["query"]) for r in cleaned if r["label"] == lb]
        print(f"  {lb:10s} {c:5d}  ({pct(c, len(cleaned))})   "
              f"长度 mean={np.mean(sub):5.2f} max={max(sub):3d}")
    n_short_kept = sum(1 for r in cleaned if len(r["query"]) < SHORT_LEN)
    print(f"  < {SHORT_LEN} 字短样本保留：{n_short_kept} 条（长度锚点）")
    print(f"  整体长度：min={min(cl_len)} max={max(cl_len)} mean={np.mean(cl_len):.2f} "
          f"p50={np.percentile(cl_len, 50):.0f} p95={np.percentile(cl_len, 95):.0f}")
    ch, bu = cl_cnt.get("CHITCHAT", 0), cl_cnt.get("BUSINESS", 0)
    ratio = bu / max(ch, 1)
    ok = 0.9 <= ratio <= 1.1
    print(f"  类别比 CHITCHAT:BUSINESS = 1 : {ratio:.3f} "
          f"{'✓ 落在 1:0.9~1:1.1 目标区间' if ok else '✗ 超出 1:0.9~1:1.1 目标区间'}")

    # ---------- 5. 长度对称性检查 ----------
    print("\n" + "-" * 78)
    print("【5. 长度分布对称性检查（防「长度 = 类别」捷径）】")
    print("-" * 78)
    sym = length_symmetry(cleaned)
    print(f"  {'长度桶':<10}{'CHITCHAT':>10}{'BUSINESS':>10}{'少数类占比':>12}")
    for b in sym["buckets"]:
        if b["empty"]:
            flag, share = "— 空桶", "     -"
        else:
            flag, share = ("✓" if b["pass"] else "✗ 单类垄断"), f"{b['minority_share'] * 100:.1f}%"
        print(f"  {b['range']:<10}{b['chitchat']:>10}{b['business']:>10}{share:>12}  {flag}")
    print(f"\n  最大长度 {sym['max_len']['CHITCHAT']} / {sym['max_len']['BUSINESS']} 字"
          f"（差 {sym['max_len_diff']} 字）；平均长度 "
          f"{sym['mean_len']['CHITCHAT']} / {sym['mean_len']['BUSINESS']} 字"
          f"（差 {sym['mean_len_diff']} 字）")
    print(f"  最差桶少数类占比 {sym['worst_minority_share'] * 100:.1f}%（阈值 20%）")
    print(f"  判定：{'✓ 长度不再携带类别信息，可以进训练' if sym['no_length_shortcut'] else '✗ 仍存在长度捷径，需继续补数据'}")
    print(f"\n清洗结果已写入：{CLEAN_JSONL}")

    report = {
        "source": SRC_JSONL,
        "source_rows": n_src,
        "generated_rows": sum(extra_info.values()),
        "extra_files": extra_info,
        "total_raw": total,
        "label_counts_raw": dict(label_cnt),
        "length_stats_raw": len_stats,
        "per_label_length": per_label_len,
        "duplicate": {
            "dup_query_kinds": len(dup_items),
            "dup_extra_rows": dup_extra,
            "normalized_dup_extra_rows": norm_dup_extra,
            "unique_queries": len(query_cnt),
            "label_conflicts": len(conflicts),
        },
        "pure_punctuation_rows": n_punct,
        "blank_queries": len(blank),
        "null_queries": len(none_q),
        "invalid_labels": other,
        "abnormal_length": {"lt_min": len(too_short), "gt_max": len(too_long)},
        "length_overlap": {
            "business_max_len": bu_max,
            "chitchat_longer_than_business_max": len(ch_over),
        },
        "top10_duplicates": [{"query": q, "count": c} for q, c in top10],
        "drop_reasons": dict(drop),
        "cleaned": {
            "path": CLEAN_JSONL,
            "total": len(cleaned),
            "label_counts": dict(cl_cnt),
            "class_ratio_chitchat_to_business": round(ratio, 4),
            "ratio_in_target_band": bool(ok),
            "short_samples_kept": n_short_kept,
            "length": {
                "min": min(cl_len), "max": max(cl_len),
                "mean": float(np.mean(cl_len)),
                "p50": float(np.percentile(cl_len, 50)),
                "p95": float(np.percentile(cl_len, 95)),
            },
        },
        "length_symmetry": sym,
        "figures": [p for p in (p1, p2, p3) if os.path.exists(p)],
    }
    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"分析报告已写入：{REPORT_JSON}")
    print("=" * 78)


if __name__ == "__main__":
    main()
