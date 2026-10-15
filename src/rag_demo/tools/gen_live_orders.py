#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : gen_live_orders.py
@Function: 生成一批「近 90 天」的模拟实时订单，用于验证增量更新链路

为什么单独造一份
----------------
data/dianshuang 是 2024 全年的静态快照（快照日 2024-12-30），它把「最近30天」
「本周」这类时效问题钉死在两年前，导致三件事没法验证：

    1. 增量入库后画像字段（order_count / avg_amount / days_since_last_buy）能否正确重算
    2. 会员等级会不会随复购跨档（avg_amount 变了，等级该跟着变）
    3. 有新鲜数据之后，时效类问题是否还答不准

与原始数据的隔离（四条硬约束）
----------------------------
1. **只读**原始 CSV：本脚本只 read_csv，不写、不改、不移动
2. 写入独立目录 data/new-dianshuang：`ingest_data.DATA_DIR` 不变就绝不会读到它
3. 每行带 `数据批次` 列，被复制到别处也认得出是模拟数据
4. **不碰数据库**：本脚本不连 PG，user_profile_vectors 里的画像基线不会被改动

产出
----
    data/new-dianshuang/<平台>.csv     6 个文件，合计 2000 行
    data/new-dianshuang/README.md      数据标记、字段说明与增量更新方案

用法
----
    uv run python src/rag_demo/tools/gen_live_orders.py
    可选：--end 2026-10-15 --rows 2000 --seed 20261015
