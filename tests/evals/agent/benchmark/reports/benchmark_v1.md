# Agent Eval · benchmark

- 任务数：40
- 数据集：`demo`
- 运行方式：真实 DeepSeek + LangGraph `run_agent` + 真实工具

## 核心指标

| 指标 | 结果 |
|---|---:|
| Task Success Rate（v1 复合口径） | **97.5%** |
| Business Correctness | **100.0%** |
| Tool Policy Compliance | **100.0%** |
| Tool Selection Accuracy | **97.5%** |
| Tool Execution Success | **93.1%** |
| Error Recovery | 100.0% |
| 平均 Steps | 2.58 |
| 平均 Tool Calls | 2.17 |
| 平均耗时 | 4.8s |

## 分类结果

| 分类 | 通过 / 总数 | Task Success |
|---|---:|---:|
| calculator | 4 / 4 | 100.0% |
| execute_sql | 10 / 10 | 100.0% |
| multi_tool | 11 / 12 | 91.7% |
| negative | 6 / 6 | 100.0% |
| rag_search | 8 / 8 | 100.0% |

## 未通过任务（1）

### bench_multi_004 · multi_tool

- 问题：按用户分群文档中的“沉默客”定义统计 demo 数据集中沉默客的数量及占全库比例（百分比保留两位小数）。
- 状态：COMPLETED
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
- 最终回答：**结论：沉默客 2,383 人，占全库 8,110 人的 29.38%。**

口径依据
- 《用户分群策略》（segmentation.md）分群维度-生命周期：新客（注册 ≤ 30 天）、活跃客（近 30 天有行为）、**沉默客（31–90 天无行为）**、流失客（> 90 天无行为）。
- 本库无绝对时间列，只有相对天数 `days_since_last_buy`（0 表示最近一次购买），因此以 `days_since_last_buy BETWEEN 31 AND 90` 落地“31–90 天无行为”。

统计 SQL
```sql
SELECT COUNT(*) AS silent_cnt,
       (SELECT COUNT(*) FROM user_profile_vectors) AS total_cnt,
       ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM user_profile_vectors), 2) AS pct
FROM user_profile_vectors
WHERE days_since


## 人工复核清单（9）

### bench_sql_002 · execute_sql

- 自动判定：PASS
- 问题：按会员等级统计平均订单数（order_count 的平均值，保留两位小数），哪个等级的平均订单数最高？数值是多少？
- 最终回答：**平均订单数最高的等级：白银，平均订单数 2.98 单**（2434 人）。

各等级明细（`user_profile_vectors` 按 `member_level` 分组，`AVG(order_count)` 保留两位）：

| 会员等级 | 人数 | 平均订单数 |
|---|---|---|
| 白银 | 2434 | 2.98 |
| 黄金 | 1217 | 2.90 |
| 普通 | 4053 | 2.34 |
| 钻石 | 403 | 1.80 |
| 黑卡 | 3 | 1.33 |

依据 SQL：
```sql
SELECT member_level, COUNT(*) AS user_count, ROUND(AVG(order_count),2) AS avg_order_count
FROM user_profile_vectors GROUP BY membe
- 复核项：白银 2.98 与黄金 2.90 差值仅 0.08，等级排序接近噪声，需人工确认该结论的业务可用性

### bench_sql_007 · execute_sql

- 自动判定：PASS
- 问题：黑卡会员分布在哪些城市？各自有多少人？
- 最终回答：**黑卡会员城市分布**

| 城市 | 黑卡会员人数 |
|---|---|
| 北京 | 3 |

- 全库黑卡会员共 3 人，且全部集中在北京（其余 11 个城市均为 0 人）。
- 依据：`SELECT city, COUNT(*) FROM user_profile_vectors WHERE member_level='黑卡' GROUP BY city`，结果仅返回 1 行（北京 3）。

说明：黑卡样本极小（占 8110 名用户的约 0.04%），因此按城市分析时统计意义有限；建议结合消费额、订单数等指标，与钻石或黄金会员一起观察。
- 复核项：黑卡仅 3 人且全部在北京，城市分布不具统计代表性，需人工确认结论措辞

