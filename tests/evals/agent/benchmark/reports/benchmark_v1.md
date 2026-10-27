# Agent Eval · benchmark

- 任务数：80
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate（v1 复合口径） | **96.2%** |
| Business Correctness | **100.0%** |
| Tool Policy Compliance | **97.5%** |
| Tool Selection Accuracy | **96.2%** |
| Tool Execution Success | **96.0%** |
| Error Recovery | 100.0% |
| 平均 Steps | 2.48 |
| 平均 Tool Calls | 1.88 |
| 平均耗时 | 3.9s |
| Input Tokens | 505,678 |
| Output Tokens | 35,806 |
| 平均 Tokens / 任务 | 6769 |
| Estimated Cost | N/A（未配置 EVAL_*_COST_PER_1M） |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 8 / 8 | 100.0% |
| execute_sql | 20 / 20 | 100.0% |
| multi_tool | 23 / 26 | 88.5% |
| negative | 10 / 10 | 100.0% |
| rag_search | 16 / 16 | 100.0% |

## 未通过任务（3）

### bench_multi_004 · multi_tool

- 问题：按用户分群文档中的“沉默客”定义统计 demo 数据集中沉默客的数量及占全库比例（百分比保留两位小数）。
- 状态：COMPLETED
- Request ID：req_10ebb2f6ac604354
- Execution ID：exec_c8b19bb692574123
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

口径依据（segmentation.md「分群维度」原文）：
> 生命周期：新客（注册 ≤ 30 天）、活跃客（近 30 天有行为）、**沉默客（31–90 天无行为）**、流失客（> 90 天无行为）

对应字段：`days_since_last_buy BETWEEN 31 AND 90`

统计结果（SQL 直查 user_profile_vectors）：

| 指标 | 数值 |
|---|---|
| 沉默客数量 | 2,383 人 |
| 全库用户数 | 8,110 人 |
| 占全库比例 | 29.38% |

SQL 依据：`SELECT COUNT(*) AS silent_cnt, (SELECT COUNT(*) FROM user_profile_vectors) AS total_cnt, ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM user_profile_vectors),2) AS pct FROM user_profile_vectors WHERE days_since_last_

- Trace events：12
  - tool_finished · rag_search · 157.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 937.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 16.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1687.0
  - run_finished · COMPLETED · 

### bench_multi_009 · multi_tool

- 问题：统计上海各会员等级的人数，并说明人数最多等级占上海用户的比例（百分比保留两位小数）。
- 状态：COMPLETED
- Request ID：req_3bf8f79ef56b42ec
- Execution ID：exec_bd82879dfb614175
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
- 最终回答：**上海各会员等级人数**（依据 SQL：`SELECT member_level, COUNT(*) FROM user_profile_vectors WHERE city='上海' GROUP BY member_level`）

| 会员等级 | 人数 | 占上海用户比例 |
|---|---|---|
| 普通 | 334 | 48.69% |
| 白银 | 206 | 30.03% |
| 黄金 | 114 | 16.62% |
| 钻石 | 32 | 4.66% |
| 黑卡 | 0 | 0.00% |
| **合计** | **686** | 100% |

- 上海用户总数为 686 人（`SELECT COUNT(*) FROM user_profile_vectors WHERE city='上海'`），各等级人数之和为 334+206+114+32 = 686，与上海用户总数一致；上海没有黑卡会员。
- 人数最多的是**普通会员**，共 334 人，占上海用户的 **48.69%**（334/686）。

说明：本表没有绝对时间列，只有 `days_since_

- Trace events：10
  - llm_finished · chat_model · 1359.0
  - tool_started · execute_sql · 
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 0.0
  - tool_finished · execute_sql · 0.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 2016.0
  - run_finished · COMPLETED · 

### hold_016 · multi_tool

- 问题：流失客（>90 天无行为）占全库用户的比例是多少（百分比保留两位小数）？
- 状态：COMPLETED
- Request ID：req_00dbaadad4084219
- Execution ID：exec_022afa1522904cb6
- 业务正确性：PASS
- 工具策略：FAIL
- 期望工具：['rag_search', 'execute_sql', 'calculator']
- 必需工具：['rag_search', 'execute_sql', 'calculator']
- 可选工具：—
- 实际工具：['execute_sql']
- 缺少工具：['calculator', 'rag_search']
- 缺少关键词：—
- 缺少任一拒答词：—
- 非法数字：—
- 人工复核项：—
- 最终回答：按“距最后一次购买天数 > 90 天”统计，流失客占全库用户的比例为 **50.02%**。

- 流失客：4,057 人
- 全库用户：8,110 人
- 计算依据：`4,057 ÷ 8,110 × 100% = 50.02%`（SQL 统计结果）

