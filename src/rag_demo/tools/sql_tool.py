#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : sql_tool.py
@Function: Text2SQL 工具：自然语言 -> SQL -> 安全校验 -> 执行
           解决 RAG 无法回答的聚合/统计/排名/分布类问题（有多少 / 平均多少 / 排名 / 占比）
"""
import logging
import re

from rag_demo.db.connection import get_conn
from rag_demo.generation.generator import chat_completion
from rag_demo.prompts import SQL_SCHEMA, TEXT2SQL_PROMPT

logger = logging.getLogger(__name__)

# 表结构说明与 SQL 生成提示词见 rag_demo/prompts.py
# （SQL_SCHEMA 同时被 pipeline / api 的结果总结复用）

# ================= 安全校验配置 =================
# 禁止出现的关键字（写操作 / DDL / DCL）
FORBIDDEN_KEYWORDS = [
    "drop", "delete", "update", "insert", "alter", "truncate",
    "create", "grant", "revoke", "copy", "vacuum", "into", "set",
]

# 允许查询的表白名单
ALLOWED_TABLES = {"user_profile_vectors", "wiki_vectors"}

# 单条查询超时保护
STATEMENT_TIMEOUT = "10s"
# =================================================


def _strip_code_fence(sql: str) -> str:
    """去掉 LLM 可能附加的 markdown 代码块包裹与结尾分号"""
    sql = (sql or "").strip()
    if sql.startswith("```"):
        sql = re.sub(r"^```[a-zA-Z]*\s*", "", sql)
        sql = re.sub(r"\s*```$", "", sql)
    return sql.strip().rstrip(";").strip()


def text2sql(question: str) -> str:
    """
    把自然语言问题转成 SQL（只生成，不校验）

    temperature=0 保证同样的问题生成稳定的 SQL。
    """
    prompt = TEXT2SQL_PROMPT.format(schema=SQL_SCHEMA, question=question)
    resp = chat_completion(
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    sql = _strip_code_fence(resp.choices[0].message.content or "")
    logger.info("Text2SQL 生成: %s", sql)
    return sql


def validate_sql(sql: str) -> bool:
    """
    校验 SQL 安全性：只读 + 必须带 LIMIT + 只查白名单表

    任一条件不满足即返回 False，调用方不应执行。
    """
    if not sql or not isinstance(sql, str):
        logger.warning("SQL 校验失败：SQL 为空")
        return False

    low = sql.strip().lower()

    # 1. 必须是 SELECT 或 WITH（CTE）开头。
    #    WITH 是合法的只读查询（CTE），危险操作仍由下面的关键字黑名单拦截。
    if not (low.startswith("select") or low.startswith("with")):
        logger.warning("SQL 校验失败：非 SELECT/WITH 开头 -> %s", sql[:80])
        return False

    # 2. 禁止危险关键字
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", low):
            logger.warning("SQL 校验失败：包含禁用关键字 '%s'", kw)
            return False

    # 3. 必须带 LIMIT，防止全表扫描
    if not re.search(r"\blimit\b", low):
        logger.warning("SQL 校验失败：缺少 LIMIT")
        return False

    # 4. 只允许白名单表（CTE 别名不是真实表，需从检查中排除）
    cte_names = set(re.findall(r"(?:with|,)\s*([a-z_][a-z0-9_]*)\s+as\s*\(", low))
    tables = set(re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", low))
    invalid = tables - ALLOWED_TABLES - cte_names
    if invalid:
        logger.warning("SQL 校验失败：非白名单表 %s", invalid)
        return False

    return True


def execute_sql(sql: str) -> list[tuple]:
    """执行 SQL 并返回全部结果行（带 statement_timeout 保护）"""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
        cur.execute(sql)
        rows = cur.fetchall()
        logger.info("SQL 执行完成，返回 %d 行", len(rows))
        return rows
    finally:
        conn.rollback()  # 清理查询事务，避免连接长期停在 idle in transaction
        cur.close()


def query(question: str) -> dict:
    """
    Text2SQL 主入口：生成 -> 校验 -> 执行

    返回:
        {"sql": str, "rows": list[tuple], "error": str | None}
    """
    try:
        sql = text2sql(question)
    except Exception as e:  # LLM 调用失败
        logger.error("SQL 生成失败: %s", e)
        return {"sql": "", "rows": [], "error": f"SQL 生成失败: {e}"}

    if not validate_sql(sql):
        return {"sql": sql, "rows": [], "error": "SQL 校验失败"}

    try:
        rows = execute_sql(sql)
        return {"sql": sql, "rows": rows, "error": None}
    except Exception as e:
        logger.error("SQL 执行失败: %s", e)
        return {"sql": sql, "rows": [], "error": str(e)}