"""
import argparse
import glob
import json
import os
import random
import sys
from collections import Counter
from datetime import date, datetime, timedelta

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ORIG_DIR = os.path.join(BASE_DIR, "data", "dianshuang")
OUT_DIR = os.path.join(BASE_DIR, "data", "new-dianshuang")

# ---------- 可调参数 ----------
BATCH_TAG = "SIM-LIVE"          # 批次标记前缀，写进每一行的「数据批次」列
DEFAULT_DAYS = 90               # 覆盖天数
DEFAULT_ROWS = 2000             # 总行数
DEFAULT_SEED = 20261015         # 固定种子，保证可复现
DEFAULT_END = "2026-10-15"      # 窗口结束日（= 数据快照日）

NEW_USER_ROWS = 500             # 其中属于「新客首单」的行数，其余复用原始用户
NEW_USER_MEAN_ORDERS = 2.8      # 新客人均订单数（几何分布，模拟首单后复购）

# 平台：行数占比 + 价格系数（对齐 data/dianshuang/数据集详情.md 的平台定位）
PLATFORMS = {
    "淘宝":   (0.30, 1.00),   # 综合 C2C，标准价
    "天猫":   (0.22, 1.05),   # 高端 B2C，高 5%
    "京东":   (0.20, 1.02),   # 自营品质，高 2%
    "拼多多": (0.18, 0.85),   # 社交拼团，低 15%
    "苏宁易购": (0.05, 1.00),
    "1688":  (0.05, 1.00),
}

# 品类倾向（按平台定位设定的模拟值，非实测）
CATEGORY_WEIGHTS = {
    "default": {"服装": 0.22, "电子产品": 0.15, "美妆": 0.15, "家居": 0.14,
                "书籍": 0.12, "运动": 0.11, "玩具": 0.11},
    "苏宁易购": {"电子产品": 0.45, "家居": 0.20, "服装": 0.10, "运动": 0.10,
              "书籍": 0.05, "美妆": 0.05, "玩具": 0.05},
    "1688":   {"家居": 0.25, "电子产品": 0.25, "服装": 0.15, "运动": 0.10,
               "玩具": 0.10, "书籍": 0.08, "美妆": 0.07},
    "拼多多": {"服装": 0.28, "玩具": 0.18, "美妆": 0.16, "家居": 0.12,
              "书籍": 0.10, "运动": 0.09, "电子产品": 0.07},
}

# 下单时段权重（0-23 点）：双峰，午间小峰 + 晚间主峰
HOUR_WEIGHTS = [0.6, 0.3, 0.15, 0.1, 0.1, 0.15, 0.4, 0.8, 1.2, 1.5, 1.8, 2.0,
                2.4, 2.2, 1.9, 2.0, 2.1, 2.3, 2.6, 3.0, 3.4, 3.6, 3.0, 1.8]

# 星期权重（Mon=0）
WEEKDAY_WEIGHTS = [1.0, 1.0, 1.05, 1.05, 1.15, 1.25, 1.20]

# 大促日系数（日期固定可考：99 大促是平台营销惯例日，国庆假期是法定日期）
PROMO_DAYS = {
    date(2026, 9, 9): 3.5,      # 99 大促
}
PROMO_RANGES = [
    (date(2026, 10, 1), date(2026, 10, 7), 2.2),   # 国庆假期
]

QUANTITY_WEIGHTS = {1: 0.45, 2: 0.28, 3: 0.15, 4: 0.07, 5: 0.05}

COLUMN_ORDER = ["用户ID", "用户姓名", "商品ID", "商品名称", "商品类别", "单价",
                "购买时间", "购买数量", "消费金额", "用户城市", "用户性别",
                "用户年龄"]
EXTRA_COLUMN = "数据批次"


def weighted_choice(rng: random.Random, weights: dict):
    """按权重抽一个 key（自己实现，避免依赖第三方）"""
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


# ==================== 1. 读取原始数据（只读） ====================

def load_original() -> tuple[pd.DataFrame, dict, dict]:
    """
    只读原始 CSV，抽出三样东西：
        users   用户ID -> (姓名, 性别, 年龄, 城市, 历史订单数)
        catalog (类别, 商品名) -> (商品ID, 基准单价)
        raw     合并后的交易表（仅用于统计与校验，不外传）
    """
    files = sorted(glob.glob(os.path.join(ORIG_DIR, "*.csv")))
    if not files:
        raise SystemExit(f"[中止] 找不到原始数据: {ORIG_DIR}")

    frames = []
    for f in files:
        df = pd.read_csv(f, encoding="utf-8-sig")
        df["_platform"] = os.path.splitext(os.path.basename(f))[0]
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    raw["用户ID"] = raw["用户ID"].astype(str)

    # 用户属性 + 历史订单数（复购倾向的依据）
    agg = raw.groupby("用户ID").agg(
        name=("用户姓名", "first"), gender=("用户性别", "first"),
        age=("用户年龄", "first"), city=("用户城市", "first"),
        orders=("商品ID", "size"),
    )
    # ⚠ 必须用 r["name"] 而不是 r.name：Series.name 是**索引标签**（这里就是 user_id），
    # 不是名为 name 的那一列。写错的话用户姓名会整列变成用户 ID——
    # 而且不会报错，只能靠肉眼或自检发现（本项目已踩过一次）。
    users = {
        uid: {"name": r["name"], "gender": r["gender"], "age": int(r["age"]),
              "city": r["city"], "orders": int(r["orders"])}
        for uid, r in agg.iterrows()
    }

    # 商品目录：只需要 (类别, 商品名, 商品ID)——价格不在商品上，见下
    standard = raw[raw["_platform"] == "淘宝"]
    catalog, seen = [], set()
    for _, r in standard.iterrows():
        key = (r["商品类别"], r["商品名称"])
        if key not in seen:
            seen.add(key)
            catalog.append((r["商品类别"], r["商品名称"], r["商品ID"]))

    # 价格模型：原始数据是「逐笔在类别区间内均匀抽样 × 平台系数」，**不是固定 SKU 价**。
    # 实测依据（2026-10-15）：
    #   1. 同一商品名在同一平台内，各笔订单的单价两两不同（淘宝 1000 笔 = 1000 个唯一价）
    #   2. 各商品的价格中位数都贴着类别中位数（服装各商品 400~570，而类别区间 20~1008）
    # 所以按类别区间均匀抽样，区间取淘宝（标准价）的实测 min/max。
    price_range = {
        cat: (float(g["单价"].min()), float(g["单价"].max()))
        for cat, g in standard.groupby("商品类别")
    }

    return users, catalog, price_range, raw


def report_pricing(raw: pd.DataFrame, price_range: dict) -> None:
    """
    报告定价模型：类别基准区间 + 平台系数（文档声称 vs 实测）

    只为透明，不阻断生成。实测结论：文档的平台价格策略在**中位数层面成立**，
    在**单笔层面不成立**——同一商品在各平台的价格是各自独立抽样的，
    拿单笔去比会得出「天猫 96 元、苏宁 994 元」这种没有意义的结论。
    """
    print("\n[定价] 类别基准区间（取自淘宝）")
    for cat, (lo, hi) in sorted(price_range.items()):
        print(f"    {cat:<6} {lo:>9.2f} ~ {hi:>9.2f}")

    piv = raw.pivot_table(index=["商品类别", "商品名称"], columns="_platform",
                          values="单价", aggfunc="median")
    if "淘宝" not in piv:
        return
    base = piv["淘宝"]
    print("\n[定价] 平台系数：文档声称 vs 实测中位数比值")
    for plat, (_, mult) in PLATFORMS.items():
        if plat not in piv:
            continue
        got = (piv[plat] / base).dropna().median()
        flag = "一致" if abs(got - mult) <= 0.05 else "偏差较大"
        print(f"    {plat:<8} 文档 {mult:.2f}  实测 {got:>5.2f}  -> {flag}")
    print("    注：京东实测约 1.09 与文档 1.02 有偏差，本生成器按文档取值")


# ==================== 2. 用户：复用老客 + 分配新客 ID ====================

def build_users(rng: random.Random, users: dict, n_rows: int) -> list[str]:
    """
    决定 2000 行分别属于谁

    老客（n_rows - NEW_USER_ROWS 行）：按「历史订单数 ^ 0.5」加权抽样，
        让老客户更容易复购——这比平均抽样真实，也更能压出会员等级跨档的场景。
    新客（NEW_USER_ROWS 行）：从 U1000~U9999 里**未被占用的 ID** 分配。

    为什么新客也放在 U1000~U9999 区间：该区间是数据集的文档化 ID 域，
    FT-01（「U99999 是什么用户」）的期望答案正是「ID 不在 U1000-U9999 范围」。
    新客若用区间外 ID，会把那条既有用例的期望打破。
    """
    existing = list(users)
    weights = [max(users[u]["orders"], 1) ** 0.5 for u in existing]

    n_existing = n_rows - NEW_USER_ROWS
    picked = rng.choices(existing, weights=weights, k=n_existing)

    # 新客：先按几何分布定每人几单，再摊到 NEW_USER_ROWS 行
    used = set(existing)
    free_ids = [f"U{i}" for i in range(1000, 10000) if f"U{i}" not in used]
    rng.shuffle(free_ids)

    new_rows: list[str] = []
    idx = 0
    p = 1.0 / NEW_USER_MEAN_ORDERS
    while len(new_rows) < NEW_USER_ROWS and idx < len(free_ids):
        k = 1
        while rng.random() < 1 - p and k < 6:
            k += 1
        k = min(k, NEW_USER_ROWS - len(new_rows))
        new_rows.extend([free_ids[idx]] * k)
        idx += 1

    rng.shuffle(new_rows)
    all_rows = picked + new_rows
    rng.shuffle(all_rows)
    return all_rows


def make_new_user_attrs(rng: random.Random, users: dict) -> dict:
    """给新客编属性：姓氏/名字/城市/年龄分布都从原始数据里学"""
    return {
        "surname_w": dict(Counter(u["name"][0] for u in users.values())),
        "given_w": dict(Counter(u["name"][1:] for u in users.values())),
        "city_w": dict(Counter(u["city"] for u in users.values())),
        "age_pool": [u["age"] for u in users.values()],
        "rng": rng,
    }


def new_user_profile(pools: dict) -> dict:
    rng = pools["rng"]
    return {
        "name": weighted_choice(rng, pools["surname_w"]) + weighted_choice(rng, pools["given_w"]),
        "gender": rng.choice(["男", "女"]),
        "age": rng.choice(pools["age_pool"]),
        "city": weighted_choice(rng, pools["city_w"]),
    }


# ==================== 3. 时间：时段 + 周末 + 大促 ====================

def build_timestamps(rng: random.Random, n: int, end: date, days: int) -> list[datetime]:
    """按天分配行数，再在天内按小时权重抽时刻"""
    start = end - timedelta(days=days - 1)
    day_list = [start + timedelta(days=i) for i in range(days)]

    weights = []
    for d in day_list:
        w = WEEKDAY_WEIGHTS[d.weekday()] * rng.uniform(0.85, 1.15)
        if d in PROMO_DAYS:
            w *= PROMO_DAYS[d]
        for a, b, mult in PROMO_RANGES:
            if a <= d <= b:
                w *= mult
        weights.append(w)

    total_w = sum(weights)
    exact = [w / total_w * n for w in weights]
    counts = [int(x) for x in exact]
    # 余数按小数部分从大到小补齐，保证总数严格等于 n
    rest = n - sum(counts)
    order = sorted(range(days), key=lambda i: exact[i] - counts[i], reverse=True)
    for i in order[:rest]:
        counts[i] += 1

    stamps = []
    for d, c in zip(day_list, counts):
        for h in rng.choices(range(24), weights=HOUR_WEIGHTS, k=c):
            stamps.append(datetime(d.year, d.month, d.day, h,
                                   rng.randrange(60), rng.randrange(60)))
    stamps.sort()
    rng.shuffle(stamps)   # 打散后再按平台分片，避免「早时段全归淘宝」这类伪相关
    return stamps


# ==================== 4. 组装订单 ====================

def build_records(args) -> tuple[dict, dict]:
    rng = random.Random(args.seed)
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    users, catalog, price_range, raw = load_original()
    report_pricing(raw, price_range)

    by_category: dict[str, list] = {}
    for cat, pname, pid in catalog:
        by_category.setdefault(cat, []).append((pname, pid))

    # 平台行数：按占比分配，余数补给占比最大的平台，保证总数精确
    raw_counts = {p: args.rows * w for p, (w, _) in PLATFORMS.items()}
    counts = {p: int(v) for p, v in raw_counts.items()}
    diff = args.rows - sum(counts.values())
    if diff:
        top = max(raw_counts, key=lambda p: raw_counts[p] - counts[p])
        counts[top] += diff

    owner = build_users(rng, users, args.rows)
    stamps = build_timestamps(rng, args.rows, end, args.days)
    platform_seq = [p for p, c in counts.items() for _ in range(c)]
    rng.shuffle(platform_seq)

    pools = make_new_user_attrs(rng, users)
    new_cache: dict[str, dict] = {}
    batch = f"{BATCH_TAG}-{end - timedelta(days=args.days - 1):%Y%m%d}-{end:%Y%m%d}"

    records = []
    for uid, plat, ts in zip(owner, platform_seq, stamps):
        if uid in users:
            attr = users[uid]
        else:
            if uid not in new_cache:
                new_cache[uid] = new_user_profile(pools)
            attr = new_cache[uid]

        cat = weighted_choice(rng, CATEGORY_WEIGHTS.get(plat, CATEGORY_WEIGHTS["default"]))
        pname, pid = rng.choice(by_category[cat])
        lo, hi = price_range[cat]
        price = round(rng.uniform(lo, hi) * PLATFORMS[plat][1], 2)
        qty = weighted_choice(rng, QUANTITY_WEIGHTS)

        records.append({
            "平台": plat,
            "用户ID": uid, "用户姓名": attr["name"], "商品ID": pid,
            "商品名称": pname, "商品类别": cat, "单价": price,
            "购买时间": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "购买数量": qty, "消费金额": round(price * qty, 2),
            "用户城市": attr["city"], "用户性别": attr["gender"],
            "用户年龄": attr["age"], EXTRA_COLUMN: batch,
        })

    stats = {
        "batch": batch,
        "rows": len(records),
        "days": args.days,
        "start": (end - timedelta(days=args.days - 1)).isoformat(),
        "end": end.isoformat(),
        "seed": args.seed,
        "platforms": counts,
        "users_total": len({r["用户ID"] for r in records}),
        "users_existing": len({r["用户ID"] for r in records if r["用户ID"] in users}),
        "users_new": len({r["用户ID"] for r in records if r["用户ID"] not in users}),
        "new_user_ids": sorted({r["用户ID"] for r in records if r["用户ID"] not in users})[:12],
        "categories": dict(Counter(r["商品类别"] for r in records)),
    }
    return records, stats, raw


# ==================== 5. 落盘 ====================

def write_files(records: list[dict], stats: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for plat in PLATFORMS:
        sub = [r for r in records if r["平台"] == plat]
        sub.sort(key=lambda r: r["购买时间"])
        df = pd.DataFrame(sub)[COLUMN_ORDER + [EXTRA_COLUMN]]
        path = os.path.join(OUT_DIR, f"{plat}.csv")
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"[写出] {plat}.csv  {len(df)} 行")

    with open(os.path.join(OUT_DIR, "batch_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def verify(records: list[dict], stats: dict, raw: pd.DataFrame) -> bool:
    ok = True
    print("\n=== 自检 ===")

    def check(label, cond, extra=""):
        nonlocal ok
        ok = ok and cond
        print(f"[{'OK' if cond else 'FAIL'}] {label}{extra}")

    check("总行数 == 2000", len(records) == 2000, f"（实际 {len(records)}）")
    check("平台行数与预算一致",
          all(sum(1 for r in records if r["平台"] == p) == c for p, c in stats["platforms"].items()),
          f"（{stats['platforms']}）")
    bad_amt = [r for r in records if abs(r["消费金额"] - r["单价"] * r["购买数量"]) > 0.011]
    check("消费金额 == 单价 × 数量", not bad_amt, f"（异常 {len(bad_amt)} 行）")

    ids = {r["用户ID"] for r in records}
    check("用户 ID 全落在 U1000~U9999", all(1000 <= int(u[1:]) <= 9999 for u in ids))

    orig_ids = set(raw["用户ID"].astype(str))
    check("新客 ID 与原始用户无重叠",
          not ({u for u in ids if u not in orig_ids} & orig_ids))
    check("时间窗在 90 天内",
          min(r["购买时间"] for r in records) >= stats["start"]
          and max(r["购买时间"] for r in records)[:10] <= stats["end"],
          f"（{min(r['购买时间'] for r in records)} ~ {max(r['购买时间'] for r in records)}）")

    # 属性一致性：老客的姓名/城市/年龄必须与原始完全一致。
    # 这条是为了兜住「取属性时取错列」这类错误——它不报错，只会静默产出脏数据。
    orig_attr = raw.groupby("用户ID").agg(
        n=("用户姓名", "first"), c=("用户城市", "first"), a=("用户年龄", "first")
    )
    om = {u: (r["n"], r["c"], int(r["a"])) for u, r in orig_attr.iterrows()}
    bad_attr = [r for r in records if r["用户ID"] in om
                and (r["用户姓名"], r["用户城市"], r["用户年龄"]) != om[r["用户ID"]]]
    check("老客属性与原始一致（姓名/城市/年龄）", not bad_attr, f"（不一致 {len(bad_attr)} 行）")
    check("用户姓名不等于用户ID（防取错列）",
          all(r["用户姓名"] != r["用户ID"] for r in records))
    dup_name = [r for r in records if r["用户姓名"].startswith("U") and len(r["用户姓名"]) <= 6]
    check("无「U+数字」形式的假姓名", not dup_name, f"（{len(dup_name)} 行）")

    print(f"\n[用户] 触及 {stats['users_total']} 人"
          f"（老客 {stats['users_existing']} + 新客 {stats['users_new']}）"
          f"，占原始 8110 人的 {stats['users_total'] / 8110 * 100:.1f}%")
    print(f"[品类] {stats['categories']}")
    print(f"[批次] {stats['batch']}")

    # 价格分布一致性：新老数据同源才能合并，否则客单价的变化分不清是更新逻辑还是定价口径
    print("\n[价格] 类别单价中位数：原始 vs 本批（偏差 >25% 视为异常）")
    gen = pd.DataFrame(records)
    for cat, g in gen.groupby("商品类别"):
        o_med = float(raw.loc[raw["商品类别"] == cat, "单价"].median())
        g_med = float(g["单价"].median())
        dev = abs(g_med - o_med) / o_med * 100
        check(f"  {cat} 中位数偏差 {dev:.1f}%（原始 {o_med:.0f} / 本批 {g_med:.0f}）", dev <= 25)
    return ok


def write_readme(stats: dict) -> None:
    day_rows = stats["rows"] / stats["days"]
    plat_rows = "\n".join(
        f"| {p} | {c} | {PLATFORMS[p][1]:.2f} | {c / stats['rows'] * 100:.0f}% |"
        for p, c in stats["platforms"].items()
    )
    readme = f"""# 近 90 天模拟实时订单（`new-dianshuang`）

