# Agent Eval v1.9 · Runtime v0.2

v1.9 不新增题目，重点补 Runtime 可观测性。

## 新增

### 1. Request / Execution 身份

```text
request_id
execution_id
parent_execution_id
```

`run_agent` 可接收调用方传入的 `request_id` / `parent_execution_id`；未传时自动生成。

API：

```json
{
  "query": "...",
  "request_id": "可选",
  "parent_execution_id": "可选"
}
```

响应新增：

```text
request_id
execution_id
parent_execution_id
event_trace
```

### 2. Event Trace

通过 LangChain callbacks 旁路采集，不改 Graph：

```text
run_started
llm_started / llm_finished / llm_failed
tool_started / tool_finished / tool_failed
run_finished / run_failed
```

事件包含：

```text
timestamp
run_id
name
duration_ms
status / error
input_preview / output_preview
```

### 3. Eval 集成

Eval 结果保存：

```text
request_id
execution_id
parent_execution_id
event_trace
```

失败报告会显示：

```text
Request ID
Execution ID
Trace events
最后 8 个事件
```

## 实测 trace

一次真实 calculator 运行：

```text
run_started
llm_started / llm_finished (1141ms)
tool_started calculator
tool_finished calculator
llm_started / llm_finished (954ms)
run_finished COMPLETED
```

## 当前 Eval 指标

本次只改 Runtime，不重跑 60 题；沿用 v1.8.2 真实结果：

```text
Task Success（v1）       95.0%
Business Correctness    100.0%
Tool Policy Compliance  100.0%
Tool Selection          95.0%
Tool Execution          97.2%
Error Recovery          100.0%
```

## 说明

- Runtime v0.2 的 request/execution ID、event trace、eval 集成已落地
- timeout / budget / cancellation / checkpoint 仍是下一阶段
- 不把 trace 写死在报告正文，只在失败任务和 JSON 中保留，避免报告膨胀
