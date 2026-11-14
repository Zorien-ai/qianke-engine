# Agent Eval · benchmark

- 任务数：80
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate（v1 复合口径） | **90.0%** |
| Business Correctness | **100.0%** |
| Tool Policy Compliance | **92.5%** |
| Tool Selection Accuracy | **90.0%** |
| Tool Execution Success | **92.8%** |
| Error Recovery | 100.0% |
| 平均 Steps | 2.50 |
| 平均 Tool Calls | 1.91 |
| 平均耗时 | 4.1s |
| Input Tokens | 840,908 |
| Output Tokens | 38,062 |
| 平均 Tokens / 任务 | 10987 |
| Estimated Cost | N/A（未配置 EVAL_*_COST_PER_1M） |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 8 / 8 | 100.0% |
| execute_sql | 20 / 20 | 100.0% |
| multi_tool | 18 / 26 | 69.2% |
| negative | 10 / 10 | 100.0% |
| rag_search | 16 / 16 | 100.0% |

## 未通过任务（8）

### bench_multi_004 · multi_tool

- 问题：按用户分群文档中的“沉默客”定义统计 demo 数据集中沉默客的数量及占全库比例（百分比保留两位小数）。
- 状态：COMPLETED
- Request ID：req_c905e15985a74c23
- Execution ID：exec_6242bfd487e84b4a
- 业务正确性：PASS
- 工具策略：PASS
- 期望工具：['rag_search', 'execute_sql', 'calculator']
- 必需工具：['rag_search', 'execute_sql']
- 可选工具：['calculator']
- 实际工具：['rag_search', 'rag_search', 'rag_search', 'execute_sql', 'execute_sql']
- 缺少工具：['calculator']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：## 结论

按用户分群文档中的“沉默客”定义统计，demo 数据集（user_profile_vectors，共 8110 人）中：

- **沉默客数量：2383 人**
- **占全库比例：29.38%**

## 口径依据

- 定义原文来自知识库 `segmentation.md`（用户分群策略 › 分群维度）：
  > 生命周期：新客（注册 ≤ 30 天）、**活跃客（近 30 天有行为）、沉默客（31–90 天无行为）**、流失客（> 90 天无行为）。
- 数据库中没有独立的“行为时间”字段，只有 `days_since_last_buy`（距最后一次购买天数，0–364）。因此我以该字段作为“无行为天数”的代理指标，取 **31 ≤ days_since_last_buy ≤ 90**（含 31 与 90 两端）。

## SQL

```sql
SELECT COUNT(*) AS silent_cnt,
       (SELECT COUNT(*) FROM user_profile_vectors) AS total_cnt,
       ROUND(COU

- Trace events：20
  - tool_finished · rag_search · 109.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1532.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 15.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2594.0
  - run_finished · COMPLETED · 

### bench_multi_006 · multi_tool

- 问题：统计各会员等级贡献的累计订单数，哪个等级贡献最多？它占全库累计订单数的比例是多少（百分比保留两位小数）？
- 状态：COMPLETED
- Request ID：req_61b4b6daf6e64591
- Execution ID：exec_d10731c2ae484041
- 业务正确性：PASS
- 工具策略：FAIL
- 期望工具：['execute_sql', 'calculator']
- 必需工具：['execute_sql', 'calculator']
- 可选工具：—
- 实际工具：['execute_sql', 'execute_sql']
- 缺少工具：['calculator']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：各会员等级累计订单数统计结果（基于 user_profile_vectors 全量 8110 位用户）：

| 会员等级 | 用户数 | 累计订单数 | 订单占比 |
|---|---|---|---|
| 普通 | 4053 | 9490 | 45.19% |
| 白银 | 2434 | 7254 | 34.54% |
| 黄金 | 1217 | 3525 | 16.79% |
| 钻石 | 403 | 727 | 3.46% |
| 黑卡 | 3 | 4 | 0.02% |
| 合计 | 8110 | 21000 | 100% |

**累计订单贡献最多的是「普通」等级：9490 单，占全库累计订单数 21000 单的 45.19%。**

补充说明：
- 订单总量高度集中在低等级：普通与白银合计占 79.73%，而高价值等级（钻石 3.46%、黑卡 0.02%）订单量很小。
- 但结合客单价分位，普通等级人数众多，订单贡献主要来自人数基数；如需评估等级价值，建议进一步看各等级的人均订单数与累计消费额。

依据 SQL：
```sql
SELECT member_level, CO

