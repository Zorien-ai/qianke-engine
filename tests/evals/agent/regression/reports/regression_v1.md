# Agent Eval · regression

- 任务数：20
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate（v1 复合口径） | **100.0%** |
| Business Correctness | **100.0%** |
| Tool Policy Compliance | **100.0%** |
| Tool Selection Accuracy | **100.0%** |
| Tool Execution Success | **100.0%** |
| Error Recovery | N/A |
| 平均 Steps | 2.15 |
| 平均 Tool Calls | 1.45 |
| 平均耗时 | 2.8s |
| Input Tokens | 88,129 |
| Output Tokens | 5,522 |
| 平均 Tokens / 任务 | 4683 |
| Estimated Cost | N/A（未配置 EVAL_*_COST_PER_1M） |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 5 / 5 | 100.0% |
| execute_sql | 5 / 5 | 100.0% |
| multi_tool | 5 / 5 | 100.0% |
| rag_search | 5 / 5 | 100.0% |

## 未通过任务（0）

全部通过。

## 人工复核清单（0）

无。