> ⚠️ **这是模拟数据，不是生产数据，也不是原始数据。**
> 由 `src/rag_demo/tools/gen_live_orders.py` 生成，固定随机种子 `{stats['seed']}`，可完全复现。
> 每行都带 `数据批次` 列（值 `{stats['batch']}`），被复制到任何地方都能认出是模拟数据。

## 一、与原始数据的隔离（四条硬约束）

1. **原始数据零改动** —— 生成器对 `data/dianshuang/` 只做 `read_csv`，不写不改不移动
2. **独立目录** —— 本目录与 `data/dianshuang/` 同名文件互不覆盖；`ingest_data.DATA_DIR`
   指向原目录时，**绝不会**读到这批数据
3. **行内标记** —— `数据批次` 列是每行的显式标记，不依赖文件名或目录
4. **不写数据库** —— 生成器不连 PG；`user_profile_vectors` 里的 8110 条画像基线不受影响。
   要用这批数据做入库实验，必须由你显式执行，且建议先备份画像表

## 二、这批数据是什么

| 项 | 值 |
|---|---|
| 时间窗 | `{stats['start']}` ~ `{stats['end']}`（{stats['days']} 天） |
| 快照日 | `{stats['end']}`（= 窗口最后一天） |
| 总行数 | {stats['rows']} 行（约 {day_rows:.1f} 行/天） |
| 触及用户 | {stats['users_total']} 人（老客 {stats['users_existing']} + 新客 {stats['users_new']}），占原始 8110 人的 {stats['users_total'] / 8110 * 100:.1f}% |
| 商品目录 | 复用原始 49 个 SKU（7 大类 × 7 商品），商品 ID 与原始一致 |
| 定价模型 | 逐笔在类别区间内均匀抽样 × 平台系数（与原始数据同模型，见下） |
| 新增列 | `数据批次` |

