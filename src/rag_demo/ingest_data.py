#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : ingest_data.py
@Function: 多来源 CSV → 聚合画像样本 → 写入结构化字段 + 向量
           结构化字段供 Text2SQL 聚合使用，profile_text 供 RAG 检索使用

数据口径（2026-10-16 实测，必读）
--------------------------------
本数据集（`data/dianshuang`）的 `user_id` **不是用户实体键**：它逐行独立随机生成，
同一个 ID 在不同行、不同平台上的姓名 / 年龄 / 城市互不相同。实测证据：

  · 跨平台同名 ID 抽样 2000 个，四项属性全部冲突 —— 2000 / 2000（100%）
  · 平台内部重复 ID 同样 100% 冲突（天猫 52/52、1688 55/55、ecommerce_data 4441/4441）
  · `(用户ID, 用户姓名)` 组合数 = 21000 = 总行数（ID 不携带身份信息）
  · 每个 ID 的行数分布与「21000 次随机抽样落在 9000 个 ID 上」的理论分布几乎重合
    （实际 distinct 8110 vs 理论 8127；2049 vs 2036.4、2319 vs 2375.8 …）

因此本脚本聚合出的「8110 个用户」是**聚合样本**，不是 8110 个真实个体；
`order_count` / `avg_amount` / `top_category` 也都是样本口径（且 CSV 无订单号，
`order_count` 实为「购买记录行数」）。详见 README「数据口径」一节。
"""
import glob
import json
import logging
import os
from typing import Any, Callable

import pandas as pd
from langchain_core.documents import Document
from sentence_transformers import SentenceTransformer

from rag_demo.config import (
    DATA_DIR,
    DEFAULT_DATASET,
    DEVICE,
    DTYPE,
    MODEL_PATH,
    SEARCH_INDEX_TABLE,
)
from rag_demo.db.connection import (
    close_conn,
    get_conn,
    require_write_scope,
    writes_to,
)
from rag_demo.db.schema import ensure_base_tables
from rag_demo.splitter import DOC_TYPE_PROFILE, split

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ================= 配置区 =================
BATCH = 50

# 会员等级分档：**按本次构建的数据分布标定**，不再用写死的绝对金额。
#
# 这条演进线留着，免得又被「修」回去：
#   1. 最初是绝对金额（钻石 2000 / 黄金 1000 / 白银 500）→ 区分度崩了（钻石占 59%）
#   2. 改成按分位数标定，但把**当时那份数据的实测值**写成了常量
#      （14555 / 6680 / 2495 = 演示数据的 p95 / p80 / p50）
#   3. 常量搬到真实小店上就失效了：真实客单价中位 176 元，永远到不了 2495，
#      195 个用户全是「普通」——字段在、规则也在，等级却等于没生效（见 bug/10.17）
#   4. 现在每次构建按本批用户人均客单价的分位数分档：口径与第 2 步完全一致，
#      数据换了规则跟着走。演示数据上算出来仍≈原来那三个数（p95/p80/p50 不变）
#
# 生效前提（缺一不可，缺了就把整列留空并说明原因，不产出「看起来精确」的假结论）：
#   字段：金额列必须映射上（没有 avg_amount 就没有等级）
#   规则：本批用户数 ≥ MEMBER_LEVEL_MIN_USERS（几个人算分位数没有意义）
#
# 注：本表不跟 data/docs/tag_definitions.md 的客单标签（高客单 ≥1000）挂钩——
#     该口径对演示数据同样偏松（约 70% 用户满足），属另一个待处理的数据问题。
MEMBER_LEVEL_QUANTILES = [("钻石", 0.95), ("黄金", 0.80), ("白银", 0.50)]
MEMBER_LEVEL_MIN_USERS = 20

# 结构化字段 DDL（幂等，保留现有 8110 条数据，不 DROP 重建）
ALTER_SQL = """
ALTER TABLE user_profile_vectors
    ADD COLUMN IF NOT EXISTS age INT,
    ADD COLUMN IF NOT EXISTS gender VARCHAR(4),
    ADD COLUMN IF NOT EXISTS city VARCHAR(50),
    ADD COLUMN IF NOT EXISTS member_level VARCHAR(20),
    ADD COLUMN IF NOT EXISTS order_count INT,
    ADD COLUMN IF NOT EXISTS total_amount NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS avg_amount NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS top_category VARCHAR(50),
    ADD COLUMN IF NOT EXISTS days_since_last_buy INT,
    ADD COLUMN IF NOT EXISTS platforms VARCHAR(200)
