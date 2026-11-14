# Agent Eval · benchmark

- 任务数：80
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate（v1 复合口径） | **95.0%** |
| Business Correctness | **98.8%** |
| Tool Policy Compliance | **98.8%** |
| Tool Selection Accuracy | **96.2%** |
| Tool Execution Success | **92.9%** |
| Error Recovery | 87.5% |
| 平均 Steps | 2.50 |
| 平均 Tool Calls | 1.94 |
| 平均耗时 | 4.0s |
| Input Tokens | 635,626 |
| Output Tokens | 36,428 |
| 平均 Tokens / 任务 | 8401 |
| Estimated Cost | N/A（未配置 EVAL_*_COST_PER_1M） |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 8 / 8 | 100.0% |
| execute_sql | 20 / 20 | 100.0% |
| multi_tool | 23 / 26 | 88.5% |
| negative | 9 / 10 | 90.0% |
| rag_search | 16 / 16 | 100.0% |

## 未通过任务（4）

### bench_multi_001 · multi_tool

- 问题：“高客单用户”的标签口径是什么？按该口径统计 demo 数据集中高客单用户的数量及其占全库用户的比例（百分比保留两位小数）。
- 状态：COMPLETED
- Request ID：req_7245b7b2decb4060
- Execution ID：exec_cc2f9c6bb39f4244
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
- 最终回答：## 一、标签口径（来源：知识库 `tag_definitions.md`）

> **高客单用户**：累计平均客单价 **≥ 1000 元**，使用累计口径、T+1 更新，负责人为数据部-用户价值组；用途是高客单价商品推荐、VIP 服务分配、利润分析。

## 二、按该口径统计（demo 数据集）

统计 SQL：
```sql
SELECT COUNT(*) AS total_users,
       SUM(CASE WHEN avg_amount >= 1000 THEN 1 ELSE 0 END) AS high_aov_users,
       ROUND(100.0*SUM(CASE WHEN avg_amount >= 1000 THEN 1 ELSE 0 END)/COUNT(*), 2) AS high_aov_pct
FROM user_profile_vectors LIMIT 1
```

| 指标 | 数值 |
|---|---|
| 全库用户数 | 8,110 |
| 高客单用户数（avg_amount ≥ 1000 元） | **6,708** |


- Trace events：12
  - tool_finished · rag_search · 94.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1343.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 16.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2828.0
  - run_finished · COMPLETED · 

### bench_multi_004 · multi_tool

- 问题：按用户分群文档中的“沉默客”定义统计 demo 数据集中沉默客的数量及占全库比例（百分比保留两位小数）。
- 状态：COMPLETED
- Request ID：req_79eac23f4e944f07
- Execution ID：exec_716f8c535e3c4e93
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
- 最终回答：## 沉默客数量与占比

**口径依据**（segmentation.md「用户分群策略 › 分群维度」原文）：
> 生命周期：新客（注册 ≤ 30 天）、活跃客（近 30 天有行为）、**沉默客（31–90 天无行为）**、流失客（> 90 天无行为）。

本库没有绝对时间列，因此用 `days_since_last_buy`（距最后一次购买天数）作为"无行为天数"的代理，取 **31 ≤ days_since_last_buy ≤ 90**。

**统计结果**：

| 指标 | 数值 |
|---|---|
| 沉默客数量 | **2,383 人** |
| 全库用户总数 | 8,110 人 |
| 占全库比例 | **29.38%** |

SQL 依据：
```sql
SELECT COUNT(*) FILTER (WHERE days_since_last_buy BETWEEN 31 AND 90) AS silent_cnt,
       COUNT(*) AS total_cnt,
       ROUND(COUNT(*) FILTER (WHERE days_s

- Trace events：12
  - tool_finished · rag_search · 93.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1266.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 16.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2093.0
  - run_finished · COMPLETED · 

### hold_011 · multi_tool

- 问题：男性用户占全库用户的比例是多少（百分比保留两位小数）？
- 状态：COMPLETED
- Request ID：req_7e1f2ba31eba4740
- Execution ID：exec_012eef0a5c66461e
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
- 最终回答：男性用户占全库（user_profile_vectors，共 8110 人）的比例为 **49.38%**（4005 / 8110）。

依据 SQL：
```sql
SELECT COUNT(*) AS total,
       SUM(CASE WHEN gender='男' THEN 1 ELSE 0 END) AS male_count,
       ROUND(SUM(CASE WHEN gender='男' THEN 1 ELSE 0 END)*100.0/COUNT(*), 2) AS male_pct
