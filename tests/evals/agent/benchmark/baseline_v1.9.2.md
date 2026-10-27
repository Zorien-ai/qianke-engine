# Agent Eval v1.9.2 · Runtime v0.2.2

v1.9.2 补 Retry / Checkpoint，Runtime v0.2 到这里完整。

## 新增

### Retry

```python
run_agent_with_retry(
    question,
    max_retries=1,
    request_id="req_...",
    checkpoint_dir="...",
)
```

规则：

```text
同一个 request_id
每次 retry 新 execution_id
重试的 parent_execution_id 指向上一次 execution
只重试 FAILED / TIMEOUT / MAX_STEPS_EXCEEDED / MAX_TOOL_CALLS_EXCEEDED
不重试 COMPLETED / CANCELLED / BUDGET_EXCEEDED
```

### Checkpoint

每次尝试保存：

```text
attempt
request_id
execution_id
parent_execution_id
status
steps
tool_call_count
total_tokens
final_answer
event_trace
```

## API

`POST /api/agent/run` 新增：

```json
{
  "max_retries": 0
}
```

上限在 API 内限制为 3。

响应新增：

```text
attempts
```

## 测试

新增：

- retry 使用新 execution_id
- parent_execution_id 指向上一轮
- checkpoint 文件落盘
- request_id 保持不变

## 指标

本次只改 Runtime，不重跑 60 题；指标沿用 v1.8.2 真实结果。

## Runtime v0.2 完成度

```text
Request ID         ✅
Execution ID       ✅
Event Trace        ✅
Timeout            ✅
Budget             ✅
Cancellation       ✅
Retry              ✅
Checkpoint         ✅
```

下一步 v2.0：private holdout。
