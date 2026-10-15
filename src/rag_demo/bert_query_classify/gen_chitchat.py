#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 2.1：补充长句 CHITCHAT（闲聊）训练数据

为什么需要补：清洗后 CHITCHAT 只剩 775 条，且集中在「你好 / 早上好 / 在吗」这类
2-4 字短话术，而 BUSINESS 是 9.3 字均值的中长术语。模型极易学到
「短 = 闲聊」这个捷径，线上遇到「你能帮我做什么」这种 7 字闲聊就会判错。

补数据目标：
  - 用 LLM 生成一批 **中长句** 闲聊（6~30 字，均值 ≥ 8 字）
  - 覆盖 5 个子类：情绪表达 / 通用知识 / 无关话题 / 观点询问 / 身份能力询问
  - 与已有 query 严格去重（含近似去重），且不含业务词汇
  - 选出的样本与现有 775 条合并后，CHITCHAT ≈ 1100，与 BUSINESS 1031 回到 1 : 0.94

输入：data/1.jsonl
输出：data/chitchat_generated_all.jsonl  全量候选池（含 category，可追溯）
      data/chitchat_generated.jsonl      最终入选、待并入 cleaned 的样本
      data/_gen_raw.jsonl                断点续跑用原始累积（每个 batch 落盘一次）

独立运行：uv run python src/rag_demo/bert_query_classify/gen_chitchat.py
"""
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

from rag_demo.generation.generator import chat_completion  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
SRC_JSONL = os.path.join(BASE, "data", "1.jsonl")
RAW_POOL = os.path.join(BASE, "data", "_gen_raw.jsonl")
POOL_JSONL = os.path.join(BASE, "data", "chitchat_generated_all.jsonl")
OUT_JSONL = os.path.join(BASE, "data", "chitchat_generated.jsonl")

SEED = 42
BATCHES = 16          # 批次数
PER_BATCH = 32        # 每批请求条数 -> 目标候选 ~500
TARGET_NEW = 300      # 最终并入的条数（使 CHITCHAT 775+25+300 ≈ 1100）
MIN_LEN, MAX_LEN = 6, 30
MAX_RETRY = 3

# 业务词汇黑名单：出现即判定为 BUSINESS 语义，不能进闲聊集
BIZ_WORDS = [
    "用户", "画像", "会员", "风控", "黑名单", "白名单", "名单", "规则", "标签", "指标",
    "统计", "订单", "消费", "积分", "等级", "权益", "门槛", "渠道", "客户", "销售",
    "转化", "漏斗", "留存", "客单", "类目", "人群", "分层", "字段", "数据", "表格",
    "SQL", "sql", "同比", "环比", "维度", "口径", "阈值", "策略", "命中",
]
# 纯闲聊里不该出现的「更像业务查询」的动词组合
BIZ_PATTERNS = ["查一下", "查下", "查询", "筛选", "列出", "导出", "汇总", "统计一下"]

CATEGORIES = [
    ("情绪表达", ["今天很累", "心情不太好", "有点开心", "焦虑", "无聊", "委屈", "失眠", "压力大", "自我怀疑", "突然emo"]),
    ("通用知识", ["天气常识", "地理", "历史典故", "科学常识", "健康作息", "传统节日", "动植物", "数学小问题", "天文", "学外语"]),
    ("无关话题", ["电影", "音乐", "美食", "旅游", "游戏", "宠物", "运动", "追剧", "综艺", "周末安排"]),
    ("观点询问", ["对人工智能的看法", "对某个社会现象的看法", "人生建议", "二选一纠结", "对未来的看法", "怎样才算幸福"]),
    ("身份能力询问", ["你是谁", "你能做什么", "你会不会某项能力", "你和别的助手有什么不同", "你有没有记忆", "你懂不懂方言"]),
    # 手工种子：用户明确指出缺失的句式，保证一定进池
    ("__seed__", ["你能帮我做什么", "今天心情不太好想聊聊天", "你觉得人工智能会取代人类吗",
                  "推荐一部适合周末看的电影"]),
]

HAND_SEEDS = list(CATEGORIES[-1][1]) + [
    "最近总是睡不好有什么建议",
    "今天上班特别累不想说话",
    "你平时会感到无聊吗",
    "给我讲个冷笑话吧",
    "你觉得人为什么要努力工作",
    "周末不知道去哪玩求推荐",
    "我最近迷上了跑步",
    "有没有好听的中文歌推荐",
    "你会不会有情绪",
    "我好像有点emo了",
    "怎么才能早起不困",
    "你觉得养猫好还是养狗好",
    "帮我推荐一本适合睡前读的书",
    "最近压力有点大想放松一下",
    "今天天气真好适合出去玩",
    "你会讲方言吗",
    "你觉得现在的年轻人焦虑吗",
    "我想学做一道简单的家常菜",
    "有没有适合新手的运动推荐",
    "你最喜欢什么样的音乐",
    "陪我聊聊天好吗",
    "我最近有点迷茫不知道做什么",
    "你觉得读研还是工作好",
    "推荐几个适合散心的地方",
    "你懂星座吗",
    "今天心情不错想找人说说话",
    "怎么样才能让自己更有动力",
    "你喜欢什么颜色",
    "你觉得一个人旅行有意思吗",
    "给我一点生活上的建议吧",
    "我最近总是走神怎么办",
    "你会不会讲笑话逗我开心",
    "好无聊啊你在干嘛",
    "你平时喜欢干什么",
]

PROMPT_TMPL = """你在为一个中文二分类意图识别模型构造训练数据。模型只判断两件事：
- CHITCHAT：与业务数据无关的日常闲聊
- BUSINESS：查询用户画像 / 会员 / 风控 / 名单 / 指标 等业务数据

