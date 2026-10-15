#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 2.7：补长句 BUSINESS + 短句 BUSINESS + 中段 CHITCHAT，消除长度偏置

为什么不是「只补长句业务」：
  阶段 2 补完长句闲聊后，长度分桶是这样的（清洗后）：
      桶       CHITCHAT  BUSINESS
      1-3        242        0     <- 业务侧零样本，"短 = 闲聊" 依然成立
      4-6        402       154
      7-9        147       399
      10-12       34       353    <- 业务侧压倒多数，"中长 = 业务" 又出现了
      13-15       52       110
      16-18      153        13
      19-24       61        0     <- 业务侧零样本，"长 = 闲聊"
  只补长句业务，只是把偏置从「长=闲聊」换成「中长=业务」。真正的目标是
  **没有任何长度桶被单一类别垄断**，因此四档一起补：

      任务               长度      目标条数   修掉的偏置
      business_short23   2-3 字        90     1-3 字业务零样本
      business_short     2-4 字       150     补充极简业务输入
      business_midlong  16-18 字       60     16-18 字业务稀疏
      business_long     19-26 字       90     19+ 字业务零样本
      chitchat_medium    8-16 字      250     7-12 字闲聊稀疏

  注 1：business_short 的区间写成 2-4 字，实测模型绝大多数给的是 4 字，
  1-3 字桶只补进 37 条、少数类占比 13.3% 不达标——所以另开 business_short23
  把 2-3 字区间单独掐死，避免「区间给了但实际全落在同一头」。
  注 2：字数合规 ≠ 样本可用。模型为凑字数会生造「沉睡户 / 积分余 / 渠道单 /
  按品类分」这类词，所以最终入选前还要过一遍 LLM 质检（judge_natural）——
  这些词一旦进训练集，等于教模型学习不存在的词汇分布。

输入：data/1.jsonl / chitchat_generated.jsonl / probes.py（探针必须排除）
输出：data/business_generated.jsonl          入选的业务补充样本
      data/chitchat_medium_generated.jsonl   入选的中段闲聊样本
      data/_supp_pool.jsonl                  全量候选池（断点续跑用）

独立运行：uv run python src/rag_demo/bert_query_classify/gen_supplement.py
"""
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

from rag_demo.generation.generator import chat_completion  # noqa: E402

from probes import probe_norm_set  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
SEED = 42
BATCH = 40
MAX_RETRY = 3

# 去重基线只放「原始数据 + 步骤 2.1 的长句闲聊」。
# 千万不要把本脚本自己的输出文件（business_generated / chitchat_medium_generated）
# 也放进来：池子是全量保留的，第二次运行时会拿「上次的输出」把自己去重掉，
# 表现为候选数骤降、输出越跑越少（踩过：business_short 候选直接变 0）。
SRC_FILES = [
    "1.jsonl",
    "chitchat_generated.jsonl",
]
POOL_JSONL = os.path.join(DATA, "_supp_pool.jsonl")
BIZ_OUT = os.path.join(DATA, "business_generated.jsonl")
CC_OUT = os.path.join(DATA, "chitchat_medium_generated.jsonl")

# 业务实体词：业务样本必须至少含一个，防止模型掺进闲聊
BIZ_ENTITY = [
    "用户", "会员", "订单", "品类", "类目", "渠道", "名单", "画像", "风控", "积分",
    "等级", "权益", "留存", "复购", "客单", "转化", "消费", "标签", "规则", "优惠券",
    "活动", "流失", "沉睡", "新客", "老客", "客群", "人群", "门店", "地区", "城市",
    "下单", "退款", "退货", "加购", "浏览", "点击", "曝光", "漏斗", "分层", "阈值",
    "指标", "统计", "人数", "占比", "排名", "环比", "同比", "GMV", "渠道来源",
    # 短术语常用词（2-3 字任务里最容易命中 no_entity 误杀的就是这些）
    "活跃", "折扣", "优惠", "门槛", "购买", "回购", "首单", "发货", "物流", "库存",
    "价格", "毛利", "金额", "频次", "周期", "时长", "召回", "触达", "转化率", "留存率",
]
# 闲聊词：业务样本里出现即判为串类
CC_MARKERS = [
    "心情", "开心", "无聊", "聊天", "聊天", "笑话", "电影", "音乐", "美食", "旅游",
    "游戏", "宠物", "天气", "星座", "情绪", "人生", "陪伴", "睡不着", "焦虑", "怎么了",
]
# 业务词：闲聊样本里出现即判为串类
BIZ_WORDS = [
    "用户", "画像", "会员", "风控", "黑名单", "白名单", "名单", "规则", "标签", "指标",
    "统计", "订单", "消费", "积分", "等级", "权益", "门槛", "渠道", "客户", "销售",
    "转化", "漏斗", "留存", "客单", "类目", "人群", "分层", "字段", "数据", "同比",
    "环比", "维度", "口径", "阈值", "策略", "命中", "GMV",
]
BIZ_PATTERNS = ["查一下", "查下", "查询", "筛选", "列出", "导出", "汇总", "统计一下", "帮我查"]

PUNCT = set(" \t\r\n？?！!。.，,~～、；;：:「」“”\"'•·…—_-=+*/\\|@#$%^&()[]{}<>《》【】")

BIZ_PROMPT = """你在为一个中文业务数据查询系统构造训练数据。这个系统回答用户关于
「用户画像 / 会员 / 订单 / 品类 / 渠道 / 风控名单 / 积分权益」等业务数据的问题。

