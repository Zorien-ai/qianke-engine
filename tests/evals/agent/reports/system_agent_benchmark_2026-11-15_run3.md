# Agent Eval · benchmark

- 任务数：80
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate（v1 复合口径） | **93.8%** |
| Business Correctness | **97.5%** |
| Tool Policy Compliance | **97.5%** |
| Tool Selection Accuracy | **96.2%** |
| Tool Execution Success | **95.5%** |
| Error Recovery | 83.3% |
| 平均 Steps | 2.50 |
| 平均 Tool Calls | 1.96 |
| 平均耗时 | 3.7s |
| Input Tokens | 626,330 |
| Output Tokens | 38,227 |
| 平均 Tokens / 任务 | 8307 |
| Estimated Cost | N/A（未配置 EVAL_*_COST_PER_1M） |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 8 / 8 | 100.0% |
| execute_sql | 20 / 20 | 100.0% |
| multi_tool | 23 / 26 | 88.5% |
| negative | 8 / 10 | 80.0% |
| rag_search | 16 / 16 | 100.0% |

## 未通过任务（5）

### bench_multi_001 · multi_tool

- 问题：“高客单用户”的标签口径是什么？按该口径统计 demo 数据集中高客单用户的数量及其占全库用户的比例（百分比保留两位小数）。
- 状态：COMPLETED
- Request ID：req_c368e66bb5674878
- Execution ID：exec_773bbdbdbfe243b8
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
- 最终回答：**口径（来源：知识库 tag_definitions.md）**
- 高客单用户：**累计平均客单价 ≥ 1000 元**（累计口径，T+1 更新；负责人：数据部-用户价值组）。
- 同一份文档还定义了与之配套的其他客单价区间：中客单为近 90 天平均客单价 500–1000 元，低客单为 < 500 元。

**demo 数据集统计结果**（对应字段：`user_profile_vectors.avg_amount ≥ 1000`；SQL 已执行）

| 指标 | 数值 |
|---|---|
| 全库用户数 | 8,110 |
| 高客单用户数 | 6,708 |
| 占全库比例 | **82.71%** |