- Trace events：8
  - run_started ·  · 
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1688.0
  - tool_started · execute_sql · 
  - tool_finished · execute_sql · 0.0
  - llm_started · chat_model · 
  - llm_finished · chat_model · 1093.0
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

**平均订单数最高的是「白银」等级，均值为 2.98 单。**

补充说明：黑卡仅有 3 名用户，样本极小，其均值（1.33）参考意义有限；钻石（1.80）也低于白银、黄金与普通，说明该库中会员等级高低与实际下单频次并非单调正相关。

依据：`SELECT member_level, COUNT(*), ROUND(AVG(order_count),2) ... GROUP BY member_level ORDER BY av
- 复核项：白银 2.98 与黄金 2.90 差值仅 0.08，等级排序接近噪声，需人工确认该结论的业务可用性

### bench_sql_007 · execute_sql

- 自动判定：PASS
- 问题：黑卡会员分布在哪些城市？各自有多少人？
- 最终回答：黑卡会员全库共 3 人，且全部集中在北京。

| 城市 | 黑卡会员人数 |
|---|---|
| 北京 | 3 |
| 合计 | 3 |

依据：SQL `SELECT city, COUNT(*) FROM user_profile_vectors WHERE member_level='黑卡' GROUP BY city` 返回唯一一行「北京 = 3」，与表结构中黑卡总计 3 人一致，即其余 11 个城市（杭州/南京/上海/深圳/苏州/天津/广州/重庆/武汉/成都/西安）均无黑卡会员。

补充提示：样本仅 3 人，占比约 0.037%（3/8110），不足以支撑城市层面的黑卡分布结论，建议仅作为个案参考。
- 复核项：黑卡仅 3 人且全部在北京，城市分布不具统计代表性，需人工确认结论措辞

### bench_multi_011 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员的平均客单价是钻石会员的多少倍（保留两位小数）？
- 最终回答：黑卡会员的平均客单价约是钻石会员的 **1.76 倍**。

计算依据：以下查询按会员等级对 `avg_amount` 求平均。
- 黑卡会员：3 人，平均客单价为 37,665.00 元
- 钻石会员：403 人，平均客单价为 21,416.52 元

两者的比值计算为：37,665.00 ÷ 21,416.52 ≈ **1.7587**，四舍五入保留两位小数后为 **1.76**。

补充说明：黑卡会员仅有 3 人，样本量很小，因此该倍数更容易受到个别用户影响。
- 复核项：黑卡仅 3 人，黑卡/钻石客单价倍数样本不稳定，需人工确认结论可用性

### bench_neg_001 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中被营销活动触达过的用户数量。如果现有数据不支持该统计，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有数据不支持该统计，无法给出触达用户数

我没有编造任何数字；原因来自对表结构和知识库的实际核查：

**1）画像表 `user_profile_vectors` 没有任何活动触达字段**
它只有 8110 条用户的 ID、画像文本、age/gender/city/member_level、order_count/total_amount/avg_amount、top_category、days_since_last_buy、platforms，都是“画像 + 累计消费”口径，不包含活动 ID、触达时间、触达渠道、发送/送达状态。

**2）知识库只有“规则文字”，没有触达记录**
rag_search 命中的 marketing_playbook.md「五、通用频控规则」只说明了频控约束（“同一用户每日最多接收 3 条营销消息”“同一活动同一用户最多触达 2 次”“退订后停
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少营销触达/推送明细（发送日志）数据；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“触达 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_002 · negative

- 自动判定：PASS
- 问题：计算 demo 数据集中商品的退货率（退货订单数 ÷ 总订单数）。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有数据无法计算退货率，因此不提供数字

### 原因（依据工具结果）

1. **没有订单明细表**：当前库里只有两张表：

   - `user_profile_vectors`（用户画像，8110 条）
   - `wiki_vectors`（知识库文档分块，36 条）

   这两张表都没有订单级记录，因此 “退货订单数 ÷ 总订单数” 中的分子和分母都无从统计。

2. **画像表没有退货相关字段**：`user_profile_vectors` 只有 user_id / profile_text / age / gender / city / member_level / order_count / total_amount / avg_amount / top_category / days_since_last_buy / platforms。
   其中 `o
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少订单明细/退货字段（分子无来源）；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“退货率为 N%”这类带“%”单位的明确结果（forbidden_result_units=[%]）

### bench_neg_003 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中“母婴偏好”用户的数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：无法统计，现有数据不支持"母婴偏好"用户数量

### 依据一：库内品类枚举中没有"母婴"
`user_profile_vectors.top_category` 全部取值只有 7 类（SQL：`GROUP BY top_category`）：

| 品类 | 用户数 |
|---|---|
| 电子产品 | 2235 |
| 家居 | 1794 |
| 书籍 | 854 |
| 玩具 | 838 |
| 服装 | 800 |
| 运动 | 797 |
| 美妆 | 792 |

