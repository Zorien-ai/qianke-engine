# 控制面 PostgreSQL 迁移方案 v0.1

> 日期：2026-11-04 · 状态：方案设计（未实施）· 范围：C 端 mock + Super-agent 控制面

## 1. 结论

```text
继续使用 PostgreSQL
不换数据库
把控制面 SQLite（var/c_end_mock.sqlite）迁移到 PostgreSQL
```

目标：

```text
多实例 API/Worker 共享同一控制面
订单/审批/执行具备事务与行锁
备份/恢复/监控统一到 PostgreSQL
SQLite 保留为本地开发回退
```

## 2. 现状

### 2.1 已使用 PostgreSQL

```text
商家商品/订单/库存  vec_db.merchant_v1
登录/账号           rag_auth（独立 DB）
Super-agent 队列    sa_queue（QIANKE_QUEUE_BACKEND=postgres 时）
RAG 向量/知识库     PostgreSQL + pgvector
```

### 2.2 仍在 SQLite

控制面文件：

```text
var/c_end_mock.sqlite
大小约 2.76 MB
28 张表
约 2,332 行
```

表清单：

| 表 | 行数 | 用途 |
|---|---:|---|
| c_product | 6 | 商品 |
| c_order | 145 | C 端订单 |
| c_order_item | 145 | 订单明细 |
| c_after_sale | 29 | 售后工单 |
| c_compensation | 1 | 补偿记录 |
| c_quote | 15 | 谈判报价 |
| c_message | 71 | 好友消息 |
| c_app_message | 15 | C App 会话 |
| c_friend | 2 | 好友 |
| c_group | 1 | 群 |
| c_group_member | 3 | 群成员 |
| c_group_message | 12 | 群消息 |
| c_mention | 10 | @ 提及 |
| c_thread_read | 4 | 会话已读 |
| c_companion | 1 | 伙伴形象 |
| c_client_request | 18 | 客户端幂等 |
| c_reconciliation_run | 12 | 对账运行 |
| c_reconciliation_alert | 1 | 对账告警 |
| c_merchant_tenant | 3 | 租户 |
| c_merchant_member | 2 | 租户成员 |
| c_merchant_policy | 2 | 动作策略 |
| c_merchant_policy_audit | 1 | 策略审计 |
| c_tenant_provision | 1 | 开通记录 |
| sa_thread | 371 | 会话线程 |
| sa_trigger | 375 | 事件 |
| sa_work_item | 372 | 工作项 |
| sa_approval | 366 | 审批 |
| sa_job | 348 | Job（SQLite 队列时） |

### 2.3 代码依赖

```text
c_end/store.py        2,744 行
superagent/store.py   1,044 行
? 占位符             437 处
BEGIN IMMEDIATE       31 处
INSERT OR REPLACE     1 处
INSERT OR IGNORE      3 处
ON CONFLICT           5 处
json_set              1 处
json_extract          2 处
PRAGMA table_info     6 处
datetime()/date()     10 处
rowcount              5 处
```

## 3. 目标架构

```text
PostgreSQL 实例（现有）
├── rag_auth             登录/账号（已存在，独立 DB）
├── vec_db
│   ├── merchant_v1      商家数据（已存在）
│   ├── sa_queue         Super-agent Job 队列（已存在）
│   └── qianke_control   新增：控制面
└── SQLite fallback      var/c_end_mock.sqlite（仅开发）
```

理由：

```text
复用现有 PG 实例和连接池经验
schema 隔离，避免与 merchant_v1 混表
不跨 DB JOIN，auth 仍按 account_id 应用层关联
pg_dump 可一次备份 vec_db
```

如果合规要求更强隔离，可把 `qianke_control` 放到独立数据库；本方案默认同实例独立 schema。

## 4. 表与类型映射

### 4.1 类型策略

分两阶段，避免一次性大爆炸：

```text
阶段 A（兼容）：TIMESTAMP/TEXT 仍存 ISO 字符串，JSON 存 JSONB 但 adapter 返回 JSON 字符串
阶段 B（规范化）：TIMESTAMPTZ、JSONB dict、BOOLEAN
```

目标类型：

