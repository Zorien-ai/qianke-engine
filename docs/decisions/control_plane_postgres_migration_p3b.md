# 控制面 PostgreSQL 迁移 P3-B：C 端运行时切换

> 日期：2026-11-05 · 状态：C 端 store 已可切 PostgreSQL；API 已按 PG 运行

## 1. 开关

```bash
QIANKE_CEND_BACKEND=postgres
QIANKE_CONTROL_PG_SCHEMA=qianke_control
```

默认 `sqlite`，切换需重启 API。

## 2. 实现

`c_end/store.py`：

```text
_cend_pg_enabled()
_ensure_pg_schema()
_connect()  → PG 兼容连接 / SQLite 原连接
init()      → PG schema 初始化后返回
```

`social.py` / `group.py` / `idempotency.py`：

```text
PG 模式跳过 executescript / PRAGMA，复用 control schema
```

`control/pg_compat.py` 新增：

```text
INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
字面量 % 转义（c_order LIKE 'order_%'）
```

策略审计时间过滤：

```text
(changed_at)::timestamptz 比较
```

## 3. 验证

C 端 store PG 契约测试：

```bash
pytest tests/test_cend_pg_runtime.py -q
# 1 passed
```

覆盖：

```text
list_products
list_tenants
list_all_orders
create_quote / get_quote
```

API 实测（8080，PG C 端）：

```text
/ready 200
/api/c/products 200，6 件商品
/v2/#/c 商品目录正常
/v2/#/c/orders 订单列表正常，含售后/物流状态
```

## 4. 切换步骤

```text
1. 停 API
2. 备份 SQLite
3. migrate_cend_to_pg.py --yes（最终同步）
4. QIANKE_CEND_BACKEND=postgres
5. 启动 API
6. 检查 /api/c/products、/api/c/orders、B 工作台
```

## 5. 当前边界

```text
C 端已读 PG；写入路径已通过 create_quote 测试
尚未做高并发库存/订单压测
C 端 IM WebSocket 仍走原有服务（未改）
SQLite 仅保留开发回退
```

## 6. 回滚

```text
停 API
QIANKE_CEND_BACKEND=sqlite
启动 API
恢复切换前 SQLite 备份
```
