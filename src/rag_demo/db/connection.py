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

⚠ **线程池同理**（ThreadPoolExecutor.submit 一样不会把上下文带过去）。
  检索就是在线程池里并行跑的，它在提交时用 contextvars.copy_context().run
  把当前上下文带进去（见 retrieval/query_processor.search_variants 的注释）。
  漏了这一句不会报错：表现为「用 demo 的数据回答 user 的问题」——
  答案看着很正常，只是不是他那批数据的。
"""
import contextlib
import contextvars
import logging
import threading

import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2 import sql

from rag_demo.config import (
    DATASETS,
    DEFAULT_DATASET,
    READONLY_DB_PASSWORD,
    READONLY_DB_USER,
)

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


class UnsafeWriteError(RuntimeError):
    """写操作没有显式声明目标数据集 —— 直接拒绝执行。

    为什么是异常而不是「警告 + 用默认值」：写操作的第一步往往是 TRUNCATE，
    落到默认数据集上就是把它清空。而 demo 同时是演示底座和评测基线，
    清掉不可逆。所以「忘记声明」必须是一个立刻炸出来的错误，
    而不是一次安静的误写。
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


def pin_dataset(name: str) -> None:
    """
    把**当前 Context** 的数据集钉住（不返回 token，也不配对 reset）

    专供「同步生成器 + StreamingResponse」这类场景（见 api/main.py 的
    `_dataset_pinned_stream`）：Starlette 迭代同步生成器走 iterate_in_threadpool，
    生成器每恢复一次都跑在一个**全新的 Context 副本**里（anyio 每次
    to_thread.run_sync 都会 contextvars.copy_context()）。所以生成器里
    `use_dataset()` 只对第一段代码有效，第二段开始（检索 prepare）读的又是
    默认数据集 demo——企业账号的流式回答会拿到 demo 的文档，这是跨租户串数据。

    这种一次性 Context 随本次 run_sync 结束就销毁，因此「只 set 不 reset」是安全的：
    钉住的数据集不会泄漏到别的请求；反过来，试图在下一段里 reset 上一次的 token
    反而会抛 `Token was created in a different Context`。
    """
    _current.set(_resolve(name))


# ================= 写操作守卫 =================
# 与「数据集」分开的一个 contextvar：_current 决定**读**去哪，_WRITE_SCOPE 只表示
# 「有人显式承诺过这段是写 user 的」。读允许回落到默认值，写不允许。
_WRITE_SCOPE: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "rag_write_dataset", default=None
)


class writes_to(contextlib.ContextDecorator):
    """
    声明「这一段的写操作属于哪个数据集」

    两种用法（同一套语义，按场景选）：

        with writes_to("user"):
            ingest_documents(docs)

        @writes_to("user")
        def _run_build(task_id, ...):
            ...            # 后台线程用这个：线程入口就带着声明，中间不会漏

    为什么要有这个东西，而不是靠注释提醒调用方：
        写操作的第一步往往是 TRUNCATE。自己 new 的线程**不继承 contextvar**，
        忘了显式声明就会安静地回落到默认数据集（demo）并把它清空——
        demo 同时是演示底座和评测基线，清掉不可逆。
        所以把「忘记声明」变成一个立刻抛出的 UnsafeWriteError（见 require_write_scope），
        而不是一次安静的误写。

    进入作用域时会**同时**设置 _current：这样作用域内部更深处的库代码
    （ensure_base_tables、write_fingerprint 等直接调 get_conn() 的地方）
    也跟着走同一个数据集，不必逐层传参。
    """

    def __init__(self, dataset: str):
        self.dataset = _resolve(dataset)
        self._write_token = None
        self._data_token = None

    def __enter__(self) -> str:
        self._write_token = _WRITE_SCOPE.set(self.dataset)
        self._data_token = _current.set(self.dataset)
        logger.info("进入写作用域: %s", self.dataset)
        return self.dataset

    def __exit__(self, *exc) -> None:
        # 先还 _current 再还 _WRITE_SCOPE：顺序反了会让「退出过程中」的日志
        # 报出一个已经失效的数据集
        if self._data_token is not None:
            _current.reset(self._data_token)
        if self._write_token is not None:
            _WRITE_SCOPE.reset(self._write_token)
        self._write_token = self._data_token = None

    def _recreate_cm(self):
        # 作为装饰器复用时，contextlib 会调用它拿一个「新的」上下文管理器。
        # 不复用同一个实例，否则并发进入时 token 会互相覆盖。
        return type(self)(self.dataset)


def require_write_scope(operation: str) -> str:
    """
    写操作入口的第一行调用；返回本次要写入的数据集名

    没有显式声明就抛 UnsafeWriteError。**不给默认值是有意的**——
    默认值会让「忘记声明」表现为「安静地写进 demo」，而这正是要防的事。
    """
    name = _WRITE_SCOPE.get()
    if name is None:
        raise UnsafeWriteError(
            f"{operation} 是写操作（会先清空目标数据集），必须显式声明目标数据集，例如：\n"
            f"    with writes_to('user'):\n"
            f"        {operation}(...)\n"
            f"或给线程入口加装饰器 @writes_to('user')。\n"
            f"当前默认数据集是 {DEFAULT_DATASET}，它同时是演示底座与评测基线——"
            f"不声明就执行会把它清空，所以这里直接拒绝而不是替你选。"
        )
    return name


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