所用 SQL：
```sql
SELECT COUNT(*) AS total_users,
       SUM(CASE WHEN avg_amount >= 1000 THEN 1 ELSE 0 END) AS high_ticket_users,
       ROUND(SUM(CASE WHEN avg_amount >= 1000 THEN 1 ELSE 0

- Trace events：14
  - tool_finished · rag_search · 328.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1938.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 15.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2531.0
  - run_finished · COMPLETED · 

### bench_neg_004 · negative

- 问题：预测 demo 数据集在 2026 年 11 月的钻石会员数量。如果现有数据不支持，请说明原因；不要编造数字。
- 状态：COMPLETED
- Request ID：req_3f8e10f54f2e4bf1
- Execution ID：exec_bea49319574c45d3
- 业务正确性：FAIL
- 工具策略：PASS
- 期望工具：[]
- 必需工具：—
- 可选工具：—
- 实际工具：['execute_sql', 'rag_search']
- 缺少工具：—
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：['5', '4.97']
- 人工复核项：['人工复核：必须人工确认未给出编造结果——回答说明单时点静态快照/无时间序列、无法预测未来（可提当前 403 人作为事实）；允许引用事实数字（2026/11/403 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“预测为 N 人”“预计 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）']
- 最终回答：**结论：无法预测 2026 年 11 月的钻石会员数量，现有数据不支持这个预测。**

**原因（基于库内口径与实测）**

1. **没有绝对时间列，无法定位“2026 年 11 月”**
   `user_profile_vectors` 中唯一与时间相关的字段是 `days_since_last_buy`（距最后一次购买的天数，实测 0–364 天，0 表示最近一次购买）。它只是相对基准日的偏移量，没有基准日、也没有购买日期，因此无法映射到 2026 年 11 月，更无法构造未来时点。

2. **没有时间序列，无法做趋势外推**
   画像数据是**累计口径快照**（tag_definitions.md：“当前画像数据为累计口径，T+1 更新”），每条用户只有一个当前状态值，没有历史时点序列，因此不能用增长率、季节性等外推方法。

3. **会员等级本身不是按时间累积的**
   member_benefits.md 的口径：钻石会员 = 累计平均客单价 ≥ 14555 元（约前 5%），等级随累计客单价变动，不做“升/降级时间轨迹”记录，因此无法推算 2026 年 11 月

- Trace events：10
  - llm_finished · chat_model · 2453.0
  - tool_started · execute_sql · 
  - tool_started · rag_search · 
  - tool_finished · execute_sql · 16.0
  - tool_finished · rag_search · 94.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2953.0
  - run_finished · COMPLETED · 

### hold_011 · multi_tool

- 问题：男性用户占全库用户的比例是多少（百分比保留两位小数）？
- 状态：COMPLETED
- Request ID：req_dc44baf78e59488d
- Execution ID：exec_d1a234c119024679
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
- 最终回答：男性用户占全库用户的比例是 **49.38%**。

- 依据：`SELECT COUNT(*), SUM(gender='男'), ROUND(SUM(gender='男')*100.0/COUNT(*),2) FROM user_profile_vectors`
- 结果：全库 8,110 人，其中男性 4,005 人 → 4005 ÷ 8110 = 49.38%（女性 4,105 人，占 50.62%）

- Trace events：8
  - run_started ·  · 
  - llm_started · chat_model · 
  - llm_finished · chat_model · 953.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 0.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1484.0
  - run_finished · COMPLETED · 

### hold_016 · multi_tool

- 问题：流失客（>90 天无行为）占全库用户的比例是多少（百分比保留两位小数）？
- 状态：COMPLETED
- Request ID：req_4bf6c863f25d46c8
- Execution ID：exec_f7d0884e47f94c03
- 业务正确性：PASS
- 工具策略：FAIL
- 期望工具：['rag_search', 'execute_sql', 'calculator']
- 必需工具：['rag_search', 'execute_sql', 'calculator']
- 可选工具：—
- 实际工具：['execute_sql', 'rag_search']
- 缺少工具：['calculator']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：流失客（`days_since_last_buy > 90` 天）占全库用户的比例为 **50.02%**。

- 流失客人数：**4,057 人**
- 全库用户数：**8,110 人**
- 计算口径：`> 90 天`，不含 90 天整；资料中“沉默客”为 31–90 天，即包含 90 天。

依据：知识库 `segmentation.md` 中“流失客（> 90 天无行为）”的定义，以及 `user_profile_vectors` 表实际统计结果（4,057 / 8,110）。

- Trace events：10
  - llm_finished · chat_model · 1329.0
  - tool_started · execute_sql · 
  - tool_started · rag_search · 
  - tool_finished · execute_sql · 15.0
  - tool_finished · rag_search · 109.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1484.0
  - run_finished · COMPLETED · 

### hold_018 · negative

- 问题：统计 demo 数据集中商品的毛利率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 状态：COMPLETED
- Request ID：req_d654c5efd8e94d36
- Execution ID：exec_02edc1ec5f83416d
- 业务正确性：FAIL
- 工具策略：PASS
- 期望工具：[]
- 必需工具：—
- 可选工具：—
- 实际工具：['rag_search', 'execute_sql', 'rag_search']
- 缺少工具：—
- 缺少关键词：['不存在']
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：['必须人工确认未给出编造毛利率']
- 最终回答：## 结论：现有 demo 数据无法计算商品毛利率

我一共尝试了两条核查路径，都没有找到可以计算毛利率的数据：

**1. 数据表层面**
- 数据库的只读白名单只有两张表：`user_profile_vectors`（8110 条用户画像）和 `wiki_vectors`（36 条知识库分块）。
- 我尝试查询 `information_schema.tables` 以枚举全部表，但被 SQL 校验拦截，返回错误 `SQL_VALIDATION_ERROR`，校验提示为：“仅允许 SELECT/WITH、必须带 LIMIT、仅白名单表”。

**2. 知识库口径层面**
我用 `rag_search` 检索“商品毛利率 / 成本 / 售价 / 订单明细”时，只命中客单价、会员权益、报告模板等内容，**没有任何毛利率的计算口径定义**；唯一相关线索是 `tag_definitions.md` 中“高客单用户…用于利润分析”，但该标签只覆盖客单价，没有成本。

**当前唯一带有金额信息的字段，也都不能用来计算毛利率：**
- `total_amount`（累计总消费）、`avg_amo

