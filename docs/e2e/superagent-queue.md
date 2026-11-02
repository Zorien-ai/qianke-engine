# Super-agent 持久化 Worker 队列与重启恢复

> 日期：2026-11-02 · 状态：真实重启恢复 E2E 通过

## 1. 问题

旧实现使用进程内 `ThreadPoolExecutor`：

```text
API 重启 → 正在运行 / 排队中的任务丢失
多实例 → 没有原子领取
失败 → 没有持久化重试状态
```

## 2. sa_job

```sql
CREATE TABLE sa_job (
  job_id, work_item_id, kind,
  status PENDING/RUNNING/DONE/FAILED,
  attempts, max_attempts,
  available_at, lease_until, worker_id,
  last_error, created_at, updated_at
);
UNIQUE(work_item_id, kind)
```

规则：

```text
enqueue 幂等：同一 WorkItem/kind 只有一个 Job
claim 原子：UPDATE ... WHERE PENDING/租约过期
租约默认 1800s
失败重试最多 2 次
超过 max_attempts → FAILED
```

## 3. 启动恢复

```text
API 启动
→ runtime.start_dispatcher()
→ requeue_expired_jobs()
→ pending_jobs()
→ 重新提交执行
```

dispatcher 每 15 秒检查一次：

```text
过期租约 RUNNING → PENDING
PENDING Job → 提交 Worker
```

## 4. 真实 E2E

创建 PENDING Job：

```text
work_item: saw_01379fb59ad74bb2
job:       saj_292505a5a80145b9
status:    PENDING
```

重启 API 后日志：

```text
Super-agent 队列 dispatcher 已启动
Super-agent 队列恢复 requeued=0 pending=1
```

结果：

```text
job:  DONE / attempts=1
item: WAITING_APPROVAL / worker=deepagents
action: CANCEL_ORDER
```

说明重启后 PENDING Job 自动恢复并完成调查。

## 5. 动作执行也走队列

审批通过不再同步执行：

```text
POST /approve
→ status EXECUTING / execution_pending=true
→ ACTION Job 入队
→ Worker 执行白名单动作
→ DONE / EXECUTION_FAILED
→ 企业微信回写结果
```

真实 E2E：

```text
work_item: saw_b6f91832a191447c
order:     order_01f759fee5624ce6
approve:   200 / EXECUTING / execution_pending=true
action job: saj_f38ec163f6414e7a / ACTION / DONE / attempts=1
最终:      DONE / EXECUTED / ticket as_01f378dfc9384b94
```

## 6. API

```text
GET /api/superagent/jobs?limit=50
```

用于观测 Job 状态、attempts、lease、last_error。

## 7. 测试

```bash
pytest tests/test_superagent.py -q
# 13 passed
```

覆盖：

```text
入队幂等
原子 claim
重复 claim 拒绝
租约过期恢复为 PENDING
finish DONE
```

完整套件：

```text
610 passed, 5 skipped, 1 warning
```

## 8. 已知限制

```text
独立 Worker 与 PostgreSQL SKIP LOCKED 已接入，见 superagent-worker.md
队列仍是单机控制面依赖 SQLite WorkItem
dispatcher 模式与独立 Worker 模式二选一
没有优先级、延迟任务 UI、死信重放页面
固定公网域名/可信 IP 仍需人工配置
```
