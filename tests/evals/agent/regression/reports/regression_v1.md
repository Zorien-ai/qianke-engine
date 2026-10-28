# Agent Eval · regression

- 任务数：20
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate（v1 复合口径） | **95.0%** |
| Business Correctness | **95.0%** |
| Tool Policy Compliance | **100.0%** |
| Tool Selection Accuracy | **100.0%** |
| Tool Execution Success | **100.0%** |
| Error Recovery | N/A |
| 平均 Steps | 2.15 |
| 平均 Tool Calls | 1.40 |
| 平均耗时 | 2.7s |
| Input Tokens | 85,988 |
| Output Tokens | 5,493 |
| 平均 Tokens / 任务 | 4574 |
| Estimated Cost | N/A（未配置 EVAL_*_COST_PER_1M） |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 5 / 5 | 100.0% |
| execute_sql | 5 / 5 | 100.0% |
| multi_tool | 5 / 5 | 100.0% |
| rag_search | 4 / 5 | 80.0% |

## 未通过任务（1）

### rag_004 · rag_search

- 问题：钻石会员的累计平均客单价门槛是多少？
- 状态：COMPLETED
- Request ID：req_873ff891852b45af
- Execution ID：exec_40470e29716b4daa
- 业务正确性：FAIL
- 工具策略：PASS
- 期望工具：['rag_search']
- 必需工具：['rag_search']
- 可选工具：—
- 实际工具：['rag_search', 'rag_search']
- 缺少工具：—
- 缺少关键词：['14555']
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：**钻石会员门槛：累计平均客单价 ≥ 14,555 元**（约前 5%）

依据《member_benefits.md》「等级划分标准」（会员等级按「累计平均客单价」划分，T+1 更新）：

| 等级 | 累计平均客单价区间 |
|---|---|
| 钻石会员 | ≥ 14,555 元 |
| 黄金会员 | 6,680 – 14,555 元 |
| 白银会员 | 2,495 – 6,680 元 |
| 普通会员 | < 2,495 元 |

补充口径：
- **升级**：累计平均客单价达到上一等级门槛后，T+1 自动升级，权益次日生效。
- **保级**：无固定保级考核期，等级随累计平均客单价的变动实时调整（即跌破门槛会降级）。
- 库内 `member_level` 实测钻石 403 人、黑卡 3 人；资料中仅给出到钻石等级的划分标准，未给出黑卡门槛。

- Trace events：10
  - llm_finished · chat_model · 1391.0
  - tool_started · rag_search · 
  - tool_started · rag_search · 
  - tool_finished · rag_search · 141.0
  - tool_finished · rag_search · 141.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1671.0
  - run_finished · COMPLETED · 


## 人工复核清单（0）

无。