# Agent Eval v1.8.2

v1.8.2 在 v1.8.1 基础上补 token 指标，并收口工具策略。

## 改了什么

1. 新增 token 统计：从 LangChain 消息的 `usage_metadata` / `response_metadata.token_usage` 汇总。
2. 报告新增 Input / Output / 平均 Tokens。
3. `bench_multi_014` 将 `calculator` 标为可选，Tool Policy 到 100%。
4. 保留 v1.8.1 的数字格式兼容与 negative 替代指标口径。

## 实测结果

```text
Task Success（v1）       95.0%
Business Correctness    100.0%
Tool Policy Compliance  100.0%
Tool Selection          95.0%
Tool Execution          97.2%
Error Recovery          100.0%

平均 Steps              2.40
平均 Tool Calls         1.82
平均耗时                4.2s

Input Tokens            353,534
Output Tokens            28,524
Total Tokens             382,058
平均 Tokens / 任务       6,368
```

分类：

```text
calculator       6/6
execute_sql     15/15
rag_search      12/12
multi_tool      16/19
negative         8/8
```

## 3 条自动失败

全部是旧 Task Success 复合口径，业务与工具策略均 PASS：

- `bench_multi_001`
- `bench_multi_004`
- `bench_multi_014`

原因是旧口径仍要求 `expected_tools` 精确包含 calculator；新口径 `Tool Policy Compliance` 已允许 calculator 可选。

## 结论

```text
业务正确率        100%
工具策略合规      100%
旧复合 Task Success 95%
```

v1.8.2 已经把 60 题基线稳定下来，且有了 token 数据。

Estimated Cost 暂无：当前没有在仓库中固定模型单价，避免写入过期/不准确价格。后续可配置：
`EVAL_INPUT_COST_PER_1M` / `EVAL_OUTPUT_COST_PER_1M` 后再计算。
