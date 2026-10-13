#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : connection.py
@Function: PostgreSQL 连接单例管理（带探活重连）
"""
import logging

import psycopg2
from pgvector.psycopg2 import register_vector

from rag_demo.config import DB_CONFIG

logger = logging.getLogger(__name__)

_conn = None


def get_conn():
    """每次调用探活，失败则重连。解决服务端 kill 后 _conn.closed 仍为 0 的问题。"""
    global _conn

    if _conn is not None and not _conn.closed:
        try:
            with _conn.cursor() as cur:
                cur.execute("SELECT 1")
            _conn.rollback()  # 探活后立即清理事务，避免连接长期停在 idle in transaction
            return _conn
        except Exception as e:
            logger.warning(f"连接探活失败，准备重连: {e}")
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None

    logger.info("建立新数据库连接...")
    _conn = psycopg2.connect(**DB_CONFIG)
    register_vector(_conn)
    return _conn


def close_conn():
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None
