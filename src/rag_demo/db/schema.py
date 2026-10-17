#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : schema.py
@Function: 建表（两张源数据表 + 检索索引表）与索引新鲜度判定

本文档管两类表：
  1. **源数据表** user_profile_vectors / wiki_vectors —— 由 ensure_base_tables 建。
     改造前它们的建表 DDL **不在仓库里**（ingest 只做 ALTER ADD COLUMN + TRUNCATE，
     默认表已存在），于是「全新环境」根本跑不起来。M2 要建新库，顺手把 DDL 补上：
     结构是按活库反推的（列类型、长度、默认值、HNSW 索引都逐一对齐）。
     注意结构化字段的 btree 索引不在这里，在 ingest_data.INDEX_SQL —— 因为
     那些列是 ingest 用 ALTER 加的，索引跟着列走，避免同一份定义散在两个文件里。
  2. **检索索引表** search_index / search_index_meta —— 由 ensure_schema 建。

为什么单独建 search_index，而不是往源表加列：
  bm25_tokens 与 sparse_weights 都是**派生数据**，随时可由源表重建。
  独立存放的好处是——不会被 ingest 脚本的 TRUNCATE 连带清掉，
  且可单独重建、单独监控，源表保持"业务数据"的纯粹语义。

稀疏权重用 pgvector 原生 sparsevec 类型（而非 JSONB），
这样稀疏检索能直接在库内完成，不必把 8146 条权重拉进内存。

附：search_index_meta 表记录**构建时的语料指纹**，用来回答
「索引是不是已经落后于源表了」。理由见本文末「语料指纹」一节。
"""
import logging
from datetime import datetime

from rag_demo.config import EMBED_DIM, SEARCH_INDEX_TABLE, SPARSE_VEC_DIM
from rag_demo.db.connection import get_conn, require_write_scope

logger = logging.getLogger(__name__)

# ================= 源数据表（user_profile_vectors / wiki_vectors） =================
# 结构按活库反推，逐列对齐（含默认值与长度限制）；建表语句幂等，
# 已有表的环境执行它是 no-op，所以可以放心在 ingest 前无条件调用。

USER_PROFILE_DDL = f"""
CREATE TABLE IF NOT EXISTS user_profile_vectors (
    id                   SERIAL PRIMARY KEY,
    user_id              VARCHAR(50)  NOT NULL,
    profile_text         TEXT         NOT NULL,
    embedding            vector({EMBED_DIM}),
    dept                 VARCHAR(50),
    sensitivity          INT          DEFAULT 1,
    update_time          TIMESTAMP    DEFAULT NOW(),
    metadata             JSONB,
    age                  INT,
    gender               VARCHAR(4),
    city                 VARCHAR(50),
    member_level         VARCHAR(20),
    order_count          INT,
    total_amount         NUMERIC,
    avg_amount           NUMERIC,
    top_category         VARCHAR(50),
    days_since_last_buy  INT,
    platforms            VARCHAR(200)
)
"""

WIKI_DDL = f"""
CREATE TABLE IF NOT EXISTS wiki_vectors (
    id           SERIAL PRIMARY KEY,
    doc_name     VARCHAR(100),
    chunk_text   TEXT      NOT NULL,
    embedding    vector({EMBED_DIM}),
    dept         VARCHAR(50),
    sensitivity  INT       DEFAULT 1,
    update_time  TIMESTAMP DEFAULT NOW(),
    metadata     JSONB
)
"""

# 稠密向量的 HNSW 近邻索引。
# 为什么这里给 wiki 也建、而活库的 wiki_vectors 没有：活库里 wiki 只有 36 条，
# 顺序扫描完全够用；但 M2 的用户可能上传几十篇文档、切出上千块，那时没索引会明显变慢。
# 稠密向量用 HNSW 是既有选择（user_profile_vectors 本来就带这个索引）；
# 只有**稀疏**向量默认不建 HNSW，理由见下面 ENABLE_SPARSE_HNSW。
USER_PROFILE_EMBED_INDEX = (
    "CREATE INDEX IF NOT EXISTS user_profile_vectors_embedding_idx "
    "ON user_profile_vectors USING hnsw (embedding vector_cosine_ops)"
)
WIKI_EMBED_INDEX = (
    "CREATE INDEX IF NOT EXISTS wiki_vectors_embedding_idx "
    "ON wiki_vectors USING hnsw (embedding vector_cosine_ops)"
)

BASE_TABLE_SQL = [
    USER_PROFILE_DDL,
    WIKI_DDL,
    USER_PROFILE_EMBED_INDEX,
    WIKI_EMBED_INDEX,
]


def ensure_base_tables(cur=None) -> None:
    """
    幂等建两张源数据表与它们的向量索引

    cur 传了就用调用方的 cursor、不提交（复用其事务）；不传则自己开连接并 **立即提交**——
    提交的理由与 ensure_schema 相同：get_conn() 每次探活都会 rollback 未提交事务，
    不提交的话建表会被后续任何一次取连接悄悄冲掉。

    为什么允许传入 cursor：ingest 的写库流程里，建表要和 TRUNCATE、INSERT 在
    同一个连接/事务序列上，中间夹一次 get_conn() 探活反而会打断它。
    """
    if cur is not None:
        for sql in BASE_TABLE_SQL:
            cur.execute(sql)
        return

    conn = get_conn()
    cur = conn.cursor()
    try:
        for sql in BASE_TABLE_SQL:
            cur.execute(sql)
        conn.commit()
        logger.info("源数据表 user_profile_vectors / wiki_vectors 已就绪")
    finally:
        cur.close()

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {SEARCH_INDEX_TABLE} (
    corpus_id       VARCHAR(64)  PRIMARY KEY,
    source          VARCHAR(128) NOT NULL,
    text            TEXT         NOT NULL,
    bm25_tokens     TEXT[],
    sparse_weights  sparsevec({SPARSE_VEC_DIM}),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
)
"""