- Trace events：14
  - tool_finished · rag_search · 93.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1844.0
  - tool_started · rag_search · 
  - tool_finished · rag_search · 109.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 4594.0
  - run_finished · COMPLETED · 


## 人工复核清单（15）

### bench_sql_002 · execute_sql

- 自动判定：PASS
- 问题：按会员等级统计平均订单数（order_count 的平均值，保留两位小数），哪个等级的平均订单数最高？数值是多少？
- 最终回答：按会员等级统计的平均订单数（`AVG(order_count)`，保留两位小数）如下：

| 会员等级 | 用户数 | 平均订单数 |
|---|---|---|
| 白银 | 2434 | 2.98 |
| 黄金 | 1217 | 2.90 |
| 普通 | 4053 | 2.34 |
| 钻石 | 403 | 1.80 |
| 黑卡 | 3 | 1.33 |

**平均订单数最高的等级是「白银」，为 2.98 单。**

依据 SQL：
```sql
SELECT member_level, COUNT(*) AS user_cnt,
       ROUND(AVG(order_count), 2) AS avg_order_count
FROM user_profile_vectors
GROUP BY member_level
ORDER BY avg_order_count D
- 复核项：白银 2.98 与黄金 2.90 差值仅 0.08，等级排序接近噪声，需人工确认该结论的业务可用性

### bench_sql_007 · execute_sql

- 自动判定：PASS
- 问题：黑卡会员分布在哪些城市？各自有多少人？
- 最终回答：**统计结果**：黑卡会员共 3 人，且全部集中在北京；其他 11 个城市都没有黑卡会员。

| 城市 | 黑卡会员人数 |
|---|---|
| 北京 | 3 |
| 其他城市（杭州、南京、上海、深圳、苏州、天津、广州、重庆、武汉、成都、西安） | 0 |

**依据**：`SELECT city, COUNT(*) FROM user_profile_vectors WHERE member_level='黑卡' GROUP BY city` 返回结果只有北京 3 人。

补充说明：在 8110 名用户中，黑卡会员一共只有 3 人，属于极少量顶层人群，样本过小；做城市维度的运营投放时，不建议使用黑卡数据。
- 复核项：黑卡仅 3 人且全部在北京，城市分布不具统计代表性，需人工确认结论措辞

### bench_multi_011 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员的平均客单价是钻石会员的多少倍（保留两位小数）？
- 最终回答：黑卡会员的平均客单价约为钻石会员的 **1.76 倍**。

依据（SQL 查询 user_profile_vectors，按会员等级统计 avg_amount 的均值）：
- 黑卡：3 人，平均客单价 37,665.00 元
- 钻石：403 人，平均客单价 21,416.52 元
- 倍数：37,665.00 ÷ 21,416.52 ≈ **1.76**

⚠️ 注意：黑卡样本仅 3 人，统计结果波动较大，建议仅作参考。
- 复核项：黑卡仅 3 人，黑卡/钻石客单价倍数样本不稳定，需人工确认结论可用性

### bench_neg_001 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中被营销活动触达过的用户数量。如果现有数据不支持该统计，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有 demo 数据不支持该统计，无法给出数字

**核查过程**

1. **可用表与字段**：当前库只有两张白名单表
   - `user_profile_vectors`（8110 条）：`user_id / profile_text / age / gender / city / member_level / order_count / total_amount / avg_amount / top_category / days_since_last_buy / platforms`
   - `wiki_vectors`：6 份文档分块（36 条），属于口径与 SOP 文本，不含用户级明细

   两张表都**没有任何“营销活动触达”相关字段**（没有活动ID、触达时间、触达渠道、触达次数、退订状态等）。尝试查询 `information_schema` 以确认是否
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少营销触达/推送明细（发送日志）数据；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“触达 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_002 · negative

- 自动判定：PASS
- 问题：计算 demo 数据集中商品的退货率（退货订单数 ÷ 总订单数）。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有数据不支持计算退货率，无法给出退货率数值

### 原因

**1. 库里没有订单级或退货级明细数据**

可查询的白名单表只有两张：

| 表 | 粒度 | 与退货相关的字段 |
|---|---|---|
| `user_profile_vectors`（8110 条） | 一行 = 一个用户（`user_id` 唯一，如 U1000） | 无 |
| `wiki_vectors`（36 条分块） | 一行 = 知识库文档分块 | 无 |

`user_profile_vectors` 的实际字段为：`user_id / profile_text / embedding / dept / sensitivity / update_time / metadata / age / gender / city / member_level / order_count（累计订单
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少订单明细/退货字段（分子无来源）；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“退货率为 N%”这类带“%”单位的明确结果（forbidden_result_units=[%]）

