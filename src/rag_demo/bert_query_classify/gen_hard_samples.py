#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 2.9：手工整理的「字母/数字类极短输入」难样本

为什么需要（2026-10-16 实测缺口）
---------------------------------
入口意图路由换成 BERT 后，短业务探针仍错 2 条，且都是**极短 + 字母数字标识符**：

    看下GMV   p_chitchat = 0.9969  判成闲聊 -> 拒答真问题
    U2765     p_chitchat = 0.9962  判成闲聊 -> 拒答真问题

（完整对比见 bug/bert意图路由替换-延迟与准确率对比.md §4.4）

根因是训练集里这类形态太少：
  1. ID 几乎只以「更长的中文句子」出现（如「U2765的年龄」「U9911 有没有领过优惠券」），
     所以**裸 ID** 在模型眼里是没见过的东西，落到了闲聊一侧；
  2. 业务缩写（GMV / UV / ROI / DAU / SKU）在训练集里几乎没有独立样本。

因此按形态补两类业务样本，并补一小批**同长度的字母数字闲聊负样本**：

    business_id_abbrev.jsonl
        biz_id_short  裸标识符 / 标识符 + 极短业务词
        biz_abbrev    动作 + 业务缩写（看GMV / 查UV / 拉下ROI）
        biz_term      2~4 字极短业务名词（日活 / 动销 / 转化率）
    chitchat_alnum_short.jsonl
        cc_alnum      字母数字类闲聊（zzz / 6666 / yyds）

**「边界闲聊负样本」不是凑数**：只加正样本的话，模型会学成「含字母数字就是业务」，
于是 test 集里的 asdf / yes / 1 / testing 会从「正确拦截」变成「漏判」——
那是用一个错误换另一个错误。负样本的作用是把边界钉住。

两条硬约束（脚本内自检，不靠人盯）
----------------------------------
1. **不得与 probes.py 的探针重合**（归一化后），也**不得包含「全词未见过」探针的整串**。
   探针是分布外评测唯一的标尺。一旦混进训练集，探针指标会虚高且看不出来；
   更隐蔽的是 split_data.build_probes 遇到重合会**把探针丢掉**——评测集悄悄少一条，
   比漏判更难发现。
   包含关系（`UNSEEN_MUST_STAY`）是实测踩出来的第二层：等值自检放过
   「看下GMV明细」，但它把探针「看下GMV」从 unseen 翻成了 fragment，
   等于把「字面没见过也判得对」偷换成「见过前缀」。
   两种命中都**跳过并在输出里点名**。
2. **不得与已有数据冲突**（原始 data/1.jsonl 与其它补充文件，归一化后）。
   重合会在清洗阶段被静默去重（先到先得），白写一条还不知道；
   若重合但标签相反，那是真冲突，直接报错中止。

为什么手工整理而不是 LLM 生成
  这批样本要精确命中「标识符形态」这一种模式，且 ID 必须像真实系统里的
  （U + 四位数字），LLM 容易给出 U123456789 这类超长串——那反而教坏模型。
  手工可控、可复现、可逐条解释。

输出：data/business_id_abbrev.jsonl
      data/chitchat_alnum_short.jsonl