CREATE_INDEX_SQL = [
    f"CREATE INDEX IF NOT EXISTS idx_{SEARCH_INDEX_TABLE}_source "
    f"ON {SEARCH_INDEX_TABLE} (source)",
]

# 索引构建时的语料指纹（键值对，行数很少，不需要额外类型设计）
META_TABLE = f"{SEARCH_INDEX_TABLE}_meta"

CREATE_META_SQL = f"""
CREATE TABLE IF NOT EXISTS {META_TABLE} (
    key   VARCHAR(32) PRIMARY KEY,
    value TEXT        NOT NULL
)
"""

# 运行期是否用 HNSW 近邻索引加速稀疏检索。
# 当前语料 8146 条，精确全表扫描已足够快；HNSW 是近似算法，
# 会带来「检索结果与精确内积不一致」的风险，故默认不建，留待规模上去再启用。
ENABLE_SPARSE_HNSW = False

HNSW_SQL = (
    f"CREATE INDEX IF NOT EXISTS idx_{SEARCH_INDEX_TABLE}_sparse "
    f"ON {SEARCH_INDEX_TABLE} USING hnsw (sparse_weights sparsevec_ip_ops)"
)


def ensure_schema() -> None:
    """
    幂等建表 + 建索引，**立即提交**

    必须提交，不能把 DDL 留在事务里：get_conn() 每次探活都会 rollback
    未提交事务，后续任何一次取连接都会把建表悄悄冲掉（已实际踩过）。
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(CREATE_TABLE_SQL)
        cur.execute(CREATE_META_SQL)
        for sql in CREATE_INDEX_SQL:
            cur.execute(sql)
        if ENABLE_SPARSE_HNSW:
            cur.execute(HNSW_SQL)
        conn.commit()
        logger.info("检索索引表 %s 已就绪", SEARCH_INDEX_TABLE)
    finally:
        cur.close()


def index_stats() -> dict:
    """索引表概况：条数 / 来源分布 / 更新时间 / 缺失列统计"""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE}")
        total = cur.fetchone()[0]

        cur.execute(
            f"SELECT source, COUNT(*) FROM {SEARCH_INDEX_TABLE} "
            f"GROUP BY source ORDER BY COUNT(*) DESC"
        )
        by_source = cur.fetchall()

        cur.execute(f"SELECT MIN(updated_at), MAX(updated_at) FROM {SEARCH_INDEX_TABLE}")
        updated_from, updated_to = cur.fetchone()

        cur.execute(
            f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE} WHERE sparse_weights IS NULL"
        )
        missing_sparse = cur.fetchone()[0]

        cur.execute(
            f"SELECT COUNT(*) FROM {SEARCH_INDEX_TABLE} WHERE bm25_tokens IS NULL"
        )
        missing_bm25 = cur.fetchone()[0]
    finally:
        conn.rollback()
        cur.close()

    return {
        "table": SEARCH_INDEX_TABLE,
        "total": total,
        "by_source": by_source,
        "updated_from": updated_from,
        "updated_to": updated_to,
        "missing_sparse": missing_sparse,
        "missing_bm25": missing_bm25,
    }


# ==================== 语料指纹：判定「索引是否落后于源表」 ====================
#
# 背景：索引与源表之间**没有自动失效机制**，一致性由「显式重建」保证。
# 画像重导后忘了跑 build_search_index.py，检索会静默使用旧索引——不报错，
# 表现是「数据明明更新了，回答还是旧的」（见 data/new-dianshuang/README.md 6.4）。
#
# 为什么不能只比条数：重导画像后**条数不变**（还是 8110 条），但文本已经变了，
# 条数比对完全看不见这种情况。所以对「内容」做摘要：把每行的
# (主键, md5(文本)) 排序后拼接、再取一次 md5——对顺序不敏感、对内容敏感。
#
# 为什么在 SQL 里算：8110 条画像文本不必拉进 Python；库内 md5 聚合在毫秒级。

_PROFILE_FP_SQL = """
    SELECT COUNT(*)::text,
           COALESCE(md5(string_agg(user_id || ':' || md5(profile_text), '|'
                                   ORDER BY user_id)), '')
    FROM user_profile_vectors
