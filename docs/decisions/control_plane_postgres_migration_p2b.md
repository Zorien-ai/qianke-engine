# 控制面 PostgreSQL 迁移 P2-B：Super-agent 运行时切换

> 日期：2026-11-05 · 状态：已在本机执行 sa_* 维护窗口切换；API 因 8000 端口被 WinNAT 动态排除，临时运行在 8080

## 1. 运行时开关

```bash
QIANKE_CONTROL_BACKEND=postgres
QIANKE_CONTROL_PG_SCHEMA=qianke_control
QIANKE_QUEUE_BACKEND=postgres
QIANKE_QUEUE_SCHEMA=sa_queue
QIANKE_QUEUE_PG_DB=vec_db
```

队列默认库已与控制面统一到 `vec_db`；旧部署仍可用 `QIANKE_QUEUE_PG_DB` 指回独立库。

- `QIANKE_CONTROL_BACKEND=sqlite` 保持原行为
- 切换需要重启 API/Worker
- C 端交易/IM 表仍走 SQLite（P3 再迁）

## 2. 实现方式

`superagent/store.py` 增加：

```text
_control_pg_enabled()
_connect()            # PG 兼容连接 / SQLite 原连接
init()                # PG 初始化 qianke_control schema
_queue_is_pg()        # control=postgres 时队列也走 sa_queue
```

新增：

```text
src/rag_demo/control/pg_compat.py
```

PG 兼容层覆盖：

```text
? → %s
BEGIN IMMEDIATE → BEGIN
json_extract(...) → jsonb ->>
行返回 dict
search_path 指向控制面 schema
```

SQLite 差异修复：

```text
INSERT OR REPLACE → ON CONFLICT DO UPDATE
json_set → 应用层合并 result JSON
CASE WHEN ? → CASE WHEN ? = 1
审计时间范围 → PG timestamptz 比较
```

队列：

```text
control=postgres → 自动使用 sa_queue
QIANKE_QUEUE_SCHEMA 可覆盖测试 schema
```

## 3. 验证

### 3.1 模块级 PG 烟测

```bash
python scripts/smoke_control_pg.py
```

结果：

```text
create_trigger  → Thread/WorkItem
start           → RUNNING
finish          → WAITING_APPROVAL
decide          → EXECUTING
complete        → DONE
approval        → EXECUTED
audit_total     → 1
job enqueue     → PENDING
claim           → RUNNING
finish_job      → DONE
ok=true
```

### 3.2 API 级 PG 烟测

临时端口 `8011`，临时 schema：

```text
GET /ready → 200
status=ok
control_store 4.63ms
superagent_store 34.21ms
queue 54.98ms
merchant_store 52.00ms

GET /metrics → 200
```

`/ready` 现在检查 `control_store`（按 backend 选择 SQLite/PG），不再固定检查 SQLite。

### 3.3 切换预演

```bash
python scripts/rehearse_control_pg_switch.py
```

结果：

```text
SQLite → 临时 PG schema
sa_thread     371
sa_trigger    375
sa_work_item  372
sa_approval   366
sa_job        348
target 全部一致

PG 写审批流：
write_status=DONE
approval=EXECUTED
audit_total=28
ok=true

结束后 DROP 临时 schema
```

### 3.4 测试

```text
pytest tests/test_superagent_pg_control.py -q
# 3 passed

完整套件
# 657 passed, 5 skipped, 1 warning
```

覆盖：

```text
PG 创建 Trigger/Thread/WorkItem
start/finish/decide/complete
审计查询（动作过滤/未来日期 0 条）
审批幂等
队列 enqueue/claim/finish
```

## 4. 切换 runbook（本次已按此执行）

```text
1. 备份 SQLite（backup_control_plane.py）
2. 停 API/Worker
3. python scripts/migrate_superagent_to_pg.py --yes
   校验 target 计数
4. 设置环境变量
   QIANKE_CONTROL_BACKEND=postgres
   QIANKE_CONTROL_PG_SCHEMA=qianke_control
   QIANKE_QUEUE_BACKEND=postgres
   QIANKE_QUEUE_SCHEMA=sa_queue
5. 启动 API/Worker
6. /ready 200，检查 WorkItem/审批/队列
7. 观察 24h
8. 回滚：恢复环境变量为 sqlite，重启，恢复 SQLite 备份
```

注意：切换后新写入不会自动回到 SQLite；维护窗口内切换。

## 5. 本机实际切换（2026-11-05）

```text
备份：backups/20261105-144618/c_end_mock.sqlite
回填：
  sa_thread     371
  sa_trigger    375
  sa_work_item  372
  sa_approval   366
  sa_queue.sa_job 348
目标计数全部一致
```

启动：

```bash
QIANKE_CONTROL_BACKEND=postgres
QIANKE_CONTROL_PG_SCHEMA=qianke_control
QIANKE_QUEUE_BACKEND=postgres
QIANKE_QUEUE_SCHEMA=sa_queue
QIANKE_QUEUE_PG_DB=vec_db
```

/ready：

```text
control_store     34.12ms
superagent_store  37.28ms
queue             74.16ms
merchant_store    87.52ms
status=ok
```

/metrics：

```text
qianke_queue_jobs{status="done"} 348
qianke_work_items{status="waiting_approval"} 347
```

B 工作台实测：

```text
Super-agent 工作项 共 50 项
数据来自 PostgreSQL qianke_control
```

端口问题：

```text
8000 被 Windows 动态排除段 7942–8041 占用
无法绑定；本次 API 运行在 8080
需管理员清理端口排除或重启后刷新 WinNAT，才能恢复 8000
```

观察期：尚未满 24h，需继续观察 `/ready`、队列、审计、审批。

观察脚本：

```bash
python scripts/observe_control_pg.py --once
python scripts/observe_control_pg.py --duration 86400 --interval 60
```

输出：

```text
logs/control_pg_observation.jsonl
```

本机已采样 3 次：

```text
ready 200
queue_done 348
waiting_approval 347
stuck 1
```


## 6. 已知限制（切换后）

```text
C 端交易/IM 仍在 SQLite
没有双写
没有行锁级别的并发保护
PG 兼容层只覆盖当前 SQL 子集
JSON/TEXT 类型尚未规范化
每请求新建 PG 连接，性能未优化
没有真正执行生产切换
```

## 7. 下一步

```text
1. 维护窗口真实切换 sa_*
2. 观察 /ready、队列、审计、审批
3. P3：c_* 交易/IM 表迁移
4. 类型规范化：JSONB / TIMESTAMPTZ / BOOLEAN
5. 连接池与并发压测
```
