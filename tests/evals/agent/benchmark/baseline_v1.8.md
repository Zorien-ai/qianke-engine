# Agent Eval v1.8

v1.8 将 Benchmark 从 40 条扩展到 60 条，并保持 Regression 20 条独立。

## 题量

| 分类 | v1.7 | v1.8 |
|---|---:|---:|
| execute_sql | 10 | 15 |
| rag_search | 8 | 12 |
| multi_tool | 12 | 19 |
| negative | 6 | 8 |
| calculator | 4 | 6 |
| **合计** | **40** | **60** |

新增 20 条：

- execute_sql 5 条：北京均值、等级消费总额、品类订单数、最高消费用户、钻石平均客单价
- rag_search 4 条：钻石折扣、流失挽回时机、质量问题流程、高潜用户定义
- multi_tool 7 条：流失客占比、北京钻石占比、美妆平均订单、黑卡权益占比、订单数极差、上海钻石占比、黑卡/普通客单价倍数
- negative 2 条：近 7 天登录次数、退货原因分布
- calculator 2 条：优惠券预算、返现金额

## 构建约束

- 新题 expected 由 demo SQL / 知识库原文复算
- 新题构建期没有运行 Agent
- 旧 40 条题目与 expected 保持不变
- 新题中的 `multi_tool` 任务使用 `required_tools` / `optional_tools`，允许 SQL 内完成比例计算

## 实测结果

```text
Task Success（v1）       93.3%
Business Correctness    96.7%
Tool Policy Compliance  98.3%
Tool Selection          96.7%
Tool Execution          92.7%
Error Recovery          100.0%
平均 Steps              2.55
平均 Tool Calls         2.05
平均耗时                4.4s
```

分类：

```text
calculator       6/6
execute_sql     14/15
rag_search      12/12
multi_tool      17/19
negative         7/8
```

## 自动未通过

1. `bench_multi_001`：答案正确，但旧 Task Success 要求 calculator；Tool Policy 已 PASS。
2. `bench_multi_008`：答案正确，工具策略缺少 calculator；属于旧任务口径。
3. `bench_sql_013`：答案使用 `6,864`，expected keyword 使用 `6864`，属于格式匹配问题。
4. `bench_neg_007`：回答在拒答后给出“近 7 天有购买”的替代指标 5.1%，业务口径上有争议，保留为真实失败。

## 结论

v1.8 不是“把分数做高”的版本，而是扩大覆盖后暴露更多真实问题：

- 业务正确性 96.7%
- 负样本 7/8
- 工具策略 98.3%
- 新题主要暴露：工具路径口径、数字格式、近似口径边界

下一版优先修 `bench_sql_013` 的数字格式匹配和负样本近似口径，不急于继续扩题。
