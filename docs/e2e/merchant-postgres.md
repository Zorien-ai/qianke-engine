# PostgreSQL 商家 adapter E2E

> 日期：2026-10-31 · 状态：通过（PostgreSQL 16 + C 端下单真实链路）

## 1. 配置

```bash
QIANKE_MERCHANT_BACKEND=postgres
QIANKE_MERCHANT_PG_HOST=127.0.0.1
QIANKE_MERCHANT_PG_PORT=5432
QIANKE_MERCHANT_PG_USER=postgres
QIANKE_MERCHANT_PG_PASSWORD=123456
QIANKE_MERCHANT_PG_DBNAME=vec_db
QIANKE_MERCHANT_PG_SCHEMA=merchant_v1
```

SQLite 仍是默认；不设置 `QIANKE_MERCHANT_BACKEND` 时行为不变。

## 2. 实测 C 端下单链路

使用独立 schema `qianke_probe_<uuid>`，跑完后 DROP SCHEMA：

```text
backend postgres schema qianke_probe_399d6ca64c

C 端 prepare_order
→ draft_09cec155d8d5466c
→ 商家预占 draft_09cec155d8d5466c

C 端 confirm_order
→ order_fb8b54a6ed2a4ae2
→ merchant_status CREATED
→ merchant_source merchant_v1

PostgreSQL merchant order
→ order_fb8b54a6ed2a4ae2
→ status CREATED

库存
→ 20 → 19
```

## 3. 自动化测试

```bash
pytest tests/ -q
# 536 passed, 5 skipped, 1 warning
```

PostgreSQL 专项：

```bash
pytest tests/test_merchant_postgres.py -q
# 13 passed（真实 PG16）
```

无 PG 时：

```bash
QIANKE_MERCHANT_PG_PORT=1 pytest tests/test_merchant_postgres.py -q
# 13 skipped
```

覆盖：

```text
seed / schema / 表隔离
商品 / SKU / 库存 / 订单读
reserve / commit / release
create_order
update_order_status
cancel_order + 库存补偿
refund_order 部分退款
租户隔离 / limit
并发预占不超卖（FOR UPDATE）
factory env 切换
seed(force=True)
```

## 4. 已知限制

- 仍不是真实 OMS；只是把本地 SQLite 数据层替换为 PostgreSQL。
- 短连接，无连接池/读写分离/主从/分片；生产高并发需连接池与超时治理。
- schema/DDL 由 adapter 幂等初始化；生产建议迁移工具（Alembic/Flyway）+ 受限账号。
- 金额/时间以 TEXT 与 SQLite 语义对齐；BI 可另建 NUMERIC/TIMESTAMPTZ 视图。
- 无库存流水/价格历史/退款流水表；退款仍是本地模拟。