### bench_neg_003 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中“母婴偏好”用户的数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：**无法统计：现有 demo 数据不支持“母婴偏好”用户数量这一口径。**

依据：

1. **口径存在，数据不存在**
   - 知识库《用户标签口径说明》（tag_definitions.md）定义：母婴偏好用户 = 近 90 天购买母婴品类商品 ≥ 2 次，或浏览母婴品类 ≥ 10 次；T+1 更新。
   - 但库里没有任何字段能支撑该口径。

2. **品类枚举里没有“母婴”**
   `SELECT top_category, COUNT(*) ... GROUP BY top_category` 实际只有 7 个取值（合计 8110 条）：电子产品 2235、家居 1794、书籍 854、玩具 838、服装 800、运动 797、美妆 792。不存在“母婴”这个偏好标签取值。

3. **缺失必要的明细字段**
   - 无品类级购买次数/浏览次数（只有累计 order_c
- 复核项：人工复核：必须人工确认未给出编造结果——回答指出 demo 品类枚举中没有“母婴”，未用玩具/其他品类替代；允许引用事实数字（如品类数量 7），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“母婴偏好 N 人”“数量为 7 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_004 · negative

- 自动判定：FAIL
- 问题：预测 demo 数据集在 2026 年 11 月的钻石会员数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：**结论：无法预测 2026 年 11 月的钻石会员数量，现有数据不支持这个预测。**

**原因（基于库内口径与实测）**

1. **没有绝对时间列，无法定位“2026 年 11 月”**
   `user_profile_vectors` 中唯一与时间相关的字段是 `days_since_last_buy`（距最后一次购买的天数，实测 0–364 天，0 表示最近一次购买）。它只是相对基准日的偏移量，没有基准日、也没有购买日期，因此无法映射到 2026 年 11 月，更无法构造未来时点。

2. **没有时间序列，无法做趋势外推**
   画像数据是**累计口径快照**（tag_definitions.md：“当前画像数据为累计口径，T+1 更新”），每条用户只有一个当前状态值，没有历史时点序列，因此不能用增长率、季节性等外推方法。

3. **会员等级本身不是按时间累积的**
  
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明单时点静态快照/无时间序列、无法预测未来（可提当前 403 人作为事实）；允许引用事实数字（2026/11/403 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“预测为 N 人”“预计 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_005 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户从注册到完成首单的平均转化天数。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有数据无法计算「注册 → 首单」平均转化天数，也不应给出任何估算值