### 文件清单

| 平台 | 行数 | 价格系数 | 占比 |
|---|---:|---:|---:|
{plat_rows}

价格系数对齐 `data/dianshuang/数据集详情.md` 的平台定位（天猫 +5% / 京东 +2% /
拼多多 -15% / 其余标准价）。

### 定价模型：为什么不是"一个 SKU 一个价"

实测原始数据（2026-10-15）：

- **同一商品名、同一平台内，各笔订单的单价两两不同**——淘宝 1000 笔订单 = 1000 个唯一单价
- **各商品的价格中位数都贴着类别中位数**——服装各商品中位数 400~570，而类别区间是 20~1008

两条合起来说明：原始数据的定价不是"固定 SKU 价"，而是
**「先选类别 → 在类别价格区间内均匀抽一个数 → 乘平台系数」**。
本批次沿用同一模型（区间取淘宝实测 min/max），这样新老数据的客单价分布同源，
合并后不会因为定价口径不同而失真。

另外：文档里的平台价格策略只在**中位数层面**成立，单笔层面不成立——
同一商品在各平台的价格是各自独立抽样的，拿单笔对照会得出
「T恤 天猫 96 元、苏宁 994 元」这种没有意义的结论。实测中位数比值：
天猫 1.06（文档 1.05）、拼多多 0.86（0.85）、苏宁 0.96（1.00）、1688 1.02（1.00）一致；
**京东 1.09 与文档 1.02 有偏差**，本生成器按文档取值。

