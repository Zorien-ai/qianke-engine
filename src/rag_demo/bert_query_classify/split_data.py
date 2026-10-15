#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 2.5 / 2.6：数据集划分 + 「短业务 query」分布外测试集构造

2.5 划分：train 80% / val 10% / test 10%，**分层抽样**（保证三集类别比一致），seed=42
2.6 短业务测试集：20~30 条**极短**的业务查询（2~6 字），专门用来验证
    模型是不是靠「长度」这个捷径做题——

    训练集里 BUSINESS 均值 9.3 字，而线上用户可能直接打「美妆用户」「风控」
    这种极简缩写。如果模型真学了长度捷径，这批短业务 query 会被判成 CHITCHAT。

输入：data/cleaned.jsonl
输出：data/train.jsonl / data/val.jsonl / data/test.jsonl
      data/short_business_test.jsonl
      outputs/split_summary.json

独立运行：uv run python src/rag_demo/bert_query_classify/split_data.py
"""
import json
import os
from collections import Counter

from sklearn.model_selection import train_test_split

BASE = os.path.dirname(os.path.abspath(__file__))
CLEAN_JSONL = os.path.join(BASE, "data", "cleaned.jsonl")
OUT_DIR = os.path.join(BASE, "outputs")
SPLIT_JSON = os.path.join(OUT_DIR, "split_summary.json")

SEED = 42
VAL_RATIO = 0.1
TEST_RATIO = 0.1

SRC = os.path.join(BASE, "data")
TRAIN_JSONL = os.path.join(SRC, "train.jsonl")
VAL_JSONL = os.path.join(SRC, "val.jsonl")
TEST_JSONL = os.path.join(SRC, "test.jsonl")
SHORT_TEST_JSONL = os.path.join(SRC, "short_business_test.jsonl")


def norm(s: str) -> str:
    drop = set(" \t\r\n？?！!。.，,~～、；;：:「」“”\"'")
    return "".join(ch for ch in str(s) if ch not in drop)


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def dump_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 2.6 短业务测试集：全部 ≤ 6 字，且都不是闲聊
# ---------------------------------------------------------------------------
SHORT_BIZ_CANDIDATES = [
    # 极简缩写（线上常见的「懒人输入」）
    "美妆用户", "风控", "积分", "等级", "画像", "黑名单", "白名单",
    "客单价", "复购率", "留存率", "活跃度", "人群包", "转化漏斗",
    "会员等级", "积分门槛", "权益规则", "消费分层", "渠道来源",
    "沉睡用户", "高客单", "标签体系", "等级权益", "订单量",
    # 带 ID / 极短检索式
    "查U2765", "U2765", "查A类用户", "看下GMV", "调下画像",
    "美妆类目", "风控标签",
]


def build_short_test(cleaned: list[dict]) -> list[dict]:
    """构造分布外短业务测试集，并标注它与训练集的词面关系"""
    queries = [r["query"] for r in cleaned]
    norm_set = {norm(q) for q in queries}
    train_norm = {norm(r["query"]) for r in cleaned if r.get("_split") == "train"}
    all_norm = norm_set

    items, dropped = [], []
    for q in SHORT_BIZ_CANDIDATES:
        nq = norm(q)
        if nq in all_norm:
            dropped.append(q)          # 清洗集里已有原文 -> 会泄漏，剔除
            continue
        # 是否作为「片段」出现在某些更长 query 里：这类才是长度偏置的关键探针
        as_fragment = any(nq in norm(other) and nq != norm(other) for other in queries)
        items.append({
            "query": q,
            "label": "BUSINESS",
            "probe_type": "fragment" if as_fragment else "unseen",
            "in_train_exact": nq in train_norm,
        })
    print(f"  短业务测试集：{len(items)} 条"
          f"（fragment {sum(1 for i in items if i['probe_type'] == 'fragment')} / "
          f"unseen {sum(1 for i in items if i['probe_type'] == 'unseen')}）")
    if dropped:
        print(f"  因与清洗集重复而剔除：{dropped}")
    return items


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
    # 第一步切出 20% 临时集（分层）
    tr_idx, tmp_idx = train_test_split(
        idx, test_size=VAL_RATIO + TEST_RATIO, random_state=SEED, stratify=labels
    )
    # 第二步把 20% 对半分成 val / test（分层）——1:1，所以最终 8:1:1
    tmp_labels = [labels[i] for i in tmp_idx]
    val_idx, test_idx = train_test_split(
        tmp_idx, test_size=0.5, random_state=SEED, stratify=tmp_labels
    )

    splits = {"train": tr_idx, "val": val_idx, "test": test_idx}
    paths = {"train": TRAIN_JSONL, "val": VAL_JSONL, "test": TEST_JSONL}
    for name, ids in splits.items():
        rows = [{**data[i], "_split": name} for i in ids]
        dump_jsonl(paths[name], [{"query": r["query"], "label": r["label"]} for r in rows])
        splits[name] = rows

    summary = {}
    print(f"\n{'子集':<8}{'样本数':>8}{'占比':>9}   CHITCHAT / BUSINESS   "
          f"{'比例':>12}   长度 mean")
    print("-" * 78)
    for name in ("train", "val", "test"):
        rows = splits[name]
        c = Counter(r["label"] for r in rows)
        ch, bu = c.get("CHITCHAT", 0), c.get("BUSINESS", 0)
        mean_len = sum(len(r["query"]) for r in rows) / len(rows)
        print(f"{name:<8}{len(rows):>8}{len(rows) / n * 100:>8.1f}%   "
              f"{ch:>8} / {bu:<8}  1 : {bu / max(ch, 1):<8.3f}  {mean_len:>8.2f}")
        summary[name] = {
            "path": paths[name],
            "n": len(rows),
            "ratio_of_total": round(len(rows) / n, 4),
            "label_counts": dict(c),
            "chitchat_to_business": round(bu / max(ch, 1), 4),
            "mean_len": round(mean_len, 3),
        }

    # 一致性校验
    print("-" * 78)
    ratios = [s["chitchat_to_business"] for s in summary.values()]
    spread = max(ratios) - min(ratios)
    print(f"分层一致性：三集 1:B 比例 {['%.3f' % r for r in ratios]}，极差 {spread:.4f} "
          f"-> {'✓ 分层有效' if spread < 0.02 else '✗ 存在偏斜，需检查'}")
    overlap = (set(norm(r['query']) for r in splits['train'])
               & set(norm(r['query']) for r in splits['val']))
    overlap |= (set(norm(r['query']) for r in splits['train'])
                & set(norm(r['query']) for r in splits['test']))
    print(f"训练/验证/测试 交叉重复：{len(overlap)} 条 -> {'✓ 无泄漏' if not overlap else '✗ 有泄漏'}")
    print(f"四个文件已写入：{os.path.dirname(TRAIN_JSONL)}")

    # ---------- 2.6 ----------
    print("\n" + "=" * 78)
    print("步骤 2.6：构造「短业务 query」分布外测试集")
    print("=" * 78)
    short_items = build_short_test(
        [{**data[i], "_split": "train"} for i in tr_idx]
        + [{**data[i], "_split": "val"} for i in val_idx]
        + [{**data[i], "_split": "test"} for i in test_idx]
    )
    dump_jsonl(SHORT_TEST_JSONL, short_items)
    lens = [len(i["query"]) for i in short_items]
    tr_biz = [len(r["query"]) for r in splits["train"] if r["label"] == "BUSINESS"]
    tr_chi = [len(r["query"]) for r in splits["train"] if r["label"] == "CHITCHAT"]
    print(f"  长度：min={min(lens)} max={max(lens)} mean={sum(lens) / len(lens):.2f}")
    print(f"  对照训练集：BUSINESS mean={sum(tr_biz) / len(tr_biz):.2f}，"
          f"CHITCHAT mean={sum(tr_chi) / len(tr_chi):.2f}")
    print(f"  已写入：{SHORT_TEST_JSONL}")

    summary["short_business_test"] = {
        "path": SHORT_TEST_JSONL,
        "n": len(short_items),
        "purpose": "分布外探针：极短业务 query，用于检验模型是否依赖长度捷径",
        "mean_len": round(sum(lens) / len(lens), 3),
        "probe_types": dict(Counter(i["probe_type"] for i in short_items)),
        "items": short_items,
    }
    with open(SPLIT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  划分摘要已写入：{SPLIT_JSON}")
    print("=" * 78)


if __name__ == "__main__":
    main()