合计 8110，与表总行数一致，即不存在未被列出的第 8 个品类。

### 依据二：文本层面也无任何"母婴"痕迹
对 `top_category`、`profile_text` 做 `%母婴% / %孕% / %婴儿%` 全文匹配，返回 **matched_users = 0**。说明画像摘要里也没
- 复核项：人工复核：必须人工确认未给出编造结果——回答指出 demo 品类枚举中没有“母婴”，未用玩具/其他品类替代；允许引用事实数字（如品类数量 7），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“母婴偏好 N 人”“数量为 7 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_004 · negative

- 自动判定：PASS
- 问题：预测 demo 数据集在 2026 年 11 月的钻石会员数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：**结论：现有数据不支持预测 2026 年 11 月的钻石会员数量，因此本次不提供预测值。**

原因：

1. **没有真实的时间维度数据。** 表 `user_profile_vectors` 只有相对天数 `days_since_last_buy`，取值区间为 0–364 天（依据 SQL：`MIN=0, MAX=364`），这只是一个相对“最后购买日”的天数偏移量，无法映射为具体的年/月/日。所以既无法确定“当前”对应的日历日期，也无法推算 2026 年 11 月这一时点。
2. **没有可供预测的历史时间序列。** 全库仅 8110 条用户画像快照，字段都是累计口径（`order_count`、`total_amount`、`avg_amount` 为累计值，资料也明确“当前画像数据为累计口径，T+1 更新”，来源：tag_definitions.md）。缺少按月或按期的会员等级
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明单时点静态快照/无时间序列、无法预测未来（可提当前 403 人作为事实）；允许引用事实数字（2026/11/403 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“预测为 N 人”“预计 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_005 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户从注册到完成首单的平均转化天数。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有数据无法计算「注册→首单平均转化天数」，未给出数字

### 为什么算不了
我依据实际表结构查询（`SELECT * FROM user_profile_vectors LIMIT 1`）得到以下可用列：
`user_id, profile_text, age, gender, city, member_level, order_count, total_amount, avg_amount, top_category, days_since_last_buy, platforms`，另有 id/embedding/dept/sensitivity/update_time/metadata。

本表中**缺少计算所需两个关键字段**：
1. **无注册时间字段**（无 register_time / register_date / 注册days：0），没有任何「注册时点」锚
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少注册时间与首单时间字段；允许引用事实数字（如数据规模），但禁止“约/预计/估算”等近似表述后跟结果数字；本题 forbidden_result_units=[] 不限定单位，靠人工确认不得出现任何编造转化天数（如“平均 N 天”）

### bench_neg_006 · negative

- 自动判定：PASS
- 问题：“高价值用户”的标签定义是什么？demo 数据集能否精确统计高价值用户数量？如果无法精确统计，请说明原因，不要编造统计数字。
- 最终回答：## 1. 「高价值用户」的标签定义（原文引用）

来自知识库 `tag_definitions.md`：

> **高价值用户**
> 定义：近 90 天消费金额排名前 20%，且近 30 天有活跃行为（登录、浏览、下单任一）。
> 更新频率：T+1。
> 负责人：数据部-用户增长组。
> 用途：营销优先级排序、专属客服分配。

`segmentation.md` 的价值分层口径与之一致：高价值 = 近 90 天消费前 20%，中价值 = 20%–70%，低价值 = 后 30%。

注意不要与 **高客单用户**（`tag_definitions.md`：累计平均客单价 ≥ 1000 元，且该画像数据是累计口径、T+1 更新）混淆；两者属于不同口径，是不同的标签。

## 2. demo 数据集能否精确统计？——不能

我**不提供高价值用户数量**，因为这个数据集无法按定义口径算出精确
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明定义是近90天消费前20%且近30天活跃、demo 缺近90天消费明细与行为日志（90/20/30 为定义数字，允许出现）；允许引用事实数字，但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“高价值用户 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_multi_016 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员有哪些专属权益？黑卡会员占全库比例是多少（百分比保留两位小数）？
- 最终回答：## 一、黑卡会员专属权益

**知识库中没有「黑卡会员」的权益条目，无法给出确切权益。** 检索 `member_benefits.md` 全量相关分块后，只找到以下等级的权益：
- 普通、白银、黄金、钻石会员各自有明确的权益清单，其中钻石会员的权益最完整，包括 7×24 专属客服、全场免运费、全场 9 折、生日 200 元券 + 双倍积分、新品提前 48 小时、30 天无理由退换、积分 2 倍；
- 「等级划分标准」只列出四档：钻石（累计平均客单价 ≥ 14555 元）、黄金（6680–14555）、白银（2495–6680）、普通（<2495），**没有为黑卡设定门槛**；
- 升级与保级规则也是按这四档表述的，即达到上一等级的门槛后，T+1 自动升级。