"""

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_upv_age ON user_profile_vectors (age)",
    "CREATE INDEX IF NOT EXISTS idx_upv_city ON user_profile_vectors (city)",
    "CREATE INDEX IF NOT EXISTS idx_upv_gender ON user_profile_vectors (gender)",
    "CREATE INDEX IF NOT EXISTS idx_upv_member_level ON user_profile_vectors (member_level)",
    "CREATE INDEX IF NOT EXISTS idx_upv_top_category ON user_profile_vectors (top_category)",
    "CREATE INDEX IF NOT EXISTS idx_upv_avg_amount ON user_profile_vectors (avg_amount)",
    "CREATE INDEX IF NOT EXISTS idx_upv_total_amount ON user_profile_vectors (total_amount)",
]

COLUMN_MAP = {
    "用户ID": "user_id",
    "用户姓名": "user_name",
    "用户性别": "gender",
    "用户年龄": "age",
    "用户城市": "city",
    "商品ID": "product_id",
    "商品名称": "product_name",
    "商品类别": "category",
    "单价": "unit_price",
    "购买时间": "purchase_time",
    "购买数量": "quantity",
    "消费金额": "amount",
}

# 数据集说明书（data/dianshuang/数据集详情.md）登记的 6 个平台。
# 注意：用户上传时「文件名恰好叫天猫.csv」会被当作平台名——这是**有意保留**的，
# 因为那正是命中的情况；不命中就落到 UNKNOWN_PLATFORM，不会被误认。
#
# 为什么需要白名单：**文件名 ≠ 平台名**。目录里还有 `ecommerce_data.csv`，
# 它不在说明书登记的平台之列。实测（2026-10-16）：
#   · 与 6 个平台文件的行级重叠（用户ID+商品ID+购买时间）= 0 / 1000，
#     即它不是这些平台的合并或超集（不存在重复计数）
#   · 15000 行，占全量 21000 行的 71%；唯一商品 13802，而平台文件各约 994
#     （SKU 空间大一个量级），时间窗同为 2024 全年
# 此前按「文件名即平台」处理，它被当成第 7 个平台，并以
# 「活跃平台：ecommerce_data」写进了绝大多数画像文本——对用户是误导（它不是平台）。
# 未登记的来源统一记为 UNKNOWN_PLATFORM，原文件名只留在日志里以便追溯。
KNOWN_PLATFORMS = {"天猫", "淘宝", "京东", "拼多多", "苏宁易购", "1688"}
UNKNOWN_PLATFORM = "未标注来源"
# ==========================================


# 只有 user_id 是硬性必需：没有它就没有「一个用户」这个聚合单位，画像无从谈起。
# 其余字段全部可跳过（MVP 5.2「允许跳过不重要字段」），跳过的字段在画像文本里
# 整段不出现——见 build_profile_text。
REQUIRED_COLUMNS = ("user_id",)

# 进度回调：(已完成, 总数, 阶段说明)
ProgressFn = Callable[[int, int, str], None]

# 阶段回调：(阶段名, 该阶段的真实数量)
# 与 ProgressFn 分开的原因：ProgressFn 报的是「写入循环里的进度」，而清洗/聚合
# 这两步**没有可切分的循环**（一次读全部、一次聚合全部），只有「做完了、数量是多少」。
# 构建任务的进度条要覆盖它们，就必须能收到这个「阶段完成」的信号——
# 否则进度条会在最耗时的前两步上一直停在 0%，最后突然跳到一半。
PhaseFn = Callable[[str, dict], None]


def _present(value: Any) -> bool:
    """
    值是否「有内容」：不是 None、不是 NaN、不是空串

    画像文本要按片段拼装，每一段都得先问一句「这个字段到底有没有」。
    单独抽出来是因为 pandas 的缺失值有三种形态（None / NaN / NaT），
    每个片段各写一遍判断，迟早漏掉一种。
    """
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass  # 数组/列表之类 pd.isna 会报错，按「有内容」处理
    return str(value).strip() != ""


def _to_int(value: Any) -> int | None:
    """容错的整数转换：缺失或不可转换时返回 None，而不是抛异常中断整批"""
    try:
        if not _present(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    """容错的浮点转换（同上）"""
    try:
        if not _present(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def calibrate_member_levels(avg_amounts: pd.Series) -> list[tuple[str, float]] | None:
    """
    按本批用户的人均客单价分布算出分档阈值；前提不满足返回 None

    None 的含义是「**本次等级不生效**」，调用方据此把整列留空并解释原因。
    这和「算出来全是普通」是两件不同的事：前者诚实，后者是假装有结论。
    """
    values = pd.to_numeric(avg_amounts, errors="coerce").dropna()
    if len(values) < MEMBER_LEVEL_MIN_USERS:
        return None
    return [(name, float(values.quantile(q))) for name, q in MEMBER_LEVEL_QUANTILES]


def build_member_level(
    avg_amount: float | None, thresholds: list[tuple[str, float]] | None
) -> str | None:
    """按标定好的阈值判档；没有金额数据、或规则本次没生效时返回 None"""
    if thresholds is None or not _present(avg_amount):
        return None
    for name, threshold in thresholds:
        if avg_amount >= threshold:
            return name
    return "普通"


def _clean_level(value: Any) -> str | None:
    """
    用户自己给的等级值：去空白、限长

    限长不是洁癖：member_level 列是 VARCHAR(20)，用户列里偶尔混进备注或整段文字，
    超长会让 INSERT 在 **TRUNCATE 之后**才炸——那时表已经被清空了，代价太大。
    """
    if not _present(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > 20:
        logger.warning("会员等级值超长（%d 字），已截断：%r", len(text), text[:30])
        return text[:20]
    return text


def ensure_schema(cur: Any) -> None:
    """幂等补充结构化字段与聚合索引"""
    cur.execute(ALTER_SQL)
    for sql in INDEX_SQL:
        cur.execute(sql)
    logger.info("结构化字段与索引已就绪")


def build_profile_text(row: pd.Series) -> str:
    """
    生成画像摘要文本（RAG 检索用）

    注意：画像文本是 RAG 唯一的可见载体。任何结构化字段若只入列、不入文本，
    检索层就完全看不到它——此前 member_level 就是这样缺失的（见 bug/10.11 会员等级缺口）。
    故拼成「钻石会员」这类连续词，同时兼顾 BM25 分词与向量语义。

    M2 起每段都是**可选**的：用户在字段确认页跳过的字段，对应片段整段不出现，
    而不是留下「0岁，人，会员」这种残句——残句不只是难看，它会进入向量与 BM25，
    变成永远匹配不上的噪声。字段齐全时输出与改造前**逐字节一致**
    （由 search_index_meta 里的语料指纹比对保证，重构时用它做回归门禁）。
    """
    # 抬头：有姓名就带上，没有就只留 ID
    head = f"用户{row['user_id']}"
    head += f"（{row['user_name']}）：" if _present(row.get("user_name")) else "："

    # 人群属性段：{age}岁{gender}，{city}人，{member_level}会员。
    demo_bits = []
    if _present(row.get("age")):
        demo_bits.append(f"{row['age']}岁")
    if _present(row.get("gender")):
        demo_bits.append(f"{row['gender']}")
    demo_parts = ["".join(demo_bits)] if demo_bits else []
    if _present(row.get("city")):
        demo_parts.append(f"{row['city']}人")
    if _present(row.get("member_level")):
        # 等级名可能是用户自己给的（M2 第 5 块），本来就带「会员」二字时要防空拼：
        # 「普通会员」不该变成「普通会员会员」。演示数据的钻石/黄金不受影响。
        level = str(row["member_level"]).strip()
        demo_parts.append(level if level.endswith("会员") else f"{level}会员")
    demo = "，".join(demo_parts) + "。" if demo_parts else ""

    # 消费段：累计订单N笔，总消费X元，平均客单价Y元，偏好品类为Z。
    order_parts = []
    if _present(row.get("order_count")):
        order_parts.append(f"累计订单{row['order_count']}笔")
    if _present(row.get("total_amount")):
        order_parts.append(f"总消费{row['total_amount']:.0f}元")
    if _present(row.get("avg_amount")):
        order_parts.append(f"平均客单价{row['avg_amount']:.0f}元")
    if _present(row.get("top_category")):
        order_parts.append(f"偏好品类为{row['top_category']}")
    order = "，".join(order_parts) + "。" if order_parts else ""

    # 时间/来源段：最近一次购买在D，活跃平台：P。
    time_parts = []
    if _present(row.get("last_buy")):
        time_parts.append(f"最近一次购买在{row['last_buy'].strftime('%Y-%m-%d')}")
    if _present(row.get("platforms")):
        time_parts.append(f"活跃平台：{row['platforms']}")
    tail = "，".join(time_parts) + "。" if time_parts else ""

    return head + demo + order + tail


def column_map_from_confirmed(confirmed: dict[str, str | None]) -> dict[str, str]:
    """
    把「字段确认页」的选择反推成 ingest 用的列映射

    confirmed: {系统字段 key: 用户数据里的实际列名 或 None}
    返回     : {实际列名: 系统字段 key}

    方向很容易搞反，所以写下来：确认页是「字段 → 列」
    （一个字段选一列，用户看着自然），而 rename 需要「列 → 字段」。
    跳过的字段（值为 None）直接不参与映射。
    """
    return {col: key for key, col in confirmed.items() if col}


def load_transactions(
    csv_paths: list[str] | None = None,
    column_map: dict[str, str] | None = None,
    data_dir: str = DATA_DIR,
) -> pd.DataFrame:
    """
    读取并合并来源 CSV

    csv_paths : 显式文件列表（M2 用户上传后落盘的路径）；
                None = 扫 data_dir，即脚本用法，行为与改造前一致
    column_map: {原始列名: 规范列名}；None = 用写死的 COLUMN_MAP（现有数据集口径）。
                M2 由用户在字段确认页选出的映射反推而来，见 column_map_from_confirmed
    data_dir  : 仅在 csv_paths 为 None 时生效

    经 KNOWN_PLATFORMS 白名单识别平台名；未登记的文件统一记为 UNKNOWN_PLATFORM，
    原文件名只留在日志里——不能让文件名冒充平台名写进画像文本（原因见常量处注释）。

    编码固定按 utf-8-sig（带 BOM 的 UTF-8）读：M2 的上传接口在落盘时
    已把 GBK 等来源统一转成 UTF-8，所以这里不需要（也不应该）再猜编码。
    """
    if csv_paths is None:
        csv_files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
        logger.info("正在读取 %s 下的 CSV...", data_dir)
    else:
        csv_files = list(csv_paths)

    if not csv_files:
        raise ValueError("没有找到任何 CSV 文件")

    mapping = COLUMN_MAP if column_map is None else column_map

    frames = []
    unregistered: list[tuple[str, int]] = []
    for f in csv_files:
        stem = os.path.splitext(os.path.basename(f))[0]
        registered = stem in KNOWN_PLATFORMS
        platform = stem if registered else UNKNOWN_PLATFORM
        df = pd.read_csv(f, encoding="utf-8-sig")  # 注意 BOM
        df["platform"] = platform
        frames.append(df)
        if registered:
            logger.info("  [平台] %s: %d 条", stem, len(df))
        else:
            unregistered.append((stem, len(df)))
            logger.warning(
                "  [未登记来源] %s: %d 条 -> 记为「%s」（不在数据集说明书的平台清单内）",
                stem, len(df), UNKNOWN_PLATFORM,
            )

    if unregistered:
        logger.warning(
            "未登记来源共 %d 个文件 / %d 行，已统一记为「%s」。"
            "若其中确有需要参与画像的平台，请显式加进 KNOWN_PLATFORMS。",
            len(unregistered), sum(n for _, n in unregistered), UNKNOWN_PLATFORM,
        )

    df_all = pd.concat(frames, ignore_index=True)
    df_all = df_all.rename(columns=mapping)

    missing = [c for c in REQUIRED_COLUMNS if c not in df_all.columns]
    if missing:
        raise ValueError(
            "缺少必需的数据列：" + "、".join(missing)
            + "。请回到字段确认页，手动指定它对应的列。"
        )

    if "purchase_time" in df_all.columns:
        # errors="coerce"：个别脏时间只让那一行退化成 NaT，不该让整批导入直接抛异常。
        # 现有数据集的时间列是干净的，这一改动不影响它的输出。
        before_na = int(df_all["purchase_time"].isna().sum())
        df_all["purchase_time"] = pd.to_datetime(df_all["purchase_time"], errors="coerce")
        broken = int(df_all["purchase_time"].isna().sum()) - before_na
        if broken > 0:
            logger.warning("有 %d 行的时间无法解析，已忽略（这些行的画像里不会有购买时间信息）", broken)
    else:
        logger.warning("未指定「下单时间」字段：画像里不会有最近购买时间相关信息")

    logger.info("合并后共 %d 条交易记录", len(df_all))
    return df_all


def build_profiles(df_all: pd.DataFrame) -> pd.DataFrame:
    """
    按用户聚合出画像（含结构化字段）

    可选字段缺失时，对应的**键仍然产出、值为 None**——不能整个键不出现：
    splitter.split_profile_documents 是按 row["age"] 这样逐键取的（splitter.py L139-148），
    少一个键就是 KeyError。所以「跳过字段」的降级只发生在画像文本里，不发生在列结构上。
    """
    # 兜一次时间类型：build_profiles 现在是公开函数，调用方不一定经过 load_transactions
    # （那里已经把时间转成 datetime）。拿着字符串时间去算日期差会抛
    # AttributeError: 'str' object has no attribute 'date'，而且只在日志行里炸，很难查。
    if "purchase_time" in df_all.columns and not pd.api.types.is_datetime64_any_dtype(
        df_all["purchase_time"]
    ):
        df_all = df_all.copy()
        df_all["purchase_time"] = pd.to_datetime(df_all["purchase_time"], errors="coerce")

    cols = set(df_all.columns)
    has_time = "purchase_time" in cols
    has_amount = "amount" in cols
    has_category = "category" in cols
    # 用户映射了「会员等级」列 = 他愿意用自己的等级口径（M2 第 5 块）
    has_level = "member_level" in cols

    snapshot_date = None
    if has_time:
        snapshot_date = df_all["purchase_time"].max()
        if _present(snapshot_date):
            logger.info("数据快照日期（最后一次购买）: %s", snapshot_date.date())
        else:
            snapshot_date = None
            logger.warning("下单时间列里没有可用时间值，将跳过「最近购买」相关聚合")

    if not has_amount:
        # 有等级列时别说「没有会员等级」——那种情况等级照常有，缺的只是消费类结论
        logger.warning(
            "未指定「订单金额」字段：画像里不会有消费金额%s",
            "" if has_level else "与推导的会员等级",
        )
    if not has_category:
        logger.warning("未指定「商品类目」字段：画像里不会有偏好品类")

    def first(g: pd.DataFrame, col: str) -> Any:
        """取分组首行的某列；该列整体没被指定时返回 None"""
        return g[col].iloc[0] if col in cols else None

    def pick_level(g: pd.DataFrame) -> str | None:
        """
        取这一组（同一用户的多笔订单）里出现最多的等级值

        为什么取众数而不是首行：同一用户的明细可能跨等级（升级当天的订单还是旧等级），
        众数是「他大部分时间处在哪一档」，比随便取第一行稳。
        """
        if not has_level:
            return None
        vals = g["member_level"].dropna().astype(str).str.strip()
        vals = vals[vals != ""]
        return None if vals.empty else str(vals.mode().iloc[0])

    def agg_user(g: pd.DataFrame) -> pd.Series:
        last_buy = g["purchase_time"].max() if has_time else None
        row: dict[str, Any] = {
            "user_name": first(g, "user_name"),
            "gender": first(g, "gender"),
            "age": _to_int(first(g, "age")),
            "city": first(g, "city"),
            # 用户自己的等级原值；没映射这一列时是 None（键仍然产出，见函数开头说明）
            "member_level_raw": pick_level(g),
            "order_count": int(len(g)),
            "total_amount": _to_float(g["amount"].sum()) if has_amount else None,
            "avg_amount": _to_float(g["amount"].mean()) if has_amount else None,
            # 品类要按金额加权才知道「偏好」哪个，两者缺一就没法算
            "top_category": (
                g.groupby("category")["amount"].sum().idxmax()
                if (has_category and has_amount) else None
            ),
            "platforms": ",".join(sorted(g["platform"].unique())),
        }
        if _present(last_buy) and snapshot_date is not None:
            row["last_buy"] = last_buy
            row["days_since_last_buy"] = int((snapshot_date - last_buy).days)
        else:
            row["last_buy"] = None
            row["days_since_last_buy"] = None
        return pd.Series(row)

    profiles = (
        df_all.groupby("user_id", group_keys=False)
              .apply(agg_user, include_groups=False)
              .reset_index()
    )
    # ---------- 会员等级：用户自己的口径优先，没有才推导 ----------
    # 「把口径交给业务」：他店里的「黑卡」就是黑卡，系统不去猜一个相对位置。
    # 只有**没给等级列**时才回退到按本批分位数推导（那是上一块的做法）。
    if has_level:
        level_source = "user"
        given = profiles["member_level_raw"].map(_clean_level)
        profiles["member_level"] = given
        filled = int(given.notna().sum())
        logger.info("会员等级：使用用户自己那一列（%d/%d 个用户有值）", filled, len(profiles))
        if filled < len(profiles):
            # 缺值**不拿推导值去补**：一列里混两套等级名（黑卡 / 钻石）比留几个空更糟，
            # 检索和统计都没法解释「为什么他身上有两个名字」。
            logger.warning(
                "会员等级：%d 个用户在自己那列里没有值，这些用户不产出等级"
                "（不与推导值混用）",
                len(profiles) - filled,
            )
    else:
        thresholds = calibrate_member_levels(profiles["avg_amount"])
        if thresholds is None:
            # 说清「为什么这一列是空的」：要么没金额列，要么人太少。
            # 用户看到的画像里不会有等级片段，日志里必须有据可查。
            level_source = "none"
            logger.info(
                "会员等级本次不生效（没有等级列，需要金额列且至少 %d 个用户；本批 %d 个用户）",
                MEMBER_LEVEL_MIN_USERS, len(profiles),
            )
        else:
            level_source = "derived"
            logger.info(
                "会员等级分档阈值（未映射等级列，按本批 %d 个用户的人均客单价标定）：%s",
                len(profiles),
                "；".join(f"{name} ≥ {value:.2f}" for name, value in thresholds),
            )
        profiles["member_level"] = profiles["avg_amount"].apply(
            lambda v: build_member_level(v, thresholds)
        )
    # 用 attrs 带出「这一列是怎么来的」，不改函数签名（build_profiles 有别的调用方，
    # 返回元组会把它们全弄坏）。调用方按需取，取不到就当 unknown。
    profiles.attrs["member_level_source"] = level_source
    profiles["profile_text"] = profiles.apply(build_profile_text, axis=1)

    logger.info("共得到 %d 个用户画像", len(profiles))
    # 没有金额字段时 member_level 整列为空，这时打印 value_counts 只会得到
    # 「Series([], )」这种既没信息量又让人以为出错的输出，直接跳过。
    counts = profiles["member_level"].value_counts()
    if len(counts):
        logger.info("会员等级分布:\n%s", counts.to_string())
    return profiles


def write_to_db(
    documents: list[Document],
    model: SentenceTransformer,
    progress: ProgressFn | None = None,
) -> int:
    """
    向量化并写入 pgvector（含结构化字段）

    入参是切分产物 List[Document]：结构化字段都装在 metadata 里，
    所以这里不必再回查 DataFrame——一个 Document 就能取齐所有列。

    每批 commit 后回调一次 progress，构建任务的进度条据此推进。
    """
    if not documents:
        # 与 ingest_documents 同一原则：空输入不能走到 TRUNCATE，
        # 否则「用户上传的文件一行都没解析出来」会变成「原有画像被清空」。
        raise ValueError("没有可写入的用户画像")

    # 写操作守卫：函数体第一行就校验，不能等到 TRUNCATE 前面——
    # 这中间已经花了时间（模型加载、向量化），报错越晚越像「跑了一半崩了」。
    dataset = require_write_scope("write_to_db")

    conn = get_conn(dataset)
    cur = conn.cursor()

    # 先保证表存在，再 ALTER 加结构化字段。顺序不能反：ensure_schema 里全是
    # ALTER TABLE ... ADD COLUMN，表不存在时会直接报「relation does not exist」，
    # 而 M2 的 user 库是空的，第一次构建就会踩到。
    ensure_base_tables(cur)
    ensure_schema(cur)
    cur.execute("TRUNCATE user_profile_vectors RESTART IDENTITY;")
    conn.commit()

    logger.info("正在生成向量并写入...")
    for i in range(0, len(documents), BATCH):
        batch = documents[i:i + BATCH]
        vecs = model.encode(
            [d.page_content for d in batch], batch_size=16, show_progress_bar=False
        )
        for doc, v in zip(batch, vecs):
            m = doc.metadata
            cur.execute(
                """INSERT INTO user_profile_vectors
                   (user_id, profile_text, embedding, dept, sensitivity, metadata,
                    age, gender, city, member_level, order_count, total_amount,
                    avg_amount, top_category, days_since_last_buy, platforms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    m["user_id"],
                    doc.page_content,
                    v,
                    m["dept"],
                    m["sensitivity"],
                    json.dumps({
                        "platforms": m["platforms"],
                        "top_category": m["top_category"],
                    }, ensure_ascii=False),
                    m["age"],
                    m["gender"],
                    m["city"],
                    m["member_level"],
                    m["order_count"],
                    m["total_amount"],
                    m["avg_amount"],
                    m["top_category"],
                    m["days_since_last_buy"],
                    m["platforms"],
                )
            )
        conn.commit()
        done = min(i + BATCH, len(documents))
        logger.info("  已写入 %d/%d", done, len(documents))
        if progress:
            progress(done, len(documents), "写入画像")

    return len(documents)