独立运行：uv run python src/rag_demo/bert_query_classify/gen_hard_samples.py
"""
import json
import os

from probes import norm, probe_norm_set

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

BIZ_OUT = os.path.join(DATA, "business_id_abbrev.jsonl")
CC_OUT = os.path.join(DATA, "chitchat_alnum_short.jsonl")

# 参与比对的既有数据（与 analyze_data.py 的合并顺序一致：原始在前、补充在后）
EXISTING_FILES = [
    "1.jsonl",
    "chitchat_generated.jsonl",
    "chitchat_medium_generated.jsonl",
    "business_generated.jsonl",
]

# ---------------- 1) 标识符类业务样本 ----------------
# 形态刻意覆盖「裸 ID」「前缀 ID」「ID + 极短业务词」「动作 + ID」四种，
# 因为线上这四种都会出现，而训练集里只有长句形式。
IDS = [
    "U8801", "U3027", "U6512", "U9043", "U1187",
    "U4470", "U7209", "U3355", "U6028", "U9917",
]
SHORT_IDS = ["A13", "B27", "C05", "D48", "V9", "S102", "M2048", "K360"]

# 每个模板套到 ID 上（模板里的 {} 表示 ID 位置）
ID_TEMPLATES = [
    "{}",
    "查{}",
    "看下{}的数据",
    "{}的等级",
    "{}的客单价",
    "用户{}",
    "拉一下{}",
]

# ---------------- 2) 动作 + 业务缩写 ----------------
ABBREVS = [
    "GMV", "UV", "PV", "ROI", "DAU", "MAU",
    "SKU", "CTR", "CVR", "ARPU", "GPM", "GMV明细",
]
ABBREV_VERBS = ["看", "查", "拉下", "看下"]
# 注：「看下」×「GMV」正好组合出探针「看下GMV」，会被下面的探针自检拦下并点名——
#     留这一组是为了让自检**有东西可拦**（一条永远不触发的守卫等于没有守卫）。
#     同族的「看GMV / 查GMV / 拉下GMV」才是真正进训练集的形态，这让模型学到的是
#     「动作 + 业务缩写 = 业务」，而不是把探针原样背下来。

# ---------------- 3) 极短业务名词（2~4 字）----------------
# 刻意避开探针里的 客单价 / 复购率 / 留存率 / 活跃度 / 订单量 / 高客单 等词，
# 否则等于把探针的构成词直接喂进去。
BIZ_TERMS = [
    "日活", "月活", "动销", "转化率", "退款率", "加购数",
    "收藏数", "浏览数", "店铺数", "商品数", "会员数", "新客数",
    "老客数", "首单数", "结算额", "支付率", "履约率", "净销额",
]

# ---------------- 4) 边界闲聊负样本 ----------------
# 与正样本**同长度、同字符集**（字母/数字/重复），区别只在「有没有业务语义」。
# 不含 test 集里已有的 asdf / yes / 1 / testing / test test（否则是同一批样本）。
CC_ALNUM = [
    "zzz", "qqqq", "hhhhh", "wwwww", "lalala", "hihihi",
    "gogogo", "okok", "yyds", "xswl", "emmm", "emmmmm",
    "2333", "23333", "6666", "8888", "5555", "111",
    "000", "777", "233", "999",
    "aaaa", "bbbb", "asd", "qwe", "zxc", "ooo", "kkk", "mmm", "ppp",
    "xixi", "hehe", "hiahia", "tql", "awsl",
    "6", "55", "666", "呜呜", "哈哈哈", "嘿嘿嘿",
    "eeee", "iiii", "ooooo", "nono", "yaya", "keke",
    "pipi", "didi", "hahaha", "233333", "9999", "wwww",
]


# 目前**全词未见过**的短探针（split_data 会按「是否作为子串出现在清洗集里」判定
# fragment / unseen）。这 8 条是短端里唯一还能测「字面没见过也判得对」的样本，
# 新样本**不得包含它们的完整串**——否则它们会静默翻成 fragment，
# 测的从泛化变成半记忆。等值自检抓不到这种包含关系（实测踩过：
# 「看下」×「GMV明细」组合出的「看下GMV明细」就把探针「看下GMV」翻了类型）。
UNSEEN_MUST_STAY = [
    "转化漏斗", "积分门槛", "权益规则", "查A类用户",
    "看下GMV", "调下画像", "美妆类目", "风控标签",
]


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_candidates() -> list[tuple[str, str, str]]:
    """返回 (query, label, task)，顺序即写入顺序"""
    rows: list[tuple[str, str, str]] = []

    for q in IDS + SHORT_IDS:
        rows.append((q, "BUSINESS", "biz_id_short"))
    for tpl in ID_TEMPLATES:
        if tpl == "{}":
            continue  # 裸 ID 已在上面写入
        for q in IDS:
            rows.append((tpl.format(q), "BUSINESS", "biz_id_short"))

    for verb in ABBREV_VERBS:
        for ab in ABBREVS:
            rows.append((f"{verb}{ab}", "BUSINESS", "biz_abbrev"))

    for q in BIZ_TERMS:
        rows.append((q, "BUSINESS", "biz_term"))

    for q in CC_ALNUM:
        rows.append((q, "CHITCHAT", "cc_alnum"))

    return rows


def main() -> None:
    print("=" * 78)
    print("步骤 2.9：字母/数字类极短输入 —— 难样本补齐")
    print("=" * 78)

    probes = probe_norm_set()
    existing: dict[str, str] = {}
    for fname in EXISTING_FILES:
        for r in load_jsonl(os.path.join(DATA, fname)):
            existing.setdefault(norm(r["query"]), r["label"])
    print(f"既有数据 {len(existing)} 条（归一化去重后）；探针 {len(probes)} 条")

    candidates = build_candidates()
    print(f"候选样本 {len(candidates)} 条（含正负两侧）")

    kept: list[tuple[str, str, str]] = []
    skipped_probe: list[str] = []
    skipped_contain: list[str] = []
    skipped_existing: list[str] = []
    seen: set[str] = set()
    conflicts: list[str] = []

    for q, label, task in candidates:
        nq = norm(q)
        if not nq:
            continue
        if nq in probes:
            skipped_probe.append(q)
            continue
        # 包含性守卫：不得把「全词未见过」的探针整串包进新样本
        hit = next((p for p in UNSEEN_MUST_STAY if norm(p) in nq), None)
        if hit:
            skipped_contain.append(f"{q}（含探针 {hit}）")
            continue
        if nq in existing:
            if existing[nq] != label:
                conflicts.append(f"{q}：既有={existing[nq]} 本次={label}")
            skipped_existing.append(q)
            continue
        if nq in seen:
            continue
        seen.add(nq)
        kept.append((q, label, task))

    print("\n" + "-" * 78)
    print("自检结果")
    print("-" * 78)
    print(f"  与探针重合被跳过：{len(skipped_probe)} 条"
          f"{' -> ' + str(skipped_probe) if skipped_probe else '（无）'}")
    print(f"  含 unseen 探针整串被跳过：{len(skipped_contain)} 条"
          f"{' -> ' + str(skipped_contain) if skipped_contain else '（无）'}")
    print(f"  与既有数据重合被跳过：{len(skipped_existing)} 条"
          f"{' -> ' + str(skipped_existing[:8]) + ('...' if len(skipped_existing) > 8 else '') if skipped_existing else '（无）'}")
    if conflicts:
        raise SystemExit(f"[fatal] 标签冲突（同形不同标签，先解决再生成）：{conflicts}")
    print(f"  标签冲突：0 条")

    # 自检落盘前的最后一道：写出的内容必须真的不含探针（等值 + 包含两种都查）
    leak = [q for q, _, _ in kept if norm(q) in probes]
    contain = [q for q, _, _ in kept
               if any(norm(p) in norm(q) for p in UNSEEN_MUST_STAY)]
    if leak or contain:
        raise SystemExit(f"[fatal] 探针污染自检失败：等值={leak} 包含={contain}")

    biz = [(q, task) for q, lb, task in kept if lb == "BUSINESS"]
    cc = [(q, task) for q, lb, task in kept if lb == "CHITCHAT"]

    with open(BIZ_OUT, "w", encoding="utf-8") as f:
        for q, task in biz:
            f.write(json.dumps({"query": q, "label": "BUSINESS", "task": task},
                               ensure_ascii=False) + "\n")
    with open(CC_OUT, "w", encoding="utf-8") as f:
        for q, task in cc:
            f.write(json.dumps({"query": q, "label": "CHITCHAT", "task": task},
                               ensure_ascii=False) + "\n")

    print("\n" + "-" * 78)
    print("输出")
    print("-" * 78)
    for path, rows in ((BIZ_OUT, biz), (CC_OUT, cc)):
        lens = [len(q) for q, _ in rows] or [0]
        by_task: dict[str, int] = {}
        for _, t in rows:
            by_task[t] = by_task.get(t, 0) + 1
        print(f"  {os.path.basename(path):<28}{len(rows):>4} 条  "
              f"长度 {min(lens)}~{max(lens)}  任务 {by_task}")

    # 难样本清单（人工核对用，只打前 12 条 + 后 6 条）
    print("\n  业务侧样例：" + " / ".join(q for q, _ in biz[:12]) + " ...")
    print("  消极样例：  " + " / ".join(q for q, _ in cc[:14]) + " ...")
    print(f"\n探针污染自检（等值+包含）："
          f"{'✓ 干净' if not (leak or contain) else '✗ 等值=' + str(leak) + ' 包含=' + str(contain)}")
    print("=" * 78)


if __name__ == "__main__":
    main()