### 为什么只触及 {stats['users_total']} 人

{stats['rows']} 行分散在 {stats['users_total']} 个用户上，**其余约 {8110 - stats['users_total']} 个用户没有任何新订单**。
这是刻意的：增量更新的核心问题正是"哪些画像需要重算"，如果所有用户都被触及，
就测不出"未被触及的画像是否被误改"。

## 三、字段说明

沿用原始 12 列：

`用户ID, 用户姓名, 商品ID, 商品名称, 商品类别, 单价, 购买时间, 购买数量, 消费金额, 用户城市, 用户性别, 用户年龄`

外加 1 列标记：

- `数据批次`：`{stats['batch']}`，常量。用途见第一节第 3 条。

约束：`消费金额 = 单价 × 购买数量`（严格成立，与原始数据一致）；
用户 ID 全落在 `U1000~U9999`（与原始域一致，不会打破 FT-01 那条「U99999 不在范围内」的用例期望）。

## 四、怎么用它（强烈建议先只读验证）

**方式 A：只做只读核对，不入库**（推荐第一步）

```bash
# 把 DATA_DIR 临时指过来跑一遍聚合，看看画像会变成什么样（不写库）
# 注意：ingest_data 当前会 TRUNCATE 再写入，直接跑会覆盖画像基线，见下一条
```