def ingest_transactions(
    csv_paths: list[str] | None = None,
    column_map: dict[str, str] | None = None,
    model: SentenceTransformer | None = None,
    progress: ProgressFn | None = None,
    on_phase: PhaseFn | None = None,
) -> dict:
    """
    端到端：CSV → 清洗 → 聚合画像 → 切分 → 向量化 → 写入 user_profile_vectors

    **M2 的构建入口**（服务里调用）。与 main() 的唯一区别是数据来源：
    main() 就是「两个参数都不传」（扫固定的 data/dianshuang + 写死的 COLUMN_MAP），
    而服务路径两者都由调用方给——用户上传的路径 + 用户在字段确认页选出的映射。

    model 不传则自行加载（脚本/离线场景）；服务路径必须传检索侧单例，
    否则进程里会同时存在两份 bge-m3（config 已警示 fp32 双模型约 4.4GB，会 OOM）。

    progress: 写入画像的批进度（每 commit 一批回调一次）。
    on_phase: 清洗/聚合/切分三步的完成信号，带真实数量（见 PhaseFn 的注释）。

    这里同样**不关连接**，连接生命周期归调用方。

    ⚠ 会写库（链路末端是 TRUNCATE + 全量重写），因此**必须在 writes_to(...) 作用域内调用**。
    """
    # 早于模型加载就校验：加载 bge-m3 要几十秒、聚合画像也要时间，等这些都跑完
    # 才报「没声明写作用域」，用户看到的就是「跑了一半崩了」。
    require_write_scope("ingest_transactions")

    if model is None:
        logger.info("正在加载 bge-m3 模型（device=%s, dtype=%s）...", DEVICE, DTYPE)
        model = SentenceTransformer(
            str(MODEL_PATH), device=DEVICE, model_kwargs={"dtype": DTYPE}
        )

    df_all = load_transactions(csv_paths, column_map)
    if on_phase:
        # 只回报阶段与**真实数量**（行数/用户数），不回报时间预估——
        # 进度条最容易骗人的地方就是「按时间猜」，而这里的数量都是算出来的
        on_phase("load_done", {"rows": len(df_all)})
    profiles = build_profiles(df_all)
    if on_phase:
        on_phase("profile_done", {"profiles": len(profiles)})
    documents = split(DOC_TYPE_PROFILE, {"profiles": profiles})
    if on_phase:
        on_phase("split_done", {"documents": len(documents)})
    count = write_to_db(documents, model, progress)
    logger.info("成功导入 %d 条用户画像（含结构化字段）", count)
    return {
        "rows": len(df_all),
        "profiles": count,
        # 这一列是怎么来的：user（用户自己的等级列）/ derived（按本批分位推导）/ none
        "member_level_source": profiles.attrs.get("member_level_source", "unknown"),
    }


