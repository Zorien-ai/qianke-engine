# Agent Eval · benchmark

- 任务数：8
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate（v1 复合口径） | **87.5%** |
| Business Correctness | **100.0%** |
| Tool Policy Compliance | **100.0%** |
| Tool Selection Accuracy | **87.5%** |
| Tool Execution Success | **95.2%** |
| Error Recovery | 100.0% |
| 平均 Steps | 3.38 |
| 平均 Tool Calls | 2.62 |
| 平均耗时 | 6.2s |
| Input Tokens | 86,506 |
| Output Tokens | 4,112 |
| 平均 Tokens / 任务 | 11327 |
| Estimated Cost | N/A（未配置 EVAL_*_COST_PER_1M） |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| multi_tool | 7 / 8 | 87.5% |

## 未通过任务（1）

### bench_multi_004 · multi_tool

- 问题：按用户分群文档中的“沉默客”定义统计 demo 数据集中沉默客的数量及占全库比例（百分比保留两位小数）。
- 状态：COMPLETED
- Request ID：req_1d17024ca5d843d5
- Execution ID：exec_ff495c6b618846aa
- 业务正确性：PASS
- 工具策略：PASS
- 期望工具：['rag_search', 'execute_sql', 'calculator']
- 必需工具：['rag_search', 'execute_sql']
- 可选工具：['calculator']
- 实际工具：['rag_search', 'execute_sql']
- 缺少工具：['calculator']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：**沉默客统计结果**

- 口径依据：segmentation.md「生命周期：新客（注册 ≤ 30 天）、活跃客（近 30 天有行为）、**沉默客（31–90 天无行为）**、流失客（> 90 天无行为）」
- 实现口径：本库无绝对时间列，仅 `days_since_last_buy`（距最后一次购买天数，0–364），以其作为“最近一次行为距今天数”的代理，取 `31 ≤ days_since_last_buy ≤ 90`
- 统计结果：沉默客 **2,383 人**，全库 8,110 人，占比 **29.38%**

SQL 依据：
```sql
SELECT COUNT(*) AS silent_cnt,
       (SELECT COUNT(*) FROM user_profile_vectors) AS total_cnt,
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM user_profile_vectors), 2) AS silent_pct
FROM user_profile_vectors
WHE

- Trace events：12
  - tool_finished · rag_search · 12687.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1453.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 157.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2250.0
  - run_finished · COMPLETED · 


## 人工复核清单（1）

### bench_multi_019 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员的平均客单价是普通会员的多少倍（保留两位小数）？
- 最终回答：**约 28.55 倍。**

依据（SQL 实测，按会员等级分组计算 avg_amount 均值）：

| 会员等级 | 人数 | 平均客单价（元） |
|---|---|---|
| 黑卡 | 3 | 37,665.00 |
| 普通 | 4,053 | 1,319.11 |

- 计算：37,665.00 ÷ 1,319.11 ≈ 28.55

提示：黑卡样本仅 3 人，该倍数受极小样本影响，波动风险较大，建议结合中位数或分位数再作判断。
- 复核项：黑卡仅 3 人，倍数样本不稳定，需人工确认