"""

_WIKI_FP_SQL = """
    SELECT COUNT(*)::text,
           COALESCE(md5(string_agg(id::text || ':' || md5(doc_name || '|' || chunk_text), '|'
                                   ORDER BY id)), '')
    FROM wiki_vectors
"""

# status 取值
FRESH = "fresh"      # 索引与源表一致
STALE = "stale"      # 源表变了、索引没重建
UNKNOWN = "unknown"  # 没有基线指纹（旧索引 / 从未构建）


def current_fingerprint() -> dict:
    """
    源表**当前**的语料指纹

    与构建索引时写入的指纹用同一套算法；两者不一致 = 索引已过期。
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(_PROFILE_FP_SQL)
        p_count, p_hash = cur.fetchone()
        cur.execute(_WIKI_FP_SQL)
        w_count, w_hash = cur.fetchone()
    finally:
        conn.rollback()
        cur.close()

    return {
        "profile_count": int(p_count),
        "wiki_count": int(w_count),
        "profile_hash": p_hash,
        "wiki_hash": w_hash,
    }


def write_fingerprint(cur, fingerprint: dict) -> None:
    """
    把指纹写进 meta 表（**复用调用方的 cursor 与事务**）

    必须与索引行同一个事务提交：否则可能留下「行写进去了、指纹没写」的中间态，
    下次检查会误报 unknown，反而把真正的问题盖住。
    """
    rows = [("built_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))]
    rows += [
        (k, str(fingerprint[k]))
        for k in ("profile_count", "wiki_count", "profile_hash", "wiki_hash")
    ]
    for key, value in rows:
        cur.execute(
            f"INSERT INTO {META_TABLE} (key, value) VALUES (%s, %s) "
            f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value),
        )


def read_fingerprint() -> dict | None:
    """
    读回构建时记录的指纹

    meta 表不存在（老库第一次检查）或没有 profile_hash 时返回 None——
    「没有基线」必须与「基线不匹配」区分开，否则老库一上线就报 stale。
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT to_regclass(%s)", (META_TABLE,))
        if cur.fetchone()[0] is None:
            return None
        cur.execute(f"SELECT key, value FROM {META_TABLE}")
        raw = dict(cur.fetchall())
    finally:
        conn.rollback()
        cur.close()

    if not raw.get("profile_hash"):
        return None

    out: dict = {"built_at": raw.get("built_at")}
    for k in ("profile_count", "wiki_count"):
        try:
            out[k] = int(raw[k])
        except (KeyError, TypeError, ValueError):
            out[k] = None
    for k in ("profile_hash", "wiki_hash"):
        out[k] = raw.get(k)
    return out


def classify_freshness(stored: dict | None, current: dict) -> tuple[str, str]:
    """
    比对「构建时指纹」与「源表当前指纹」——**纯函数，不碰数据库**

    返回 (status, reason)，status ∈ {fresh, stale, unknown}。

    单独抽出来的原因：这段判断是本次改动的全部业务逻辑，抽成纯函数才**不需要
    PostgreSQL** 就能验证（本机 PG / Docker 未启动，DB 路径无法端到端跑）。
    """
    if not stored or not stored.get("profile_hash"):
        return UNKNOWN, (
            "索引未记录语料指纹（旧索引或从未构建过），无法判定新鲜度；"
            "跑一次 build_search_index.py 即可建立基线"
        )

    diffs: list[str] = []
    if stored.get("profile_count") != current["profile_count"]:
        diffs.append(
            f"画像条数 {stored.get('profile_count')} -> {current['profile_count']}"
        )
    if stored.get("wiki_count") != current["wiki_count"]:
        diffs.append(
            f"文档分块数 {stored.get('wiki_count')} -> {current['wiki_count']}"
        )
    # 下面两条才是关键：条数没变、内容变了（重导画像的典型情况）
    if stored.get("profile_hash") != current["profile_hash"]:
        diffs.append("画像文本内容已变（条数可能未变）")
    if stored.get("wiki_hash") != current["wiki_hash"]:
        diffs.append("文档分块内容已变")

    if not diffs:
        return FRESH, "索引与源表一致"
    return STALE, "索引已过期：" + "；".join(diffs)


def index_freshness() -> dict:
    """
    索引新鲜度总入口：stored / current / status / reason

    调用方据此决定「告警」「拒绝服务」还是「展示」——本函数只做判定，不做处置。
    """
    stored = read_fingerprint()
    current = current_fingerprint()
    status, reason = classify_freshness(stored, current)
    return {
        "status": status,
        "reason": reason,
        "stored": stored,
        "current": current,
        "meta_table": META_TABLE,
    }


# ==================== 数据集级 UI 配置 ====================
# 存在 meta 表里（与语料指纹同一张键值表，key 加前缀区分），理由是「先复用、不必新开表」。
#
# 目前三项：
#   assistant_name       助手名（拒答兜底文案里的「我是XX」）
#   sample_question      兜底文案末尾的示例问句
#   member_level_names   等级档位名（逗号分隔，高档在前，最后一个是兜底档）
#
# ⚠ 这里**不放「支持哪些能力」**：能力清单必须由代码决定（改了就是撒谎）。
#   用户能改的只有称呼、示例与自己业务的档位名，改不了「系统会做什么」。
UI_CONFIG_PREFIX = "ui_"
UI_CONFIG_KEYS = ("assistant_name", "sample_question", "member_level_names")


def read_ui_config() -> dict[str, str]:
    """
    读当前数据集的 UI 配置；表不存在或没有配置时返回空 dict

    空 dict 与「配置成空串」是两件事：前者由调用方用默认值，后者是用户有意清空。
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT to_regclass(%s)", (META_TABLE,))
        if cur.fetchone()[0] is None:
            return {}
        cur.execute(f"SELECT key, value FROM {META_TABLE}")
        raw = dict(cur.fetchall())
    finally:
        conn.rollback()
        cur.close()

    # 在 Python 里过滤而不是 LIKE 'ui_%'：LIKE 里的下划线是通配符，
    # 会把 uixxxx 也匹配进来；键只有几十个，取回来过滤更省心。
    return {
        k[len(UI_CONFIG_PREFIX):]: v
        for k, v in raw.items()
        if k.startswith(UI_CONFIG_PREFIX)
    }


def read_index_meta(key: str) -> str | None:
    """
    读索引/数据布局类元数据（与 UI 配置同一张表，但不带 ui_ 前缀）

    典型用途：doc_source_dir —— 文档原文在哪个目录。M2 上传的文档落在
    data/uploads/<id>/ 下，检索层的 Parent Document 扩展若只认 data/docs，
    用户上传的文档就永远拿不到全文（静默退化，只留一条 warning）。
    """
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT to_regclass(%s)", (META_TABLE,))
        if cur.fetchone()[0] is None:
            return None
        cur.execute(f"SELECT value FROM {META_TABLE} WHERE key = %s", (key,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.rollback()
        cur.close()


def write_index_meta(key: str, value: str | None) -> None:
    """写索引/数据布局类元数据（写操作，需在 writes_to 作用域内调用）"""
    require_write_scope("write_index_meta")

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(CREATE_META_SQL)
        if value is None:
            cur.execute(f"DELETE FROM {META_TABLE} WHERE key = %s", (key,))
        else:
            cur.execute(
                f"INSERT INTO {META_TABLE} (key, value) VALUES (%s, %s) "
                f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (key, value),
            )
        conn.commit()
    finally:
        cur.close()


def write_ui_config(values: dict[str, str | None]) -> None:
    """
    写当前数据集的 UI 配置（值为 None 表示删除该键）

    这是**写操作**，必须显式声明目标数据集（writes_to / require_write_scope）——
    与 ingest 同一条守卫：不声明就落到默认数据集，而默认是 demo（评测基线）。
    """
    require_write_scope("write_ui_config")

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(CREATE_META_SQL)
        for name, value in values.items():
            if name not in UI_CONFIG_KEYS:
                raise ValueError(f"不支持的 UI 配置项: {name}（可选：{UI_CONFIG_KEYS}）")
            key = UI_CONFIG_PREFIX + name
            if value is None:
                cur.execute(f"DELETE FROM {META_TABLE} WHERE key = %s", (key,))
            else:
                cur.execute(
                    f"INSERT INTO {META_TABLE} (key, value) VALUES (%s, %s) "
                    f"ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    (key, str(value).strip()),
                )
        conn.commit()
    finally:
        cur.close()
