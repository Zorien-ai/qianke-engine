#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : connection.py
@Function: PostgreSQL 连接管理（按数据集隔离 + 带探活重连）

改造前只有一个进程级全局连接。M2 起数据分库（原因见 config.DATASETS 的注释）：
    demo -> vec_db        仓库自带的示例数据，同时是评测基线
    user -> vec_db_user   用户自己上传并构建的数据

这里只讲「怎么分」——用 contextvar 记住当前数据集，而不是全局变量：

  服务里 demo 页与向导页同进程共存。若用全局变量，A 请求把当前库切成 user 之后，
  B 请求会接着用 user 库，也就是「A 改了 B 的状态」。这类串台不会报错，
  只会表现为「答案时对时错」，属于最难查的一类问题。contextvar 按请求隔离，各走各的。

  顺带的好处是调用方不必层层传参——pipeline / hybrid_retriever / sql_tool 里
  几十处 get_conn() 一行都不用改。

⚠ 自己 new 的 threading.Thread **不会**继承 contextvar（构建线程就是这种）。
  那里必须显式 use_dataset("user")，否则它会安静地连回默认的 demo 库，
  而构建的第一步就是 TRUNCATE——那正好会把评测基线和 demo 一起清掉。
"""
import contextvars
import logging
import threading

import psycopg2
from pgvector.psycopg2 import register_vector

from rag_demo.config import DATASETS, DEFAULT_DATASET

logger = logging.getLogger(__name__)

# 每个数据集各持一条连接。不做连接池：单机单用户，池子带来的复杂度
# （归还、超时、脏事务、失效检测）远大于收益；真有并发需求时再说。
_conns: dict[str, "psycopg2.extensions.connection"] = {}

# 数据集级互斥锁（见 dataset_lock）——不是给 get_conn 用的，是给
# 「构建期间的写」与「查询的读」协调用的。
_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()

_current: contextvars.ContextVar[str] = contextvars.ContextVar(
    "rag_dataset", default=DEFAULT_DATASET
)


class UnknownDataset(ValueError):
    """数据集名不存在。

    单独定义而不直接抛 ValueError，是为了让调用方能区分
    「名字写错了」（改代码就能修）和「连不上库」（要看数据库服务）。
    """


def _resolve(name: str | None) -> str:
    """把 None 解析成「当前数据集」，并校验名字合法"""
    target = name or _current.get()
    if target not in DATASETS:
        raise UnknownDataset(f"未知数据集 {target!r}，可选：{sorted(DATASETS)}")
    return target


def current_dataset() -> str:
    """当前生效的数据集名（供日志与接口回显用）"""
    return _current.get()


def use_dataset(name: str):
    """
    切换当前数据集，返回 token；必须与 reset_dataset 成对使用

    用 token 而不是「自己记住旧值再设回去」：嵌套切换（demo→user→demo）时，
    手工还原很容易只还原一层，剩下的一层会一路泄漏到后续请求里。
    """
    token = _current.set(_resolve(name))
    logger.debug("数据集切换 -> %s", name)
    return token


def reset_dataset(token) -> None:
    """还原到 use_dataset 之前的数据集"""
    _current.reset(token)


def get_conn(dataset: str | None = None):
    """
    取指定数据集的连接；不传则用当前 contextvar 里的数据集

    每次调用探活，失败则重连。解决服务端 kill 后 conn.closed 仍为 0 的问题。
    """
    name = _resolve(dataset)

    conn = _conns.get(name)
    if conn is not None and not conn.closed:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.rollback()  # 探活后立即清理事务，避免连接长期停在 idle in transaction
            return conn
        except Exception as e:
            logger.warning("数据集 %s 连接探活失败，准备重连: %s", name, e)
            try:
                conn.close()
            except Exception:
                pass
            _conns.pop(name, None)

    logger.info("建立新数据库连接（数据集 %s）...", name)
    conn = psycopg2.connect(**DATASETS[name])
    register_vector(conn)
    _conns[name] = conn
    return conn


def dataset_lock(dataset: str | None = None) -> threading.RLock:
    """
    取某个数据集的互斥锁（可重入）

    为什么需要它：psycopg2 的连接**不是线程安全的**。构建任务在线程里逐批
    INSERT 并 commit，若此时另一个线程拿着同一条连接跑查询，会撞上
    「another command is already in progress」——而且是在用户点查询的瞬间随机炸。

    所以约定：**构建期间由构建线程持锁，查询侧用 acquire(blocking=False) 试探**，
    拿不到就明确回「正在构建，暂时不能查询」，而不是硬闯。
    这既避免了崩溃，也正好符合产品的期望（构建中本来就不该查询）。
    """
    with _locks_guard:
        name = _resolve(dataset)
        lock = _locks.get(name)
        if lock is None:
            lock = _locks[name] = threading.RLock()
        return lock


def close_conn(dataset: str | None = None) -> None:
    """
    关闭连接：不传数据集 = 关闭全部

    保留「不传就关全部」是有意的——改造前它关的就是唯一那条连接。
    若改成「不传就只关当前」，服务退出时另一个数据集的连接会留在库里，
    表现是「进程没了但连接还在」，排查很费时间。
    """
    names = [_resolve(dataset)] if dataset else list(_conns)
    for name in names:
        conn = _conns.pop(name, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
