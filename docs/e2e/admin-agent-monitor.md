# 管理员端本地 LangSmith：Agent 调用监控

日期：2026-11-15  
范围：系统管理员 A 端  
基线：`b-end-2.0-p0`（Agent 调用监控新增）

## 目标

在管理员端提供一个本地 LangSmith 风格的中台：

```text
Agent 调用列表
  → 状态 / 耗时 / Steps / Tools / Tokens / 问题
  → 点击查看 Trace 时间线
  → LLM / Tool / 错误 / 最终回答
```

不依赖外部 LangSmith，不需要 API Key；复用现有控制面 `ai_traces`。

## 采集

在 `rag_demo/agent/service.py::execute_agent` 统一埋点：

```text
begin_trace("agent.execute", account)
  ↓
runner 执行
  ↓
record_trace_usage(total_tokens)
finish_trace(
  status=success/error,
  total_ms=...,
  meta={
    question, request_id, execution_id, status,
    steps, tool_call_count, total_tokens, error,
    tool_calls, final_answer, agent_events,
    attempts, retried
  }
)
```

- 采集失败由 `ai_monitor._safe` 吞掉，不阻断 Agent 主链路。
- 不新增表，复用 `ai_traces` / `ai_spans`。
- `agent_events` 来自 Agent Runtime 的 `event_trace`，保留 LLM / Tool 开始、结束、错误与耗时。

## API（仅系统管理员）

```text
GET /api/admin/agent-traces
  query: range=1h|24h|7d|30d
         status=success|error
         q=问题/request_id/trace_id
         limit / offset

GET /api/admin/agent-traces/{trace_id}
  返回 trace + meta + agent_events
```

权限实测：

```text
匿名：401
企业管理员 / 非系统管理员：403
```

## 页面

路由：

```text
/admin/agent-monitor
```

导航：平台 → Agent 调用监控（仅系统管理员可见）。

页面能力：

```text
概览：调用数 / 成功率 / P95 / Token / 工具调用
列表：时间、入口、问题、状态、耗时、Steps、Tools、Tokens
筛选：1h / 24h / 7d / 30d、状态、关键词
详情：LangSmith 式时间线 + trace/request/execution ID + 错误 + 最终回答
窄屏：详情抽屉全宽，无横向溢出
```

截图：

![Agent 调用列表](docs/design/admin-agent-monitor-list.png)

![Trace 详情](docs/design/admin-agent-monitor-detail.png)

![移动详情](docs/design/admin-agent-monitor-detail-mobile.png)

## 验证

```text
pytest tests/ -q
  → 830 passed, 6 skipped

新增：
  tests/test_agent_monitoring.py
  tests/test_admin_agent_monitor_api.py

web build：PASS

真实写入验证：
  execute_agent 假 runner 写入 1 条 agent.execute trace
  question / total_tokens=123 / tool_call_count=1 可被 agent_traces 查出

页面验证（mock 系统管理员 + mock trace API）：
  列表 2 行、详情 6 个时间线事件
  1440 / 390 无横向溢出
```

## 已知限制

```text
1. 本轮用 mock 管理员验证页面；真实系统管理员账号口令未在本地留存，
   上线前需用真实系统管理员再点一次列表/详情/筛选。
2. Agent 事件明细保存在 ai_traces.meta.agent_events；
   本轮未单独写 ai_spans，后续如需 span 级查询可补。
3. 暂未做 prompt/response 全文回放、导出、采样与告警；
   属于下一阶段，不影响本次只读监控 MVP。
```