FROM user_profile_vectors LIMIT 10;
-- 结果：total=8110, male_count=4005, male_pct=49.38
```
性别口径中，女性用户为 4105 人，占 50.62%。

- Trace events：8
  - run_started ·  · 
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1656.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 16.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1375.0
  - run_finished · COMPLETED · 

### hold_018 · negative

- 问题：统计 demo 数据集中商品的毛利率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 状态：COMPLETED
- Request ID：req_62704776441d4374
- Execution ID：exec_1f386a5415f043ab
- 业务正确性：FAIL
- 工具策略：PASS
- 期望工具：[]
- 必需工具：—
- 可选工具：—
- 实际工具：['rag_search', 'rag_search', 'execute_sql']
- 缺少工具：—
- 缺少关键词：['不存在']
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：['必须人工确认未给出编造毛利率']
- 最终回答：## 结论：现有数据无法统计商品毛利率，我没有做任何估算

### 依据（实际检索与查询结果）

1. **数据表层面**：demo 数据集中只有两张表：
   - `user_profile_vectors`：用户画像表，字段为用户 ID、画像文本、年龄、性别、城市、会员等级、累计订单数、累计总消费 `total_amount`、平均客单价 `avg_amount`、偏好品类 `top_category`、距最后一次购买天数 `days_since_last_buy`、平台。**没有商品 ID/SKU、售价、数量、成本等任何商品级或订单行级字段**。
   - `wiki_vectors`：知识库文档分块（标签口径、权益、SOP、报告模板等），**不含毛利率的定义或计算公式**。
   - 我尝试用 `information_schema` 查询全库表结构时，被只读白名单校验拒绝（错误码 `SQL_VALIDATION_ERROR`），说明该库只开放上述白名单表，没有可用的商品表或成本表。

2. **知识库层面**：用“毛利率”“成本”“售价”检索 `wiki_vectors`，命

- Trace events：14
  - tool_finished · rag_search · 157.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1281.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 0.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 5422.0
  - run_finished · COMPLETED · 


## 人工复核清单（15）

### bench_sql_002 · execute_sql

- 自动判定：PASS
- 问题：按会员等级统计平均订单数（order_count 的平均值，保留两位小数），哪个等级的平均订单数最高？数值是多少？
- 最终回答：按会员等级统计的平均订单数（order_count 平均值，保留两位小数）如下：

| 会员等级 | 用户数 | 平均订单数 |
|---|---|---|
| 白银 | 2434 | 2.98 |
| 黄金 | 1217 | 2.90 |
| 普通 | 4053 | 2.34 |
| 钻石 | 403 | 1.80 |
| 黑卡 | 3 | 1.33 |

**平均订单数最高的是「白银」等级，为 2.98 单。**（黄金紧随其后 2.90；钻石、黑卡用户量少，均值偏低）

依据：`SELECT member_level, COUNT(*), ROUND(AVG(order_count),2) FROM user_profile_vectors GROUP BY member_level ORDER BY 3 DESC`。
- 复核项：白银 2.98 与黄金 2.90 差值仅 0.08，等级排序接近噪声，需人工确认该结论的业务可用性

### bench_sql_007 · execute_sql

- 自动判定：PASS
- 问题：黑卡会员分布在哪些城市？各自有多少人？
- 最终回答：**黑卡会员城市分布（SQL 实测）**

| 城市 | 人数 |
|---|---|
| 北京 | 3 |

- 黑卡会员总数为 **3 人**，全部集中在北京（覆盖城市数 = 1）。

依据：`SELECT city, COUNT(*) FROM user_profile_vectors WHERE member_level='黑卡' GROUP BY city`；全表 8110 条中黑卡仅 3 条，样本极小，因此城市分布结论只具有描述意义，不宜用于推断整体会员结构或做城市级投放决策。
- 复核项：黑卡仅 3 人且全部在北京，城市分布不具统计代表性，需人工确认结论措辞

### bench_multi_011 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员的平均客单价是钻石会员的多少倍（保留两位小数）？
- 最终回答：**结论：约为 1.76 倍。**

依据（SQL 统计 `user_profile_vectors`）：

| 会员等级 | 人数 | 平均客单价（avg_amount 的均值） |
|---|---|---|
| 黑卡 | 3 | 37,665.00 元 |
| 钻石 | 403 | 21,416.52 元 |

计算：37,665.00 ÷ 21,416.52 ≈ **1.76**

说明：黑卡样本仅 3 人，统计波动较大，结论宜作参考；若需要，可改看中位数或分布区间。
- 复核项：黑卡仅 3 人，黑卡/钻石客单价倍数样本不稳定，需人工确认结论可用性

### bench_neg_001 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中被营销活动触达过的用户数量。如果现有数据不支持该统计，请说明缺少什么；不要编造数字。
- 最终回答：**结论：现有 demo 数据不支持这项统计，无法给出被营销活动触达的用户数量。我不会编造数字。**

依据核查：

1. **表结构里没有触达相关字段**
   - `user_profile_vectors` 只有 12 列：user_id / profile_text / age / gender / city / member_level / order_count / total_amount / avg_amount / top_category / days_since_last_buy / platforms（其中没有任何字段是“营销活动触达记录”，也没有活动 ID、触达渠道、触达时间或触达次数）。
   - `wiki_vectors` 是知识库文档分块，只有 36 条规则文本，不是用户级的触达明细。
   - 我尝试查询 `information_schema` 以确认
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少营销触达/推送明细（发送日志）数据；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“触达 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_002 · negative

- 自动判定：PASS
- 问题：计算 demo 数据集中商品的退货率（退货订单数 ÷ 总订单数）。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：**结论：当前 demo 数据集无法计算退货率，因此我不给出任何数值。**

**原因（基于工具核查）：**

1. **无退货字段**：对 `user_profile_vectors` 查询 `return_count` 时，数据库直接报错 `UndefinedColumn: column "return_count" does not exist`。该表只有 user_id / profile_text / age / gender / city / member_level / order_count / total_amount / avg_amount / top_category / days_since_last_buy / platforms 这些字段，**没有任何退货、退款、售后类字段**。
2. **无订单明细表**：`order_count` 只是“累计订单数（1–1
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少订单明细/退货字段（分子无来源）；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“退货率为 N%”这类带“%”单位的明确结果（forbidden_result_units=[%]）

### bench_neg_003 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中“母婴偏好”用户的数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有数据无法统计“母婴偏好”用户数量，因为这个标签在本数据集中不存在，没有可用数字

### 1. 口径有定义，但数据没有对应字段
知识库确实定义了该标签（`tag_definitions.md`）：
> **母婴偏好用户**：近 90 天购买母婴品类商品 ≥ 2 次，或浏览母婴品类 ≥ 10 次。更新频率 T+1。

然后按这个口径核对当前库，两个必要条件都缺失：
- **没有“母婴”这个品类值**：`user_profile_vectors.top_category` 实际只有 7 个取值，全部统计结果如下（`GROUP BY top_category`）：

| 品类 | 用户数 |
|---|---|
| 电子产品 | 2235 |
| 家居 | 1794 |
| 书籍 | 854 |
| 玩具 | 838 |
| 服装 | 800 |
| 运动 | 797 |
| 美
- 复核项：人工复核：必须人工确认未给出编造结果——回答指出 demo 品类枚举中没有“母婴”，未用玩具/其他品类替代；允许引用事实数字（如品类数量 7），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“母婴偏好 N 人”“数量为 7 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_004 · negative

- 自动判定：PASS
- 问题：预测 demo 数据集在 2026 年 11 月的钻石会员数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：# 结论：无法预测 2026 年 11 月的钻石会员数量，现有数据不支持

## 原因

1. **user_profile_vectors 表只包含一份静态快照。**该表包含 8110 条用户画像，没有注册时间、会员等级生效时间、等级变更记录或历史快照日期等任何绝对时间字段；因此无法按年、月或日筛选，也无法重建过去任一月份的会员结构。
2. **该表唯一的时间字段是相对天数。**这个字段是 `days_since_last_buy`，实测范围为 0~364 天，它只表示“距最后一次购买的天数”，不含具体的日历日期；因此既不能定位到 2026 年 11 月，也不能作为时间序列来外推。
3. **缺少预测所需的数据。**要预测 2026 年 11 月的会员数，至少需要历史逐月会员等级存量、升级和降级规则以及升级转化率、新增和流失人数，或者会员权益门槛的变动。当前库内都没有这些数据。
4. *
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明单时点静态快照/无时间序列、无法预测未来（可提当前 403 人作为事实）；允许引用事实数字（2026/11/403 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“预测为 N 人”“预计 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_005 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户从注册到完成首单的平均转化天数。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有数据不支持计算“注册→首单”平均转化天数

### 依据（已核对数据）
1. **`user_profile_vectors` 的全部字段**（`SELECT * ... LIMIT 2` 返回的 18 个字段）只有：id、user_id、profile_text、embedding、dept、sensitivity、update_time、metadata、age、gender、city、member_level、order_count、total_amount、avg_amount、top_category、days_since_last_buy、platforms。
   → 其中**没有注册时间字段，也没有首单时间字段**，只有 `days_since_last_buy`（距最后一次购买的天数）和累计值（`order_count`、`total_amount`、`a
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少注册时间与首单时间字段；允许引用事实数字（如数据规模），但禁止“约/预计/估算”等近似表述后跟结果数字；本题 forbidden_result_units=[] 不限定单位，靠人工确认不得出现任何编造转化天数（如“平均 N 天”）