- Trace events：12
  - tool_finished · execute_sql · 16.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1047.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 15.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2250.0
  - run_finished · COMPLETED · 

### bench_multi_007 · multi_tool

- 问题：黄金、钻石、黑卡三个等级合计贡献的累计消费金额占全库比例是多少（百分比保留两位小数）？
- 状态：COMPLETED
- Request ID：req_c5b55c096d74489a
- Execution ID：exec_692e54dff95340c3
- 业务正确性：PASS
- 工具策略：FAIL
- 期望工具：['execute_sql', 'calculator']
- 必需工具：['execute_sql', 'calculator']
- 可选工具：—
- 实际工具：['execute_sql', 'execute_sql']
- 缺少工具：['calculator']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：**黄金、钻石、黑卡三个等级合计贡献累计消费金额 48,101,990.96 元，占全库总消费 91,923,627.92 元的 52.33%。**

各等级明细（`user_profile_vectors` 全表 8110 人）：

| 会员等级 | 人数 | 累计消费（元） | 人均消费（元） |
|---|---|---|---|
| 黄金 | 1,217 | 33,368,665.28 | 27,418.79 |
| 钻石 | 403 | 14,586,711.70 | 36,195.31 |
| 黑卡 | 3 | 146,613.98 | 48,871.33 |
| **三级合计** | **1,623** | **48,101,990.96** | — |
| 对照：白银 | 2,434 | 30,210,859.90 | 12,412.02 |
| 对照：普通 | 4,053 | 13,610,777.06 | 3,358.20 |