请造 {n} 条中文业务数据查询，长度**必须正好是 {lo}~{hi} 个字**（含标点也算）。

要求：
1. 每条都是「想查看某类业务数据」的提问或名词短语，读完能知道用户想看什么数据
2. 口语化、自然。{style}
3. 严禁闲聊内容：不要出现 心情/电影/天气/宠物/星座/情绪 这类话题
4. 业务面要广：用户、会员、订单、商品类目、渠道、风控、积分、复购、留存、消费分层都要覆盖
5. 不要重复已给出的句子；句式要多样，不要都用同一个开头
6. **写完请逐条数一遍字数**——最常见的错误就是写得偏短。不够长就补上时间范围
   或筛选条件（例如「最近九十天」「按城市」「在活动期间」），而不是换个更短的句子

{avoid_block}

只输出**严格合法的 JSON 数组**，不要解释、不要 markdown 代码块：
[{{"query": "……"}}, ...]

本批共 {n} 条，长度区间 {lo}~{hi} 字。"""

CC_PROMPT = """请造 {n} 条中文日常闲聊短句，长度**必须正好是 {lo}~{hi} 个字**。

要求：
1. 纯闲聊：聊心情、生活小事、兴趣、吃喝、出行、天气、学习、观点都可以
2. **严禁**涉及业务数据查询：不得出现 用户/会员/订单/画像/风控/名单/标签/指标/
   统计/类目/渠道/积分/等级/权益/客单/复购 等词
3. 不得写成「帮我查一下…」「统计一下…」这种查询口吻
4. 句式要多样，不要都用同一个开头；不要与已给出的句子重复

{avoid_block}

只输出**严格合法的 JSON 数组**，不要解释、不要 markdown 代码块：
[{{"query": "……"}}, ...]

本批共 {n} 条，长度区间 {lo}~{hi} 字。"""

TASKS = [
    {
        "name": "business_short23", "kind": "biz", "label": "BUSINESS",
        "lo": 2, "hi": 3, "want": 480, "target": 90,
        "style": "两三个字的业务术语（不要四字），例如：客单 / 复购 / 留存 / 积分 / 等级 / 标签 / 品类",
    },
    {
        # 长度区间保持 2-4：池子已按此生成，不改区间以便复用；
        # 2-3 字由上面的 business_short23 单独补足
        "name": "business_short", "kind": "biz", "label": "BUSINESS",
        "lo": 2, "hi": 4, "want": 480, "target": 150,
        "style": "极简输入，像用户偷懒时只打两三个字，例如：订单量 / 复购率 / 客单价 / 风控名单",
    },
    {
        "name": "business_midlong", "kind": "biz", "label": "BUSINESS",
        "lo": 16, "hi": 18, "want": 200, "target": 60,
        "style": "一句话问清一件事，例如：上个月新增的钻石会员一共有多少人",
    },
    {
        "name": "business_long", "kind": "biz", "label": "BUSINESS",
        "lo": 19, "hi": 26, "want": 240, "target": 90,
        "style": "完整的口语化提问，可以有「帮我」「想看下」「麻烦」开头，"
                 "例如：帮我查一下最近三个月高客单用户的复购情况",
    },
    {
        "name": "chitchat_medium", "kind": "cc", "label": "CHITCHAT",
        "lo": 8, "hi": 16, "want": 480, "target": 250,
        "style": "",
    },
]


def norm(s: str) -> str:
    return "".join(ch for ch in str(s) if ch not in PUNCT)


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
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        t = parts[1] if len(parts) > 1 else t
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    i, j = t.find("["), t.rfind("]")
    if i == -1 or j == -1 or j <= i:
        raise ValueError("no JSON array found")
    return json.loads(t[i:j + 1])


def is_valid(q: str, task: dict) -> tuple[bool, str]:
    q = str(q).strip()
    if not q:
        return False, "empty"
    if not (task["lo"] <= len(q) <= task["hi"]):
        return False, "length"
    if task["kind"] == "biz":
        if not any(w in q for w in BIZ_ENTITY):
            return False, "no_entity"
        if any(m in q for m in CC_MARKERS):
            return False, "chitchat_word"
    else:
        if any(w in q for w in BIZ_WORDS):
            return False, "biz_word"
        if any(p in q for p in BIZ_PATTERNS):
            return False, "biz_pattern"
    if norm(q) == "":
        return False, "empty"
    return True, "ok"


JUDGE_PROMPT = """下面是一批候选的「用户业务数据查询」。请逐条判断：**它像不像真实用户会输入的东西**。