| SQLite | PostgreSQL（阶段 B） | 备注 |
|---|---|---|
| TEXT id | TEXT | 保留现有 ID |
| TEXT 时间 | TIMESTAMPTZ | 统一 UTC |
| REAL 金额 | NUMERIC(12,2) | 不再用浮点 |
| INTEGER 0/1 | BOOLEAN | adapter 转换 |
| TEXT JSON | JSONB | 查询用 `->>` / `@>` |
| INTEGER | INTEGER/BIGINT | 按量级 |

阶段 A 用兼容类型落地，先保证行为一致，再逐步收紧。

### 4.2 约束与索引

必须保留：

```text
c_order.idempotency_key UNIQUE
c_order_item PK(order_id, product_id) + FK
c_after_sale OPEN 唯一部分索引
c_compensation.order_id UNIQUE
c_merchant_member.account_id PK
sa_thread.thread_key UNIQUE
sa_approval.work_item_id UNIQUE
sa_job(work_item_id, kind) UNIQUE
sa_job(status, available_at) 索引
sa_work_item(status, created_at DESC) 索引
```

迁移前先查孤儿数据：

```sql
SELECT COUNT(*) FROM c_after_sale a
LEFT JOIN c_order o ON o.order_id = a.order_id
WHERE o.order_id IS NULL;
```

有孤儿时先修数据，再加 FK。

### 4.3 Job 表特殊处理

当前有两套 `sa_job`：

```text
SQLite 控制面 sa_job
PostgreSQL sa_queue.sa_job
```

迁移原则：

```text
启用 QIANKE_QUEUE_BACKEND=postgres 后
sa_queue.sa_job 是唯一权威
SQLite sa_job 只做一次性回填，不再双写
```

不要迁移成 `qianke_control.sa_job`，否则又出现两套队列。

## 5. 代码改造

### 5.1 Repository 层

新增：

```text
rag_demo/control/repository.py      接口
rag_demo/control/sqlite_repository.py
rag_demo/control/postgres_repository.py
rag_demo/control/factory.py
```

`c_end/store.py` 与 `superagent/store.py` 保留函数签名，内部委托 repository：

```text
QIANKE_CONTROL_BACKEND=sqlite|postgres
```

这样 API/Worker 不感知底层。

### 5.2 SQLite 方言改造清单

| 方言 | 改造 |
|---|---|
| `?` 占位符 | 按 backend 生成 `%s` 或统一用命名参数 |
| `BEGIN IMMEDIATE` | PG 用 `BEGIN` + 行锁/唯一约束 |
| `INSERT OR REPLACE` | `INSERT ... ON CONFLICT ... DO UPDATE` |
| `INSERT OR IGNORE` | `INSERT ... ON CONFLICT DO NOTHING` |
| `json_set` | `jsonb_set` 或应用层合并后整列更新 |
| `json_extract` | `->>` / `#>>` |
| `PRAGMA table_info` | `information_schema.columns` |
| `datetime()` / `date()` | `timestamptz` 比较或 `date_trunc` |
| `rowcount` | PG cursor 行为兼容，需测试 |
| SQLite 自动提交 | 统一显式事务边界 |

### 5.3 事务与并发热点

必须逐项加锁/约束：

```text
confirm_order          库存预占 + 幂等键
cancel_order           订单状态迁移
resolve_after_sale     工单状态
receive_after_sale     库存回补
create_compensation    order UNIQUE
enqueue_job            (work_item_id, kind) UNIQUE
claim_next_job         FOR UPDATE SKIP LOCKED（已有 PG 队列）
decide_approval        审批状态 CAS
complete_execution     执行结果只写一次
upsert_merchant_policy 策略并发更新
```

建议：

```text
唯一约束兜底
关键状态迁移用 UPDATE ... WHERE status = ? RETURNING
必要时 SELECT ... FOR UPDATE
不要用 advisory lock 代替业务唯一约束
```

## 6. 回填

脚本：

```text
scripts/migrate_control_to_pg.py
```

流程：

```text
1. 创建 qianke_control schema
2. 按外键顺序建表/索引
3. 分批复制（batch 500）
4. ON CONFLICT (pk) DO NOTHING 保证幂等
5. 校验行数
6. 校验 JSON 合法性
7. 校验外键孤儿
8. 抽样对比关键业务行
9. 输出 manifest（源文件、时间、行数、sha256）
```

顺序：