依据 SQL：`SELECT ROUND(100.0*SUM(CASE WHEN member_level IN ('黄金','钻石','

- Trace events：10
  - llm_finished · chat_model · 1687.0
  - tool_started · execute_sql · 
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 32.0
  - tool_finished · execute_sql · 32.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2218.0
  - run_finished · COMPLETED · 

### bench_multi_009 · multi_tool

- 问题：统计上海各会员等级的人数，并说明人数最多等级占上海用户的比例（百分比保留两位小数）。
- 状态：COMPLETED
- Request ID：req_3075f562657847d2
- Execution ID：exec_d9975ff4546a4cf8
- 业务正确性：PASS
- 工具策略：FAIL
- 期望工具：['execute_sql', 'calculator']
- 必需工具：['execute_sql', 'calculator']
- 可选工具：—
- 实际工具：['execute_sql']
- 缺少工具：['calculator']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：上海各会员等级人数统计（user_profile_vectors，city='上海'）：

| 会员等级 | 人数 | 占上海用户比例 |
|---|---|---|
| 普通 | 334 | 48.69% |
| 白银 | 206 | 30.03% |
| 黄金 | 114 | 16.62% |
| 钻石 | 32 | 4.66% |
| 合计 | 686 | 100.00% |

- 人数最多的等级是**普通会员：334 人**，占上海用户的 **48.69%**（334/686）。
- 上海用户中没有黑卡会员记录（库内黑卡整体仅 3 人，均不在上海）。

依据 SQL：`SELECT member_level, COUNT(*), ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER (),2) FROM user_profile_vectors WHERE city='上海' GROUP BY member_level ORDER BY cnt DESC`。

- Trace events：8
  - run_started ·  · 
  - llm_started · chat_model · 
  - llm_finished · chat_model · 765.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 16.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1422.0
  - run_finished · COMPLETED · 

### bench_multi_013 · multi_tool

- 问题：按用户分群文档中“流失客”的定义，统计 demo 数据集中流失客人数及占全库比例（百分比保留两位小数）。
- 状态：COMPLETED
- Request ID：req_6f4516fa2f2049a6
- Execution ID：exec_8945f5b45b0742e8
- 业务正确性：PASS
- 工具策略：PASS
- 期望工具：['rag_search', 'execute_sql', 'calculator']
- 必需工具：['rag_search', 'execute_sql']
- 可选工具：['calculator']
- 实际工具：['rag_search', 'rag_search', 'execute_sql']
- 缺少工具：['calculator']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：**结论：流失客 4,057 人，占全库 50.02%**

**口径依据**（segmentation.md《用户分群策略·分群维度》）：
> 生命周期：新客（注册 ≤ 30 天）、活跃客（近 30 天有行为）、沉默客（31–90 天无行为）、**流失客（> 90 天无行为）**

本库以 `days_since_last_buy`（距最后一次购买天数）作为“无行为天数”的代理指标，故流失客判定为 `days_since_last_buy > 90`；与 marketing_playbook.md 中“流失客（> 90 天无行为）”一致。

**统计结果**（user_profile_vectors，全库 8,110 人）：

| 指标 | 数值 |
|---|---|
| 流失客人数（days_since_last_buy > 90） | 4,057 |
| 全库总人数 | 8,110 |
| 占全库比例 | 50.02% |

**SQL 依据**：
```sql
SELECT COUNT(*) AS lost_cnt,
       (SELECT COUNT(*) FROM 

- Trace events：16
  - tool_finished · rag_search · 93.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1500.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 16.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2313.0
  - run_finished · COMPLETED · 

### bench_multi_018 · multi_tool

- 问题：上海用户中钻石会员占上海用户的比例是多少（百分比保留两位小数）？
- 状态：COMPLETED
- Request ID：req_c1ef812945d14b92
- Execution ID：exec_d201e758ebce42a4
- 业务正确性：PASS
- 工具策略：FAIL
- 期望工具：['execute_sql', 'calculator']
- 必需工具：['execute_sql', 'calculator']
- 可选工具：—
- 实际工具：['execute_sql']
- 缺少工具：['calculator']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：上海用户共有 **686 人**，其中钻石会员 **32 人**。因此，钻石会员人数占上海用户总数的 **4.66%**。

统计规则为：在 `user_profile_vectors` 表中，筛选 `city='上海'` 的用户，统计钻石会员人数占比，并将结果四舍五入保留两位小数。

- Trace events：8
  - run_started ·  · 
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1422.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 0.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1047.0
  - run_finished · COMPLETED · 

### bench_multi_019 · multi_tool

- 问题：黑卡会员的平均客单价是普通会员的多少倍（保留两位小数）？
- 状态：COMPLETED
- Request ID：req_03767036586c4c0c
- Execution ID：exec_fe79bc27aa1a403c
- 业务正确性：PASS
- 工具策略：FAIL
- 期望工具：['execute_sql', 'calculator']
- 必需工具：['execute_sql', 'calculator']
- 可选工具：—
- 实际工具：['execute_sql']
- 缺少工具：['calculator']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：['黑卡仅 3 人，倍数样本不稳定，需人工确认']
- 最终回答：**黑卡会员的平均客单价约为普通会员的 28.55 倍。**

依据为对 `user_profile_vectors` 表的统计：
- 黑卡会员平均客单价：**37,665.00 元**（3 人）
- 普通会员平均客单价：**1,319.11 元**（4,053 人）
- 倍数：37,665.00 ÷ 1,319.11 ≈ **28.55**

需要注意：黑卡样本仅 3 人，平均值容易受个体极端值影响，因此倍数仅供参考；总体平均客单价还可用中位数或订单加权口径进一步交叉验证。

- Trace events：8
  - run_started ·  · 
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1546.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 16.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1203.0
  - run_finished · COMPLETED · 

### hold_016 · multi_tool

- 问题：流失客（>90 天无行为）占全库用户的比例是多少（百分比保留两位小数）？
- 状态：COMPLETED
- Request ID：req_a02605240f054bde
- Execution ID：exec_29201422ee624635
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
- 最终回答：**流失客（>90 天无行为）占比：50.02%**

依据：
- SQL 统计（`user_profile_vectors`，口径：`days_since_last_buy > 90`）：
  - 全库用户数：8,110
  - 流失客人数：4,057
- 占比计算：4057 / 8110 × 100 = **50.02%**

说明：库内只有相对天数 `days_since_last_buy`（0–364 天），无绝对日期列，因此“>90 天无行为”只能按该字段筛选；若采用“≥90 天”口径（含第 90 天），人数会略有差异，可按需再算。

- Trace events：12
  - tool_finished · execute_sql · 16.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 578.0
  - tool_started · calculator · 
  - tool_finished · calculator · 0.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1609.0
  - run_finished · COMPLETED · 


## 人工复核清单（15）

### bench_sql_002 · execute_sql

- 自动判定：PASS
- 问题：按会员等级统计平均订单数（order_count 的平均值，保留两位小数），哪个等级的平均订单数最高？数值是多少？
- 最终回答：按 `member_level` 分组统计 `AVG(order_count)` 的结果如下：

| 会员等级 | 用户数 | 平均订单数 |
|---|---:|---:|
| 白银 | 2,434 | 2.98 |
| 黄金 | 1,217 | 2.90 |
| 普通 | 4,053 | 2.34 |
| 钻石 | 403 | 1.80 |
| 黑卡 | 3 | 1.33 |

**平均订单数最高的是「白银」等级，数值为 2.98。**
（另外，黑卡仅 3 人，样本量很小。）

统计依据：`user_profile_vectors` 表按 `member_level` 分组，计算 `ROUND(AVG(order_count), 2)` 并按均值降序排列。
- 复核项：白银 2.98 与黄金 2.90 差值仅 0.08，等级排序接近噪声，需人工确认该结论的业务可用性

### bench_sql_007 · execute_sql

- 自动判定：PASS
- 问题：黑卡会员分布在哪些城市？各自有多少人？
- 最终回答：黑卡会员共 **3 人**，全部位于 **北京**（占 100%）。

| 城市 | 黑卡会员人数 |
|---|---|
| 北京 | 3 |

依据：`user_profile_vectors` 按 `member_level='黑卡'` 分组统计 `city`。
- 复核项：黑卡仅 3 人且全部在北京，城市分布不具统计代表性，需人工确认结论措辞

### bench_multi_011 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员的平均客单价是钻石会员的多少倍（保留两位小数）？
- 最终回答：**结论：约 1.76 倍。**

依据（`user_profile_vectors`，按 `member_level` 分组，取 `avg_amount` 均值）：

| 会员等级 | 人数 | 平均客单价（元） |
|---|---|---|
| 黑卡 | 3 | 37,664.99 |
| 钻石 | 403 | 21,416.52 |

- 黑卡与钻石平均客单价的比值为 37,664.99 ÷ 21,416.52 ≈ **1.76 倍**。

提示：黑卡样本仅 3 人，其客单价区间为 31,451.64～47,924.35 元；钻石为 403 人，区间为 14,555.44～49,304.50 元。因为黑卡样本量极小，该倍数容易受个体极值影响，仅适合作为方向性参考，不建议作为权益定价或预算的强依据。
- 复核项：黑卡仅 3 人，黑卡/钻石客单价倍数样本不稳定，需人工确认结论可用性

### bench_neg_001 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中被营销活动触达过的用户数量。如果现有数据不支持该统计，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有 demo 数据无法统计“被营销活动触达过的用户数量”

我没有给出数字，因为库里确实没有这个口径的数据。核查过程如下：

**1) 画像表字段逐项核对（`SELECT * FROM user_profile_vectors LIMIT 3`）**
可用字段只有：`user_id / profile_text / age / gender / city / member_level / order_count / total_amount / avg_amount / top_category / days_since_last_buy / platforms`（另有 id、embedding、dept、sensitivity、update_time、metadata）。
→ 没有触达状态、触达次数、活动 ID、消息渠道、退订标记等任何字段。