本次只造 **CHITCHAT（闲聊）** 样本。

硬性要求：
1. 自然口语化的中文，长度 **6~30 个字**，尽量中长句（12~25 字最好），不要只给两三个字
2. 严禁涉及业务数据查询：不得出现 用户/画像/会员/风控/名单/规则/标签/指标/统计/订单/消费/积分/等级/权益/类目/字段 等词
3. 不得重复已给出的句子或其近似改写
4. 句式、语气、话题都要分散，不要连续用同一个开头
5. 本批侧重子类：**{category}**（话题提示：{hints}）

{avoid_block}

只输出**严格合法的 JSON 数组**，不要解释、不要 markdown 代码块，格式：
[{{"query": "……", "category": "{category}"}}, ...]

本批共 {n} 条。"""


def norm(s: str) -> str:
    """归一化：去空白与句末标点，用于去重比较"""
    drop = set(" \t\r\n？?！!。.，,~～、；;：:「」“”\"'")
    return "".join(ch for ch in str(s) if ch not in drop)


def bigrams(s: str) -> set:
    s = norm(s)
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def append_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def extract_json_array(text: str) -> list:
    """从 LLM 输出里抠 JSON 数组（容忍代码块包裹 / 前后废话）"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1] if len(t.split("```")) > 1 else t
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    i, j = t.find("["), t.rfind("]")
    if i == -1 or j == -1 or j <= i:
        raise ValueError("no JSON array found")
    return json.loads(t[i:j + 1])


def is_valid(query: str) -> tuple[bool, str]:
    q = str(query).strip()
    if not q:
        return False, "empty"
    if not (MIN_LEN <= len(q) <= MAX_LEN):
        return False, "length"
    if any(w in q for w in BIZ_WORDS):
        return False, "biz_word"
    if any(p in q for p in BIZ_PATTERNS):
        return False, "biz_pattern"
    if norm(q) == "":
        return False, "empty"
    return True, "ok"


def gen_batch(category: str, hints: list[str], avoid: list[str], n: int) -> list[dict]:
    avoid_block = ""
    if avoid:
        sample = random.sample(avoid, min(10, len(avoid)))
        avoid_block = "已生成过的句子（禁止重复或近似改写）：\n" + "\n".join(f"- {a}" for a in sample)
    prompt = PROMPT_TMPL.format(category=category, hints="、".join(hints),
                                avoid_block=avoid_block, n=n)
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            resp = chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=1.0,
                stream=False,
            )
            items = extract_json_array(resp.choices[0].message.content)
            out = []
            for it in items:
                q = it.get("query") if isinstance(it, dict) else str(it)
                if q:
                    out.append({"query": str(q).strip(), "category": category,
                                "source": "llm"})
            if out:
                return out
            last_err = "empty result"
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(2 * attempt)
    print(f"    [warn] batch <{category}> 失败：{last_err}")
    return []


def main() -> None:
    random.seed(SEED)
    print("=" * 78)
    print("步骤 2.1：生成补充长句 CHITCHAT 数据")
    print("=" * 78)

    existing_raw = load_jsonl(SRC_JSONL)
    used_norm = {norm(r["query"]) for r in existing_raw}
    print(f"现有数据 {len(existing_raw)} 条，用于去重基线")

    # ---------- 断点续跑：已完成的 batch ----------
    done = load_jsonl(RAW_POOL)
    done_batches = {r.get("_batch") for r in done}
    pool = done
    print(f"续跑检查：已有原始候选 {len(done)} 条，完成 batch {len(done_batches)}/{BATCHES}")

    categories = [c for c in CATEGORIES if c[0] != "__seed__"]

    # ---------- LLM 批量生成 ----------
    for b in range(BATCHES):
        if b in done_batches:
            continue
        category, hints = categories[b % len(categories)]
        picked = random.sample(hints, min(3, len(hints)))
        avoid = [r["query"] for r in pool if r.get("_batch") == b - 1]
        t0 = time.time()
        items = gen_batch(category, picked, avoid, PER_BATCH)
        for it in items:
            it["_batch"] = b
        append_jsonl(RAW_POOL, items)
        pool.extend(items)
        print(f"  batch {b + 1:2d}/{BATCHES} [{category}] 返回 {len(items):2d} 条 "
              f"({time.time() - t0:.1f}s) 累计 {len(pool)}")

    # ---------- 过滤 ----------
    print("\n" + "-" * 78)
    print("过滤与去重")
    print("-" * 78)
    stat = {"biz_word": 0, "biz_pattern": 0, "length": 0, "empty": 0,
            "dup_existing": 0, "dup_inner": 0, "near_dup": 0, "ok": 0}

    candidates: list[dict] = []
    seen = set(used_norm)
    gram_index: dict[str, list[int]] = {}

    def add_ok(q: str, category: str, source: str) -> None:
        idx = len(candidates)
        candidates.append({"query": q, "category": category, "source": source})
        for g in bigrams(q):
            gram_index.setdefault(g, []).append(idx)
        seen.add(norm(q))

    # 手工种子优先进池
    for q in HAND_SEEDS:
        ok, why = is_valid(q)
        if not ok:
            stat[why] = stat.get(why, 0) + 1
            continue
        if norm(q) in seen:
            stat["dup_existing"] += 1
            continue
        add_ok(q.strip(), "__seed__", "hand")
        stat["ok"] += 1

    for it in pool:
        q = str(it.get("query", "")).strip()
        cat = it.get("category", "llm")
        ok, why = is_valid(q)
        if not ok:
            stat[why] = stat.get(why, 0) + 1
            continue
        nq = norm(q)
        if nq in seen:
            stat["dup_existing"] += 1
            continue
        # 近似去重：与共享 2-gram 的候选比 Jaccard
        bg = bigrams(q)
        near = False
        for g in list(bg)[:8]:
            for i in gram_index.get(g, [])[:40]:
                other = bigrams(candidates[i]["query"])
                if not (bg | other):
                    continue
                if len(bg & other) / len(bg | other) > 0.85:
                    near = True
                    break
            if near:
                break
        if near:
            stat["near_dup"] += 1
            continue
        add_ok(q, cat, "llm")
        stat["ok"] += 1

    for k, v in stat.items():
        print(f"  {k}: {v}")

    with open(POOL_JSONL, "w", encoding="utf-8") as f:
        for r in candidates:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n候选池（去重后）：{len(candidates)} 条 -> {POOL_JSONL}")

    # ---------- 按子类轮转挑选 TARGET_NEW 条 ----------
    by_cat: dict[str, list[dict]] = {}
    for r in candidates:
        by_cat.setdefault(r["category"], []).append(r)
    for v in by_cat.values():
        random.shuffle(v)

    order = ["__seed__"] + [c[0] for c in categories]
    selected: list[dict] = []
    cursor = {k: 0 for k in by_cat}
    while len(selected) < TARGET_NEW and any(cursor[k] < len(v) for k, v in by_cat.items()):
        for k in order:
            if k not in by_cat or cursor[k] >= len(by_cat[k]):
                continue
            if len(selected) >= TARGET_NEW:
                break
            selected.append(by_cat[k][cursor[k]])
            cursor[k] += 1

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in selected:
            f.write(json.dumps({"query": r["query"], "label": "CHITCHAT",
                                "category": r["category"]}, ensure_ascii=False) + "\n")

    lens = [len(r["query"]) for r in selected]
    print(f"\n入选 {len(selected)} 条 -> {OUT_JSONL}")
    print(f"  长度 min={min(lens)} max={max(lens)} mean={sum(lens) / len(lens):.2f}")
    cat_cnt = {c: sum(1 for r in selected if r["category"] == c) for c in by_cat}
    for k in order:
        if k in cat_cnt:
            print(f"  {k:12s} {cat_cnt[k]:3d}")
    print("=" * 78)


if __name__ == "__main__":
    main()
