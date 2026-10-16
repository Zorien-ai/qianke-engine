#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 2.10：高重合对照组探针（整句 4-gram Jaccard ≥ 0.6）

为什么需要它
------------
evaluate.py 的【4】按「整句 4-gram Jaccard 相似度」把探针分组，本意是回答：

    模型的成绩里，多少来自**词面记忆**（内容见过），多少来自**语义泛化**？

2026-10-16 实测的结果是：55 条探针**没有一条**落进高重合组（最高 0.40 / 0.25）。
于是分组对比只剩一个组，比较无从谈起——evaluate.py 里那句
「⚠ 没有任何探针落在「高重合(>=0.6)」组 —— 缺少对照组，分组对比本身不成立」
说的就是这件事。本模块补的正是这个缺失的对照组。

怎么造
------
从**训练集**的业务句出发，只做**最小改写**（追加语气词 / 前置礼貌语）：

    训练句「各会员等级的人数分布以及对应的平均消费」
      -> 「各会员等级的人数分布以及对应的平均消费呢」（+1 字，4-gram 相似 0.92）

    训练句「上个月新增的钻石会员里有多少人已完成首单」
      -> 「请问，上个月新增的钻石会员里有多少人已完成首单」（+3 字，相似 ~0.8）

三条硬约束（与 gen_hard_samples.py 同一套思路，脚本内自检）：

1. **整句相似度 ≥ 0.7**（比 0.6 的判据留出余量，避免贴在边界上被算进低重合组）。
   注：相似度用**字符 4-gram 的 Jaccard**，与 evaluate.py::_grams 同一定义——
   两处口径必须一致，否则造出来的样本在评测里落错组。
2. **与清洗集原文不重合**（否则是泄漏：模型背过这句，测的就不是"内容相似"）。
3. **语义不变**。对照组要测的是"内容见过了，还判得对吗"，所以变量只能有一个：
   词面重合度。改写一旦动了业务语义，高低两组的差异就分不清是"记忆"还是"问题变难了"。

⚠ 必须在 split_data 之后生成，且**数据一变就要重生成**
   本模块依赖 train 划分。旧的高重合探针在新划分里可能**落进训练集**，
   那一刻它就从对照组变成了泄漏——而且指标只会更好看，不会报错。
   因此 split_data.py 每次划分完都会重跑本步骤（见该文件末尾），
   并由本模块重新执行上面的第 2 条检查。

为什么短句做不出高重合对照组
   4-gram Jaccard 的下限由长度决定：句长 L 追加 1 个字符时相似度 = (L-3)/(L-2)。
   L=4 时只有 0.5，达不到 0.6；L=6 时 0.75。**所以高重合组必然由中长句构成**，
   短端（U2765 / 看下GMV 这类）天然无法构造"内容见过"的对照——
   这本身是个结论：短端只能靠 unseen/fragment 探针测，别再指望用重合度分组解释它。

