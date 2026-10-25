# Agent Eval · regression

- 任务数：20
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate | **95.0%** |
| Tool Selection Accuracy | **100.0%** |
| Tool Execution Success | **92.2%** |
| Error Recovery | 50.0% |
| 平均 Steps | 2.70 |
| 平均 Tool Calls | 2.55 |
| 平均耗时 | 5.1s |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 5 / 5 | 100.0% |
| execute_sql | 5 / 5 | 100.0% |
| multi_tool | 5 / 5 | 100.0% |
| rag_search | 4 / 5 | 80.0% |

## 未通过任务（1）

### rag_001 · rag_search

- 问题：高价值用户怎么定义？
- 状态：MAX_STEPS_EXCEEDED
- 期望工具：['rag_search']
- 实际工具：['rag_search', 'rag_search', 'execute_sql', 'execute_sql', 'execute_sql', 'rag_search', 'execute_sql', 'calculator', 'calculator', 'calculator']
- 缺少工具：—
- 缺少关键词：['90']
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：已达到最大推理步数（6），未能完成全部工具调用。


## 人工复核清单（0）

无。