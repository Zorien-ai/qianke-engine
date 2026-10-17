#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : schema_facts.py
@Function: 从**当前数据集的实库**采集提示词所需的数据事实（表结构 / 取值 / 范围 / 时间口径）

为什么要有这个模块
------------------
改造前的 `prompts.SQL_SCHEMA` 是一段写死的文本：「约 8110 条」、12 个城市、
「钻石 / 黄金 / 白银 / 普通」、快照日 2024-12-30、6 个平台……

这些不是系统规则，是 **data/dianshuang 这一份 demo 数据集的说明书**。把它当系统规则
会直接产出错误答案，而且错得很像真的：

    换一批数据后，模型仍按旧枚举写 `WHERE city IN ('北京','上海')`，
    命中 0 行；再叠加「照字段取值范围解释空结果」的规则，
    这次 0 行会被解释成「数据里没有这个类别」—— 枚举过期被包装成了业务结论。

所以本模块的立场是：**列是系统契约（由 ingest 写入），值是数据**。
列名、列的业务含义可以写在代码里；条数、枚举、范围、时间覆盖、分位
一律在运行时从当前数据集查。

多数据集
--------
连接层用 contextvar 区分 demo / user / test（见 db/connection.py），
本模块的缓存 key 也必须带数据集名，否则「用 demo 的结构回答 user 的问题」。
"""

import logging
import threading
import time
from dataclasses import dataclass, field

from rag_demo.config import SQL_SCHEMA_CACHE_TTL, SQL_SCHEMA_ENUM_LIMIT
from rag_demo.db.connection import current_dataset, get_conn

logger = logging.getLogger(__name__)

# ================= 列的业务含义（系统契约，不含具体取值） =================
# kind 决定「怎么从数据里取值」：
#   id      主键/标识：只给不同取值数与少量样例
#   enum    低基数枚举：给「取值(条数)」并按条数降序
#   list    逗号分隔的多值串：拆开统计
#   numeric 数值：给实测 min-max 与不同取值数
#   text    长文本：只说明用途，不展示内容
#
# ⚠ 这里**不允许**写任何具体取值（城市名、等级名、条数、日期）。
#   一旦写进来，就又退回到「把 demo 说明书当系统规则」。
COLUMN_DOCS: dict[str, tuple[str, str]] = {
    "user_id": ("用户ID", "id"),
    "age": ("年龄", "numeric"),
    "gender": ("性别", "enum"),
    "city": ("城市", "enum"),
    "member_level": ("会员等级", "enum"),
    "order_count": ("累计订单数", "numeric"),
    "total_amount": ("累计总消费（元）", "numeric"),
    "avg_amount": ("平均客单价（元）", "numeric"),
    "top_category": ("偏好品类", "enum"),
    "days_since_last_buy": ("距最后一次购买的天数（相对基准日，越小越近）", "numeric"),
    "platforms": ("活跃平台（逗号分隔）", "list"),
    "profile_text": ("自然语言画像摘要", "text"),
    "doc_name": ("文档名", "enum"),
    "chunk_text": ("分块内容", "text"),
}

# 表的中文名（系统契约）
TABLE_LABELS = {
    "user_profile_vectors": "用户画像",
    "wiki_vectors": "知识库文档分块",
}

# 每张表里「需要展示取值分布」的列——由 COLUMN_DOCS 的 kind 决定，
# 这里只负责挑出候选，避免把 embedding / 向量列也扫一遍。
_COLLECT_KINDS = ("id", "enum", "list", "numeric")


@dataclass
class ColumnFact:
    """一列的运行时事实"""

    name: str
    type_name: str
    doc: str
    kind: str
    distinct: int | None = None
    vmin: float | None = None
    vmax: float | None = None
    values: list[tuple[str, int]] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)


@dataclass
class TableFact:
    """一张表的运行时事实"""

    name: str
    label: str
    rows: int
    columns: list[ColumnFact] = field(default_factory=list)


# ================= 缓存 =================
# 每次问答都重新扫一遍分布没有意义（8110 行虽快，但用户上传可能是几十万行），
# 而数据变动只在 ingest 之后。故按数据集缓存，ingest 结束时显式失效。
# value = (时间戳, 完整 schema 文本, 数据口径句子列表)
_cache: dict[str, tuple[float, str, list[str]]] = {}
_cache_lock = threading.Lock()


def invalidate(dataset: str | None = None) -> None:
    """丢弃缓存：默认清空全部（ingest 后调用，不知道也没必要知道是哪个库）"""
    with _cache_lock:
        if dataset is None:
            _cache.clear()
        else:
            _cache.pop(dataset, None)


# ================= 采集 =================
def _type_label(data_type: str) -> str:
    """information_schema 的类型名 -> 提示词里好读的短名"""
    mapping = {
        "integer": "INT",
        "bigint": "BIGINT",
        "smallint": "INT",
        "numeric": "NUMERIC",
        "real": "REAL",
        "double precision": "FLOAT",
        "character varying": "VARCHAR",
        "character": "CHAR",
        "text": "TEXT",
        "timestamp without time zone": "TIMESTAMP",
        "date": "DATE",
    }
    return mapping.get((data_type or "").lower(), (data_type or "").upper())


def _columns(cur, table: str) -> list[tuple[str, str]]:
    """从 information_schema 读列清单（顺序按建表顺序）"""
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = %s AND table_schema = current_schema() "
        "ORDER BY ordinal_position",
        (table,),
    )
    return [(r[0], _type_label(r[1])) for r in cur.fetchall()]


def _collect_numeric_and_id(cur, table: str, cols: list[str]) -> dict[str, dict]:
    """
    一次扫描拿到所有数值列/ID 列的 min-max 与不同取值数

    即使没有数值列也要跑：`count(*)` 顺带在这条 SQL 里取，提前返回会漏掉条数
    （wiki_vectors 只有 doc_name / chunk_text，曾经因此被读成「空表」）。
    """
    selects = ["count(*)::bigint AS _rows"]
    for c in cols:
        selects.append(f'min("{c}") AS "{c}__min"')
        selects.append(f'max("{c}") AS "{c}__max"')
        selects.append(f'count(DISTINCT "{c}") AS "{c}__distinct"')
    cur.execute(f'SELECT {", ".join(selects)} FROM "{table}"')
    row = cur.fetchone()
    named = {d[0]: v for d, v in zip(cur.description, row)}
    out = {"_rows": int(named.pop("_rows") or 0)}
    for c in cols:
        out[c] = {
            "min": named.get(f"{c}__min"),
            "max": named.get(f"{c}__max"),
            "distinct": named.get(f"{c}__distinct"),
        }
    return out


def _collect_enum(cur, table: str, col: str) -> list[tuple[str, int]]:
    """单个枚举列的取值分布（按条数降序，截断到 SQL_SCHEMA_ENUM_LIMIT）"""
    cur.execute(
        f'SELECT "{col}"::text AS v, count(*) AS n FROM "{table}" '
        f'WHERE "{col}" IS NOT NULL '
        f'GROUP BY 1 ORDER BY 2 DESC LIMIT {int(SQL_SCHEMA_ENUM_LIMIT)}'
    )
    return [(str(v), int(n)) for v, n in cur.fetchall() if str(v).strip()]


def _collect_list(cur, table: str, col: str) -> list[tuple[str, int]]:
    """逗号分隔的多值串：拆开后统计（例：platforms = '京东,天猫'）"""
    cur.execute(
        f"SELECT btrim(p) AS v, count(*) AS n FROM ("
        f'  SELECT regexp_split_to_table("{col}", \',\') AS p '
        f'  FROM "{table}" WHERE "{col}" IS NOT NULL'
        f") t WHERE btrim(p) <> '' GROUP BY 1 ORDER BY 2 DESC "
        f"LIMIT {int(SQL_SCHEMA_ENUM_LIMIT)}"
    )
    return [(str(v), int(n)) for v, n in cur.fetchall()]


def _collect_ids(cur, table: str, col: str, limit: int = 3) -> list[str]:
    """ID 列只取少量样例：用来告诉模型「ID 长什么样」，不做全量列举"""
    try:
        cur.execute(f'SELECT "{col}"::text FROM "{table}" WHERE "{col}" IS NOT NULL LIMIT %s', (limit,))
        return [str(r[0]) for r in cur.fetchall()]
    except Exception:  # noqa: BLE001 —— 样例取不到不影响主流程
        return []


def _collect_table(cur, table: str) -> TableFact:
    """采集单张表的全部事实"""
    label = TABLE_LABELS.get(table, table)
    cols = _columns(cur, table)
    fact = TableFact(name=table, label=label, rows=0, columns=[])

    if not cols:
        # 表不存在：不编造结构，交给调用方决定怎么降级
        return fact

    planned = [(name, typ) for name, typ in cols if name in COLUMN_DOCS]
    numeric_cols = [n for n, _ in planned if COLUMN_DOCS[n][1] in ("numeric", "id")]

    stats = _collect_numeric_and_id(cur, table, numeric_cols)
    fact.rows = stats.pop("_rows", 0)

    for name, typ in planned:
        doc, kind = COLUMN_DOCS[name]
        cf = ColumnFact(name=name, type_name=typ, doc=doc, kind=kind)
        if kind in ("numeric", "id") and name in stats:
            s = stats[name]
            cf.distinct = s["distinct"]
            if kind == "numeric":
                cf.vmin = float(s["min"]) if s["min"] is not None else None
                cf.vmax = float(s["max"]) if s["max"] is not None else None
            else:
                cf.samples = _collect_ids(cur, table, name)
        elif kind == "enum":
            try:
                cf.values = _collect_enum(cur, table, name)
                cf.distinct = len(cf.values)
            except Exception as e:  # noqa: BLE001
                logger.warning("采集 %s.%s 取值失败: %s", table, name, e)
        elif kind == "list":
            try:
                cf.values = _collect_list(cur, table, name)
                cf.distinct = len(cf.values)
            except Exception as e:  # noqa: BLE001
                logger.warning("采集 %s.%s 拆值失败: %s", table, name, e)
        fact.columns.append(cf)

    return fact


def _time_fact(cur, table: str, cols: list[str]) -> str:
    """
    时间口径：只能用库里真实存在的时间信息推

    改造前提示词写死「2024 全年历史快照」「2024-12-30 单时点」。那是 demo 的事实，
    但不能换个数据集就改期——所以这里只陈述实测到的覆盖范围；
    没有绝对时间列就明说没有，而不是拿一个记忆里的日期填上。
    """
    try:
        if "last_buy" in cols:
            cur.execute(f'SELECT min(last_buy), max(last_buy) FROM "{table}"')
            lo, hi = cur.fetchone()
            if lo and hi:
                return (
                    f"时间口径：last_buy 覆盖 {lo:%Y-%m-%d} ~ {hi:%Y-%m-%d}；"
                    "没有按日/月聚合的时间序列表，未来时点问题算不出来"
                )
        if "days_since_last_buy" in cols:
            cur.execute(
                f'SELECT min(days_since_last_buy), max(days_since_last_buy) FROM "{table}"'
            )
            lo, hi = cur.fetchone()
            if lo is not None and hi is not None:
                return (
                    f"时间口径：没有绝对时间列，只有一个相对天数 days_since_last_buy"
                    f"（实测 {lo} ~ {hi} 天，0 表示最近一次购买）。"
                    "无法按年/月/日筛选，也无法回答未来时点问题（无时间序列）"
                )
    except Exception as e:  # noqa: BLE001
        logger.warning("采集时间口径失败（%s）: %s", table, e)
    return "时间口径：本表没有可用的时间列"


def _amount_quantiles(cur, table: str, cols: list[str]) -> str:
    """
    客单价分位：给「高/低客单」这类业务口径一个数据来源

    改造前提示词写死「高客单 = avg_amount >= 1000；低客单 < 500」——那是 dianshuang
    的金额量级。换一家客单价 50 元的店，这条口径会把所有用户都判成低客单。
    分位数是相对的，换数据集仍然成立。
    """
    if "avg_amount" not in cols:
        return ""
    try:
        cur.execute(
            f'SELECT percentile_cont(0.25) WITHIN GROUP (ORDER BY avg_amount), '
            f'percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_amount), '
            f'percentile_cont(0.75) WITHIN GROUP (ORDER BY avg_amount), '
            f'percentile_cont(0.9) WITHIN GROUP (ORDER BY avg_amount) '
            f'FROM "{table}" WHERE avg_amount IS NOT NULL'
        )
        q25, q50, q75, q90 = cur.fetchone()
        if q25 is None:
            return ""
        return (
            f"客单价分位（本库实测）：P25={q25:.0f} / P50={q50:.0f} / "
            f"P75={q75:.0f} / P90={q90:.0f} 元；"
            "「高客单/低客单」按这些分位理解，不要用固定的绝对金额"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("采集客单价分位失败（%s）: %s", table, e)
        return ""


def _render_column(cf: ColumnFact) -> str:
    """单列渲染：取值/范围都来自采集结果，没有就只写业务含义"""
    detail = cf.doc
    if cf.kind == "enum" and cf.values:
        shown = " / ".join(f"{v}({n})" for v, n in cf.values)
        detail = f"{cf.doc}：{shown}"
    elif cf.kind == "list" and cf.values:
        shown = " / ".join(f"{v}({n})" for v, n in cf.values)
        detail = f"{cf.doc}：{shown}"
    elif cf.kind == "numeric":
        if cf.vmin is not None and cf.vmax is not None:
            detail = f"{cf.doc}（实测 {_num(cf.vmin)}-{_num(cf.vmax)}）"
    elif cf.kind == "id":
        if cf.samples:
            detail = f"{cf.doc}（示例：{'、'.join(cf.samples)}）"
        if cf.distinct is not None:
            detail += f"，{cf.distinct} 个不同取值"
    return f"  {cf.name:<19} {cf.type_name:<9} {detail}"


def _num(v: float) -> str:
    """数值展示：整数不带小数点，免得「18.0-65.0」显得像小数"""
    return f"{v:.0f}" if float(v).is_integer() else f"{v:g}"


def _render_table(tf: TableFact) -> str:
    """单表渲染"""
    head = f"表 {tf.name}（{tf.label}，{tf.rows} 条）："
    if not tf.columns:
        return f"{head}\n（该表不存在或尚未建表）"
    if tf.rows == 0:
        return f"{head}\n（该表为空，尚无数据）"
    lines = [head] + [_render_column(c) for c in tf.columns]
    return "\n".join(lines)


def collect(dataset: str | None = None) -> tuple[list[TableFact], list[str]]:
    """
    采集当前数据集的事实

    返回 (表事实列表, 数据口径说明列表)。口径说明只放「从数据里算出来的结论」，
    例如时间覆盖、客单价分位——这些正是改造前被写死在提示词里的东西。
    """
    conn = get_conn(dataset)
    cur = conn.cursor()
    try:
        tables: list[TableFact] = []
        facts: list[str] = []
        for table in ("user_profile_vectors", "wiki_vectors"):
            tf = _collect_table(cur, table)
            tables.append(tf)
            cols = [c.name for c in tf.columns]
            if table == "user_profile_vectors" and tf.rows:
                for fn in (_time_fact(cur, table, cols), _amount_quantiles(cur, table, cols)):
                    if fn:
                        facts.append(fn)
        conn.rollback()  # 只读，清理事务，避免连接停在 idle in transaction
        return tables, facts
    finally:
        cur.close()


def render(tables: list[TableFact], facts: list[str]) -> str:
    """
    渲染成提示词里的 schema 文本（纯函数，不碰数据库，便于离线验证）

    结构固定（表 -> 列 -> 数据口径），具体数值全部来自采集结果。
    """
    blocks = [_render_table(t) for t in tables]
    if facts:
        blocks.append("数据口径（从库内实际数据统计）：\n" + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(blocks)


def _build(dataset: str) -> tuple[str, list[str]]:
    """真正去库里采集并渲染：返回 (完整 schema 文本, 数据口径句子)"""
    tables, facts = collect(dataset)
    return render(tables, facts), facts


# 拿不到数据时的降级文案。**故意不给枚举兜底**：回退到写死的取值
# 等于把「demo 说明书」重新偷偷塞回提示词，正是本次要修的问题。
_UNAVAILABLE = (
    "（暂时无法读取表结构：数据库不可用。"
    "不要猜测字段名与取值范围，也不要用任何固定枚举值拼条件。）"
)


def _load(dataset: str, force: bool) -> tuple[str, list[str]]:
    """取缓存或重新采集"""
    now = time.time()
    if not force:
        with _cache_lock:
            cached = _cache.get(dataset)
        if cached and now - cached[0] < SQL_SCHEMA_CACHE_TTL:
            return cached[1], cached[2]

    try:
        text, facts = _build(dataset)
    except Exception as e:  # noqa: BLE001
        logger.warning("读取表结构失败（数据集 %s）: %s", dataset, e)
        return _UNAVAILABLE, []

    with _cache_lock:
        _cache[dataset] = (now, text, facts)
    return text, facts


def get_sql_schema(force: bool = False) -> str:
    """提示词用的表结构 + 数据事实文本（按数据集缓存）"""
    return _load(current_dataset(), force)[0]


def get_time_capability(force: bool = False) -> str:
    """
    只取「时间能力」这一条结论，供**不需要完整表结构**的提示词使用

    典型用法：多路规划提示词要按「有没有时间序列」决定是否需要 SQL 路。
    改造前那里写死「库里只有 2024-12-30 的单时点静态快照」——那是 demo 的事实，
    接入真实数仓后会把有时间序列的库也当成没有，直接关掉 SQL 路。
    """
    _, facts = _load(current_dataset(), force)
    for f in facts:
        if f.startswith("时间口径"):
            return f
    return "时间口径：无法读取（数据库不可用时不要假设存在时间序列）"