输出：data/high_overlap_business_test.jsonl
独立运行：uv run python src/rag_demo/bert_query_classify/overlap_probes.py
"""
import json
import os
from collections import Counter

from probes import norm

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
HIGH_OUT = os.path.join(DATA, "high_overlap_business_test.jsonl")
TRAIN_JSONL = os.path.join(DATA, "train.jsonl")
CLEAN_JSONL = os.path.join(DATA, "cleaned.jsonl")

# 最小改写模板：(函数, 说明, 适用的最短原句长度)
#
# 长度下限是怎么来的：句长 L 追加 1 字后相似度 = (L-3)/(L-2)，要 ≥0.6 需 L≥5，
# 留余量取 6；前置 3 字则新增 3 个 gram，需 L 更长才划算（10 / 12）。
TEMPLATES = [
    (lambda q: q + "呢", "追加语气词「呢」", 6),
    (lambda q: "请问，" + q, "前置「请问，」", 10),
    (lambda q: "麻烦看下，" + q, "前置「麻烦看下，」", 12),
]

TARGET = 20          # 目标条数（够做分组对比，又不至于让 CI 过宽）
MIN_SIM = 0.7        # 比评测判据 0.6 留余量
LEN_BUCKETS = [(6, 9), (10, 14), (15, 20), (21, 32)]
PER_BUCKET = TARGET // len(LEN_BUCKETS)


def grams(s: str, n: int = 4) -> set:
    """字符 n-gram；与 evaluate.py::_grams 同一定义（去空白、保留标点）"""
    s = "".join(ch for ch in str(s) if ch not in " \t\r\n")
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _index(queries: list[str]) -> tuple[list[set], dict[str, list[int]]]:
    gs = [grams(q) for q in queries]
    inv: dict[str, list[int]] = {}
    for i, g in enumerate(gs):
        for x in g:
            inv.setdefault(x, []).append(i)
    return gs, inv


def max_sim(query: str, queries: list[str], gs: list[set],
            inv: dict[str, list[int]], top_cand: int = 40) -> tuple[int, float]:
    """最大 Jaccard 相似度及其对应下标（与 evaluate.py 的最近邻算法一致）"""
    g = grams(query)
    cand: dict[int, int] = {}
    for x in g:
        for k in inv.get(x, []):
            cand[k] = cand.get(k, 0) + 1
    best_i, best_j = -1, 0.0
    for k in sorted(cand, key=lambda x: -cand[x])[:top_cand]:
        o = gs[k]
        j = len(g & o) / len(g | o) if (g | o) else 0.0
        if j > best_j:
            best_i, best_j = k, j
    return best_i, best_j


def build_overlap_probes(train_rows: list[dict], cleaned_rows: list[dict],
                         target: int = TARGET, min_sim: float = MIN_SIM) -> tuple[list[dict], dict]:
    """生成高重合对照组探针。返回 (items, stats)"""
    biz = sorted({r["query"] for r in train_rows if r["label"] == "BUSINESS"},
                 key=lambda q: (len(q), q))
    gs, inv = _index(biz)
    clean_norm = {norm(r["query"]) for r in cleaned_rows}
    train_norm = {norm(q) for q in biz}

    items: list[dict] = []
    used_src: set[str] = set()
    used_probe: set[str] = set()
    rejected = Counter()

    for lo, hi in LEN_BUCKETS:
        picked = 0
        for src in biz:
            if picked >= PER_BUCKET:
                break
            if not (lo <= len(src) <= hi):
                continue
            if norm(src) in used_src:
                continue
            # 轮换模板顺序，避免全部命中同一个「最省事」的改写方式
            # （不轮换的话 20 条探针会清一色是「加个呢」，看上去像只试了一种招）
            rot = picked % len(TEMPLATES)
            for edit, desc, min_len in TEMPLATES[rot:] + TEMPLATES[:rot]:
                if len(src) < min_len:
                    continue
                q = edit(src)
                nq = norm(q)
                if nq == norm(src):
                    continue
                if nq in clean_norm:
                    rejected["与清洗集重合(泄漏)"] += 1
                    continue
                if nq in train_norm:
                    rejected["与训练集原文重合"] += 1
                    continue
                if nq in used_probe:
                    rejected["重复"] += 1
                    continue
                i, j = max_sim(q, biz, gs, inv)
                if i < 0 or j < min_sim:
                    rejected[f"相似度不足(<{min_sim})"] += 1
                    continue
                items.append({
                    "query": q,
                    "label": "BUSINESS",
                    "probe_kind": "high",
                    "probe_type": "high_overlap",
                    "edit": desc,
                    "source_train": src,
                    "max_4gram_jaccard": round(j, 4),
                })
                used_src.add(norm(src))
                used_probe.add(nq)
                picked += 1
                break

    sims = [i["max_4gram_jaccard"] for i in items] or [0.0]
    lens = [len(i["query"]) for i in items] or [0]
    stats = {
        "n": len(items),
        "target": target,
        "min_sim_required": min_sim,
        "sim_min": min(sims), "sim_mean": round(sum(sims) / len(sims), 4),
        "sim_max": max(sims),
        "len_min": min(lens), "len_max": max(lens),
        "len_mean": round(sum(lens) / len(lens), 3),
        "by_edit": dict(Counter(i["edit"] for i in items)),
        "rejected": dict(rejected),
    }
    return items, stats


def dumps_jsonl(path: str, items: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def build_and_write(train_rows: list[dict], cleaned_rows: list[dict]) -> tuple[list[dict], dict]:
    """供 split_data.py 调用的入口：生成 + 落盘 + 自检"""
    items, stats = build_overlap_probes(train_rows, cleaned_rows)
    dumps_jsonl(HIGH_OUT, items)

    clean_norm = {norm(r["query"]) for r in cleaned_rows}
    leak = [i["query"] for i in items if norm(i["query"]) in clean_norm]
    below = [i["query"] for i in items if i["max_4gram_jaccard"] < MIN_SIM]
    stats["leak_after_write"] = leak
    stats["below_min_sim_after_write"] = below
    if leak or below:
        raise SystemExit(f"[fatal] 高重合探针自检失败：泄漏={leak} 相似度不足={below}")
    return items, stats


def main() -> None:
    print("=" * 78)
    print("步骤 2.10：高重合对照组探针（整句 4-gram Jaccard ≥ 0.6）")
    print("=" * 78)

    train_rows = load_jsonl(TRAIN_JSONL)
    cleaned_rows = load_jsonl(CLEAN_JSONL)
    print(f"训练集 {len(train_rows)} 条；清洗集 {len(cleaned_rows)} 条")

    items, stats = build_and_write(train_rows, cleaned_rows)

    print(f"\n{'探针':<34}{'相似度':>8}{'原句长度':>10}  改写方式")
    print("-" * 78)
    for it in items:
        print(f"  {it['query'][:30]:<32}{it['max_4gram_jaccard']:>8.3f}"
              f"{len(it['source_train']):>10}  {it['edit']}")
        print(f"      ⇐ 训练原句：{it['source_train']}")

    print("\n" + "-" * 78)
    print(f"生成 {stats['n']} 条（目标 {stats['target']}）")
    print(f"  相似度 min {stats['sim_min']:.3f} / mean {stats['sim_mean']:.3f} / "
          f"max {stats['sim_max']:.3f}（门槛 {stats['min_sim_required']}）")
    print(f"  长度 {stats['len_min']}~{stats['len_max']} mean {stats['len_mean']}")
    print(f"  改写方式分布：{stats['by_edit']}")
    print(f"  被拒样本统计：{stats['rejected']}")
    print(f"  落盘后自检：泄漏 {len(stats['leak_after_write'])} 条 / "
          f"相似度不足 {len(stats['below_min_sim_after_write'])} 条 -> ✓ 通过")
    print(f"\n已写入：{HIGH_OUT}")
    print("=" * 78)


if __name__ == "__main__":
    main()