### bench_multi_011 · multi_tool

- 自动判定：PASS
- 问题：黑卡会员的平均客单价是钻石会员的多少倍（保留两位小数）？
- 最终回答：**结论：黑卡会员的平均客单价约为钻石会员的 1.76 倍。**

依据如下（SQL 对 `user_profile_vectors` 按会员等级统计）：

| 会员等级 | 人数 | 平均客单价（元） |
|---|---|---|
| 黑卡 | 3 | 37,665.00 |
| 钻石 | 403 | 21,416.52 |

计算：37,665.00 ÷ 21,416.52 = 1.7587 ≈ **1.76**

需要注意：
- 黑卡样本仅 3 人，均值波动大，只能作为参考，不能直接推广到黑卡整体。
- 这两个等级都远远高于本库客单价 P90 分位（10,383 元），属于极端高客单群体。
- 复核项：黑卡仅 3 人，黑卡/钻石客单价倍数样本不稳定，需人工确认结论可用性

### bench_neg_001 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中被营销活动触达过的用户数量。如果现有数据不支持该统计，请说明缺少什么；不要编造数字。
- 最终回答：**结论：现有数据不支持该统计，无法给出「被营销活动触达过的用户数」。**

依据（已核查）：

1. **表结构里没有任何触达/活动相关字段。** 实际字段为：`id, user_id, profile_text, embedding, dept, sensitivity, update_time, metadata, age, gender, city, member_level, order_count, total_amount, avg_amount, top_category, days_since_last_buy, platforms`（`SELECT * FROM user_profile_vectors LIMIT 1`）。其中没有任何营销活动ID、触达渠道、触达时间、触达次数、退订状态等列。
2. **画像文本与 metadata 中也没有触达痕迹。** 对 `pro
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少营销触达/推送明细（发送日志）数据；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“触达 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_002 · negative

- 自动判定：PASS
- 问题：计算 demo 数据集中商品的退货率（退货订单数 ÷ 总订单数）。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有 demo 数据无法计算退货率

**检索与验证过程**

1. 全表字段核对（`SELECT * FROM user_profile_vectors LIMIT 1`）：实际字段为
   `id, user_id, profile_text, embedding, dept, sensitivity, update_time, metadata, age, gender, city, member_level, order_count, total_amount, avg_amount, top_category, days_since_last_buy, platforms`
   → 没有任何与退货、退款、售后相关的字段（如 return_flag / return_count / refund_amount）。

2. 知识库检索（`rag_search` 退货率口
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少订单明细/退货字段（分子无来源）；允许引用事实数字（8110/36 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“退货率为 N%”这类带“%”单位的明确结果（forbidden_result_units=[%]）

### bench_neg_003 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中“母婴偏好”用户的数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：**结论：现有 demo 数据不支持统计“母婴偏好”用户数量，无法给出数字（不编造）。**

原因有三点：

1. **画像表没有母婴品类**：`user_profile_vectors.top_category` 的全部取值只有 7 个：电子产品 2235、家居 1794、书籍 854、玩具 838、服装 800、运动 797、美妆 792（合计 8110，与表总量一致）。品类枚举中不存在“母婴”。
2. **文本中也没有命中**：`WHERE top_category LIKE '%母婴%' OR profile_text LIKE '%母婴%'` 的命中数为 **0**，即连画像摘要文本里也没有出现母婴相关描述。
3. **口径所需字段缺失**：据知识库 `tag_definitions.md`，“母婴偏好用户”的定义是「近 90 天购买母婴品类商品 ≥ 2 次，或浏览母婴品类 ≥ 
- 复核项：人工复核：必须人工确认未给出编造结果——回答指出 demo 品类枚举中没有“母婴”，未用玩具/其他品类替代；允许引用事实数字（如品类数量 7），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“母婴偏好 N 人”“数量为 7 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_004 · negative

- 自动判定：PASS
- 问题：预测 demo 数据集在 2026 年 11 月的钻石会员数量。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：无法预测，现有数据不支持该问题。原因如下：

**1. 缺少绝对时间轴**
`user_profile_vectors` 只有相对天数 `days_since_last_buy`（实测 0~364 天，SQL 验证：min=0，max=364，n=8110），它表示“距最后一次购买多少天”，以某个未标注的基准日为起点。表中没有任何日期、月份或年份字段，既无法确定基准日是哪一天，也无法生成历史时间序列。

**2. 缺少可用于时间外推的序列**
预测 2026 年 11 月的会员数，至少需要“按月的钻石会员存量序列”或“升级、降级、流失事件表”。本库是 8110 条用户画像静态快照，每条记录一行，没有会员等级变更历史的表，因此无法拟合趋势；任何数字都只能是编造。

**3. 可如实给出的只有当前快照**
当前钻石会员为 403 人（SQL：`SELECT COUNT(*) FROM user
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明单时点静态快照/无时间序列、无法预测未来（可提当前 403 人作为事实）；允许引用事实数字（2026/11/403 等），但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“预测为 N 人”“预计 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）

