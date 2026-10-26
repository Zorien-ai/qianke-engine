# Agent Eval v1.7

v1.7 聚焦工具策略，不新增题目。

> **结果说明：** 本版没有重新运行 Agent。`Task Success` / `Business Correctness` / 工具轨迹沿用 v1.6.1 的真实 benchmark 结果，仅按新的 `required_tools / optional_tools` 重新计算 `Tool Policy Compliance`。

## 改了什么

`bench_multi_004` / `bench_multi_011` 增加任务级工具策略：

```json
{
  "required_tools": ["execute_sql"],
  "optional_tools": ["calculator"],
  "forbidden_tools": []
}
```

含义：

- `execute_sql` 是必需工具
- `calculator` 是可选的，允许模型在 SQL 内直接算比例
- 如果缺少必需工具，或调用禁用工具，Tool Policy 才失败

旧 `expected_tools` 保留，继续用于：

- Task Success（v1 复合口径）
- Tool Selection Accuracy

## 指标结果

### Regression 20

```text
Task Success（v1）      100.0%
Business Correctness    100.0%
Tool Policy Compliance  100.0%
Tool Execution          100.0%
```

### Benchmark 40

```text
Task Success（v1）       97.5%
Business Correctness    100.0%
Tool Policy Compliance  100.0%
Tool Selection          97.5%
Tool Execution          93.1%
Error Recovery          100.0%
```

## 指标解释

`bench_multi_004` 仍然在旧 Task Success 口径下失败：

```text
expected_tools = [rag_search, execute_sql, calculator]
actual_tools   = [rag_search, execute_sql]
```

因为答案正确，且 `calculator` 已声明可选：

```text
Business Correctness   PASS
Tool Policy Compliance PASS
Task Success（v1）      FAIL
```

这不是 Agent 答错，而是旧复合指标要求精确工具路径。

## 与 v1.6.1 的差异

- v1.6.1：Tool Policy Compliance = 97.5%（multi_004 被视为缺 calculator）
- v1.7：Tool Policy Compliance = 100%（calculator 可选）
- Task Success 与 Business Correctness 不变

## 下一步

v1.8 再做 Benchmark 扩展（60–100 条）和 token / cost 指标。

当前 40 条保持稳定，不为了 100% 改题。
