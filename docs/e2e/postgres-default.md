# PostgreSQL 连接池 / Alembic / 默认后端 E2E

> 日期：2026-11-01 · 状态：通过（真实 PostgreSQL 16）

## 1. 连接池

`PostgresMerchantRepository` 已从短连接切换为：

```text
psycopg2.pool.ThreadedConnectionPool
默认 min=1 / max=8
QIANKE_MERCHANT_PG_POOL_MIN / POOL_MAX 可配
```

生命周期：

```text
读操作 -> ROLLBACK -> putconn
写事务 -> COMMIT/ROLLBACK -> putconn
close() -> closeall()
```

真实验证：

```text
backend postgres schema merchant_v1 products 18
pool True max 8
```

专项测试：

```bash
pytest tests/test_merchant_postgres.py -q
# 18 passed
```

## 2. Alembic

新增：

```text
alembic.ini
alembic/env.py
alembic/versions/0001_merchant_v1.py
```

命令：

```bash
QIANKE_MERCHANT_PG_SCHEMA=qianke_alembic_xxx \
  uv run alembic upgrade head
```

实测：

```text
INFO  Context impl PostgresqlImpl
INFO  Running upgrade  -> 0001_merchant_v1, merchant_v1 baseline
tables: alembic_version, m_inventory, m_meta, m_order,
        m_order_item, m_product, m_reservation, m_sku
version: 0001_merchant_v1
```

迁移只创建独立 schema 的表；`alembic_version` 也在该 schema，不写 public。

## 3. PostgreSQL 默认

`QIANKE_MERCHANT_BACKEND` 未设置时：

```text
postgres
```

SQLite 显式回退：

```bash
QIANKE_MERCHANT_BACKEND=sqlite
```

测试隔离：

```text
tests/conftest.py 强制离线套件使用 SQLite
PG 专项测试自己选择 postgres + 唯一 schema
```

## 4. 真实 C 端下单（默认 PG）

启动 API（不设置 backend）后：

```text
order_5695476eb1c8441e
merchant_status CREATED
merchant_source merchant_v1
P003 库存 50 -> 49
backend postgres
```

说明 C 端 `prepare_order` / `confirm_order` 已真实写入 PostgreSQL 商家库。

## 5. 测试与构建

```bash
pytest tests/ -q
# 572 passed, 5 skipped, 1 warning
```

前端未改，沿用上一轮 build。

## 6. 已知限制

```text
C 端订单库仍是 SQLite；切换只针对商家数据层
连接池是进程内池，不做跨进程/跨机器
Alembic 只有 merchant_v1 基线，没有历史版本回放
API 启动不自动执行 alembic upgrade，需部署时显式执行
无 PG 环境需显式设置 QIANKE_MERCHANT_BACKEND=sqlite
没有连接池健康检查/自动重连策略（getconn 失败会抛出结构化 MERCHANT_UNAVAILABLE）
```
