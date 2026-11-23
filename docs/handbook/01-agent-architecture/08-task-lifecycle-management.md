---
title: Task Manager 任务生命周期管理
description: 从 WorkItem、Job、Claim、Lease、Retry、审批到执行审计，解释长任务生命周期；对照 Qianke Super-agent 的独立任务队列
section: Agent Architecture
section_order: 1
order: 8
slug: task-lifecycle-management
doc_status: 草稿
implementation_status: 已实现 + 部分实现
version: 0.1.0
updated: 2026-11-23
reading_minutes: 14
prerequisites:
  - 队列与 Worker
  - 幂等
  - 审批
tags:
  - Agent
  - Task
  - Queue
related:
  - agent-runtime
  - human-in-the-loop
  - enterprise-agent-architecture
---

# Task Manager 任务生命周期管理

> 交互式 Agent 是“请求—响应”；长任务需要“入队—领取—租约—重试—审批—执行—审计”。
> 本文以 Qianke Super-agent 的独立任务链路为例，说明任务生命周期与 Agent Runtime 的边界。

## 1. 为什么需要 Task Manager

同步 `/api/agent/run` 适合：

```text
交互式分析
分钟级以内
用户愿意等待
```

不适合：

```text
长调查
批量处理
审批后异步执行
Worker 重启恢复
```

如果没有任务层：

```text
请求超时后状态丢失
重复提交会重复执行
Worker 崩溃后任务卡住
审批和执行没有统一状态
```

## 2. 任务与 Job 的区别

```text
WorkItem：业务任务（调查订单、售后、审批）
Job：执行任务（Worker/ACTION）
Attempt：一次执行尝试
```

一个 WorkItem 可能对应多个 Job/Attempt。

## 3. Qianke 当前 Super-agent 链路

```mermaid
flowchart LR
    EV["事件/路由"] --> WI["WorkItem"]
    WI --> Q["Job Queue"]
    Q --> W["Worker"]
    W --> R["调查结果"]
    R --> AP["审批"]
    AP --> EX["Action 执行"]
    EX --> AU["审计"]
```

代码：

```text
src/rag_demo/superagent/store.py
src/rag_demo/superagent/queue_pg.py
src/rag_demo/superagent/runtime.py
src/rag_demo/superagent/worker.py
```

注意：

```text
这条链路不是主 /api/agent/run 的队列；
主 Agent 也没有被改成“所有请求先入队”。
```

## 4. 状态机

WorkItem 常见状态：

```text
PENDING
RUNNING
WAITING_APPROVAL
DONE
FAILED
CANCELLED
STUCK
EXECUTION_FAILED
REJECTED
```

Job：

```text
PENDING
RUNNING
DONE
FAILED
DEAD
```

原则：

```text
状态只能通过明确条件迁移
终态不能被后续 Worker 覆盖
Watchdog 标记 STUCK，不自动伪造完成
```

## 5. Claim 与 Lease

```text
Worker 领取 Job → status=RUNNING
worker_id + lease_until
心跳续租
租约过期 → 重新可领取 / 或 DEAD
```

Qianke：

```text
claim_next_job
renew_lease
requeue_expired_jobs
scan_stuck_work_items
```

这些机制解决：

```text
多 Worker 并发
Worker 崩溃
长时间任务
重复领取
```

## 6. Retry 与死信

```text
可重试：临时失败 / 租约过期
不重试：终态、审批拒绝、用户取消
max_attempts 后 DEAD
需人工重放/对账
```

不能：

```text
无限重试
把失败终态重试成成功
重试写动作没有幂等
```

## 7. 审批与执行

```text
Worker 生成调查结果/动作建议
→ 写入审批
→ 人工批准/拒绝
→ ACTION Job
→ 执行
→ 审计
```

关键：

```text
审批的是同一个动作参数，不能被替换
执行要有幂等键
执行结果写回审计
```

## 8. Qianke 当前状态

已实现（独立 Super-agent 链路）：

```text
WorkItem / Job 表
原子 claim / lease / retry / DEAD
Worker 恢复
审批动作
执行审计
```

部分实现：

```text
跨任务统一看板
统一任务资源配额
与主 Agent Runtime 的统一任务抽象
```

规划中：

```text
通用 Task Manager 服务
跨 B/C/A 任务编排
```

## 9. 与 Agent Runtime 的边界

```text
Runtime：一次执行内的循环
Task Manager：一次任务从创建到完结
Queue：任务执行资源调度
Approval：业务风险控制
```

不要用 Runtime 代替任务队列，也不要用队列代替 Agent Runtime。

## 10. 常见误区

1. 所有请求都先入队，导致交互延迟。
2. Worker 无租约，崩溃后任务永久 RUNNING。
3. 重试没有幂等。
4. 审批后重新生成动作参数。
5. Watchdog 自动把 STUCK 改成 DONE。
6. 任务状态与业务动作状态混成一个字段。

## 11. 总结

```text
任务生命周期需要：
明确状态机
claim/lease
超时/重试/死信
审批与执行分离
审计与恢复
```

Qianke 的 Super-agent 已有独立任务/队列/审批/审计链路；
统一 Task Manager 仍是演进方向。

## 12. 延伸阅读

- [Agent Runtime 设计](03-agent-runtime.md)
- [Agent Orchestrator 设计](04-agent-orchestrator.md)
- `src/rag_demo/superagent/`
- `docs/agent-design-current-vs-target.md`
- PostgreSQL `FOR UPDATE SKIP LOCKED`：<https://www.postgresql.org/docs/>
