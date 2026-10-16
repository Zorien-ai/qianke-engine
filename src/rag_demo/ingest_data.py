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
from typing import Any

import pandas as pd
from langchain_core.documents import Document
from sentence_transformers import SentenceTransformer

from rag_demo.config import DATA_DIR, DEVICE, DTYPE, MODEL_PATH, SEARCH_INDEX_TABLE
from rag_demo.db.connection import close_conn, get_conn
from rag_demo.splitter import DOC_TYPE_PROFILE, split

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ================= 配置区 =================
BATCH = 50

# 会员等级阈值（按平均客单价推导，原始 CSV 无该字段）
#
# 历史问题：原阈值（钻石 2000 / 黄金 1000 / 白银 500）是绝对金额，但本数据集
# 客单价整体虚高（p30=1531、p50=2495、p90=10382），导致钻石占 59%、等级几乎无区分度。
# 现改为按分位数标定（2026-10-11 实测分布）：
#   钻石 ≈ top 5%    (p95 = 14555)
#   黄金 ≈ 5%~20%    (p80 = 6680)
#   白银 ≈ 20%~50%   (p50 = 2495)
#   普通 ≈ bottom 50%
# 注：本表不再与 data/docs/tag_definitions.md 的客单标签（高客单≥1000）挂钩——
#     该口径对这份数据同样偏松（约 70% 用户满足），属另一个待处理的数据问题。
MEMBER_LEVELS = [("钻石", 14555.0), ("黄金", 6680.0), ("白银", 2495.0)]

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


def build_member_level(avg_amount: float) -> str:
    """按平均客单价推导会员等级（原始 CSV 无该字段）"""
    for name, threshold in MEMBER_LEVELS:
        if avg_amount >= threshold:
            return name
    return "普通"


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
    """
    return (
        f"用户{row['user_id']}（{row['user_name']}）：{row['age']}岁{row['gender']}，"
        f"{row['city']}人，{row['member_level']}会员。累计订单{row['order_count']}笔，"
        f"总消费{row['total_amount']:.0f}元，平均客单价{row['avg_amount']:.0f}元，"
        f"偏好品类为{row['top_category']}。"
        f"最近一次购买在{row['last_buy'].strftime('%Y-%m-%d')}，"
        f"活跃平台：{row['platforms']}。"
    )


def load_transactions() -> pd.DataFrame:
    """
    读取并合并所有来源 CSV

    经 KNOWN_PLATFORMS 白名单识别平台名；未登记的文件统一记为 UNKNOWN_PLATFORM，
    原文件名只留在日志里——不能让文件名冒充平台名写进画像文本（原因见常量处注释）。
    """
    csv_files = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
    logger.info("正在读取 %s 下的 CSV...", DATA_DIR)

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
    df_all = df_all.rename(columns=COLUMN_MAP)
    df_all["purchase_time"] = pd.to_datetime(df_all["purchase_time"])
    logger.info("合并后共 %d 条交易记录", len(df_all))
    return df_all


def build_profiles(df_all: pd.DataFrame) -> pd.DataFrame:
    """按用户聚合出画像（含结构化字段）"""
    snapshot_date = df_all["purchase_time"].max()
    logger.info("数据快照日期（最后一次购买）: %s", snapshot_date.date())

    def agg_user(g: pd.DataFrame) -> pd.Series:
        top_cat = g.groupby("category")["amount"].sum().idxmax()
        last_buy = g["purchase_time"].max()
        return pd.Series({
            "user_name": g["user_name"].iloc[0],
            "gender": g["gender"].iloc[0],
            "age": int(g["age"].iloc[0]),
            "city": g["city"].iloc[0],
            "order_count": int(len(g)),
            "total_amount": float(g["amount"].sum()),
            "avg_amount": float(g["amount"].mean()),
            "top_category": top_cat,
            "last_buy": last_buy,
            "days_since_last_buy": int((snapshot_date - last_buy).days),
            "platforms": ",".join(sorted(g["platform"].unique())),
        })

    profiles = (
        df_all.groupby("user_id", group_keys=False)
              .apply(agg_user, include_groups=False)
              .reset_index()
    )
    profiles["member_level"] = profiles["avg_amount"].apply(build_member_level)
    profiles["profile_text"] = profiles.apply(build_profile_text, axis=1)

    logger.info("共得到 %d 个用户画像", len(profiles))
    logger.info("会员等级分布:\n%s", profiles["member_level"].value_counts().to_string())
    return profiles


def write_to_db(documents: list[Document], model: SentenceTransformer) -> int:
    """
    向量化并写入 pgvector（含结构化字段）

    入参是切分产物 List[Document]：结构化字段都装在 metadata 里，
    所以这里不必再回查 DataFrame——一个 Document 就能取齐所有列。
    """
    conn = get_conn()
    cur = conn.cursor()

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
        logger.info("  已写入 %d/%d", min(i + BATCH, len(documents)), len(documents))

    return len(documents)


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
    logger.info("正在加载 bge-m3 模型（device=%s, dtype=%s）...", DEVICE, DTYPE)
    model = SentenceTransformer(
        str(MODEL_PATH), device=DEVICE, model_kwargs={"dtype": DTYPE}
    )

    df_all = load_transactions()
    profiles = build_profiles(df_all)
    documents = split(DOC_TYPE_PROFILE, {"profiles": profiles})
    count = write_to_db(documents, model)
    logger.info("成功导入 %d 条用户画像（含结构化字段）", count)

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