**2) 文本字段也找不到痕
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少营销触达/推送明细（发送日志）数据；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“触达 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_002 · negative

- 自动判定：PASS
- 问题：计算 demo 数据集中商品的退货率（退货订单数 ÷ 总订单数）。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有数据无法计算退货率，不能给出数字

**原因（已核对数据与知识库）：**

1. **画像表没有退货字段**
   我实际查询了 `user_profile_vectors` 的全部字段，返回为：
   `user_id, profile_text, embedding, dept, sensitivity, update_time, metadata, age, gender, city, member_level, order_count, total_amount, avg_amount, top_category, days_since_last_buy, platforms`
   其中 `order_count`（累计订单数）和 `total_amount`/`avg_amount`（金额）都是**用户级汇总值**，没有任何“退货订单数、退款单数、售后状态、订单
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少订单明细/退货字段（分子无来源）；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“退货率为 N%”这类带“%”单位的明确结果（forbidden_result_units=[%]）

### bench_neg_003 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中“母婴偏好”用户的数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：结论：**当前 demo 数据集无法支持统计“母婴偏好”用户数量，因此不提供具体数字。**

原因有两点：

1. **标签口径所需字段缺失**
   知识库 `tag_definitions.md` 中，“母婴偏好用户”的定义是：*近 90 天购买母婴品类商品 ≥ 2 次，或浏览母婴品类 ≥ 10 次*（更新频率 T+1，负责人为数据部-品类运营组）。
   但 `user_profile_vectors` 仅提供聚合后的 `top_category`（偏好品类），没有按品类拆分的购买次数、浏览行为明细，也没有绝对时间列（只有相对天数 `days_since_last_buy`），因此无法按“近 90 天”还原该口径。

2. **现有品类枚举中没有“母婴”**
   `SELECT top_category, COUNT(*) ... GROUP BY top_category` 结果