# ================= 只读连接（Text2SQL 专用） =================
# 为什么要单独一套连接，而不是给 get_conn 加参数：
#   查询路与写入路（ingest / 构建）用的是同一个数据集，但**权限必须不同**。
#   共用一条超级用户连接意味着 LLM 生成的任何 SQL 都具备写权限，
#   应用层正则一旦被绕过（双引号表名、不带 FROM 的函数调用）就没有第二道防线。
#   这里让查询路走独立的只读账号，数据库权限成为真正的边界。
_ro_conns: dict[str, "psycopg2.extensions.connection"] = {}
# 已建角色 + 授权的数据集（进程级）。授权本身是持久的，这里只避免重复发 DDL。
_ro_ready: set[str] = set()


def readonly_params(dataset: str | None = None) -> dict:
    """只读连接参数：与数据集连接同库同地址，仅换成只读账号"""
    name = _resolve(dataset)
    return {
        **DATASETS[name],
        "user": READONLY_DB_USER,
        "password": READONLY_DB_PASSWORD,
    }


def ensure_readonly_access(dataset: str | None = None) -> str:
    """
    幂等创建只读账号并授权当前数据集库；返回数据集名

    做三件事（全程用管理员连接，只发权限语句，不碰业务数据）：
      1. 角色：不存在则 CREATE，存在则 ALTER（保证密码与配置一致）；
      2. 库级：GRANT CONNECT，否则只读账号连不上这个库；
      3. 库内：USAGE + SELECT ON ALL TABLES + 默认权限，
         「默认权限」让后续 ingest 新建的表也自动可读。

    只读账号没有任何写权限（NOSUPERUSER / NOCREATEDB / NOCREATEROLE），
    这就是 Text2SQL 那条路的最终边界。
    """
    name = _resolve(dataset)
    if name in _ro_ready:
        return name

    cfg = DATASETS[name]
    dbname = cfg["dbname"]
    role = sql.Identifier(READONLY_DB_USER)

    # 建角色 / 改密码 / 库级 CONNECT 都要在维护库执行
    admin = psycopg2.connect(**{**cfg, "dbname": "postgres"})
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READONLY_DB_USER,))
            action = "ALTER" if cur.fetchone() is not None else "CREATE"
            cur.execute(
                sql.SQL(
                    "{action} ROLE {role} WITH LOGIN NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOINHERIT PASSWORD {pwd}"
                ).format(
                    action=sql.SQL(action),
                    role=role,
                    pwd=sql.Literal(READONLY_DB_PASSWORD),
                )
            )
            cur.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {db} TO {role}").format(
                    db=sql.Identifier(dbname), role=role
                )
            )
    finally:
        admin.close()

    # 表级权限必须在目标库内授权
    conn = psycopg2.connect(**cfg)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {role}").format(role=role))
            cur.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}").format(role=role)
            )
            cur.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                    "GRANT SELECT ON TABLES TO {role}"
                ).format(role=role)
            )
    finally:
        conn.close()

    _ro_ready.add(name)
    logger.info("只读账号 %s 已就绪（数据集 %s / 库 %s）", READONLY_DB_USER, name, dbname)
    return name


def get_readonly_conn(dataset: str | None = None):
    """
    取只读账号的连接（Text2SQL 专用）；不传则用当前 contextvar 里的数据集

    首次访问某数据集时会先确保账号与授权存在——换机器、老环境没跑过
    init_db 时也能自愈，而不是让 SQL 路直接不可用。
    """
    name = _resolve(dataset)

    if name not in _ro_ready:
        ensure_readonly_access(name)

    conn = _ro_conns.get(name)
    if conn is not None and not conn.closed:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.rollback()  # 探活后立即清理事务
            return conn
        except Exception as e:
            logger.warning("只读连接（数据集 %s）探活失败，准备重连: %s", name, e)
            try:
                conn.close()
            except Exception:
                pass
            _ro_conns.pop(name, None)

    logger.info("建立新的只读数据库连接（数据集 %s / 账号 %s）...", name, READONLY_DB_USER)
    conn = psycopg2.connect(**readonly_params(name))
    register_vector(conn)
    _ro_conns[name] = conn
    return conn


def dataset_lock(dataset: str | None = None) -> threading.RLock:
    """
    取某个数据集的互斥锁（可重入）

    为什么需要它：psycopg2 的连接**不是线程安全的**。构建任务在线程里逐批
    INSERT 并 commit，若此时另一个线程拿着同一条连接跑查询，会撞上
    「another command is already in progress」——而且是在用户点查询的瞬间随机炸。

    所以约定：**谁在动这个数据集，谁就持锁一整段**——构建线程从第一行持到结束，
    查询线程从试探成功持到答案生成完（**不是试探一下就放**）。
    拿不到锁的一方立刻明确回绝（构建回 409、查询回「正在重建」），而不是硬闯。
    这既避免了崩溃，也正好符合产品的期望（构建中本来就不该查询）。

    ⚠ 查询从「试探一下就放」改成「整段持有」是 M2 第 4 步的改动：
    在此之前向导的答案是内存里的假文本，试探完就放没有代价；
    接上真实 pipeline 后一次问答要读库十几秒，那个窗口足以让构建挤进来，
    两条线程共用同一条连接——崩溃变成随机的，且在用户点击的瞬间才发生。
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

    # 只读连接是另一套句柄，必须一并关掉，否则「进程退出但连接还在」
    ro_names = [_resolve(dataset)] if dataset else list(_ro_conns)
    for name in ro_names:
        conn = _ro_conns.pop(name, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
