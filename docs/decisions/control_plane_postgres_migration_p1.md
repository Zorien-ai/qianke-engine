# 控制面 PostgreSQL 迁移 P1：schema 与 repository 骨架

> 日期：2026-11-04 · 状态：P1 完成 · 决策：全选迁移方案建议

## 1. 本阶段交付

```text
PostgreSQL 目标 schema DDL（28 表 + 索引）
PostgresControlRepository 骨架
SQLiteControlRepository 对照实现
控制面 repository 工厂
双后端 schema 契约测试
```

运行时 API/Worker 尚未接入，P1 只建立可验证的存储底座。

## 2. 文件

```text
src/rag_demo/control/__init__.py
src/rag_demo/control/settings.py
src/rag_demo/control/schema_pg.sql
src/rag_demo/control/postgres_repository.py
src/rag_demo/control/sqlite_repository.py
src/rag_demo/control/factory.py
tests/test_control_repository_contract.py
```

## 3. Schema

目标：

```text
vec_db.qianke_control
28 张表
```

DDL 由现有 SQLite schema 生成并人工校对：

```text
TEXT → TEXT
INTEGER → INTEGER
REAL 金额 → NUMERIC(12,2)
时间暂存 TEXT（兼容阶段）
JSON 暂存 TEXT（兼容阶段）
主键/唯一约束/外键/索引/部分唯一索引
```

关键索引：

```text
idx_c_after_sale_open        部分唯一：OPEN 工单
idx_c_after_sale_order
idx_c_message_owner_friend
idx_c_app_message_owner_thread
idx_c_group_message_owner_group
idx_c_mention_owner_target
idx_c_reconciliation_started
idx_c_reconciliation_alert_open
idx_sa_thread_key            唯一
idx_sa_trigger_thread
idx_sa_work_item_status
idx_sa_approval_work_item    唯一
idx_sa_job_claim
idx_sa_job_work_item         唯一
```

## 4. Repository 骨架

```python
from rag_demo.control import get_control_repository

repo = get_control_repository()  # QIANKE_CONTROL_BACKEND=sqlite|postgres
repo.init_schema()
repo.list_tables()
repo.counts()
repo.health()
repo.close()
```

PostgreSQL 配置：

```text
QIANKE_CONTROL_PG_HOST / PORT / USER / PASSWORD / DBNAME / SCHEMA
回退 RAG_PG_*
默认 dbname=vec_db
默认 schema=qianke_control
```

SQLite 初始化同时覆盖：

```text
c_end.store
superagent.store
c_end.social
c_end.group
c_end.idempotency
```

## 5. 契约测试

```bash
pytest tests/test_control_repository_contract.py -q
# 3 passed
```

覆盖：

```text
SQLite 28 表与期望集合一致
PostgreSQL 28 表与 SQLite 集合一致
PostgreSQL 行数查询覆盖全部表
health 正常
init_schema 幂等
```

PG 测试使用：

```text
唯一 schema：qianke_control_test_<uuid>
测试结束 DROP SCHEMA CASCADE
无 PG 自动 skip
```

完整套件：

```text
653 passed, 5 skipped, 1 warning
```

## 6. 决策落实

```text
✅ qianke_control 独立 schema（vec_db）
✅ M1 首切接受维护窗口
✅ 金额首切 NUMERIC(12,2)
✅ 时间先 TEXT，第二阶段 TIMESTAMPTZ
✅ Auth 保持独立 rag_auth
```

## 7. 已知限制

```text
尚未接入现有 c_end/store.py / superagent/store.py
尚未实现 CRUD repository 方法
尚未实现回填脚本
尚未双写/切换
JSON 字段仍是 TEXT，不是 JSONB
时间字段仍是 TEXT，不是 TIMESTAMPTZ
队列统一到 sa_queue 尚未执行
API/Worker 仍使用 SQLite
```

## 8. 下一步 P2

```text
1. Super-agent 控制表 CRUD repository
2. sa_* 读写切 PG
3. 回填脚本（先 sa_*）
4. 双后端 contract tests 扩展为 CRUD
5. 队列统一到 sa_queue
6. 维护窗口切换预演
```