因此，黑卡权益属于知识库没有覆盖的空白项，建议向数据部-用户价值组或会员运营确认后再作答，不要用钻石权益替代。

## 二、黑卡
- 复核项：黑卡仅 3 人，占比样本极小，需人工确认结论可用性

### bench_multi_019 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员的平均客单价是普通会员的多少倍（保留两位小数）？
- 最终回答：**结论：黑卡会员的平均客单价约为普通会员的 28.55 倍。**

依据（SQL 统计，表 user_profile_vectors）：
- 黑卡会员：3 人，平均客单价 37,665.00 元
- 普通会员：4,053 人，平均客单价 1,319.11 元
- 倍数 = 37,665.00 ÷ 1,319.11 ≈ **28.55**

提示：黑卡样本仅 3 人，该倍数受个别超高消费用户影响较大，建议仅作参考，不宜直接用于投放定档。
- 复核项：黑卡仅 3 人，倍数样本不稳定，需人工确认

### bench_neg_007 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户近 7 天的登录次数。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：**结论：现有数据无法统计「近 7 天登录次数」，因此不给出任何数字。**

**缺少的数据**
1. **无登录行为明细表**：库内只有 `user_profile_vectors`（用户画像汇总）和 `wiki_vectors`（知识库文档），没有登录日志、事件流或活跃明细表，因此没有“登录次数”这个字段。
2. **无绝对日期列**：唯一的近因性字段是 `days_since_last_buy`（距最后一次**购买**的天数，0–364），它只覆盖“购买”行为，且只是相对天数，不是登录时间戳，也没有可聚合的日期，因此无法筛出“近 7 天”这个窗口。
3. **口径文档也不支持**：知识库 `tag_definitions.md` 中“活跃行为”只是把登录、浏览、下单合并为一个布尔判断，例如定义“高价值用户”为近 30 天有活跃行为，并不提供登录次数统计口径；且这些标签是 T+1 的标
- 复核项：必须人工确认：若给出替代指标，必须明确标注它不是登录次数

### bench_neg_008 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中商品退货原因分布。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有数据不支持统计「商品退货原因分布」

**缺失的数据**
- 数据库只有两张表：
  - `user_profile_vectors`（用户画像，8110 条）：字段为 user_id、年龄、性别、城市、会员等级、订单数、消费金额、客单价、偏好品类、距最后一次购买天数、活跃平台；**无订单明细、无商品 ID、无退货或售后字段**。
  - `wiki_vectors`（知识库 36 个分块）：6 份文档（分析报告模板、会员权益、标签口径、分层、营销手册、客服 SOP），**无退货原因类目与口径定义**。

**实际核查结果**
1. SQL 核查：`SELECT COUNT(*) FROM user_profile_vectors WHERE profile_text LIKE '%退货%' OR profile_text LIKE '%退款%'` → **返回 0**，说
- 复核项：必须人工确认未给出编造结果

### hold_017 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户的投诉率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：**结论：无法计算投诉率——当前 demo 数据集不含任何投诉／工单相关数据，我不会编造数字。**

依据：

1. **知识库无投诉率口径**：`cs_sop.md` 只写了投诉／客诉的**处理流程**（物流延迟投诉、商品质量问题的致歉、补偿方案、记录工单并打标等），`tag_definitions.md`、`member_benefits.md`、`marketing_playbook.md` 等也没有“投诉率”的分子／分母定义。检索结果中，得分最高的内容都是处理流程原文，不含任何统计口径。

2. **表结构无投诉字段**：库内只有两张表。
   - `user_profile_vectors`（8110 条）：字段为 user_id、profile_text、age、gender、city、member_level、order_count、total_amount、avg_amou
- 复核项：必须人工确认未给出编造投诉率

### hold_018 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中商品的毛利率。如果现有数据不支持，请说明缺少什么；不要编造数字。
- 最终回答：## 结论：现有数据不支持计算商品毛利率，无法给出任何数值

### 已核实的事实

1. **本库中可用的表只有两张**：
   - `user_profile_vectors`：用户画像维表（用户ID、年龄、性别、城市、会员等级、订单数、消费额、偏好品类、距上次购买天数、活跃平台）
   - `wiki_vectors`：知识库文档分块，共 36 条

   我尝试查询元数据表，探查是否还有其他表，返回 `SQL_VALIDATION_ERROR`，说明该工具**仅允许访问白名单表**，库内不存在商品表或订单明细表。

2. **知识库中也没有毛利率口径**：我对 `wiki_vectors` 做了 `chunk_text ILIKE '%毛利%' OR '%成本%' OR '%利润%'` 的检索，只有 1 条命中 `tag_definitions.md` 的「高客单用户」标签，其“用
- 复核项：必须人工确认未给出编造毛利率