判为「不合格」的三种情形：
- 生造的缩写，中文里不成立（例如「沉睡户」「积分余」「渠道单」「兑积分」「风控名」）
- 半截短语，不能独立表达查询意图（例如「按品类分」「按城市」「会员等」「按订单看」）
- 语义不明，看不出用户想看什么数据

合格的标准很宽：**只要是一个完整、自然、能独立表达查询意图的词或句子就算合格**
（「积分」「复购率」「订单量」「近三十天高客单用户数」「帮我查下各城市的复购率」都合格）。

只输出**不合格项的编号**组成的 JSON 数组，例如 [2, 5, 9]；若全部合格则输出 []。
不要输出任何解释。

候选：
{items}"""

# 闲聊的判定口径必须另写一套。
# 第一版图省事复用了业务那套「能不能独立表达查询意图」，结果把
# 「楼下新开了家面包店」「晚上打算看部老电影」这类完全正常的闲聊全判成半截话
# （411 条里误杀 60 条）。判据要贴着类别写，不能跨类复制。
CC_JUDGE_PROMPT = """下面是一批候选的中文日常闲聊短句。请逐条判断：**它像不像真人会随口说的一句话**。

判为「不合格」的情形：
- 生造词或语义不通，读起来不像正常中文
- 夹杂业务数据查询意图（出现 用户/会员/订单/画像/风控/名单/标签/指标/统计 等词，
  或「帮我查」「统计一下」这种查询口吻）
- 没有任何具体内容的空话（放在任何场合都成立，例如「今天过得还不错」）
- 不是一句话，只是个孤零零的词组（例如「早上的阳光」）

合格的标准很宽：**任何一句具体的、自然的、真人会说的话都算合格**
（「楼下新开了家面包店」「晚上打算看部老电影」「最近有点失眠」都合格）。

只输出**不合格项的编号**组成的 JSON 数组，例如 [2, 5, 9]；若全部合格则输出 []。
不要输出任何解释。

