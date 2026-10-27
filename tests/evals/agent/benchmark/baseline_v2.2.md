# Agent Eval v2.2 · Benchmark 80

v2.2 将 60 题 Benchmark 与 v2.0 的 20 条 holdout 合并为 80 题。

## 分布

```text
execute_sql 20
rag_search  16
multi_tool  26
negative    10
calculator   8
合计        80
```

## 实测

```text
Task Success（v1）       96.2%
Business Correctness    100.0%
Tool Policy Compliance  97.5%
Tool Selection          96.2%
Tool Execution          96.0%
Error Recovery          100.0%

Total Tokens            541,484
平均 Tokens / 任务       6,769
平均 Steps              2.48
平均 Tool Calls         1.88
平均耗时                3.9s
```

分类：

```text
calculator       8/8
execute_sql     20/20
rag_search      16/16
multi_tool      23/26
negative        10/10
```

## 3 条自动失败

全部是旧 Task Success 复合口径，业务正确性 PASS：

- `bench_multi_004`
- `bench_multi_009`
- `hold_016`

## 说明

- 20 条 holdout 完成首次基线后退役并进入公共集
- 下一版需要重新建立新的 private holdout
- 80 题基线不用于调 Prompt