def verify(cur: Any) -> None:
    """验证结构化字段与检索链路"""
    logger.info("===== 结构化字段验证 =====")
    checks = [
        ("年龄 20-30 用户数", "SELECT COUNT(*) FROM user_profile_vectors WHERE age BETWEEN 20 AND 30"),
        ("美妆用户平均客单价", "SELECT ROUND(AVG(avg_amount), 2) FROM user_profile_vectors WHERE top_category = '美妆'"),
        ("Top5 城市分布", "SELECT city, COUNT(*) AS cnt FROM user_profile_vectors GROUP BY city ORDER BY cnt DESC LIMIT 5"),
        ("会员等级分布", "SELECT member_level, COUNT(*) AS cnt FROM user_profile_vectors GROUP BY member_level ORDER BY cnt DESC"),
    ]
    for label, sql in checks:
        cur.execute(sql)
        rows = cur.fetchall()
        if len(rows) == 1 and len(rows[0]) == 1:
            logger.info("  %s: %s", label, rows[0][0])
        else:
            logger.info("  %s: %s", label, rows)

    logger.info("===== 类型分布抽样 =====")
    cur.execute("""
        SELECT user_id, age, gender, city, member_level, order_count,
               ROUND(total_amount, 0), ROUND(avg_amount, 0), top_category,
               days_since_last_buy, platforms
        FROM user_profile_vectors ORDER BY id LIMIT 3
    """)
    for r in cur.fetchall():
        logger.info("  %s", r)