**方式 B：入库实验（会改画像表，先备份）**

```bash
# 1) 备份现有画像表
docker exec -i <pg容器> pg_dump -U postgres -d vec_db -t user_profile_vectors > backup_profiles.sql

# 2) 把 config.DATA_DIR 指向 data/new-dianshuang（或按需改 ingest 支持多目录）
# 3) 重新聚合入库
uv run python src/rag_demo/ingest_data.py

# 4) 重建检索索引（画像文本变了，不重建会静默用旧索引）
uv run python src/rag_demo/tools/build_search_index.py
```

⚠️ **`ingest_data.py` 目前是 `TRUNCATE` + 全量重写**，不是增量。直接把本目录指过去，
得到的是"只看新数据的画像"，而不是"原始 + 新增"的合并画像。要做真正的增量，见第六节。

## 五、已知局限（别当成真实业务数据）

1. **时间不连续** —— 原始数据到 2024-12-30 为止，这批是 {stats['start']} 起，
   中间有约 1.7 年的空档。这是两份数据各自的时间窗决定的，本批没有补齐 2025 年
2. **规模偏小** —— 约 {day_rows:.1f} 行/天，是演示量级，不是真实平台体量
3. **品类倾向是设定的**，不是从真实业务里学到的
4. **大促系数是拍的**（99 大促 ×3.5、国庆 ×2.2），只为制造可观测的峰值
5. **用户属性不随时间变化** —— 真实业务里年龄会变、城市会迁，这里复用原始属性