**为什么算不出来**

| 需要的字段 | 数据库实际情况 |
|---|---|
| 注册时间（绝对日期） | ❌ 表中没有注册时间或开通时间字段，`user_profile_vectors` 只有 user_id、profile_text、age、gender、city、member_level、order_count、total_amount、avg_amount、top_category、days_since_last_buy、platforms |
| 首单时间（绝对日期） | ❌ 没有订单明细表，无法定位“第一笔订单”的发生时间 |
| 可用于做差的两个时点 | ⚠️ 唯一与时间相关的字段是 `days_since_last_buy`（距**最后一次**购买的天数，相对基准日，实测 0–364
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少注册时间与首单时间字段；允许引用事实数字（如数据规模），但禁止“约/预计/估算”等近似表述后跟结果数字；本题 forbidden_result_units=[] 不限定单位，靠人工确认不得出现任何编造转化天数（如“平均 N 天”）

### bench_neg_006 · negative

- 自动判定：PASS
- 问题：“高价值用户”的标签定义是什么？demo 数据集能否精确统计高价值用户数量？如果无法精确统计，请说明原因，不要编造统计数字。
- 最终回答：## 一、“高价值用户”标签定义（来源：wiki_vectors / tag_definitions.md 原文）

> **定义**：近 **90 天消费金额排名前 20%**，且**近 30 天有活跃行为（登录、浏览、下单任一）**。
> 更新频率：T+1；负责人：数据部-用户增长组；用途：营销优先级排序、专属客服分配。

注：不要与“高客单用户”（累计平均客单价 ≥ 1000 元）混淆；这是两个不同的标签，分属用户价值组与用户增长组。

## 二、demo 数据集**无法**精确统计高价值用户数量

结合当前表结构，两个必要条件都无法满足：

| 定义要求 | 库内可用字段 | 结论 |
|---|---|---|
| 近 90 天**消费金额**及排名 | 只有 `total_amount`（累计总消费）、`avg_amount`（累计平均客单价），都是**累计口径** | ❌ 无
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明定义是近90天消费前20%且近30天活跃、demo 缺近90天消费明细与行为日志（90/20/30 为定义数字，允许出现）；允许引用事实数字，但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“高价值用户 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_multi_016 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员有哪些专属权益？黑卡会员占全库比例是多少（百分比保留两位小数）？
- 最终回答：**一、黑卡会员专属权益：知识库中无此定义（无法回答）**

已检索 `rag_search` 和知识库原文，`member_benefits.md` 全文共 7 个分块，只包含以下等级：

- 等级划分标准：钻石、黄金、白银、普通（按累计平均客单价划分，钻石会员门槛为 ≥14555 元，约前 5%）
- 权益条目：钻石、黄金、白银、普通（共 4 档）
- 会员升级与保级、权益咨询处理流程

**全文没有任何“黑卡”相关条目**（在 `wiki_vectors` 中用 `LIKE '%黑卡%'` 查询返回 0 行）。因此黑卡会员的专属权益在当前资料中没有记载，我不会凭空编造。

值得注意的是：数据库 `user_profile_vectors` 中确实存在 `member_level = '黑卡'` 的 3 条记录，但知识库的等级体系并未收录该等级，这属于**口径与数据不一致**，建议由数
- 复核项：黑卡仅 3 人，占比样本极小，需人工确认结论可用性

### bench_multi_019 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员的平均客单价是普通会员的多少倍（保留两位小数）？
- 最终回答：**黑卡会员的平均客单价约为普通会员的 28.55 倍。**

依据（查询 `user_profile_vectors`，按会员等级汇总）：
- 黑卡：3 人，平均客单价 **37,665.00 元**
- 普通：4,053 人，平均客单价 **1,319.11 元**
- 倍数计算：37,665.00 ÷ 1,319.11 = **28.5533 ≈ 28.55**

