# Agent Eval v1.8.3

v1.8.3 不重跑 Benchmark，只补齐评测基础设施。

## 新增

1. 版本对比脚本：

```bash
python tests/evals/agent/compare.py v1.8.1 v1.8.2
```

输出 Task Success、Business、Tool Policy、Steps、Tokens 等指标及差值。

2. 可配置成本估算：

```bash
export EVAL_INPUT_COST_PER_1M=...
export EVAL_OUTPUT_COST_PER_1M=...
```

未配置时报告显示 `N/A`，不在仓库中写死厂商价格。

## 当前基线

沿用 v1.8.2 的 60 题真实运行结果：

```text
Task Success（v1）       95.0%
Business Correctness    100.0%
Tool Policy Compliance  100.0%
Tool Selection          95.0%
Tool Execution          97.2%
Error Recovery          100.0%

Total Tokens            382,058
平均 Tokens / 任务       6,368
```

## 说明

- 本轮没有修改题目、判分语义或 Agent Runtime
- 新增 `compare.py`、成本估算配置和对应测试
- 旧 Task Success 的 3 条失败仍只来自精确工具路径口径
