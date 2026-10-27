# Agent Eval v1.9.1 · Runtime v0.2.1

v1.9.1 在 Runtime v0.2 上补 token 预算与协作式取消，不新增题目。

## 新增

### 1. Token Budget

```python
AgentConfig(max_total_tokens=100_000)
```

- 0 表示不限制
- 超过预算返回 `BUDGET_EXCEEDED`
- trace 的 `llm_finished` 事件包含累计 `total_tokens`

### 2. Cancellation

```python
run_agent(..., cancel_event=threading.Event())
```

- 调用方可以设置协作式取消
- 取消后返回 `CANCELLED`
- 不会把取消伪装成普通回答

### 3. Runtime 状态

新增：

```text
CANCELLED
BUDGET_EXCEEDED
```

### 4. API

`/api/agent/run` 响应增加 `total_tokens`，与现有 `event_trace` 一起返回。

## Eval 指标

本次只改 Runtime，不重跑 60 题；沿用 v1.8.2 真实结果：

```text
Task Success（v1）       95.0%
Business Correctness    100.0%
Tool Policy Compliance  100.0%
Tool Selection          95.0%
Tool Execution          97.2%
Error Recovery          100.0%
```

## 测试

新增：

- 取消测试
- token 预算测试
- `max_total_tokens` 配置校验

## 说明

- 取消是协作式的；长时间单次 LLM 调用不能从线程外硬杀，靠下一次节点检查生效
- 成本预算仍需先配置单价，当前只做 token 预算
- checkpoint / retry 仍是后续版本