### bench_neg_005 · negative

- 自动判定：PASS
- 问题：统计 demo 数据集中用户从注册到完成首单的平均转化天数。如果现有数据不支持，请说明原因；不要编造数字。
- 最终回答：## 结论：现有数据不支持该统计，无法计算

**原因（数据层面）**

1. **没有注册时间字段**：`user_profile_vectors` 只有 `days_since_last_buy`（距最后一次购买的天数，相对基准日 0–364），没有任何注册日期或注册天数。
2. **没有首单时间字段**：表中只有累计订单数 `order_count`（1–10）和累计消费 `total_amount`、`avg_amount`。这些字段只表示“累计结果”，没有首单发生的时间点，因此无法定位“首单 vs 注册”的时间差。
3. **没有单条订单明细表**：可访问的白名单表只有 `user_profile_vectors`（用户画像快照，8110 条）和 `wiki_vectors`（知识库分块，36 条）。没有订单流水表，也没有事件日志表。尝试查询 `information_schem
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明缺少注册时间与首单时间字段；允许引用事实数字（如数据规模），但禁止“约/预计/估算”等近似表述后跟结果数字；本题 forbidden_result_units=[] 不限定单位，靠人工确认不得出现任何编造转化天数（如“平均 N 天”）

### bench_neg_006 · negative

- 自动判定：PASS
- 问题：“高价值用户”的标签定义是什么？demo 数据集能否精确统计高价值用户数量？如果无法精确统计，请说明原因，不要编造统计数字。
- 最终回答：## 一、「高价值用户」的标签定义（原文引用）

依据知识库 `tag_definitions.md`：

> **高价值用户**
> 定义：近 90 天消费金额排名前 20%，且近 30 天有活跃行为（登录、浏览、下单任一）。
> 更新频率：T+1。
> 负责人：数据部-用户增长组。
> 用途：营销优先级排序、专属客服分配。

⚠️ 需要与另一个容易混淆的标签区分：「高客单用户」= 累计平均客单价 ≥ 1000 元（数据部-用户价值组），两者口径不同。

## 二、demo 数据集**无法**精确统计高价值用户数量

我核对了库内两张表（`user_profile_vectors` 用户画像、`wiki_vectors` 知识库文档分块）的字段，定义所需的两个条件都缺少可支撑字段：

**1. 「近 90 天消费金额」—— 无法还原**
- 画像表只有 `total_amount`（累计
- 复核项：人工复核：必须人工确认未给出编造结果——回答说明定义是近90天消费前20%且近30天活跃、demo 缺近90天消费明细与行为日志（90/20/30 为定义数字，允许出现）；允许引用事实数字，但禁止“约/预计/估算”等近似表述后跟结果数字，也禁止“高价值用户 N 人”这类带“人”单位的明确结果（forbidden_result_units=[人]）