## 六、企业每时每刻都有订单时，数据更新该怎么做

核心难点不是"怎么存订单"，而是 **"订单表是流水，画像是聚合结果，两者更新频率差了几个数量级"**。
订单每秒都在来，画像不可能每秒重算 8110 个用户。实战做法分四层：

### 6.1 落地层：订单进仓，先做"流水"

- 线上订单通过 **CDC（Debezium / Canal 抓 binlog）** 或业务方双写进入数仓，
  按 `订单ID` 幂等（`INSERT ... ON CONFLICT (order_id) DO NOTHING`）——
  消息重投是常态，幂等是底线
- 落地表只追加（append-only），**不做更新**。订单是事实，事实不该被改
- 分区按 `购买时间` 日分区，便于按窗口裁剪扫描

### 6.2 聚合层：画像不是"重算全量"，是"只重算被触及的用户"

这是本批数据想让你验证的关键点：

```sql
-- 1) 找出被新订单触及的用户（2000 行只会命中约 1000+ 个用户，不是全部 8110）
CREATE TEMP TABLE touched AS
SELECT DISTINCT 用户ID FROM new_orders_batch;

-- 2) 只对这些用户重算画像，其余画像原样不动
--    关键：聚合必须基于「全量历史 + 新增」，不是只看新增——
--    否则 order_count 会从 12 变成 2，avg_amount 也会错
```

