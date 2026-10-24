# Agent Eval v0.1

- 任务数：20
- 数据集：`test`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate | **95.0%** |
| Tool Selection Accuracy | **95.0%** |
| Tool Execution Success | **97.9%** |
| Error Recovery | 100.0% |
| 平均 Steps | 2.60 |
| 平均 Tool Calls | 2.40 |
| 平均耗时 | 7.2s |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 5 / 5 | 100.0% |
| execute_sql | 5 / 5 | 100.0% |
| multi_tool | 4 / 5 | 80.0% |
| rag_search | 5 / 5 | 100.0% |

## 未通过任务（1）

### multi_004 · multi_tool

- 问题：上海用户中黑卡用户占比是多少？
- 状态：COMPLETED
- 期望工具：['execute_sql', 'calculator']
- 实际工具：['execute_sql', 'rag_search', 'execute_sql']
- 缺少工具：['calculator']
- 缺少关键词：—
- 最终回答：**结论：上海用户中黑卡占比 = 1/1 = 100%，但样本仅 1 人，参考意义有限。**

数据依据

| 指标 | 数值 |
|---|---|
| 上海用户总数 | 1 |
| 其中黑卡会员 | 1 |
| 黑卡占比 | 100% |

- 明细查询（`SELECT city, member_level, COUNT(*) ... WHERE city='上海' GROUP BY ...`）：上海仅 1 条画像，会员等级为「黑卡」，对应用户「最爱喝奶茶」（3 单、总消费 3478 元、客单 1160 元、偏好美妆护肤，与知识库检索结果一致）。
- 汇总查询（`COUNT(*)` + `SUM(CASE WHEN member_level='黑卡' ...)`）同样返回 1 / 1。

口径提示
- 该库只有 9 条用户画像，城市分布为每城 1 人，因此任何单城占比只可能是 0% 或 100%，不能代表真实客群的会员结构。
- `member_level` 字段存在 1 条缺失（NaN），本次上海用户等级有值，不影响统计。
- 若要看有意义的会员结构，建议看全库：黑卡 3 人 /
