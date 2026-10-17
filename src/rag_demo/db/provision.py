#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : provision.py
@Function: 运行期建库（M3 企业库）——把 tools/init_db.py 的能力搬进服务进程

为什么需要它
------------
M3 起「数据库按企业划分」：企业审核通过只是登记数据集名，真正的
`CREATE DATABASE` 放在**第一次构建**时做。构建本来就是重操作，多花 1~2 秒
建库可以接受；而审核是一次点击，让管理员在那儿等建库不合适。

与 tools/init_db.py 的分工
--------------------------
那个脚本是**运维入口**（换机器、M5 交付时从零初始化）；本模块是
**服务内的同一套动作**，复用同样的顺序与理由：

1. `CREATE DATABASE` 不能在事务里执行 → 单独连接 + autocommit；
2. `CREATE EXTENSION vector` 必须在任何 `get_conn()` 之前 → 裸连接执行
   （`get_conn` 会调 `register_vector`，库里还没这个类型就会失败）；
3. 新建的库是空的 → 必须 `ensure_base_tables` + `ensure_schema`，否则第一次
   ingest 会报 relation does not exist。

并发：同一企业两个人同时点构建，可能同时判定"库不存在"。CREATE DATABASE
的冲突表现为 `duplicate_database`，捕获后当作"别人已经建好了"继续走，
不再往上抛——这属于正常的并发结果，不是错误。
"""
import logging

import psycopg2
from psycopg2 import errors, sql

from rag_demo.config import DATASETS
from rag_demo.db.connection import (
    close_conn,
    ensure_readonly_access,
    get_conn,
    reset_dataset,
    use_dataset,
)
from rag_demo.db.schema import ensure_base_tables, ensure_schema

logger = logging.getLogger(__name__)

# 建库要连一个已存在的库发指令；postgres 是 PostgreSQL 自带的维护库
MAINTENANCE_DB = "postgres"


def ensure_dataset_ready(dataset: str) -> bool:
    """
    确保数据集对应的库与表都存在；返回是否**新建**了库

    幂等：库和表都在时是 no-op（每张表都走 IF NOT EXISTS）。
    """
    cfg = DATASETS[dataset]
    dbname = cfg["dbname"]

    created = False
    conn = psycopg2.connect(**{**cfg, "dbname": MAINTENANCE_DB})
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if cur.fetchone() is None:
                try:
                    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
                    created = True
                    logger.info("[新建] 企业库 %s（数据集 %s）", dbname, dataset)
                except errors.DuplicateDatabase:
                    # 并发构建：另一个线程刚建好，继续往下走即可
                    logger.info("[并发] 企业库 %s 已由其他请求创建", dbname)
    finally:
        conn.close()

    if created:
        # 连接缓存里可能有同名旧连接（正常不该有，防一手）
        close_conn(dataset)

    # vector 扩展必须在 get_conn 之前装好
    conn = psycopg2.connect(**cfg)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        conn.close()

    token = use_dataset(dataset)
    try:
        ensure_base_tables()
        ensure_schema()
    finally:
        reset_dataset(token)

    # 新库的表建好之后授权只读账号，否则该企业的 Text2SQL 一律没有 SELECT 权限
    ensure_readonly_access(dataset)

    # 探活一次，确保后续 ingest 拿到的连接是好的
    get_conn(dataset)
    return created
