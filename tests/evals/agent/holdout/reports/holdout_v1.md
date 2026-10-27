# Agent Eval · holdout

- 任务数：20
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate（v1 复合口径） | **90.0%** |
| Business Correctness | **95.0%** |
| Tool Policy Compliance | **95.0%** |
| Tool Selection Accuracy | **95.0%** |
| Tool Execution Success | **97.1%** |
| Error Recovery | 100.0% |
| 平均 Steps | 2.40 |
| 平均 Tool Calls | 1.75 |
| 平均耗时 | 3.4s |
| Input Tokens | 99,510 |
| Output Tokens | 7,262 |
| 平均 Tokens / 任务 | 5339 |
| Estimated Cost | N/A（未配置 EVAL_*_COST_PER_1M） |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 2 / 2 | 100.0% |
| execute_sql | 4 / 5 | 80.0% |
| multi_tool | 6 / 7 | 85.7% |
| negative | 2 / 2 | 100.0% |
| rag_search | 4 / 4 | 100.0% |

## 未通过任务（2）

### hold_004 · execute_sql

- 问题：哪个城市的用户平均累计消费金额最高？金额是多少（保留两位小数）？
- 状态：COMPLETED
- Request ID：req_0953534515fa4440
- Execution ID：exec_f37ad759bc0c4d4a
- 业务正确性：FAIL
- 工具策略：PASS
- 期望工具：['execute_sql']
- 必需工具：['execute_sql']
- 可选工具：—
- 实际工具：['execute_sql']
- 缺少工具：—
- 缺少关键词：['11984.84']
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：平均累计消费金额最高的城市是**成都**，平均金额为 **11,984.84 元**（基于该城市 639 位用户统计）。

依据：按 `city` 分组计算 `AVG(total_amount)` 并降序排列，成都位列第一（北京 11,841.94 元、杭州 11,792.65 元分列二、三）。

- Trace events：8
  - run_started ·  · 
  - llm_started · chat_model · 
  - llm_finished · chat_model · 984.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 0.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 891.0
  - run_finished · COMPLETED · 

### hold_016 · multi_tool

- 问题：流失客（>90 天无行为）占全库用户的比例是多少（百分比保留两位小数）？
- 状态：COMPLETED
- Request ID：req_2a5a1c8e79294881
- Execution ID：exec_50baa5e53ac54188
- 业务正确性：PASS
- 工具策略：FAIL
- 期望工具：['rag_search', 'execute_sql', 'calculator']
- 必需工具：['rag_search', 'execute_sql', 'calculator']
- 可选工具：—
- 实际工具：['execute_sql', 'calculator']
- 缺少工具：['rag_search']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：按「距最后一次购买 > 90 天」定义为流失客口径统计：

- 流失客：4,057 人
- 全库用户：8,110 人
- 占比：4,057 ÷ 8,110 × 100% = **50.02%**

依据：`SELECT COUNT(*), SUM(CASE WHEN days_since_last_buy > 90 THEN 1 ELSE 0 END) FROM user_profile_vectors`，返回 8110 / 4057。

- Trace events：12
  - tool_finished · execute_sql · 15.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 766.0
  - tool_started · calculator · 
  - tool_finished · calculator · 0.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1140.0
  - run_finished · COMPLETED · 


## 人工复核清单（2）

### hold_017 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户的投诉率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有数据无法计算投诉率

**依据**

1. **表结构里没有任何投诉/售后字段**
   `user_profile_vectors`（8110 条）只有：user_id、profile_text、age、gender、city、member_level、order_count、total_amount、avg_amount、top_category、days_since_last_buy、platforms。没有投诉次数、投诉标记、工单、售后申请、退款、评价/满意度等字段。
   `wiki_vectors`（36 条）是文档分块（标签口径、权益、SOP 等），不是业务明细数据。

2. **知识库也没有投诉率的定义口径**
   检索「投诉率 定义 计算口径」只命中 `tag_definitions.md` 中的高/中/低客单、流失预警、高潜、母婴偏好、高价值用户等标签
- 复核项：必须人工确认未给出编造投诉率

### hold_018 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中商品的毛利率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有数据不支持计算商品毛利率，我不做估算

### 一、知识库层面的核查
我用 `rag_search("毛利率 计算口径 商品 成本 售价 收入")` 检索了运营知识库，命中的全部是**客单价分档标签定义**（`tag_definitions.md`：高客单 ≥1000 元、中客单 500–1000、低客单 <500），**没有任何关于毛利率、成本、商品售价、利润指标的口径文档**。因此连“毛利率该怎么计算”这一口径定义都拿不到。

### 二、数据层面的核查
数据库中实际可用的两张表都不具备商品级成本与销售数据：

| 需要的数据 | 库内现状 | 是否可用 |
|---|---|---|
| 商品、SKU、类目维度表 | 无。仅有 `top_category`（用户**偏好品类**：电子产品/家居/书籍…） | ❌ 只是偏好标签，并非商品销售明细 |
| 商品销售额、数量
- 复核项：必须人工确认未给出编造毛利率