候选：
{items}"""


def judge_chunk(chunk: list[dict], kind: str) -> set:
    """让 LLM 挑出不合格项，返回本块内不合格的下标"""
    lines = "\n".join(f"{i}. {it['query']}" for i, it in enumerate(chunk))
    tmpl = JUDGE_PROMPT if kind == "biz" else CC_JUDGE_PROMPT
    resp = chat_completion(
        messages=[{"role": "user", "content": tmpl.format(items=lines)}],
        temperature=0.0,
        stream=False,
    )
    text = resp.choices[0].message.content
    i, j = text.find("["), text.rfind("]")
    if i == -1 or j <= i:
        raise ValueError("no JSON array in judge output")
    data = json.loads(text[i:j + 1])
    out = set()
    for d in data:
        try:
            out.add(int(str(d).strip().split(".")[0]))
        except ValueError:
            continue
    return {k for k in out if 0 <= k < len(chunk)}


def judge_natural(rows: list[dict], task_name: str, kind: str,
                  chunk: int = 60) -> tuple[list[dict], list[str]]:
    """
    LLM 质检：把「为凑字数生造出来的词」剔掉

    这一步不是可选项。实测 2-3 字任务里模型会造出「沉睡户」「积分余」「渠道单」
    这种中文里不存在的缩写，4 字任务里会造出「按品类分」「按城市」这种半截短语——
    它们会被当成正样本喂进去，教模型学习不存在的词汇分布。字数合规 ≠ 样本可用。
    """
    bad: set[int] = set()
    for start in range(0, len(rows), chunk):
        part = rows[start:start + chunk]
        for attempt in range(1, 3):
            try:
                bad |= {start + k for k in judge_chunk(part, kind)}
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    print(f"    [warn] {task_name} 质检第 {start // chunk + 1} 块失败："
                          f"{type(e).__name__}: {e}（该块全部保留）")
                time.sleep(1.5 * attempt)
    kept = [r for i, r in enumerate(rows) if i not in bad]
    dropped = [r["query"] for i, r in enumerate(rows) if i in bad]
    return kept, dropped


def build_prompt(task: dict, avoid: list[str], n: int, correction: str = "") -> str:
    avoid_block = ""
    if avoid:
        sample = random.sample(avoid, min(8, len(avoid)))
        avoid_block = "已有句子（禁止重复或近似改写）：\n" + "\n".join(f"- {a}" for a in sample)
    tmpl = BIZ_PROMPT if task["kind"] == "biz" else CC_PROMPT
    return tmpl.format(n=n, lo=task["lo"], hi=task["hi"],
                       style=task.get("style", ""), avoid_block=avoid_block) + correction


def gen_batch(task: dict, avoid: list[str], n: int) -> list[dict]:
    """
    生成一批，并做**长度自检**：

    实测模型对字数要求会系统性「写短」（要 16~18 字，给的是 13~16 字），
    一次调用只能捞出个位数合格样本。所以在第一次返回后统计实际长度分布，
    不合格就把「你上一批偏短，实测 a~b 字」作为反馈塞回去重试，
    并把两次结果取并集（重复项由后续归一化去重消掉）。
    """
    collected, seen_local = [], set()
    correction = ""
    for attempt in range(1, MAX_RETRY + 1):
        prompt = build_prompt(task, avoid, n, correction)
        t0 = time.time()
        try:
            resp = chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.95 if task["kind"] == "biz" else 1.0,
                stream=False,
            )
            raw = extract_json_array(resp.choices[0].message.content)
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] attempt {attempt} 失败：{type(e).__name__}: {e}")
            time.sleep(2 * attempt)
            continue
        batch = []
        for it in raw:
            q = it.get("query") if isinstance(it, dict) else str(it)
            if not q:
                continue
            q = str(q).strip()
            if q in seen_local:
                continue
            seen_local.add(q)
            batch.append({"query": q, "kind": task["kind"],
                          "task": task["name"], "label": task["label"]})
        if not batch:
            continue
        collected.extend(batch)
        lens = [len(b["query"]) for b in batch]
        in_range = sum(1 for v in lens if task["lo"] <= v <= task["hi"])
        rate = in_range / len(batch)
        print(f"    ({time.time() - t0:.1f}s) 返回 {len(batch)} 条，长度 "
              f"{min(lens)}~{max(lens)}，合格 {in_range}（{rate:.0%}）")
        if rate >= 0.6:
            break
        correction = (
            f"\n\n【重要修正】你上一次给出的 {len(batch)} 条句子，长度是 "
            f"{min(lens)}~{max(lens)} 字，**整体偏短**，不符合 {task['lo']}~{task['hi']} 字的要求。"
            f"这次请逐条数字数，确保**每一条都不少于 {task['lo']} 个字**："
            f"句子不够长时，补上时间范围或筛选条件（例如「最近九十天」「按城市」「在活动期间」）。"
        )
    return collected


def main() -> None:
    random.seed(SEED)
    print("=" * 78)
    print("步骤 2.7：补充数据 —— 三档业务长度 + 中段闲聊")
    print("=" * 78)

    base_norm = set()
    for f in SRC_FILES:
        rows = load_jsonl(os.path.join(DATA, f))
        base_norm |= {norm(r["query"]) for r in rows}
    probes = probe_norm_set()
    print(f"去重基线：已有 {len(base_norm)} 条 + 探针 {len(probes)} 条（探针禁止进入训练补充集）")
    base_norm |= probes

    pool = load_jsonl(POOL_JSONL)
    done = {(r.get("task"), r.get("_batch")) for r in pool}
    print(f"续跑检查：候选池已有 {len(pool)} 条")

    # ---------- 生成 ----------
    for task in TASKS:
        n_batch = (task["want"] + BATCH - 1) // BATCH
        print(f"\n[{task['name']}] 目标 {task['target']} 条，请求 {task['want']} 条 "
              f"（{n_batch} 批 × {BATCH}，长度 {task['lo']}~{task['hi']}）")
        for b in range(n_batch):
            if (task["name"], b) in done:
                continue
            avoid = [r["query"] for r in pool if r.get("task") == task["name"]]
            print(f"  batch {b + 1}/{n_batch}:", flush=True)
            items = gen_batch(task, avoid, BATCH)
            for it in items:
                it["_batch"] = b
            append_jsonl(POOL_JSONL, items)
            pool.extend(items)
            print(f"    入池 {len(items):2d} 条，池内累计 {len(pool)}")

    # ---------- 过滤 + 去重 ----------
    print("\n" + "-" * 78)
    print("过滤与去重")
    print("-" * 78)
    stat = {}
    by_task: dict[str, list[dict]] = {t["name"]: [] for t in TASKS}
    seen = set(base_norm)
    # 每个 task 各自一份 2-gram 倒排索引：索引里存的是「该 task 已接受列表」的下标，
    # 共用一份会串下标（查到别的 task 的样本上去）
    gram_index: dict[str, dict[str, list]] = {t["name"]: {} for t in TASKS}

    # 按 TASKS 顺序处理，而不是按池子里的写入顺序：
    # 跨任务去重是「先到先得」，顺序决定了 2-3 字的短术语归给 short23 还是 short
    for task in TASKS:
        name = task["name"]
        for it in [x for x in pool if x.get("task") == name]:
            q = str(it.get("query", "")).strip()
            ok, why = is_valid(q, task)
            if not ok:
                stat[f"{name}/{why}"] = stat.get(f"{name}/{why}", 0) + 1
                continue
            nq = norm(q)
            if nq in seen:
                stat[f"{name}/dup"] = stat.get(f"{name}/dup", 0) + 1
                continue
            gi = gram_index[name]
            bg = bigrams(q)
            near = False
            for g in list(bg)[:8]:
                for i in gi.get(g, [])[:40]:
                    other = bigrams(by_task[name][i]["query"])
                    if bg | other and len(bg & other) / len(bg | other) > 0.85:
                        near = True
                        break
                if near:
                    break
            if near:
                stat[f"{name}/near_dup"] = stat.get(f"{name}/near_dup", 0) + 1
                continue
            idx = len(by_task[name])
            by_task[name].append({"query": q, "label": task["label"], "task": name})
            for g in bigrams(q):
                gi.setdefault(g, []).append(idx)
            seen.add(nq)

    for k in sorted(stat):
        print(f"  {k}: {stat[k]}")

    # ---------- 选取 ----------
    biz_sel, cc_sel = [], []
    print("\n" + "-" * 78)
    print("LLM 质检（剔除生造缩写 / 半截短语）")
    print("-" * 78)
    natural: dict[str, list[dict]] = {}
    for task in TASKS:
        kept, dropped = judge_natural(by_task[task["name"]], task["name"], task["kind"])
        natural[task["name"]] = kept
        stat[f"{task['name']}/unnatural"] = len(dropped)
        print(f"  {task['name']:18s} 候选 {len(by_task[task['name']]):3d} -> "
              f"自然 {len(kept):3d}（剔除 {len(dropped):2d}）")
        if dropped:
            print(f"      剔除示例：{' / '.join(dropped[:12])}")

    print("\n" + "-" * 78)
    print("选取结果")
    print("-" * 78)
    for task in TASKS:
        cand = natural[task["name"]]
        random.shuffle(cand)
        sel = cand[:task["target"]]
        print(f"  {task['name']:18s} 自然候选 {len(cand):3d} -> 选中 {len(sel):3d}"
              f"（目标 {task['target']}）  长度 "
              f"{min((len(s['query']) for s in sel), default=0)}~"
              f"{max((len(s['query']) for s in sel), default=0)}")
        if task["kind"] == "biz":
            biz_sel.extend(sel)
        else:
            cc_sel.extend(sel)

    for path, rows in ((BIZ_OUT, biz_sel), (CC_OUT, cc_sel)):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"query": r["query"], "label": r["label"],
                                    "task": r["task"]}, ensure_ascii=False) + "\n")
        lens = [len(r["query"]) for r in rows]
        print(f"\n{path}\n  {len(rows)} 条，长度 mean={sum(lens) / max(len(lens), 1):.2f} "
              f"min={min(lens, default=0)} max={max(lens, default=0)}")

    # 污染自检
    leak = [r["query"] for r in biz_sel + cc_sel if norm(r["query"]) in probes]
    print(f"\n探针污染自检：{len(leak)} 条 -> {'✓ 干净' if not leak else '✗ ' + str(leak)}")
    print("=" * 78)


if __name__ == "__main__":
    main()
