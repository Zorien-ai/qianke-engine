#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : kb_stats.py
@Function: 知识库概况的纯计算层（M3 企业后台）

为什么单独一个模块
------------------
`/api/kb/overview`（知识库概况）与 `/api/kb/clear`（清空）里真正需要想清楚的
只有几件事：文档矩阵怎么组装、汇总怎么算、last_build 怎么序列化/解析、
清空的二次确认怎么判、索引新鲜度怎么归一。它们全是**纯计算**。

所以这里刻意**不 import 数据库 / torch / FastAPI**：
接口层负责「取数与鉴权」，本模块只负责「怎么算、怎么判」。
好处是这些判定可以不起服务、不连库、不加载 2GB 模型，直接用 pytest 跑
（见 tests/test_kb_stats.py）；而一旦把它们写进接口函数，测一遍就得有
PostgreSQL + 登录态 + 已构建的数据集。

约定
----
本模块所有函数都**不抛业务异常**（除了 Python 自身的类型错误，而调用方传的
都是接口层组好的数据）：脏数据一律降级成 0 / None / unknown。
概况页是「看一眼」的页面，宁可显示 0，也不该因为一行脏数据整页 500。
"""
import json

# 索引新鲜度的三个合法状态（与 db/schema.py 的 FRESH/STALE/UNKNOWN 同一套取值）。
# 这里重新声明而不是 import schema：schema 会 import config（进而 import torch），
# 本模块要能在一个没装 torch 的环境里被测试导入。
FRESH = "fresh"
STALE = "stale"
UNKNOWN = "unknown"
FRESHNESS_STATUSES = (FRESH, STALE, UNKNOWN)


def _as_int(value) -> int:
    """
    尽力转成 int：SQL 的 SUM()/COUNT() 可能是 None、Decimal 或字符串

    降级成 0 而不是报错：这是给概况页用的数字，一条 NULL 不该让整页挂掉。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ==================== 文档矩阵 ====================
def docs_from_rows(rows) -> list[dict]:
    """
    把文档矩阵的 SQL 结果转成前端要的结构

    入参是 `SELECT doc_name, COUNT(*), SUM(length(chunk_text)) ... GROUP BY doc_name`
    的原始行（元组序列），顺序**原样保留**——SQL 里已经按切片数倒序排好，
    这里再排一次只会出现「两份真源」。

    返回：[{"doc_name": str, "chunks": int, "chars": int}]
    """
    docs: list[dict] = []
    for row in rows or []:
        # 用下标而不是解包：不同驱动/版本下行类型可能是 tuple / list / Record，
        # 它们都支持下标，却不一定都支持 3 元解包（Record 解包顺序在两代 psycopg 里不同）。
        doc_name = row[0] if row[0] is not None else ""
        docs.append(
            {
                "doc_name": doc_name,
                "chunks": _as_int(row[1]),
                "chars": _as_int(row[2]),
            }
        )
    return docs


# ==================== 汇总 ====================
def totals_from(docs, profiles) -> dict:
    """
    概况汇总：文档数 / 切片数 / 画像数

    - docs = 文档矩阵的行数（不是 SUM，一篇文章一行）
    - chunks = 各文档切片数之和
    - profiles = 画像条数（来自 `SELECT COUNT(*) FROM user_profile_vectors`）

    profiles 由调用方传进来而不是从 docs 里推：它是另一张表的规模，
    两者没有数学关系（只传文档的数据集也会重建索引，但画像可以是 0）。
    """
    docs = docs or []
    return {
        "docs": len(docs),
        "chunks": sum(_as_int(d.get("chunks")) for d in docs),
        "profiles": _as_int(profiles),
    }


# ==================== last_build（重建的数据来源） ====================
def serialize_last_build(upload_id, fields, csv, md, at) -> dict:
    """
    构造「最近一次成功构建」的源描述，用于 meta 表 upsert（JSON 字符串）

    为什么要把源批次记下来：清空数据空间后，`built_at` / 指纹都没了，
    但**源文件还在 data/uploads 下**。概况页据此给出「一键重建」，
    前端拿这里的 upload_id + fields 调既有的 `POST /api/wizard/build`
    （该接口幂等：会先清空再重写），不需要新增任何重建接口。

    参数：
        upload_id  上传批次号（12 位 hex）
        fields     字段映射 {字段 key: 原始列名}
        csv / md   本批次的文件数
        at         构建成功时间 "YYYY-MM-DD HH:MM:SS"
    """
    return {
        "upload_id": str(upload_id or ""),
        "fields": dict(fields or {}),
        "csv": _as_int(csv),
        "md": _as_int(md),
        "at": at,
    }


def parse_last_build(raw) -> dict | None:
    """
    解析 meta 表里的 last_build：JSON 字符串 / None → dict / None

    坏 JSON、非对象（`[]` / `"x"`）、空串一律返回 None——
    概况页降级成「没有重建来源」，而不是整页 500。
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def last_source_from(last_build, available: bool) -> dict | None:
    """
    把 last_build 的落盘格式转成概况页的 `last_source`（没有就 None）

    两个字段名的差异是有意的：落盘键叫 `at`（写的时候只有「时间」一个语义），
    出网字段叫 `built_at`（与顶层 `built_at` 对齐，前端只认一套命名）。
    """
    if not isinstance(last_build, dict):
        return None
    upload_id = last_build.get("upload_id")
    if not upload_id:
        return None
    return {
        "upload_id": upload_id,
        "fields": last_build.get("fields") or {},
        "csv": _as_int(last_build.get("csv")),
        "md": _as_int(last_build.get("md")),
        "built_at": last_build.get("at"),
        "available": bool(available),
    }


# ==================== 清空二次确认 ====================
def validate_clear_confirm(confirm, dataset) -> str | None:
    """
    校验清空的二次确认：匹配返回 None，否则返回给用户看的中文文案

    规则：`confirm` 必须等于后端**从登录账号推导出来的** dataset 字面值。
    注意这里只做比对，绝不返回/采纳任何「要清哪个库」的信息——
    目标库只有接口层的 `_tenant_dataset()` 能决定（红线：前端无权指定数据集）。

    文案里必须带上当前 dataset 名：用户手输时最容易错在「别的企业名」，
    只回一句「确认不符」等于让他猜。
    """
    expected = (dataset or "").strip()
    given = (confirm or "").strip()
    if expected and given == expected:
        return None
    name = expected or "(未知数据空间)"
    return (
        f"二次确认不匹配：清空是不可恢复操作，请在确认框里输入当前数据空间名称"
        f"「{name}」再试"
    )


# ==================== 索引新鲜度 ====================
def freshness_payload(status, reason) -> dict:
    """
    归一索引新鲜度：{status, reason}

    状态只认 fresh / stale / unknown 三个**精确值**：
    - 未知值（None、空串、大小写不对、拼错）一律归成 unknown。
      这是给前端配色用的血条状态，多一个值就等于多一种没人设计的颜色；
    - 不做大小写归一：落盘与判定都在后端（schema.FRESH / STALE / UNKNOWN），
      出现 "FRESH " 说明调用方传错了东西，静默修正会把 bug 藏起来。

    reason 原样透出（None → 空串）：它是给人看的一句话，
    来源可能是指纹比对结果，也可能是「读取失败」的降级说明。
    """
    status_value = status if status in FRESHNESS_STATUSES else UNKNOWN
    return {
        "status": status_value,
        "reason": "" if reason is None else str(reason),
    }