def main() -> None:
    """脚本入口：扫 data/dianshuang 全量重建（与改造前行为一致）"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    # 显式声明写作用域：脚本入口是「明确知道自己在写哪个库」的地方，在这里声明一次，
    # 下面的写入与校验查询就都落在同一个库上（作用域会**同时**设置当前数据集）。
    # 不声明则 write_to_db / ingest_transactions 的第一行就抛 UnsafeWriteError——
    # 「忘记声明」正是要防的那件事，所以宁可当场炸，也不替调用方猜。
    with writes_to(DEFAULT_DATASET):
        # 不传参数 = 沿用改造前的口径（DATA_DIR + COLUMN_MAP）
        ingest_transactions()

        cur = get_conn().cursor()
        verify(cur)
        cur.close()

    close_conn()
    logger.info("数据导入与结构化字段回填完成")

    # 画像文本变了，检索索引就过期了。索引与源数据的一致性现在由「显式重建」保证，
    # 不再有本地缓存那套自动失效机制——不重建就会静默用旧索引检索。
    logger.warning(
        "画像数据已更新，检索索引 %s 需要重建，否则检索将使用旧索引：\n"
        "    uv run python src/rag_demo/tools/build_search_index.py",
        SEARCH_INDEX_TABLE,
    )


if __name__ == "__main__":
    main()
