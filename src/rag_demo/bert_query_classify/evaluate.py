#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 6：模型评估

前提认知（决定了本脚本的结构）：
    训练时 val F1 = 1.0，从第 1 个 epoch 就是满分。这意味着 **val/test 作为评估集已经失效**——
    好模型、差模型、过拟合模型在这个集上都是 1.0，无法据此区分。所以 test 集在这里只承担
    「确认没跑飞」的角色，真正的评估信号来自三处：

      1. 分布外探针（30 条极短业务 + 25 条长句业务）—— 长度捷径的定向探针
      2. 置信度分布 —— F1 只说「判对了」，置信度说「有多确定」；
         同为 1.0 的两个模型，平均置信度 0.99 与 0.65 的鲁棒性完全不同
      3. 逐长度桶指标 —— 看模型是不是靠长度做题

输出：
    outputs/classification_report.txt   分类报告
    outputs/confusion_matrix.png        混淆矩阵
    outputs/confidence_distribution.png 置信度分布
    outputs/error_analysis.txt          错误样本 + 低置信样本分析
    outputs/eval_report.json            全部结构化结果

独立运行：uv run python src/rag_demo/bert_query_classify/evaluate.py
"""
import json
import math
import os
import sys
import time

import jieba
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
OUT_DIR = os.path.join(BASE, "outputs")
MODEL_DIR = os.path.join(BASE, "models", "bert-intent")

CLASS_REPORT = os.path.join(OUT_DIR, "classification_report.txt")
CM_PNG = os.path.join(OUT_DIR, "confusion_matrix.png")
CONF_PNG = os.path.join(OUT_DIR, "confidence_distribution.png")
ERR_TXT = os.path.join(OUT_DIR, "error_analysis.txt")
REPORT_JSON = os.path.join(OUT_DIR, "eval_report.json")

LABELS = ["CHITCHAT", "BUSINESS"]
LABEL_MAP = {"CHITCHAT": 0, "BUSINESS": 1}
BUCKETS = [(1, 3), (4, 6), (7, 9), (10, 12), (13, 15), (16, 18), (19, 24)]
MAX_LENGTH = 64
LOW_CONF = 0.6      # 低于此视为「边界样本」

plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False
DPI = 150
FIGSIZE = (12, 6)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """
    Wilson 95% 置信区间

    为什么小样本必须报区间：30 条全对时点估计是 100%，但 Wilson 区间是
    [88.6%, 100%]——「统计上只能说真实准确率 ≥ 88.6%」。
    拿点估计写「准确率 100%」是过度解读，样本量越小越危险。
    """
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, center - half), min(1.0, center + half)


def fmt_ci(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {k / n * 100:.1f}%  [95% CI {lo * 100:.1f}%, {hi * 100:.1f}%]"


def bucket_of(n: int) -> str:
    for lo, hi in BUCKETS:
        if lo <= n <= hi:
            return f"{lo}-{hi}"
    return f"{BUCKETS[-1][1] + 1}+"


def tokenize_zh(s: str) -> list[str]:
    """jieba 分词，用于「短语级重合度」；过滤标点与空白"""
    drop = set(" \t\r\n？?！!。.，,~～、；;：:「」“”\"'")
    return [t for t in jieba.lcut(str(s)) if t.strip() and not all(ch in drop for ch in t)]


# ---------------------------------------------------------------------------
# 推理
# ---------------------------------------------------------------------------
class IntentPredictor:
    def __init__(self, model_dir: str = MODEL_DIR):
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir).eval()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)
        self.id2label = self.model.config.id2label
        self.label2id = self.model.config.label2id

    @torch.no_grad()
    def probs(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch_size):
            enc = self.tok(texts[i:i + batch_size], return_tensors="pt",
                           truncation=True, max_length=MAX_LENGTH, padding=True)
            enc = {k: v.to(self.device) for k, v in enc.items()}
            out.append(torch.softmax(self.model(**enc).logits, dim=-1).cpu().numpy())
        return np.concatenate(out, axis=0) if out else np.zeros((0, 2))


def eval_block(pred: IntentPredictor, rows: list[dict], batch_size: int = 32) -> dict:
    """对一组样本推理并汇总指标"""
    texts = [r["query"] for r in rows]
    y_true = np.array([LABEL_MAP[r["label"]] for r in rows])
    probs = pred.probs(texts, batch_size)
    y_pred = probs.argmax(axis=1)
    acc = int((y_pred == y_true).sum())
    n = len(rows)
    lo, hi = wilson(acc, n)
    return {
        "texts": texts, "y_true": y_true, "y_pred": y_pred, "probs": probs,
        "n": n, "correct": acc, "accuracy": acc / n if n else 0.0,
        "acc_ci": [lo, hi],
        "errors": [{"query": texts[i], "true": LABELS[y_true[i]],
                    "pred": LABELS[y_pred[i]],
                    "p_true": float(probs[i][y_true[i]]),
                    "p_pred": float(probs[i][y_pred[i]])}
                   for i in range(n) if y_pred[i] != y_true[i]],
    }


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 78)
    print("步骤 6：模型评估")
    print("=" * 78)
    pred = IntentPredictor()
    print(f"模型：{MODEL_DIR}")
    print(f"id2label={pred.id2label}  设备={pred.device}")

    test = load_jsonl(os.path.join(DATA, "test.jsonl"))
    train = load_jsonl(os.path.join(DATA, "train.jsonl"))
    short_probe = load_jsonl(os.path.join(DATA, "short_business_test.jsonl"))
    long_probe = load_jsonl(os.path.join(DATA, "long_business_test.jsonl"))

    r_test = eval_block(pred, test)
    r_short = eval_block(pred, short_probe)
    r_long = eval_block(pred, long_probe)

    # 训练集词表（用于短语重合度 + 最近邻）
    train_tokens = [set(tokenize_zh(r["query"])) for r in train]
    train_queries = [r["query"] for r in train]
    train_gram = [set(_grams(q, 4)) for q in train_queries]
    gram_index: dict[str, list[int]] = {}
    for i, g in enumerate(train_gram):
        for x in g:
            gram_index.setdefault(x, []).append(i)

    def nearest(q: str) -> tuple[int, float]:
        """训练集里与 q 内容最接近的样本（4-gram Jaccard 最大者）"""
        g = set(_grams(q, 4))
        cand: dict[int, int] = {}
        for x in g:
            for k in gram_index.get(x, []):
                cand[k] = cand.get(k, 0) + 1
        best_i, best_j = -1, 0.0
        for k in sorted(cand, key=lambda x: -cand[x])[:30]:
            o = train_gram[k]
            j = len(g & o) / len(g | o) if (g | o) else 0.0
            if j > best_j:
                best_i, best_j = k, j
        return best_i, best_j

    def diagnose(query: str) -> list[str]:
        """给错误/犹豫样本标注**可能的**成因（提示，不是结论）"""
        hints = []
        n = len(query)
        if n <= 3:
            hints.append(f"极短文本（{n} 字），可用的判别信息很少")
        if any(not ("\u4e00" <= ch <= "\u9fff") for ch in query):
            hints.append("含非中文字符（字母/数字/ID），训练集中同类样本极少")
        toks = set(tokenize_zh(query))
        cover = len(toks & train_token_union) / len(toks) if toks else 0.0
        if cover < 0.8:
            hints.append(f"词面覆盖低（{cover:.0%} 的词在训练集出现过）")
        i, j = nearest(query)
        if j < 0.2:
            hints.append(f"与训练集最长公共片段很小（max 4-gram Jaccard {j:.2f}）")
        if i >= 0:
            hints.append(f"最接近的训练句：{train_queries[i]!r}（相似 {j:.2f}）")
        return hints

    report: dict = {"model_dir": MODEL_DIR, "low_conf_threshold": LOW_CONF}

    # =====================================================================
    # [1] 测试集整体评估
    # =====================================================================
    print("\n" + "-" * 78)
    print("【1】测试集整体评估（本集已失去区分力，仅确认「没跑飞」）")
    print("-" * 78)
    y_true, y_pred = r_test["y_true"], r_test["y_pred"]
    cr = classification_report(y_true, y_pred, labels=[0, 1],
                               target_names=LABELS, digits=4, zero_division=0)
    print(cr)
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    print(f"混淆矩阵（行=真实，列=预测）:\n  真实\\预测  {LABELS[0]:>10}{LABELS[1]:>10}")
    for i, lb in enumerate(LABELS):
        print(f"  {lb:<10}{cm[i][0]:>10}{cm[i][1]:>10}")
    print(f"\n整体准确率：{fmt_ci(r_test['correct'], r_test['n'])}")
    macro_f1 = float(np.mean(
        precision_recall_fscore_support(y_true, y_pred, labels=[0, 1], zero_division=0)[2]))
    with open(CLASS_REPORT, "w", encoding="utf-8") as f:
        f.write(f"意图二分类评估 —— 测试集（{r_test['n']} 条，与训练集同分布）\n")
        f.write(f"本集指标：准确率 {r_test['correct']}/{r_test['n']} = "
                f"{r_test['accuracy'] * 100:.1f}%，macro F1 {macro_f1:.4f}"
                f"（仅 {r_test['n'] - r_test['correct']} 条错误）\n")
        f.write("注意：区分力已接近饱和——好模型与差模型在本集上都会接近满分，\n"
                "      因此本集只用于确认「训练没跑飞」。真正的评估信号见\n"
                "      outputs/eval_report.json 的探针（分布外）与置信度部分。\n\n")
        f.write(cr)
        f.write(f"\n混淆矩阵（行=真实，列=预测）\n{'':12}" +
                "".join(f"{lb:>12}" for lb in LABELS) + "\n")
        for i, lb in enumerate(LABELS):
            f.write(f"{lb:<12}" + "".join(f"{v:>12}" for v in cm[i]) + "\n")
        f.write(f"\n整体准确率：{fmt_ci(r_test['correct'], r_test['n'])}\n")
    report["test"] = {k: v for k, v in r_test.items()
                      if k not in ("texts", "y_true", "y_pred", "probs")}
    report["test"]["confusion_matrix"] = cm.tolist()

    # 混淆矩阵图
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks([0, 1], LABELS)
    ax.set_yticks([0, 1], LABELS)
    ax.set_xlabel("预测标签")
    ax.set_ylabel("真实标签")
    ax.set_title("混淆矩阵（测试集）", fontsize=14)
    total = cm.sum()
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{cm[i][j]}\n({cm[i][j] / total * 100:.1f}%)",
                    ha="center", va="center", fontsize=13,
                    color="white" if cm[i][j] > cm.max() / 2 else "black")
    fig.colorbar(im, ax=ax, shrink=0.8)
    fig.savefig(CM_PNG, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"\n混淆矩阵图：{CM_PNG}")
    print(f"分类报告：{CLASS_REPORT}")

    # =====================================================================
    # [2] 逐长度桶
    # =====================================================================
    print("\n" + "-" * 78)
    print("【2】逐长度桶指标（监控项①：1-3 字桶）")
    print("-" * 78)
    print(f"  {'桶':<9}{'n':>5}{'CH':>5}{'BU':>5}{'准确率':>10}{'95% CI':>18}"
          f"{'R_闲聊':>9}{'R_业务':>9}")
    bucket_rows = []
    for lo, hi in BUCKETS:
        idx = [i for i, t in enumerate(r_test["texts"]) if lo <= len(t) <= hi]
        if not idx:
            continue
        yt, yp = y_true[idx], y_pred[idx]
        ok = int((yt == yp).sum())
        c_lo, c_hi = wilson(ok, len(idx))
        r_ch = float((yp[yt == 0] == 0).mean()) if (yt == 0).any() else float("nan")
        r_bu = float((yp[yt == 1] == 1).mean()) if (yt == 1).any() else float("nan")
        print(f"  {f'{lo}-{hi}':<9}{len(idx):>5}{int((yt == 0).sum()):>5}"
              f"{int((yt == 1).sum()):>5}{ok / len(idx) * 100:>9.1f}%"
              f"{f'[{c_lo * 100:.1f}%, {c_hi * 100:.1f}%]':>18}"
              f"{r_ch:>9.3f}{r_bu:>9.3f}")
        bucket_rows.append({"bucket": f"{lo}-{hi}", "n": len(idx),
                            "chitchat": int((yt == 0).sum()),
                            "business": int((yt == 1).sum()),
                            "accuracy": ok / len(idx),
                            "acc_ci": [c_lo, c_hi],
                            "recall_chitchat": r_ch, "recall_business": r_bu})
    report["length_buckets_test"] = bucket_rows
    if all(b["accuracy"] == 1.0 for b in bucket_rows):
        print("\n  说明：所有长度桶准确率均为 100% —— 长度桶在 test 上也没有区分力，")
        print("        逐桶分析的价值要靠探针集体现（见【3】）。")

    # =====================================================================
    # [3] 分布外探针
    # =====================================================================
    print("\n" + "-" * 78)
    print("【3】分布外探针（监控项③：注意样本量小，一律报 Wilson 区间）")
    print("-" * 78)
    probes = {}
    for name, res, rows in (("short", r_short, short_probe), ("long", r_long, long_probe)):
        print(f"\n  [{name}] {res['n']} 条，长度 "
              f"{min(len(t) for t in res['texts'])}~{max(len(t) for t in res['texts'])}"
              f"；类别全为 BUSINESS，所以准确率 = 业务召回率")
        print(f"    准确率：{fmt_ci(res['correct'], res['n'])}")
        wrong = res["errors"]
        print(f"    判错 {len(wrong)} 条：")
        for e in wrong[:12]:
            print(f"      {e['query']!r:<34} 真={e['true']} 预测={e['pred']} "
                  f"(P真={e['p_true']:.4f})")
        by_type = {}
        for i, row in enumerate(rows):
            by_type.setdefault(row.get("probe_type", "?"), []).append(i)
        stats = {}
        for t, idx in by_type.items():
            ok = int((res["y_pred"][idx] == res["y_true"][idx]).sum())
            lo, hi = wilson(ok, len(idx))
            print(f"    类型 {t:<9} {fmt_ci(ok, len(idx))}")
            stats[t] = {"n": len(idx), "correct": ok, "accuracy": ok / len(idx),
                        "acc_ci": [lo, hi]}
        probes[name] = {"n": res["n"], "correct": res["correct"],
                        "accuracy": res["accuracy"], "acc_ci": res["acc_ci"],
                        "wrong": wrong, "by_probe_type": stats,
                        "length_min": min(len(t) for t in res["texts"]),
                        "length_max": max(len(t) for t in res["texts"])}
    report["probes"] = probes

    # =====================================================================
    # [4] 探针的词面重合度（双向）
    # =====================================================================
    print("\n" + "-" * 78)
    print("【4】探针词面重合度（双向；长探针 fragment=0，故改用短语级口径）")
    print("-" * 78)
    train_token_union = set().union(*train_tokens)
    overlap_rows = []
    for name, res, rows in (("short", r_short, short_probe), ("long", r_long, long_probe)):
        print(f"\n  [{name}]")
        print(f"    {'探针':<28}{'p→t':>7}{'t→p':>7}{'最大4gram相似':>14}  {'结果':<8}")
        for i, row in enumerate(rows):
            q = row["query"]
            toks = set(tokenize_zh(q))
            # 找内容最接近的训练句
            best_i, best_j = nearest(q)
            near_tok = train_tokens[best_i] if best_i >= 0 else set()
            # p→t：探针里的说法有多少在训练集出现过
            p2t = len(toks & train_token_union) / len(toks) if toks else 0.0
            # t→p：匹配到的训练句里有多少词被探针复现（反向）
            t2p = len(toks & near_tok) / len(near_tok) if near_tok else 0.0
            pred_ok = res["y_pred"][i] == res["y_true"][i]
            overlap_rows.append({
                "probe_kind": name, "query": q, "n_chars": len(q),
                "tokens": sorted(toks),
                "p_to_t": round(p2t, 4), "t_to_p": round(t2p, 4),
                "max_4gram_jaccard": round(best_j, 4),
                "nearest_train": train_queries[best_i] if best_i >= 0 else "",
                "correct": bool(pred_ok),
            })
            print(f"    {q[:26]:<28}{p2t:>7.2f}{t2p:>7.2f}{best_j:>14.3f}  "
                  f"{'✓' if pred_ok else '✗ 判错':<8}")
    # 按重合度分组看指标
    print("\n  按内容重合度分组（max 4-gram 相似度 ≥0.6 视为「内容也见过」）：")
    grouped = {}
    for name in ("short", "long"):
        sel = [o for o in overlap_rows if o["probe_kind"] == name]
        for tag, fn in (("高重合(>=0.6)", lambda o: o["max_4gram_jaccard"] >= 0.6),
                        ("低重合(<0.6)", lambda o: o["max_4gram_jaccard"] < 0.6)):
            sub = [o for o in sel if fn(o)]
            if not sub:
                continue
            ok = sum(1 for o in sub if o["correct"])
            lo, hi = wilson(ok, len(sub))
            print(f"    [{name}] {tag:<14} {fmt_ci(ok, len(sub))}")
            grouped[f"{name}|{tag}"] = {"n": len(sub), "correct": ok,
                                        "accuracy": ok / len(sub), "acc_ci": [lo, hi]}
    report["phrase_overlap"] = {"per_probe": overlap_rows, "grouped": grouped}

    # =====================================================================
    # [5] 置信度分布
    # =====================================================================
    print("\n" + "-" * 78)
    print("【5】置信度分布（F1 只说判对，置信度说有多确定）")
    print("-" * 78)
    conf = {"test": {}, "short": {}, "long": {}}
    for name, res in (("test", r_test), ("short", r_short), ("long", r_long)):
        mp = res["probs"].max(axis=1)
        yt = res["y_true"]
        conf[name] = {
            "mean_max_prob": float(mp.mean()),
            "p05": float(np.percentile(mp, 5)),
            "min_max_prob": float(mp.min()),
            "mean_confidence_chitchat": float(mp[yt == 0].mean()) if (yt == 0).any() else None,
            "mean_confidence_business": float(mp[yt == 1].mean()) if (yt == 1).any() else None,
            "count_lt_0.6": int((mp < 0.6).sum()),
            "count_lt_0.7": int((mp < 0.7).sum()),
            "count_lt_0.9": int((mp < 0.9).sum()),
        }
        print(f"\n  [{name}] n={res['n']}")
        print(f"    平均最大概率 {mp.mean():.4f}，p05 {np.percentile(mp, 5):.4f}，"
              f"最低 {mp.min():.4f}")
        if (yt == 0).any():
            print(f"    真实闲聊样本平均置信度 {mp[yt == 0].mean():.4f}")
        if (yt == 1).any():
            print(f"    真实业务样本平均置信度 {mp[yt == 1].mean():.4f}")
        print(f"    边界样本（<{LOW_CONF}）{int((mp < 0.6).sum())} 条；"
              f"<0.7 {int((mp < 0.7).sum())} 条；<0.9 {int((mp < 0.9).sum())} 条")

    # 低置信样本按**排名**取，不按阈值取。
    # 阈值取法在这里会得到空表（所有样本都 >0.7），而空表是没有信息的——
    # 模型确实存在犹豫的样本，只是整体置信度高位运行，必须按排名才看得见。
    all_conf_rows = []
    for name, res in (("test", r_test), ("short", r_short), ("long", r_long)):
        mp = res["probs"].max(axis=1)
        for i in range(res["n"]):
            all_conf_rows.append({
                "source": name, "query": res["texts"][i],
                "true": LABELS[res["y_true"][i]], "pred": LABELS[res["y_pred"][i]],
                "max_prob": float(mp[i]), "p_chitchat": float(res["probs"][i][0]),
                "p_business": float(res["probs"][i][1]),
                "n_chars": len(res["texts"][i]),
            })
    all_conf_rows.sort(key=lambda x: x["max_prob"])
    low_conf_rows = all_conf_rows[:20]

    print("\n  置信度最低 Top 20 的标签构成（直接回答「是不是只对某一类不自信」）：")
    c = sum(1 for r in low_conf_rows if r["true"] == "CHITCHAT")
    b = sum(1 for r in low_conf_rows if r["true"] == "BUSINESS")
    print(f"    真实闲聊 {c} 条 / 真实业务 {b} 条")
    print(f"    区间 {low_conf_rows[0]['max_prob']:.4f} ~ {low_conf_rows[-1]['max_prob']:.4f}"
          f"（阈值 {LOW_CONF} 以下 {sum(1 for x in all_conf_rows if x['max_prob'] < LOW_CONF)} 条）")
    report["confidence"] = conf
    report["low_confidence_samples"] = low_conf_rows
    report["low_confidence_label_mix"] = {"true_chitchat": c, "true_business": b}

    # 置信度分布图
    #
    # 只画直方图会退化成「一根柱子」：95% 以上的样本堆在 0.99+，
    # 真正有信息量的尾部（模型在哪儿犹豫）被压成看不见的一点。
    # 所以下面加了第三张「升序置信度曲线」并放大 y 轴到 [0.5, 1.0]——
    # 尾部才是有分析价值的部分，必须让它可见。
    colors = {"CHITCHAT": "#4C9BE8", "BUSINESS": "#F2994A"}
    mp_t = r_test["probs"].max(axis=1)
    mp_short = r_short["probs"].max(axis=1)
    mp_long = r_long["probs"].max(axis=1)
    mp_p = np.concatenate([mp_short, mp_long])

    fig = plt.figure(figsize=(12, 10))
    gs = fig.add_gridspec(2, 2, hspace=0.32, wspace=0.22)
    ax0, ax1 = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1])
    ax2 = fig.add_subplot(gs[1, :])

    for lb, code in LABEL_MAP.items():
        sel = mp_t[r_test["y_true"] == code]
        if len(sel):
            ax0.hist(sel, bins=np.linspace(0.5, 1.0, 26), alpha=0.6,
                     label=f"真实{lb} (n={len(sel)})", color=colors[lb])
    ax0.axvline(LOW_CONF, ls="--", color="red", lw=1.5, label=f"边界阈值 {LOW_CONF}")
    ax0.set_title("测试集 置信度分布（按真实类别）", fontsize=13)
    ax0.set_xlabel("max(softmax)")
    ax0.set_ylabel("样本数")
    ax0.legend()
    ax0.grid(alpha=0.3)

    ax1.hist(mp_t, bins=np.linspace(0.5, 1.0, 26), alpha=0.6,
             label=f"test (n={len(mp_t)}, 均值 {mp_t.mean():.3f})", color="#6FCF97")
    ax1.hist(mp_p, bins=np.linspace(0.5, 1.0, 26), alpha=0.6,
             label=f"探针 (n={len(mp_p)}, 均值 {mp_p.mean():.3f})", color="#EB5757")
    ax1.axvline(LOW_CONF, ls="--", color="red", lw=1.5, label=f"边界阈值 {LOW_CONF}")
    ax1.set_title("测试集 vs 探针集 置信度对比", fontsize=13)
    ax1.set_xlabel("max(softmax)")
    ax1.set_ylabel("样本数")
    ax1.legend()
    ax1.grid(alpha=0.3)

    for vals, label, col in ((mp_t, f"测试集 (n={len(mp_t)})", "#6FCF97"),
                             (mp_short, f"短业务探针 (n={len(mp_short)})", "#EB5757"),
                             (mp_long, f"长业务探针 (n={len(mp_long)})", "#9B51E0")):
        ax2.plot(np.arange(1, len(vals) + 1), np.sort(vals), marker="o", ms=3,
                 lw=1.4, color=col, label=label)
    ax2.axhline(0.99, ls=":", lw=1.2, color="gray", label="0.99 参考线")
    ax2.axhline(LOW_CONF, ls="--", lw=1.5, color="red", label=f"边界阈值 {LOW_CONF}")
    ax2.set_ylim(0.5, 1.005)
    ax2.set_xlabel("样本排名（置信度升序）")
    ax2.set_ylabel("max(softmax)")
    ax2.set_title("置信度升序曲线 —— y 轴放大到 [0.5, 1.0]，尾部才是「模型在哪儿犹豫」",
                  fontsize=13)
    ax2.legend(loc="lower right")
    ax2.grid(alpha=0.3)

    fig.suptitle("模型置信度分布（F1 只说判对，置信度说有多确定）", fontsize=14)
    fig.savefig(CONF_PNG, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  置信度分布图：{CONF_PNG}")

    # =====================================================================
    # [6] 错误样本 + 低置信样本分析（两级）
    # =====================================================================
    print("\n" + "-" * 78)
    print("【6】错误与低置信样本分析（两级：test 错误可能为空，低置信一定有内容）")
    print("-" * 78)
    print(f"  test 集错误样本：{len(r_test['errors'])} 条")
    print(f"  探针集错误样本：{len(r_short['errors']) + len(r_long['errors'])} 条")

    err_lines = ["意图二分类 —— 错误样本与低置信样本分析", "=" * 70, ""]

    def dump_errors(name: str, res: dict, out_list: list) -> None:
        print(f"\n  【{name}】错误 {len(res['errors'])} 条：")
        out_list.append(f"【{name}】错误样本 {len(res['errors'])} 条")
        if not res["errors"]:
            print("    （无）")
            out_list.append("  （无）\n")
            return
        for e in res["errors"]:
            print(f"    {e['query']!r}  真实={e['true']} 预测={e['pred']} "
                  f"P(真实)={e['p_true']:.4f}")
            out_list.append(f"  {e['query']!r}  真实={e['true']} 预测={e['pred']} "
                            f"P(真实)={e['p_true']:.4f}")
            for h in diagnose(e["query"]):
                print(f"        · {h}")
                out_list.append(f"        · {h}")
        out_list.append("")

    dump_errors("test 集", r_test, err_lines)
    dump_errors("短业务探针", r_short, err_lines)
    dump_errors("长业务探针", r_long, err_lines)

    print(f"\n  置信度最低的 Top {len(low_conf_rows)} 条（按排名取，不设阈值——"
          f"阈值筛选会得到空表）：")
    print(f"    {'来源':<7}{'长度':>4}{'真实':>10}{'预测':>10}{'max_prob':>10}  query")
    err_lines.append(f"【置信度最低 Top {len(low_conf_rows)}】")
    err_lines.append(f"  {'来源':<7}{'长度':>4}{'真实':>10}{'预测':>10}"
                     f"{'max_prob':>10}  query")
    for r in low_conf_rows:
        flag = "" if r["true"] == r["pred"] else "  <- 判错"
        print(f"    {r['source']:<7}{r['n_chars']:>4}{r['true']:>10}{r['pred']:>10}"
              f"{r['max_prob']:>10.4f}  {r['query']}{flag}")
        err_lines.append(f"  {r['source']:<7}{r['n_chars']:>4}{r['true']:>10}"
                         f"{r['pred']:>10}{r['max_prob']:>10.4f}  {r['query']}{flag}")
    err_lines.append("")
    err_lines.append(f"低置信 Top20 标签构成：真实闲聊 "
                     f"{report['low_confidence_label_mix']['true_chitchat']} 条 / "
                     f"真实业务 "
                     f"{report['low_confidence_label_mix']['true_business']} 条")

    with open(ERR_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(err_lines) + "\n")
    print(f"\n  分析已写入：{ERR_TXT}")

    # =====================================================================
    # [7] 推理速度
    # =====================================================================
    print("\n" + "-" * 78)
    print("【7】推理速度测试")
    print("-" * 78)
    sample = test[0]["query"]
    for _ in range(10):                        # 预热，避免算上首次 CUDA/图初始化
        pred.probs([sample], 1)
    if pred.device == "cuda":
        torch.cuda.synchronize()
    t0 = time.time()
    for _ in range(100):
        pred.probs([sample], 1)
    single = (time.time() - t0) / 100 * 1000
    if pred.device == "cuda":
        torch.cuda.synchronize()

    texts = [t for t in r_test["texts"]]
    t0 = time.time()
    pred.probs(texts, 32)
    if pred.device == "cuda":
        torch.cuda.synchronize()
    t_batch = (time.time() - t0) * 1000
    per_item = t_batch / len(texts)

    print(f"  单条推理（batch=1，100 次平均）：{single:.2f} ms")
    print(f"  batch=32 批量推理：{t_batch:.1f} ms / {len(texts)} 条 = "
          f"{per_item:.2f} ms/条")
    print(f"  批量相对单条加速比：{single / per_item:.1f}x")
    print(f"  验收线：单条 < 20ms -> {'✓ 达标' if single < 20 else '✗ 未达标'}")
    report["inference_speed"] = {
        "single_ms_avg_100": round(single, 3),
        "batch32_total_ms": round(t_batch, 3),
        "batch32_per_item_ms": round(per_item, 3),
        "speedup_x": round(single / per_item, 2),
        "device": pred.device,
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n结构化报告：{REPORT_JSON}")
    print("=" * 78)


def _grams(s: str, n: int = 4) -> set:
    s = "".join(ch for ch in str(s) if ch not in " \t\r\n")
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


if __name__ == "__main__":
    main()