### bench_neg_006 · negative

- 自动判定：PASS
- 问题：“高价值用户”的标签定义是什么？demo 数据集能否精确统计高价值用户数量？如果无法精确统计，请说明原因，不要编造统计数字。
- 最终回答：## 一、“高价值用户”的标签定义（引自 tag_definitions.md）

> **高价值用户**
> 定义：**近 90 天消费金额排名前 20%**，**且近 30 天有活跃行为（登录、浏览、下单任一）**。
> 更新频率：T+1。负责人：数据部-用户增长组。
> 用途：营销优先级排序、专属客服分配。

另外提醒一个容易混淆的标签：**高客单用户**= 累计平均客单价 ≥ 1000 元；它与“高价值用户”是**两个不同口径**，不能混用。

## 二、当前 demo 数据集无法精确统计高价值用户数量

有两个条件无法通过当前数据满足：

1. **没有“近 90 天消费金额”字段。** `user_profile_vectors` 只有累计口径的 `total_amount`/`avg_amount`（文档也注明是“累计口径”），没有按订单或按时间段的金额，因此无法计算“近 9
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明定义是近90天消费前20%且近30天活跃、demo 缺近90天消费明细与行为日志（90/20/30 为定义数字，允许出现）；允许引用事实数字，但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“高价值用户 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_multi_016 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员有哪些专属权益？黑卡会员占全库比例是多少（百分比保留两位小数）？
- 最终回答：**1. 黑卡权益：知识库中未收录**