推荐两种工程实现：

| 方案 | 做法 | 适用 |
|---|---|---|
| **增量聚合（推荐）** | 维护一张 `user_profile` 表，用 `UPSERT` 把新订单的影响累加进去：`order_count += n`、`total_amount += sum`，再按新值重算 `avg_amount` 与 `member_level` | 订单量大、要求分钟级新鲜度 |
| **分区重算** | 按 `user_id` 哈希分片，定时任务逐片重算该片的全量聚合 | 逻辑简单、易校验，分钟~小时级 |

### 6.3 画像字段的重算顺序（这里有坑）

`member_level` 是**推导字段**，不是独立事实。重算顺序必须是：

```
新订单 → order_count / total_amount 累加 → avg_amount 重算
       → member_level 重算（阈值比较）
       → profile_text 重新拼装 → 向量重算 → 检索索引重建
```

`profile_text` 里嵌着画像文本，**任何一个字段变了它就得重拼**，否则会出现
「结构化字段说钻石、文本里还写着黄金」——检索和 SQL 走两条路，答案会自相矛盾。
本仓库正好踩过同类的坑（`member_level` 曾经只入列、不入文本，检索层完全看不到）。

### 6.4 检索索引：这是最容易被漏掉的一环

本仓库的索引与源数据**没有自动失效机制**（P7 之后一致性由"显式重建"保证）。
所以每次画像更新后都必须：

```
画像入库 → build_search_index.py 重建（BM25 分词 + 稀疏权重落库）
        → /admin/clear-cache 清答案缓存
```

漏掉任一步，表现都是**"数据明明更新了，回答还是旧的"**——而且不报错、静默。

### 6.5 "现在"这个时点怎么办

`days_since_last_buy` 依赖快照日。企业环境里没有"快照日"概念，只有"当前时刻"，
所以要么：

- 存**绝对时间** `last_buy_at`，把"距今天数"放到查询期算（推荐，避免天级定时重算）
- 或每天凌晨重算一次 `days_since_last_buy`

本仓库现在存的是**相对天数** `days_since_last_buy`，绑定在快照日上——
这正是「最近30天」类问题答不准的结构性原因。
"""
    path = os.path.join(OUT_DIR, "README.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(readme)
    print(f"[写出] README.md")


def parse_args():
    p = argparse.ArgumentParser(description="生成近 N 天模拟实时订单")
    p.add_argument("--end", default=DEFAULT_END, help=f"窗口结束日，默认 {DEFAULT_END}")
    p.add_argument("--rows", type=int, default=DEFAULT_ROWS, help=f"总行数，默认 {DEFAULT_ROWS}")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"覆盖天数，默认 {DEFAULT_DAYS}")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"随机种子，默认 {DEFAULT_SEED}")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print(f"[生成] 窗口 {args.days} 天 / {args.rows} 行 / seed={args.seed} / 结束于 {args.end}")
    print(f"[只读] 原始数据: {ORIG_DIR}")
    print(f"[写出] 目标目录: {OUT_DIR}\n")

    records, stats, raw = build_records(args)
    write_files(records, stats)
    ok = verify(records, stats, raw)
    write_readme(stats)

    print(f"\n{'[全部通过]' if ok else '[有失败项，请检查]'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