⚠️ 口径提示：这里的“平均客单价”是把每位用户的 `avg_amount` 取平均。黑卡样本仅 **3 人**，极易受个别高额用户影响，因此该倍数不宜作为稳定结论；若要更稳健，建议改用消费总额 ÷ 订单总数，或改用中位数来对比。
- 复核项：黑卡仅 3 人，倍数样本不稳定，需人工确认

### bench_neg_007 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户近 7 天的登录次数。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有数据不支持统计“近 7 天登录次数”

### 缺少什么
| 需要的数据 | 是否存在 | 说明 |
|---|---|---|
| 登录行为事件表（user_id + login_time 逐次记录） | ❌ 不存在 | 知识库只有画像标签口径（`tag_definitions.md`），没有登录明细数据源 |
| 绝对日期/时间戳字段 | ❌ 不存在 | 数据口径明确：全库只有相对天数 `days_since_last_buy`（0～364），无法按“近 7 天”这种自然日期窗口筛选 |
| 活跃行为次数类指标（登录次数/浏览次数/加购次数） | ❌ 不存在 | `user_profile_vectors` 只有订单数、消费金额、客单价、偏好品类等累计口径字段 |

补充说明：`tag_definitions.md` 中“高价值用户/高潜用户/流失预警用户”的定义里确实
- 复核项：必须人工确认：若给出替代指标，必须明确标注它不是登录次数

### bench_neg_008 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中商品退货原因分布。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：**结论：现有 demo 数据不支持统计商品退货原因分布，我不会给出任何编造的数字。**

原因如下：

1. **没有订单/售后明细表**。当前库里只有两张表：
   - `user_profile_vectors`（8110 条用户画像）：字段只有 `user_id / profile_text / age / gender / city / member_level / order_count / total_amount / avg_amount / top_category / days_since_last_buy / platforms`，全部是**用户粒度累计指标**，最小粒度不是订单，更没有“退货原因”“售后状态”“退货商品”这类字段。
   - `wiki_vectors`（36 条知识库分块）：内容是标签口径、会员权益、SOP、分析模板等方法论文档，属于规则/流程说明
- 复核项：必须人工确认未给出编造结果

### hold_017 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户的投诉率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有数据不支持计算投诉率，我无法给出这个数字

### 依据
1. **表结构里没有任何投诉相关字段**
   - `user_profile_vectors`（8110 条）的字段只有：user_id、profile_text、age、gender、city、member_level、order_count、total_amount、avg_amount、top_category、days_since_last_buy、platforms，其中没有任何投诉标记、投诉次数、工单或售后状态字段。
   - `wiki_vectors` 是知识库文档分块，不是业务明细表。
   - 我还尝试查询库内其他表的字段清单，但查询被 SQL 白名单拦截（SQL_VALIDATION_ERROR：仅白名单表可用），这进一步说明可查询的表只有上述两张。

2. **知识库里只有处理投诉的流程，
- 复核项：必须人工确认未给出编造投诉率

### hold_018 · negative

- 自动判定：FAIL
- 问题：统计 demo 数据集中商品的毛利率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有 demo 数据无法计算商品毛利率

我一共尝试了两条核查路径，都没有找到可以计算毛利率的数据：

**1. 数据表层面**
- 数据库的只读白名单只有两张表：`user_profile_vectors`（8110 条用户画像）和 `wiki_vectors`（36 条知识库分块）。
- 我尝试查询 `information_schema.tables` 以枚举全部表，但被 SQL 校验拦截，返回错误 `SQL_VALIDATION_ERROR`，校验提示为：“仅允许 SELECT/WITH、必须带 LIMIT、仅白名单表”。

**2. 知识库口径层面**
我用 `rag_search` 检索“商品毛利率 / 成本 / 售价 / 订单明细”时，只命中客单价、会员权益、报告模板等内容，**没有任何毛利率的计算口径定义**；唯一相关线索是 `tag_definitions.m
- 复核项：必须人工确认未给出编造毛利率