我在知识库 `member_benefits.md` 中做了两次检索（“黑卡会员专属权益”“黑卡 会员等级 权益 最高等级”），该文档只包含以下等级的权益原文：

- 普通：基础售后、7天无理由退换、积分1倍
- 白银：生日50元券、10天无理由退换、积分1.2倍
- 黄金：在线客服优先、满99免运费、生日100元券、新品提前24h、15天退换、积分1.5倍
- 钻石：7×24一对一专属顾问、全场免运费、全场9折、生日200元券、新品提前48h、30天退换、积分2倍

同时，`member_benefits.md` 的「等级划分标准」只定义到钻石会员（累计平均客单价 ≥ 14555 元，约前 5%），**没有黑卡等级的门槛定义，也没有任何黑卡权益条款**。因此，我不能编造黑卡的权益内容。若需要对外答复，建议先由数据部-用户价值组补充黑卡等级及权益文
- 复核项：黑卡仅 3 人，占比样本极小，需人工确认结论可用性

### bench_multi_019 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员的平均客单价是普通会员的多少倍（保留两位小数）？
- 最终回答：**结论：黑卡会员的平均客单价约为普通会员的 28.55 倍。**

依据如下，基于 SQL 查询 `user_profile_vectors` 得到：

| 会员等级 | 人数 | 平均客单价 |
|---|---|---|
| 黑卡 | 3 | 37,665.00 元 |
| 普通 | 4,053 | 1,319.11 元 |