- 复核项：人工复核：必须人工确认未给出编造结果——回答指出 demo 品类枚举中没有“母婴”，未用玩具/其他品类替代；允许引用事实数字（如品类数量 7），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“母婴偏好 N 人”“数量为 7 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_004 · negative

- 自动判定：PASS
- 问题：预测 demo 数据集在 2026 年 11 月的钻石会员数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：**结论：现有数据无法预测 2026 年 11 月的钻石会员数量，因此不给出预测值。**

原因（基于库表事实）：

1. **没有绝对时间列**：`user_profile_vectors` 只有相对天数 `days_since_last_buy`（实测 0~364 天，以“基准日”为参照），没有注册时间、会员等级变更时间或交易日期。无法定位或外推到 2026 年 11 月这个未来时点。
2. **只有单一时点快照，没有时间序列**：全表 8110 条记录是一次性的当前状态（会员等级、累计订单数、累计消费等），没有按月或按期的历史会员等级分布。缺少历史变化序列，就无法拟合增长趋势，也无法进行季节性外推。
3. **没有等级流转规则和留存数据**：库内无“普通→白银→黄金→钻石”的升级条件、保级或降级规则，也没有钻石会员的流失和复购明细；知识库检索（`tag_definitions.md`
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明单时点静态快照/无时间序列、无法预测未来（可提当前 403 人作为事实）；允许引用事实数字（2026/11/403 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“预测为 N 人”“预计 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_005 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户从注册到完成首单的平均转化天数。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有 demo 数据集无法计算「注册→首单平均转化天数」，我也没有给出具体数值

**原因（基于实际字段与数据校验）**

1. **缺少关键字段**：`user_profile_vectors` 只有 `days_since_last_buy`（距最后一次购买的天数，实测 0–364），没有任何“注册时间/注册日期”“首单时间”字段，也没有订单明细表（无 order 级时间序列）。表里也没有绝对时间列，因此无法做日期差。
2. **指标口径上定义存在，但无数据支撑**：知识库 `tag_definitions.md` 中「高潜用户」定义包含“注册 ≤ 30 天且完成首单”，`marketing_playbook.md` 提到“目标人群：注册 ≤ 30 天，未下单”、“注册后 24 小时/第 3 天/第 7 天”触达——但这些都是运营策略与标签规则，数据集里并没有落地“注册天数
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少注册时间与首单时间字段；允许引用事实数字（如数据规模），但禁止“约/预计/估算”等近似表述后跟结果数字；本题 forbidden_result_units=[] 不限定单位，靠人工确认不得出现任何编造转化天数（如“平均 N 天”）

### bench_neg_006 · negative

- 自动判定：PASS
- 问题：“高价值用户”的标签定义是什么？demo 数据集能否精确统计高价值用户数量？如果无法精确统计，请说明原因，不要编造统计数字。
- 最终回答：## 一、“高价值用户”标签定义（原文引用）

来自知识库 `tag_definitions.md`：

> **高价值用户**
> 定义：**近 90 天消费金额排名前 20%，且近 30 天有活跃行为（登录、浏览、下单任一）**。
> 更新频率：T+1。
> 负责人：数据部-用户增长组。
> 用途：营销优先级排序、专属客服分配。

注意区分同一份文档里的另一个易混标签：**高客单用户** = 累计平均客单价 ≥ 1000 元（负责人：数据部-用户价值组），两者口径不同，不能互相替代。

## 二、能否用当前 demo 数据集精确统计？——不能

原因是该定义的两个必要条件，在现有表结构中都缺少对应字段：

| 口径要求 | 表内可用字段 | 是否可精确判定 |
|---|---|---|
| 近 **90 天**消费金额排名前 20% | 只有 `total_amount`（**累计*
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明定义是近90天消费前20%且近30天活跃、demo 缺近90天消费明细与行为日志（90/20/30 为定义数字，允许出现）；允许引用事实数字，但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“高价值用户 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_multi_016 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员有哪些专属权益？黑卡会员占全库比例是多少（百分比保留两位小数）？
- 最终回答：**一、黑卡权益：知识库中暂无定义**

我两次检索了会员权益相关文档（member_benefits.md 已全部覆盖普通、白银、黄金、钻石四个等级），但**没有找到任何“黑卡会员权益”的条款**。知识库的等级划分标准也只列出四级：

