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
import psycopg2.errors
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
from rag_demo.db import schema_facts
from rag_demo.db.schema import ensure_base_tables
from rag_demo.splitter import DOC_TYPE_PROFILE, split

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ================= 配置区 =================
BATCH = 50

# 会员等级**不再由系统推导**（M3 第五轮，客户底线）。
#
# 历史演进别改回去：
#   M2 早期没映射等级列时，系统按本批用户人均客单价的分位数推导「钻石/黄金/…」。
#   对演示数据看着成立，但真实客户的数据口径不是「金额高=等级高」：
#   企业自己的黑卡/金卡可能有合同、渠道、人工评定等依据。系统凭空按金额分档，
#   等于替客户编了一套不存在的等级体系，还会污染检索与统计。
#
# 现在的规则（写死在 build_profiles 里）：
#   · 用户在字段确认页映射了等级列 → 用他给的值（user）；
#   · 没映射 → member_level 整列记为未知（None），level_source="none"，
#     **绝不按金额或其他字段推算**。
# 相关推算常量/函数（MEMBER_LEVEL_QUANTILES 等）已删除，不要再加回来。

# 结构化字段 DDL（幂等，保留现有 8110 条数据，不 DROP 重建）
ALTER_SQL = """
ALTER TABLE user_profile_vectors
    ADD COLUMN IF NOT EXISTS age INT,
    ADD COLUMN IF NOT EXISTS gender VARCHAR(16),
    ADD COLUMN IF NOT EXISTS city VARCHAR(64),
    ADD COLUMN IF NOT EXISTS member_level VARCHAR(32),
    ADD COLUMN IF NOT EXISTS order_count INT,
    ADD COLUMN IF NOT EXISTS total_amount NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS avg_amount NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS top_category VARCHAR(64),
    ADD COLUMN IF NOT EXISTS days_since_last_buy INT,
    ADD COLUMN IF NOT EXISTS platforms VARCHAR(200)
"""

# 文本列的长度上限（与上面的 DDL、db/schema.py 的建表语句保持一致）。
#
# 为什么不能只靠 DDL：真实数据不保证遵守长度——性别写成 "Female" / "未知/保密"、
# 城市写成完整地址、品类写成 "电脑办公/外设产品/键盘鼠标" 都可能出现。
# 超长值会在 INSERT 时炸在 **TRUNCATE 之后**（表已被清空，代价最大），而且报错是
# psycopg2 的英文「value too long for type character varying(4)」——用户看不懂、
# 也不知道该改哪一列（2026-10-18 真实测试者传入 99,457 行数据踩到的就是 gender 4）。
# 所以在聚合阶段就按上限截断并留日志，DDL 只作为最后一道保险。
TEXT_LIMITS: dict[str, int] = {
    "gender": 16,
    "city": 64,
    "member_level": 32,
    "top_category": 64,
}

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

# 平台识别：**文件名默认就是平台名，只排除明确不是平台的来源**。
#
# 为什么不再用白名单：
#   旧做法把「data/dianshuang/数据集详情.md 登记过哪 6 个平台」当成了系统规则。
#   用户上传「抖音.csv」「快手.csv」全落到「未标注来源」，而这个值还会写进画像文本。
#   实测 demo 库：8110 个画像里 **7277 个**的平台是「未标注来源」——
#   目录里的 `ecommerce_data.csv` 也在数据里，白名单之外的一切都被拒了。
#   那是「一份演示数据集的说明书」越权管了入库规则。
#
# 现在反过来：默认接受，个别排除。`ecommerce_data.csv` 是合并表，实测：
#   · 与 6 个平台文件的行级重叠（用户ID+商品ID+购买时间）= 0 / 1000
#   · 15000 行，占全量 21000 行的 71%；唯一商品 13802，而平台文件各约 994
# 把它当平台，会把「活跃平台：ecommerce_data」写进绝大多数画像，对用户是误导。
NON_PLATFORM_SOURCES = {"ecommerce_data"}
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