倍数计算：37,665.00 ÷ 1,319.11 ≈ 28.55 倍（保留两位小数）。

注意：黑卡会员仅 3 人，样本极小，这一倍数受个别用户影响较大，建议参考时结合人数规模。
- 复核项：黑卡仅 3 人，倍数样本不稳定，需人工确认

### bench_neg_007 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户近 7 天的登录次数。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有数据不支持，无法统计“近 7 天登录次数”

**缺少的内容：**

| 所需数据 | 现有情况 |
|---|---|
| 登录事件明细表（login_id / 登录时间戳 / 用户ID） | ❌ 库中没有事件表，也没有任何登录日志表 |
| 绝对时间字段（可做“近 7 天”这类时间筛选） | ❌ 两张表都没有日期或时间列；`user_profile_vectors` 只有相对天数 `days_since_last_buy` |
| 登录次数指标字段 | ❌ 表的 11 个字段中没有任何字段记录“登录次数/活跃次数/访问次数” |
| 时间序列数据 | ❌ 无法按年、月、日聚合，也无法回答“某时间窗口内的次数”类问题 |

**已核实的依据：**
- 表结构：`user_profile_vectors`（8110 行）只有 user_id、profile_text、age
- 复核项：必须人工确认：若给出替代指标，必须明确标注它不是登录次数

### bench_neg_008 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中商品退货原因分布。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：**结论：现有 demo 数据集无法统计商品退货原因分布，因此我不会给出数字。**

## 原因说明

**1. 库内没有售后或退货数据表**
当前可访问的白名单表只有两张：
- `user_profile_vectors`（8110 条用户画像：年龄、性别、城市、会员等级、订单数、累计消费、平均客单价、偏好品类、距末次购买天数、活跃平台）
- `wiki_vectors`（36 条运营知识库分块：标签口径、会员权益、分层、营销手册、客服 SOP、分析报告模板）

两张表都没有「退货原因」或「退款」字段，也没有订单明细表和商品明细表。因此无法按退货原因分组统计。

**2. 知识库里只有处理流程，没有统计口径**
检索“退货原因分布 / 退货率 / 退款数据”，只命中客服 SOP 的处理场景，例如：
- `cs_sop.md` 场景一：物流延迟投诉 → 提供 10 元券或积分，记录工单并标
- 复核项：必须人工确认未给出编造结果

### hold_017 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户的投诉率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有 demo 数据无法统计投诉率，也没有任何可替代的近似算法

**核查过程与依据**

1. **用户画像表 `user_profile_vectors` 中没有投诉相关字段**
   该表只有 12 个字段：`user_id / profile_text / age / gender / city / member_level / order_count / total_amount / avg_amount / top_category / days_since_last_buy / platforms`，其中没有投诉次数、投诉标志、工单数、售后记录等任何一个字段。

2. **画像文本里也没有投诉记录**
   执行 SQL：`SELECT COUNT(*) AS total, SUM(CASE WHEN profile_text LIKE '%投诉%' THEN 1
- 复核项：必须人工确认未给出编造投诉率

### hold_018 · negative

- 自动判定：FAIL
- 问题：统计 demo 数据集中商品的毛利率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有数据无法统计商品毛利率，我没有做任何估算

### 依据（实际检索与查询结果）

1. **数据表层面**：demo 数据集中只有两张表：
   - `user_profile_vectors`：用户画像表，字段为用户 ID、画像文本、年龄、性别、城市、会员等级、累计订单数、累计总消费 `total_amount`、平均客单价 `avg_amount`、偏好品类 `top_category`、距最后一次购买天数 `days_since_last_buy`、平台。**没有商品 ID/SKU、售价、数量、成本等任何商品级或订单行级字段**。
   - `wiki_vectors`：知识库文档分块（标签口径、权益、SOP、报告模板等），**不含毛利率的定义或计算公式**。
   - 我尝试用 `information_schema` 查询全库表结构时，被只读白名单校验拒绝（错误码
- 复核项：必须人工确认未给出编造毛利率