- 钻石会员：累计平均客单价 ≥ 14555 元（约前 5%）
- 黄金会员：6680–14555 元
- 白银会员：2495–6680 元
- 普通会员：< 2495 元

也就是说，在现有权益文档中，**钻石是最高等级**（7×24 专属顾问、全场免运费、全场 9 折、生日 200 元券 + 双倍积分、新品提前 48 小时、30 天无理由退换、2 倍积分）。

注意：数据库实际存在黑卡会员（3 人），但知识库缺少对应权益说明，说明等级体系与权益文档不一致，建议补充黑卡权益条款后再对外答复。如果客服遇到黑卡用户咨询，只能按 SOP 先查等级与权益有效期，
- 复核项：黑卡仅 3 人，占比样本极小，需人工确认结论可用性

### bench_multi_019 · multi_tool

- 自动判定：FAIL
- 问题：黑卡会员的平均客单价是普通会员的多少倍（保留两位小数）？
- 最终回答：**黑卡会员的平均客单价约为普通会员的 28.55 倍。**

依据为对 `user_profile_vectors` 表的统计：
- 黑卡会员平均客单价：**37,665.00 元**（3 人）
- 普通会员平均客单价：**1,319.11 元**（4,053 人）
- 倍数：37,665.00 ÷ 1,319.11 ≈ **28.55**

需要注意：黑卡样本仅 3 人，平均值容易受个体极端值影响，因此倍数仅供参考；总体平均客单价还可用中位数或订单加权口径进一步交叉验证。
- 复核项：黑卡仅 3 人，倍数样本不稳定，需人工确认

### bench_neg_007 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户近 7 天的登录次数。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有数据不支持统计“近 7 天登录次数”

我已核实数据现状，无法给出任何登录次数数字，也不做估算。

**依据 1：表结构里没有任何登录字段**
执行 `SELECT * FROM user_profile_vectors LIMIT 1` 返回的全部列是：
`id, user_id, profile_text, embedding, dept, sensitivity, update_time, age, gender, city, member_level, order_count, total_amount, avg_amount, top_category, days_since_last_buy, platforms`
没有登录次数、最近登录时间、活跃行为记录这类字段。

**依据 2：唯一带时间语义的字段与“登录”无关，也不是绝对日期**
- `days_sinc
- 复核项：必须人工确认：若给出替代指标，必须明确标注它不是登录次数

### bench_neg_008 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中商品退货原因分布。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：**结论：当前 demo 数据集不支持统计商品退货原因分布，无法给出任何分布数字。**

依据：

1. **可用表只有两张**，均为用户画像和知识库文本，不含任何退货记录：
   - `user_profile_vectors`：`user_id / profile_text / age / gender / city / member_level / order_count / total_amount / avg_amount / top_category / days_since_last_buy / platforms`，都是用户累计统计字段，没有订单明细、商品 ID、退货原因、退货时间等字段。
   - `wiki_vectors`：只有 6 份文档分块（报告模板、权益说明、标签口径、分层方法、营销手册、客服 SOP），是文字资料，不是业务数据。
2. **我尝试通过 `inf
- 复核项：必须人工确认未给出编造结果

### hold_017 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户的投诉率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有 demo 数据无法统计投诉率，我不会编造数字

### 依据（实际核查）
1. **实际表结构核查**：执行 `SELECT * FROM user_profile_vectors LIMIT 1` 后，返回字段为：
   `id, user_id, profile_text, embedding, dept, sensitivity, update_time, metadata, age, gender, city, member_level, order_count, total_amount, avg_amount, top_category, days_since_last_buy, platforms`
   其中**没有任何与投诉、工单、售后、差评或退款相关的字段**。另一张表 `wiki_vectors` 只有 `doc_name / chunk_text`
- 复核项：必须人工确认未给出编造投诉率

### hold_018 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中商品的毛利率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有 demo 数据无法统计商品毛利率

**原因：没有商品维度，也没有成本数据。**

### 一、实际可用的数据

| 数据源 | 内容 | 是否可算毛利率 |
|---|---|---|
| `user_profile_vectors`（8110 条） | 用户级累计画像：order_count、total_amount、avg_amount、top_category、days_since_last_buy 等 | ❌ 只有用户级累计金额，无商品、无成本 |
| `wiki_vectors`（36 条） | analysis_report_template、member_benefits、tag_definitions、segmentation、marketing_playbook、cs_sop | ❌ 仅为口径与 SOP 文档，无商品毛利数据 |

我做了一次表清单核验
- 复核项：必须人工确认未给出编造毛利率
