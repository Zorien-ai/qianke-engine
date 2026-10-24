# Agent Eval v0.1

- 任务数：20
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate | **100.0%** |
| Tool Selection Accuracy | **100.0%** |
| Tool Execution Success | **97.6%** |
| Error Recovery | 100.0% |
| 平均 Steps | 2.55 |
| 平均 Tool Calls | 2.10 |
| 平均耗时 | 7.4s |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 5 / 5 | 100.0% |
| execute_sql | 5 / 5 | 100.0% |
| multi_tool | 5 / 5 | 100.0% |
| rag_search | 5 / 5 | 100.0% |

## 未通过任务（0）

全部通过。