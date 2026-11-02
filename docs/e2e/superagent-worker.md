# 独立 Worker 与 PostgreSQL 队列

> 日期：2026-11-02 · 状态：独立进程 + PG SKIP LOCKED + 租约续期 + 死信 真实 E2E 通过

## 1. 两种运行模式

### 单机模式（默认）

```text
API 进程内 dispatcher + ThreadPoolExecutor
QIANKE_QUEUE_BACKEND=sqlite
```

### 独立 Worker 模式

```text
API：只入队，不执行
Worker：独立进程领队执行
```

API：

```bash
QIANKE_SUPERAGENT_QUEUE_DISPATCHER=0
QIANKE_QUEUE_BACKEND=postgres
```

Worker：

```bash
python scripts/sa_worker.py
```

## 2. PostgreSQL 队列

环境变量：

```bash
QIANKE_QUEUE_BACKEND=postgres
QIANKE_QUEUE_PG_HOST=127.0.0.1
QIANKE_QUEUE_PG_PORT=5432
QIANKE_QUEUE_PG_USER=postgres
QIANKE_QUEUE_PG_PASSWORD=...
QIANKE_QUEUE_PG_DB=rag_auth
```

表：

```text
sa_queue.sa_job
```

领取：

```sql
FOR UPDATE SKIP LOCKED
```

支持：

```text
多 Worker 并发领取
PENDING / RUNNING / DONE / FAILED / DEAD
attempts / max_attempts
lease_until / worker_id
available_at 延迟重试
```

## 3. 租约与心跳

```text
领取时 lease_until = now + 1800s
执行中每 60s renew_lease
进程崩溃 → 租约过期 → 其他 Worker 重新领取
超过 max_attempts → DEAD
```

## 4. 独立 Worker

```bash
python scripts/sa_worker.py
```

循环：

```text
claim_next_job
→ 执行 _execute_claimed
→ 心跳续租
→ finish DONE / FAILED / retry
```

支持 SIGINT / SIGTERM 优雅退出。

## 5. 真实 E2E

### PostgreSQL 队列操作

```text
enqueue: saj_603435cbc9c945fd / PENDING
claim:   RUNNING / attempts=1 / worker_id=pg-worker-1
renew:   True
finish:  DONE
```

### 独立 Worker 进程

准备：

```text
work_item: saw_f089f4c5230443df
job:       saj_d6ff2deeb6fc4652
backend:   postgres
```

Worker 日志：

```text
Super-agent 独立 Worker 启动 worker_id=ZZQ-43300-189c69
Super-agent Worker 领取 job=saj_d6ff2deeb6fc4652
```

结果：

```text
job:  DONE / attempts=1
item: WAITING_APPROVAL
action: CANCEL_ORDER
```

证明 API 不执行，独立进程能消费 PG 队列并完成调查。

## 6. 测试

```bash
pytest tests/test_superagent.py -q
# 16 passed
```

新增覆盖：

```text
claim_next_job 原子领取
renew_lease 只允许持有者续租
租约过期 + max_attempts → DEAD
```

完整套件：

```text
617 passed, 5 skipped, 1 warning
```

## 7. 队列可观测性与死信重放

```text
GET  /api/superagent/jobs?status=DEAD&kind=WORKER&limit=50
GET  /api/superagent/jobs/stats
POST /api/superagent/jobs/{job_id}/replay
```

`/jobs` 返回：

```text
jobs 列表 + stats 汇总
```

`/jobs/stats`：

```text
total / pending / running / done / failed / dead
oldest_pending_at
```

重放规则：

```text
只允许 DEAD / FAILED
attempts 归零
status → PENDING
清空 lease_until / worker_id / last_error
API 内置 dispatcher 会立即尝试领取
独立 Worker 模式下由 Worker 下一轮领取
```

真实冒烟：

```text
dead job: saj_c42054cd8681437b / DEAD
stats.dead: 1
replay: 200 / PENDING / attempts=0
replay again: 409 / Job 状态为 RUNNING（dispatcher 已领取）
```

## 8. 回滚

```bash
unset QIANKE_QUEUE_BACKEND
unset QIANKE_SUPERAGENT_QUEUE_DISPATCHER
```

恢复 SQLite + API 内置 dispatcher，不需要迁移数据；PG 表可保留。

## 9. 已知限制

```text
PG 表固定 sa_queue.sa_job，没有迁移版本管理
Redis 队列未接入
Worker 没有 Prometheus 指标
API 和 Worker 必须共享同一个 C 端控制面数据库
多 Worker 的公平性/优先级未实现
死信只有状态，没有重放接口
租约续期依赖进程存活
```