```text
c_product
→ c_order → c_order_item
→ c_after_sale → c_compensation
→ c_quote → c_message/c_app_message
→ c_friend/c_group/c_group_member/c_group_message
→ c_mention/c_thread_read/c_companion/c_client_request
→ c_reconciliation_run/alert
→ c_merchant_tenant/member/policy/policy_audit/provision
→ sa_thread → sa_trigger → sa_work_item → sa_approval
→ sa_job → sa_queue.sa_job（仅启用 PG 队列时）
```

校验 SQL：

```sql
SELECT COUNT(*) FROM qianke_control.sa_work_item;
SELECT COUNT(*) FROM qianke_control.c_order;
```

## 7. 切换策略

### 7.1 推荐：维护窗口切换（M1）

数据量小，优先简单可靠：

```text
1. 公告维护窗口
2. 停 API / Worker
3. 备份 SQLite
4. 最后一次增量回填
5. 校验
6. 设置 QIANKE_CONTROL_BACKEND=postgres
7. 启动 API / Worker
8. 烟测：登录/租户/下单/审批/队列/审计
9. 保留 SQLite 只读备份
```

停机预计：

```text
10–30 分钟
```

### 7.2 可选：双写（后续）

如果要求零停机：

```text
写 SQLite + 写 PG
读 SQLite
异步比对
逐表切读 PG
最后切写 PG
```

代价：

```text
双写失败补偿
事务边界复杂
需要 mismatch 指标
不建议 M1 首切使用
```

## 8. 回滚

```text
1. 停 API / Worker
2. QIANKE_CONTROL_BACKEND=sqlite
3. 恢复切换前 SQLite 备份
4. 启动 API / Worker
5. 烟测
```

注意：

```text
PG 切换后新写入的数据不会自动回到 SQLite
维护窗口内切换可避免该问题
如果必须零丢失，需要反向增量同步
```

## 9. 阶段计划

| 阶段 | 内容 | 预计 |
|---|---|---|
| P0 | 本方案确认、数据校验、备份 | 0.5 天 |
| P1 | PG schema + repository 骨架 + 双后端 contract tests | 3–5 天 |
| P2 | Super-agent 表迁移 + 队列统一 | 3–4 天 |
| P3 | C 端订单/售后/交易表迁移 | 2–3 天 |
| P4 | IM/群聊/对账/租户/审计迁移 | 2–3 天 |
| P5 | 回填、切换演练、烟测、回滚演练 | 1–2 天 |
| P6 | 全量切 PG，SQLite 只保留开发回退 | 0.5 天 |

单工程师约 2–3 周；可与功能开发并行，但切换需冻结写入窗口。

## 10. 验收标准

```text
[ ] 650+ pytest 全绿（SQLite 后端）
[ ] 新增 PG contract tests 全绿
[ ] 订单确认并发不超卖
[ ] 重复审批只执行一次
[ ] 队列 claim/replay 并发正常
[ ] 回填行数/checksum 一致
[ ] 关键 API 烟测通过
[ ] 备份/恢复演练通过
[ ] 回滚演练通过
[ ] 监控 /ready、队列、审计正常
```

## 11. 风险

| 风险 | 处理 |
|---|---|
| SQLite 事务语义差异 | 逐热点加行锁/唯一约束 |
| 时间/金额类型变化 | 阶段 A 兼容，阶段 B 收紧 |
| 双队列重复 | 统一到 `sa_queue` |
| 孤儿数据 | 迁移前校验/修复 |
| 回滚丢新数据 | 维护窗口切换 |
| 测试只覆盖 SQLite | 双后端 contract tests |
| auth 跨库 | 保持 account_id 应用层关联 |

## 12. 待确认决策

```text
1. qianke_control 放 vec_db 独立 schema，还是独立数据库？
2. 首切是否接受 10–30 分钟维护窗口？
3. 金额是否首切就用 NUMERIC，还是先 DOUBLE PRECISION？
4. 时间是否首切就用 TIMESTAMPTZ，还是先 TEXT？
5. Auth 是否也迁移到同实例（当前 rag_auth 已独立）？
```

建议：

```text
1. 独立 schema
2. 接受维护窗口
3. 首切 NUMERIC
4. 首切 TEXT，第二阶段 TIMESTAMPTZ
5. Auth 不动
```
