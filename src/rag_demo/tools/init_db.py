#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : init_db.py
@Function: 初始化数据集库（建库 + 装扩展 + 建表），幂等

用法（项目根目录下执行）：
    uv run python src/rag_demo/tools/init_db.py            # 初始化全部数据集
    uv run python src/rag_demo/tools/init_db.py user       # 只建 M2 的用户库
    uv run python src/rag_demo/tools/init_db.py demo       # 只修 demo 库（表已存在，是 no-op）

为什么需要它：改造前两张源数据表的建表 DDL 不在仓库里，ingest 只做
ALTER ADD COLUMN + TRUNCATE，默认「表已经存在」。于是换一台机器、
或者 M2 要新建一个空库时，第一步就会报 relation does not exist。
这里把「从零到一个能用的库」补全，M5 的交付环境也依赖它。

安全说明：整个过程只做 CREATE ... IF NOT EXISTS，**不删不删改任何已有数据**。
"""
import logging
import sys

import psycopg2
from psycopg2 import sql

from rag_demo.config import DATASETS
from rag_demo.db.connection import close_conn, get_conn, reset_dataset, use_dataset
from rag_demo.db.schema import ensure_base_tables, ensure_schema

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# 建库要连一个已存在的库发指令；postgres 是 PostgreSQL 自带的维护库
MAINTENANCE_DB = "postgres"


def ensure_database(dataset: str) -> bool:
    """
    确保数据集对应的数据库存在；返回是否**新建**了

    CREATE DATABASE 不能在事务里执行，所以这里单独开一条连接并置 autocommit，
    不走 get_conn()（它带探活 rollback，会把这个语句冲掉）。
    """
    cfg = DATASETS[dataset]
    dbname = cfg["dbname"]

    conn = psycopg2.connect(**{**cfg, "dbname": MAINTENANCE_DB})
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if cur.fetchone() is not None:
                logger.info("[跳过] 数据库 %s 已存在", dbname)
                return False
            # 库名是标识符、不能当参数绑定，用 psycopg2.sql.Identifier 做安全引用
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
        logger.info("[新建] 数据库 %s", dbname)
        return True
    finally:
        conn.close()


def ensure_vector_extension(dataset: str) -> None:
    """
    确保 vector 扩展已安装

    必须在任何 get_conn() 之前做：get_conn() 会调 register_vector()，
    而它在注册时要去查 vector 类型的 oid——库里还没这个类型就会直接失败。
    所以这一步用裸连接，不能用 get_conn()。
    """
    cfg = DATASETS[dataset]
    conn = psycopg2.connect(**cfg)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        logger.info("[扩展] %s 已安装 vector", cfg["dbname"])
    finally:
        conn.close()


def init_dataset(dataset: str) -> None:
    """把一个数据集初始化到「可以被 ingest 直接写入」的状态"""
    logger.info("===== 初始化数据集 %s（%s）=====", dataset, DATASETS[dataset]["dbname"])
    created = ensure_database(dataset)
    ensure_vector_extension(dataset)

    if created:
        # 新建的库是空的，连接缓存里可能还留着同名旧连接（不该有，但防一手）
        close_conn(dataset)

    token = use_dataset(dataset)
    try:
        ensure_base_tables()   # 两张源数据表 + 向量索引
        ensure_schema()        # 检索索引表 search_index + 指纹表
    finally:
        reset_dataset(token)


def main(argv: list[str]) -> int:
    targets = argv[1:] or list(DATASETS)
    unknown = [t for t in targets if t not in DATASETS]
    if unknown:
        logger.error("未知数据集 %s，可选：%s", unknown, sorted(DATASETS))
        return 2

    for name in targets:
        init_dataset(name)

    # 顺手核对一句：确认默认数据集没被这次初始化带跑偏
    logger.info("默认数据集仍为，连接自检:")
    conn = get_conn()          # 不带参数 = 默认数据集
    cur = conn.cursor()
    cur.execute("SELECT current_database()")
    logger.info("  当前连接库: %s", cur.fetchone()[0])
    cur.close()
    close_conn()
    logger.info("初始化完成")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