def _clip_text(value: Any, *, field: str, limit: int) -> str | None:
    """
    文本列清洗：去空白 + 按列宽上限截断（超长留 warning）

    截断而不是报错：一条超长的性别/城市/品类不该让整批构建在 **TRUNCATE 之后** 失败；
    也不能静默——日志里写清字段、原长度与保留的前缀，排查时能对上是哪条数据。
    """
    if not _present(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > limit:
        logger.warning(
            "%s 值超长（%d 字 > 上限 %d），已截断：%r",
            field, len(text), limit, text[:40],
        )
        return text[:limit]
    return text


def _clean_level(value: Any) -> str | None:
    """
    用户自己给的等级值：去空白、限长（列宽上限见 TEXT_LIMITS）

    限长不是洁癖：用户列里偶尔混进备注或整段文字，超长会让 INSERT 在
    **TRUNCATE 之后**才炸——那时表已经被清空了，代价太大。
    """
    return _clip_text(value, field="会员等级", limit=TEXT_LIMITS["member_level"])


def ensure_schema(cur: Any) -> None:
    """
    幂等补充结构化字段与聚合索引

    除了 ADD COLUMN，还要把**旧库的窄列扩宽**：M3 之前的 gender 是 VARCHAR(4)，
    真实数据里 "Female" / "未知/保密" 这类值会直接把构建打挂（同样炸在 TRUNCATE 之后）。
    扩容只在列宽不足时执行——ALTER TYPE 会重建该列上的索引，没必要每次构建都做。
    """
    cur.execute(ALTER_SQL)
    cur.execute(
        "SELECT column_name, character_maximum_length FROM information_schema.columns "
        "WHERE table_name = 'user_profile_vectors' AND column_name = ANY(%s)",
        (list(TEXT_LIMITS),),
    )
    current = {row[0]: row[1] for row in cur.fetchall()}
    widen = {
        name: limit for name, limit in TEXT_LIMITS.items()
        if current.get(name) is not None and current[name] < limit
    }
    if widen:
        clause = ", ".join(
            f"ALTER COLUMN {name} TYPE VARCHAR({limit})" for name, limit in widen.items()
        )
        cur.execute(f"ALTER TABLE user_profile_vectors {clause}")
        logger.info(
            "结构化字段列宽已扩容: %s",
            ", ".join(f"{name}->VARCHAR({limit})" for name, limit in widen.items()),
        )
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

    平台名取文件名，**默认接受、只排除明确不是平台的来源**（NON_PLATFORM_SOURCES）。
    不做白名单：那等于让一份演示数据集的说明书决定谁能入库（原因见常量处注释）。

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
    excluded: list[tuple[str, int]] = []
    for f in csv_files:
        stem = os.path.splitext(os.path.basename(f))[0]
        is_platform = stem not in NON_PLATFORM_SOURCES
        platform = stem if is_platform else UNKNOWN_PLATFORM
        df = pd.read_csv(f, encoding="utf-8-sig")  # 注意 BOM
        df["platform"] = platform
        frames.append(df)
        if is_platform:
            logger.info("  [平台] %s: %d 条", stem, len(df))
        else:
            excluded.append((stem, len(df)))
            logger.warning(
                "  [非平台来源] %s: %d 条 -> 记为「%s」（在 NON_PLATFORM_SOURCES 里）",
                stem, len(df), UNKNOWN_PLATFORM,
            )

    if excluded:
        logger.info(
            "非平台来源共 %d 个文件 / %d 行，已记为「%s」。"
            "若它其实是一个平台，把它从 NON_PLATFORM_SOURCES 移出即可。",
            len(excluded), sum(n for _, n in excluded), UNKNOWN_PLATFORM,
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
        # format="mixed"：逐行推断格式，而不是拿第一行的格式去套整列。
        # 真实导出里同一个文件常混着 "2026-01-03 12:00:00"、"2026/1/9"、"2026.2.5"，
        # 不带 mixed 时只有与首行格式一致的那几行能被解析，其余全变 NaT——
        # 表现就是「看着导入成功，其实大部分行的购买时间丢了」。
        before_na = int(df_all["purchase_time"].isna().sum())
        df_all["purchase_time"] = pd.to_datetime(
            df_all["purchase_time"], errors="coerce", format="mixed"
        )
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
        # 有等级列时别说「没有会员等级」——那种情况等级照常有，缺的只是消费类结论。
        # 注意：**不要再提「推导的会员等级」**——第五轮起系统不再按金额推算等级。
        logger.warning(
            "未指定「订单金额」字段：画像里不会有消费金额%s",
            "（会员等级用你自己的那一列，不受影响）" if has_level else "",
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
            "gender": _clip_text(first(g, "gender"), field="用户性别",
                                 limit=TEXT_LIMITS["gender"]),
            "age": _to_int(first(g, "age")),
            "city": _clip_text(first(g, "city"), field="用户城市",
                               limit=TEXT_LIMITS["city"]),
            # 用户自己的等级原值；没映射这一列时是 None（键仍然产出，见函数开头说明）
            "member_level_raw": pick_level(g),
            "order_count": int(len(g)),
            "total_amount": _to_float(g["amount"].sum()) if has_amount else None,
            "avg_amount": _to_float(g["amount"].mean()) if has_amount else None,
            # 品类要按金额加权才知道「偏好」哪个，两者缺一就没法算
            "top_category": _clip_text(
                (g.groupby("category")["amount"].sum().idxmax()
                 if (has_category and has_amount) else None),
                field="商品类目", limit=TEXT_LIMITS["top_category"],
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
    # ---------- 会员等级：用户自己的口径，**没有就是未知**（不再推导） ----------
    # 「把口径交给业务」：他店里的「黑卡」就是黑卡，系统不去猜一个相对位置。
    # 没映射等级列时**绝不**回退到按金额分档（M2 曾经的 derived 分支已删除）：
    # 金额高不代表等级高（合同/渠道/人工评定都可能影响），凭空造一套等级
    # 会让检索与统计给出看起来精确、实际不属于客户业务的结论。
    if has_level:
        level_source = "user"
        given = profiles["member_level_raw"].map(_clean_level)
        profiles["member_level"] = given
        filled = int(given.notna().sum())
        logger.info("会员等级：使用用户自己那一列（%d/%d 个用户有值）", filled, len(profiles))
        if filled < len(profiles):
            logger.warning(
                "会员等级：%d 个用户在自己那列里没有值，这些用户等级记为未知"
                "（不推导、不补值）",
                len(profiles) - filled,
            )
    else:
        level_source = "none"
        profiles["member_level"] = None
        logger.info(
            "会员等级：未映射等级列，该列记为未知，不按金额推算（企业口径）"
        )
    # 用 attrs 带出「这一列是怎么来的」，不改函数签名（build_profiles 有别的调用方，
    # 返回元组会把它们全弄坏）。调用方按需取，取不到就当 unknown。
    # 取值只有两种：user（用户映射的等级列）/ none（未提供，不推导）
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
    try:
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
                        # 数值列一律走容错转换：pandas 的缺失值是 NaN/NaT，
                        # 直接交给 psycopg2 会变成字符串 'NaN'，PostgreSQL 对 INT 列
                        # 报 "integer out of range"，一条 NaN 就能让整批构建失败
                        # （用户订单时间全都解析不出来时必然踩到）。
                        # 转成 None 后落库是 SQL NULL，下游按「未知」处理。
                        _to_int(m["age"]),
                        m["gender"],
                        m["city"],
                        m["member_level"],
                        _to_int(m["order_count"]),
                        _to_float(m["total_amount"]),
                        _to_float(m["avg_amount"]),
                        m["top_category"],
                        _to_int(m["days_since_last_buy"]),
                        m["platforms"],
                    )
                )
            conn.commit()
            done = min(i + BATCH, len(documents))
            logger.info("  已写入 %d/%d", done, len(documents))
            if progress:
                progress(done, len(documents), "写入画像")
    except psycopg2.errors.StringDataRightTruncation as e:
        # 兜底翻译：到了这一步说明有文本列没被 TEXT_LIMITS 覆盖（或用户直接调了本函数）。
        # 原始报错是英文「value too long for type character varying(N)」，用户既看不懂
        # 也不知道该改哪一列；这里给中文 + 下一步动作，并把原始错误带上便于排查。
        conn.rollback()
        raise ValueError(
            "写入画像失败：某个文本字段的值超过数据库列长度限制"
            "（常见是性别/城市/会员等级/品类；相关列宽会自动扩容，可直接重试构建）。"
            f"若仍失败，请检查数据里是否有异常长的文本。原始错误：{e}"
        ) from e

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
    # 画像变了，提示词里的条数 / 枚举 / 分位就都过期了。
    # 必须在这里显式失效：缓存 key 是「数据集」，条数不变但取值变了的情况
    # （重导同一批数据、只改清洗规则）光靠 TTL 是等不回来的。
    schema_facts.invalidate()
    logger.info("已失效表结构缓存（提示词下次会重新采集数据事实）")
    return {
        "rows": len(df_all),
        "profiles": count,
        # 这一列是怎么来的：user（用户映射的等级列）/ none（未提供，系统不推导）
        "member_level_source": profiles.attrs.get("member_level_source", "unknown"),
    }


# ==================== 增量合并（M3 第五轮：追加更新） ====================
# 背景：真实测试者 10 万行数据，追加一个文件要全量重跑约 2 小时。增量模式只处理
# **新上传的 CSV/MD**，并且只更新这些文件里出现的用户；其余用户一行都不动。
#
# 这一节拆成两层，理由与「为什么判定层要纯函数」相同：
#   merge_profile_row  纯函数——合并规则本身（一行用户 + 一批新订单），可脱库单测；
#   merge_incremental  DB 编排——读旧行、向量化、写回、进度回调。
# 合并规则一旦写错（例如把 total_amount 覆盖而不是相加），订单量不会报错，
# 只会安静地少算或多算——所以逐条规则都写进注释，并由 tests/test_incremental.py 锁住。

# 读旧画像行用到的列（与 user_profile_vectors 对齐，user_name 不在库里）
_EXISTING_PROFILE_COLS = (
    "user_id", "age", "gender", "city", "member_level", "order_count",
    "total_amount", "avg_amount", "top_category", "days_since_last_buy",
    "metadata", "profile_text",
)
_EXISTING_BATCH = 500

_INSERT_PROFILE_SQL = """INSERT INTO user_profile_vectors
    (user_id, profile_text, embedding, dept, sensitivity, metadata,
     age, gender, city, member_level, order_count, total_amount,
     avg_amount, top_category, days_since_last_buy, platforms)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""

_UPDATE_PROFILE_SQL = """UPDATE user_profile_vectors
    SET profile_text = %s, embedding = %s, dept = %s, sensitivity = %s, metadata = %s,
        age = %s, gender = %s, city = %s, member_level = %s, order_count = %s,
        total_amount = %s, avg_amount = %s, top_category = %s,
        days_since_last_buy = %s, platforms = %s, update_time = NOW()
    WHERE user_id = %s"""


def _first_present(*values: Any) -> Any:
    """取第一个「有内容」的值（没有则 None）——新值优先、旧值兜底，不猜不补"""
    for value in values:
        if _present(value):
            return value
    return None


def _sum_present(*values: Any) -> float | None:
    """把「有内容」的数值相加；全都缺失时返回 None（缺失≠0，不能当 0 累加）"""
    numbers = [float(v) for v in values if _present(v)]
    return sum(numbers) if numbers else None


def _min_present(*values: Any) -> int | None:
    """取「有内容」的整数最小值（天数类指标合并用）"""
    numbers = [int(v) for v in values if _present(v)]
    return min(numbers) if numbers else None


def _merge_platforms(old: Any, new: Any) -> str | None:
    """活跃平台取并集：旧画像里出现过的平台不会因为这次没出现就消失"""
    parts: list[str] = []
    for raw in (old, new):
        for item in str(raw or "").split(","):
            item = item.strip()
            if item and item not in parts:
                parts.append(item)
    return ",".join(sorted(parts)) or None


def merge_profile_row(old: dict | None, new: dict) -> dict:
    """
    纯函数：把一个用户的新聚合行合并进旧画像行（不碰数据库、不算向量）

    old: 库里的旧行（dict；None = 库里还没有这个用户）
    new: 本次新增 CSV 聚合出的一行（build_profiles 的输出记录）

    合并规则（客户底线，测试逐条断言）：
      order_count   = old + new          —— 订单数精确相加
      total_amount  = old + new          —— 总消费精确相加
      avg_amount    = total / order_count（count=0 → None，不产生 NaN）
      age/gender/city/member_level：**新文件有值用新值，否则保留旧值**（不猜、不推导）
      days_since_last_buy = min(old, new)——旧值基于更早的快照，取 min 是保守近似
                                            （真实最近一次购买只会更近，不会更远）
      top_category  ：新文件有值用新值（已在新文件内按金额加权）；否则保留旧值
                      —— 旧品类的金额已无法拆分，拿旧金额做「假加权」只会算错
      platforms     ：新旧取并集（老客户换平台消费，旧平台不应消失）
      user_name     ：同属性规则（新有值用新，否则保留；库里不存该列时通常为 None）
    """
    old = old or {}
    old_count = _to_int(old.get("order_count")) or 0
    new_count = _to_int(new.get("order_count")) or 0
    order_count = old_count + new_count

    total_amount = _sum_present(old.get("total_amount"), new.get("total_amount"))
    avg_amount = (
        round(total_amount / order_count, 2)
        if (total_amount is not None and order_count > 0)
        else None
    )

    return {
        "user_id": _first_present(new.get("user_id"), old.get("user_id")),
        "user_name": _first_present(new.get("user_name"), old.get("user_name")),
        "age": _first_present(new.get("age"), old.get("age")),
        "gender": _first_present(new.get("gender"), old.get("gender")),
        "city": _first_present(new.get("city"), old.get("city")),
        "member_level": _first_present(new.get("member_level"), old.get("member_level")),
        "order_count": order_count,
        "total_amount": total_amount,
        "avg_amount": avg_amount,
        "top_category": _first_present(new.get("top_category"), old.get("top_category")),
        "days_since_last_buy": _min_present(
            old.get("days_since_last_buy"), new.get("days_since_last_buy")
        ),
        "platforms": _merge_platforms(old.get("platforms"), new.get("platforms")),
    }


def _load_existing_profiles(cur: Any, user_ids: list[str]) -> dict[str, dict]:
    """
    按 user_id 分批读取旧画像行（只读本次受影响的用户）

    只读受影响用户而不是全表：增量更新的价值就在「10 万用户里只有几百个要动」，
    一次全表 SELECT 会把省下的时间又还回去。
    """
    existing: dict[str, dict] = {}
    ids = [str(uid) for uid in user_ids]
    for i in range(0, len(ids), _EXISTING_BATCH):
        chunk = ids[i:i + _EXISTING_BATCH]
        cur.execute(
            f"SELECT {', '.join(_EXISTING_PROFILE_COLS)} FROM user_profile_vectors "
            f"WHERE user_id = ANY(%s)",
            (chunk,),
        )
        for row in cur.fetchall():
            record = dict(zip(_EXISTING_PROFILE_COLS, row))
            meta = record.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (TypeError, ValueError):
                    meta = {}
            record["platforms"] = (meta or {}).get("platforms") if isinstance(meta, dict) else None
            existing[str(record["user_id"])] = record
    return existing


def merge_incremental(
    csv_paths: list[str],
    column_map: dict[str, str] | None,
    model: SentenceTransformer,
    progress: ProgressFn | None = None,
    on_phase: PhaseFn | None = None,
) -> dict:
    """
    增量合并：只把**新增 CSV** 的订单合并进已有画像，未出现的用户一行都不动

    参数与 ingest_transactions 对齐（progress/on_phase 语义相同）：
        progress(已完成, 总数, 说明) 每写一批 commit 后回调
        on_phase("load_done"/"profile_done", 真实数量)

    返回：
        rows_incremental  本次新增 CSV 的交易行数
        profiles_new      新增用户数（库里原本没有）
        profiles_updated  更新用户数（合并旧画像）
        profiles          = profiles_new + profiles_updated（本次受影响用户数）
        user_ids          受影响用户 ID 列表（检索索引按它做增量更新）
        member_level_source  user / none（等级只来自用户映射列，不推导）

    ⚠ 必须在 writes_to(...) 作用域内调用；写入是**分批 commit** 的，
    中途失败会留下部分已合并数据（重试同一批会重复累加，见 builder 的失败提示）。
    """
    dataset = require_write_scope("merge_incremental")
    if not csv_paths:
        raise ValueError("没有新增的 CSV 文件，无法增量更新（要重算全部数据请选「覆盖重建」）")
    if model is None:
        raise ValueError("增量合并需要传入向量模型（服务路径必须复用检索侧单例）")

    df_new = load_transactions(csv_paths, column_map)
    if df_new is None or len(df_new) == 0:
        # 空文件不能静默通过：否则会得到「构建成功但一个用户都没更新」的假象
        raise ValueError("新增的 CSV 没有解析出任何交易记录，无法增量更新")
    if on_phase:
        on_phase("load_done", {"rows": len(df_new)})

    new_profiles = build_profiles(df_new)
    if len(new_profiles) == 0:
        raise ValueError("新增的 CSV 没有聚合出任何用户，无法增量更新")
    if on_phase:
        on_phase("profile_done", {"profiles": len(new_profiles)})

    # 合并后的「最近购买」只能近似重建：库里只存了相对天数，没有绝对日期。
    # 用新数据的快照日 - 合并后的天数，得到与 days_since_last_buy 同一口径的日期；
    # 当旧天数更小时这个日期会偏新（保守近似），但不影响检索语义（画像文本只到天）。
    snapshot_date = None
    if "purchase_time" in df_new.columns:
        candidate = df_new["purchase_time"].max()
        snapshot_date = candidate if _present(candidate) else None

    conn = get_conn(dataset)
    cur = conn.cursor()
    try:
        ensure_base_tables(cur)
        ensure_schema(cur)
        conn.commit()

        records = new_profiles.to_dict("records")
        user_ids = [str(row["user_id"]) for row in records]
        existing = _load_existing_profiles(cur, user_ids)

        merged_rows: list[dict] = []
        for row in records:
            uid = str(row["user_id"])
            old = existing.get(uid)
            merged = merge_profile_row(old, row)
            if snapshot_date is not None and _present(merged.get("days_since_last_buy")):
                merged["last_buy"] = snapshot_date - pd.Timedelta(
                    days=int(merged["days_since_last_buy"])
                )
            else:
                merged["last_buy"] = None
            merged["profile_text"] = build_profile_text(pd.Series(merged))
            merged["_is_new"] = old is None
            merged_rows.append(merged)

        profiles_new = 0
        profiles_updated = 0
        total = len(merged_rows)
        logger.info("增量合并：受影响用户 %d（新增 %d / 更新 %d）",
                    total,
                    sum(1 for m in merged_rows if m["_is_new"]),
                    sum(1 for m in merged_rows if not m["_is_new"]))
        try:
            for i in range(0, total, BATCH):
                batch = merged_rows[i:i + BATCH]
                vecs = model.encode(
                    [m["profile_text"] for m in batch],
                    batch_size=16,
                    show_progress_bar=False,
                )
                for m, vec in zip(batch, vecs):
                    meta = json.dumps(
                        {
                            "platforms": m["platforms"],
                            "top_category": m["top_category"],
                        },
                        ensure_ascii=False,
                    )
                    values = (
                        m["profile_text"],
                        vec,
                        "sales",
                        1,
                        meta,
                        _to_int(m["age"]),
                        m["gender"],
                        m["city"],
                        m["member_level"],
                        _to_int(m["order_count"]),
                        _to_float(m["total_amount"]),
                        _to_float(m["avg_amount"]),
                        m["top_category"],
                        _to_int(m["days_since_last_buy"]),
                        m["platforms"],
                    )
                    if m["_is_new"]:
                        cur.execute(_INSERT_PROFILE_SQL, (str(m["user_id"]),) + values)
                        profiles_new += 1
                    else:
                        cur.execute(_UPDATE_PROFILE_SQL, values + (str(m["user_id"]),))
                        profiles_updated += 1
                conn.commit()
                done = min(i + BATCH, total)
                if progress:
                    progress(done, total, "合并画像")
        except psycopg2.errors.StringDataRightTruncation as e:
            conn.rollback()
            raise ValueError(
                "增量合并失败：某个文本字段的值超过数据库列长度限制"
                "（相关列宽会自动扩容，可直接重试构建）。原始错误：" + str(e)
            ) from e

        schema_facts.invalidate()
        logger.info(
            "增量合并完成：新增用户 %d / 更新用户 %d（其余用户未改动）",
            profiles_new, profiles_updated,
        )
        return {
            "rows_incremental": int(len(df_new)),
            "profiles_new": profiles_new,
            "profiles_updated": profiles_updated,
            "profiles": profiles_new + profiles_updated,
            "user_ids": user_ids,
            "member_level_source": new_profiles.attrs.get("member_level_source", "unknown"),
        }
    finally:
        cur.close()


def verify(cur: Any) -> None:
    """验证结构化字段与检索链路"""
    logger.info("===== 结构化字段验证 =====")
    checks = [
        ("年龄 20-30 用户数", "SELECT COUNT(*) FROM user_profile_vectors WHERE age BETWEEN 20 AND 30"),
        # 不写死某个品类：换数据集后 '美妆' 可能不存在，这条自检会恒为空，
        # 容易被误读成「检索链路坏了」。按品类分组，任何数据都有结果可看。
        (
            "Top5 品类平均客单价",
            "SELECT top_category, ROUND(AVG(avg_amount), 2) AS avg_amount "
            "FROM user_profile_vectors WHERE top_category IS NOT NULL "
            "GROUP BY top_category ORDER BY avg_amount DESC LIMIT 5",
        ),
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
