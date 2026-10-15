#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 2.5 / 2.6 / 2.8：数据集划分 + 两端分布外探针集

2.5 划分：train 80% / val 10% / test 10%，**分层抽样**，seed=42
2.6 短业务探针：2~6 字的极简业务输入（「美妆用户」「风控」「查U2765」）
2.8 长业务探针：19~30 字的口语化业务提问（「帮我查一下最近三个月高客单用户的复购情况」）

两端探针的意义：长度这条捷径有两个方向——「短 = 闲聊」和「长 = 闲聊」。
普通测试集无法分别定位它们，只有把长/短业务各自单独拎出来打分才能看见。
（探针清单放在 probes.py，gen_supplement.py 用同一份清单把探针排除在训练集外，
  否则探针会被「训练时见过」，指标虚高、问题被掩盖。）

输入：data/cleaned.jsonl
输出：data/train.jsonl / val.jsonl / test.jsonl
      data/short_business_test.jsonl
      data/long_business_test.jsonl
      outputs/split_summary.json

独立运行：uv run python src/rag_demo/bert_query_classify/split_data.py
"""
import json
import os
from collections import Counter

from sklearn.model_selection import train_test_split

from probes import LONG_BIZ_PROBES, SHORT_BIZ_PROBES, norm

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT_DIR = os.path.join(BASE, "outputs")
CLEAN_JSONL = os.path.join(DATA, "cleaned.jsonl")
SPLIT_JSON = os.path.join(OUT_DIR, "split_summary.json")

SEED = 42
VAL_RATIO = 0.1
TEST_RATIO = 0.1

BUCKETS = [(1, 3), (4, 6), (7, 9), (10, 12), (13, 15), (16, 18), (19, 24), (25, 40)]
LABELS_ALL = ["CHITCHAT", "BUSINESS"]


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def dump_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def build_probes(cleaned: list[dict], candidates: list[str], kind: str) -> list[dict]:
    """
    构造分布外探针集

    - 与清洗集**原文重合**的直接剔除（否则就是泄漏，测的成了记忆能力）
    - `fragment`：该 query 在训练集里只以**更长形式**出现过
      （训练集有「会员等级如何划分」，探针是「会员等级」）——这类才是长度捷径的探针
    - `unseen`：词面完全没见过，同时测泛化
    """
    queries = [r["query"] for r in cleaned]
    all_norm = {norm(q) for q in queries}
    train_norm = {norm(r["query"]) for r in cleaned if r.get("_split") == "train"}

    items, dropped = [], []
    for q in candidates:
        nq = norm(q)
        if nq in all_norm:
            dropped.append(q)
            continue
        as_fragment = any(nq in norm(o) and nq != norm(o) for o in queries)
        items.append({
            "query": q,
            "label": "BUSINESS",
            "probe_kind": kind,
            "probe_type": "fragment" if as_fragment else "unseen",
            "in_train_exact": nq in train_norm,
        })
    lens = [len(i["query"]) for i in items] or [0]
    print(f"  {kind:<10} {len(items):2d} 条  "
          f"(fragment {sum(1 for i in items if i['probe_type'] == 'fragment')} / "
          f"unseen {sum(1 for i in items if i['probe_type'] == 'unseen')})  "
          f"长度 {min(lens)}~{max(lens)} mean {sum(lens) / len(lens):.2f}")
    if dropped:
        print(f"             因与清洗集重合而剔除：{dropped}")
    return items


def bucket_of(n: int) -> str:
    for lo, hi in BUCKETS:
        if lo <= n <= hi:
            return f"{lo}-{hi}"
    return f"{BUCKETS[-1][1] + 1}+"


def bucket_table(rows: list[dict], title: str) -> list[dict]:
    """逐子集打印长度分桶 + 桶内少数类占比（分层抽样应保持每桶两类共存）"""
    print(f"\n  {title}")
    print(f"    {'长度桶':<9}{'CHITCHAT':>10}{'BUSINESS':>10}{'少数类占比':>12}")
    out = []
    for lo, hi in BUCKETS:
        ch = sum(1 for r in rows
                 if r["label"] == "CHITCHAT" and lo <= len(r["query"]) <= hi)
        bu = sum(1 for r in rows
                 if r["label"] == "BUSINESS" and lo <= len(r["query"]) <= hi)
        tot = ch + bu
        share = min(ch, bu) / tot if tot else 0.0
        flag = "" if not tot else ("✓" if share >= 0.2 else "✗")
        print(f"    {f'{lo}-{hi}':<9}{ch:>10}{bu:>10}{share * 100:>11.1f}%  {flag}")
        out.append({"range": f"{lo}-{hi}", "chitchat": ch, "business": bu,
                    "minority_share": round(share, 4)})
    return out


def main() -> None:
    print("=" * 78)
    print("步骤 2.5：数据集划分（8:1:1 分层抽样）")
    print("=" * 78)
    os.makedirs(OUT_DIR, exist_ok=True)

    data = load_jsonl(CLEAN_JSONL)
    labels = [r["label"] for r in data]
    n = len(data)
    print(f"输入：{CLEAN_JSONL}  {n} 条  {dict(Counter(labels))}")

    idx = list(range(n))

    # 分层键 = 类别 × 长度桶
    #
    # 只按类别分层时，长度桶的分布靠随机数兜底：test 的 16-18 桶曾出现
    # 20:4 的偶然倾斜（该桶在 test 一共才 24 条，一个样本就能撬动比例）。
    # 桶内比例一歪，「这个长度桶上模型表现差」和「这个桶本来就没几个正样本」
    # 就分不清了——而阶段 4 恰恰要看逐桶指标来判断长度偏置。
    # 所以把长度桶也纳入分层，让三个子集的联合分布一致。
    strata = [f"{labels[i]}|{bucket_of(len(data[i]['query']))}" for i in idx]
    cnt = Counter(strata)
    print(f"分层键：类别×长度桶，共 {len(cnt)} 组，最小组合 {min(cnt.values())} 条")

    tr_idx, tmp_idx = train_test_split(
        idx, test_size=VAL_RATIO + TEST_RATIO, random_state=SEED, stratify=strata
    )
    val_idx, test_idx = train_test_split(
        tmp_idx, test_size=0.5, random_state=SEED,
        stratify=[strata[i] for i in tmp_idx]
    )

    paths = {
        "train": os.path.join(DATA, "train.jsonl"),
        "val": os.path.join(DATA, "val.jsonl"),
        "test": os.path.join(DATA, "test.jsonl"),
    }
    splits = {"train": tr_idx, "val": val_idx, "test": test_idx}
    rows_with_split = []
    summary = {}
    print(f"\n{'子集':<8}{'样本数':>8}{'占比':>9}   CHITCHAT / BUSINESS   "
          f"{'比例':>13}{'长度mean':>10}")
    print("-" * 78)
    for name, ids in splits.items():
        rows = [{**data[i], "_split": name} for i in ids]
        dump_jsonl(paths[name], [{"query": r["query"], "label": r["label"]} for r in rows])
        rows_with_split.extend(rows)
        c = Counter(r["label"] for r in rows)
        ch, bu = c.get("CHITCHAT", 0), c.get("BUSINESS", 0)
        mean_len = sum(len(r["query"]) for r in rows) / len(rows)
        print(f"{name:<8}{len(rows):>8}{len(rows) / n * 100:>8.1f}%   "
              f"{ch:>8} / {bu:<8}  1 : {bu / max(ch, 1):<9.3f}{mean_len:>10.2f}")
        summary[name] = {
            "path": paths[name], "n": len(rows),
            "ratio_of_total": round(len(rows) / n, 4),
            "label_counts": dict(c),
            "chitchat_to_business": round(bu / max(ch, 1), 4),
            "mean_len": round(mean_len, 3),
        }

    # ---------- 一致性 / 泄漏校验 ----------
    #
    # 判据用「各类别样本数相对理论值的偏离」，不用「比例极差」：
    # 14 组细分层 + 271 条子集，每组至少 1 条的取整粒度会让比例极差天然到 2% 上下，
    # 但那是取整波动，不是偏斜——按样本数看，偏离只有 1 条左右。
    print("-" * 78)
    ratios = [s["chitchat_to_business"] for s in summary.values()]
    overall = Counter(labels)
    devs = []
    for name in ("train", "val", "test"):
        for lb in LABELS_ALL:
            exp = summary[name]["ratio_of_total"] * overall[lb]
            devs.append(abs(summary[name]["label_counts"].get(lb, 0) - exp))
    max_dev = max(devs)
    spread = max(ratios) - min(ratios)
    print(f"分层一致性：三集 1:B 比例 {['%.3f' % r for r in ratios]}，极差 {spread:.4f}")
    print(f"            各类别样本数相对理论值最大偏离 {max_dev:.1f} 条（阈值 3 条）-> "
          f"{'✓ 分层有效' if max_dev <= 3 else '✗ 存在偏斜'}")
    norm_sets = {name: {norm(r["query"]) for r in rows_with_split if r["_split"] == name}
                 for name in splits}
    leak = set()
    for a in splits:
        for b in splits:
            if a < b:
                leak |= norm_sets[a] & norm_sets[b]
    print(f"跨子集重复：{len(leak)} 条 -> {'✓ 无泄漏' if not leak else '✗ ' + str(sorted(leak))}")

    # 探针必须不在任何子集里
    all_norm = set().union(*norm_sets.values())
    probe_leak = [q for q in SHORT_BIZ_PROBES + LONG_BIZ_PROBES if norm(q) in all_norm]
    print(f"探针是否混入训练/验证/测试：{len(probe_leak)} 条 -> "
          f"{'✓ 干净' if not probe_leak else '✗ ' + str(probe_leak)}")

    print("\n各子集长度分桶：")
    summary["length_buckets"] = {}
    for name in ("train", "val", "test"):
        summary["length_buckets"][name] = bucket_table(
            [r for r in rows_with_split if r["_split"] == name], f"[{name}]"
        )

    # ---------- 2.6 / 2.8 探针集 ----------
    print("\n" + "=" * 78)
    print("步骤 2.6 / 2.8：构造两端的分布外探针集")
    print("=" * 78)
    short_items = build_probes(rows_with_split, SHORT_BIZ_PROBES, "short")
    long_items = build_probes(rows_with_split, LONG_BIZ_PROBES, "long")
    short_path = os.path.join(DATA, "short_business_test.jsonl")
    long_path = os.path.join(DATA, "long_business_test.jsonl")
    dump_jsonl(short_path, short_items)
    dump_jsonl(long_path, long_items)

    tr_biz = [len(r["query"]) for r in rows_with_split
              if r["_split"] == "train" and r["label"] == "BUSINESS"]
    tr_chi = [len(r["query"]) for r in rows_with_split
              if r["_split"] == "train" and r["label"] == "CHITCHAT"]
    print(f"\n  训练集对照：BUSINESS mean={sum(tr_biz) / len(tr_biz):.2f} "
          f"(min {min(tr_biz)} max {max(tr_biz)})；"
          f"CHITCHAT mean={sum(tr_chi) / len(tr_chi):.2f} "
          f"(min {min(tr_chi)} max {max(tr_chi)})")
    print(f"  已写入：{short_path}\n         {long_path}")

    summary["probes"] = {
        "short_business_test": {
            "path": short_path, "n": len(short_items),
            "purpose": "短端探针：检验模型是否「短就判闲聊」",
            "mean_len": round(sum(len(i["query"]) for i in short_items)
                              / max(len(short_items), 1), 3),
            "probe_types": dict(Counter(i["probe_type"] for i in short_items)),
            "items": short_items,
        },
        "long_business_test": {
            "path": long_path, "n": len(long_items),
            "purpose": "长端探针：检验模型是否「长就判闲聊」",
            "mean_len": round(sum(len(i["query"]) for i in long_items)
                              / max(len(long_items), 1), 3),
            "probe_types": dict(Counter(i["probe_type"] for i in long_items)),
            "items": long_items,
        },
    }
    with open(SPLIT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n划分摘要已写入：{SPLIT_JSON}")
    print("=" * 78)


if __name__ == "__main__":
    main()
