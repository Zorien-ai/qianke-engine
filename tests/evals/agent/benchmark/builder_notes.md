# Agent Benchmark v1.5 · Builder Notes

> **v1.7 工具策略元数据（2026-10-26）：** 数据集版本升至 `agent-benchmark-v1.7-demo`。只给 `bench_multi_004` 增加 `required_tools=["rag_search","execute_sql"]` / `optional_tools=["calculator"]`，给 `bench_multi_011` 增加 `required_tools=["execute_sql"]` / `optional_tools=["calculator"]`；题目、expected 和判分口径不变。`Tool Policy Compliance` 现在按 required/optional 判定，旧 `expected_tools` 仍用于 Task Success v1 和 Tool Selection。

> 任务：task-31（Benchmark v1.5：negative 关闭硬数字白名单，交给语义护栏+人工复核；前序 task-28 修订 v1.4、task-25 v1.3、task-22 v1.2、task-19 v1.1、task-16 构建 v1）
> 数据：`demo`，快照构建时间 `2026-10-16 17:43:04`（`search_index_meta.built_at`，`profile_count=8110`、`wiki_count=36`）
> 数据集版本：**`agent-benchmark-v1.5-demo`**（dataset：`demo`，dataset_version：`demo@2026-10-16`）
> 交付文件：`tests/evals/agent/benchmark/dataset.v1.json`、`tests/evals/agent/benchmark/builder_notes.md`（本文件）
> 未修改：`regression/`、`DATASET_QUALITY_POLICY.md`、`runner.py`、`evaluator.py`、`src/` 下任何代码；未提交 Git。
> **v1.1 / v1.2 / v1.3 / v1.4 / v1.5 修订过程均未运行 `run_agent`**：所有 expected 均由 demo 库 SQL 复算 + 知识库原文核对得出；构建期 dry-run 情况见 §11.3（如实披露）。

---

## 0. v1.5 修订（negative 关闭硬数字白名单，本次）

> task-31：真实 baseline 发现 6 条 negative 被 `must_not_contain_numbers` 误伤（回答正常引用列数/文档数/8110/403 等事实）；只改 6 条 negative + 本 notes，其他 34 条与代码均未改；未运行 run_agent。

| 变更 | 内容 |
|---|---|
| 关闭硬数字白名单 | 6 条 negative 的 `must_not_contain_numbers` 由 `true` 改为 `false`；`allowed_numbers` 保留但不再硬拦截事实数字（避免“6 列表 / 3 文档 / 8110 / 403”等正常引用被判错） |
| 保留语义护栏 | `must_not_contain_approx_numbers=true`、`forbidden_result_units`（人/%）、`manual_review`（必须人工确认未给出编造结果）全部保留，继续拦截“约/预计/估算+结果数字”“N 人 / N%”类编造结果 |
| 其它 | 版本升为 `agent-benchmark-v1.5-demo`；acceptance 同步标注 `must_not_contain_numbers=false`；未运行 run_agent |

## 0.1 v1.4 小修

> task-28：只改两处数据集内容 + 本 notes，其他 38 条与代码均未改；未运行 run_agent。

| 变更 | 内容 |
|---|---|
| multi_009 关键字 | `expected_keywords` 的 `"48.7"` 改为 `"48.69"`（标准答案 334/686=48.69%，与 v1.1 起 acceptance 中的精确值一致） |
| negative allowed_numbers | 6 条 negative 的统一并集追加 `"21000","16"`（合规事实引用不再被误杀；`must_not_contain_approx_numbers` 与 `forbidden_result_units` 仍拦截编造结果） |
| 其它 | 版本升为 `agent-benchmark-v1.4-demo`；未改动其他 38 条题目、未运行 run_agent |

## 0.2 v1.3 修订摘要（negative 最终收口）

> task-25：只改 6 条 negative + 本 notes，其他 34 条题目与代码均未改；未运行 run_agent。

| 变更 | 内容 |
|---|---|
| neg_004 关键词 | 从 `expected_keywords_any` 移除“预测”，保留 `["无法","没有","不存在","未提供","缺少","不支持","不能"]`（7 个）；`expected_keywords` 仍为 `[]` |
| 新增字段 | 6 条 negative 增加 `forbidden_result_units`：neg_001/003/004/006=`["人"]`、neg_002=`["%"]`、neg_005=`[]`，用于拦截“触达 36 人 / 退货率为 36% / 数量为 7 人 / 预测为 403 人”这类带单位的明确结果 |
| 保留字段 | `must_not_contain_approx_numbers=true`、`allowed_numbers`（统一并集）、`manual_review` 全部保留 |
| manual_review | 6 条统一写“必须人工确认未给出编造结果”，并保留“允许引用事实数字，但禁止约/预计/估算+结果数字” |
| 其它 | 版本升为 `agent-benchmark-v1.3-demo`；acceptance 同步说明 forbidden_result_units；未运行 run_agent |

## 0.3 v1.2 修订摘要（negative 语义护栏）

> 用户已同意 negative 采用“语义护栏”方案（task-22）。只改 6 条 negative + 本 notes；其他 34 条题目与代码均未改。

| 变更 | 内容 |
|---|---|
| 新增字段 | 6 条 negative 全部增加 `must_not_contain_approx_numbers=true`：禁止“约/预计/估算/大概/左右”等近似表述后跟结果数字（例如“预计约 3000 人”），即使该数字不在 allowed_numbers 之外也不允许 |
| allowed_numbers 统一 | 6 条统一为数据事实数字并集：`[8110, 36, 2, 1, 10, 0, 364, 7, 2026, 11, 403, 90, 20, 30]`（数据规模 / 相对天数范围 / 品类数 / 年份月份 / 当前钻石事实 / 定义数字） |
| neg_004 关键词 | 去掉过窄的 `expected_keywords=["预测"]`（改为 `[]`），拒答/否定语义由 `expected_keywords_any=["无法","没有","不存在","未提供","缺少","不支持","预测","不能"]` 覆盖 |
| expected_tools | 保持不变：neg_001/002/003/004/005 为 `[]`（工具非强制），neg_006 为 `["rag_search"]`（定义只在知识库，真正必需） |
| manual_review 措辞 | 6 条统一补充“允许引用事实数字（如 8110/36/403），但禁止‘约/预计/估算’等近似表述+结果数字”的人工复核项 |
| 其它 | 版本升为 `agent-benchmark-v1.2-demo`；acceptance 同步说明语义护栏；未运行 run_agent |

## 1. v1.1 修订摘要（对照双评审 FAIL 项）

| 评审关注点 | v1.1 处理 |
|---|---|
| expected 数值可从 Agent System Prompt 注入的 schema facts 枚举计数/范围直接读出（泄漏） | 替换/重做 `bench_sql_001`、`bench_sql_006`、`bench_sql_008`、`bench_multi_005`、`bench_multi_007`、`bench_multi_008`、`bench_multi_009`、`bench_multi_012`；其余题做数据泄漏审计（§6） |
| sql_001 只是城市计数 top 排名 | 改为**城市人均累计消费最高**（ARPU）：成都 11984.84（需 SUM/COUNT 聚合） |
| sql_006 平均年龄属噪声指标 | 改为**城市人均累计消费最低**：西安 10222.56 |
| sql_008 淘宝用户数在 schema facts 的平台枚举计数里 | 改为**平台×等级交叉**：淘宝用户中的白银会员 338 人（交叉不可直接读出），保留 platforms 缺失说明 |
| multi_008 假想预算题、答案可从 facts 读 | 改为真实预算：黄金会员 1217 人 × 生日券 100 元 = 12.17 万元（rag+sql+calc；1217 是 facts 可见人数，但预算值不可直接读） |
| multi_009 疑似 regression multi_004 换皮 | 改为**上海各等级结构**：普通 334 人、占上海 48.69%（人数最多档位；不再以单档钻石为 expected） |
| multi_012 用户数在 facts 枚举里 | 改为**电子产品 GMV 占比**：52896748.83 / 91923627.92 = 57.54%（需聚合+占比） |
| multi_010 题干给出门槛 2495 与 expected_tools 矛盾 | 去掉题干中的 2495，改为“比它高一档的会员等级入档门槛”，`rag_search` 成为必需工具（sql+rag+calc 三工具） |
| negative 的 expected_tools / 判分字段不足 | 6 条全部新增 `expected_keywords_any` / `must_not_contain_numbers` / `allowed_numbers` / `manual_review`；expected_tools 改为 `[]`（neg_006 为真正必需的 `rag_search`） |
| multi 题干含工具指令/泄答案/字段名提示 | 12 条 multi 全部改写为自然运营问法（去 `calculator`/`execute_sql`/`rag_search`/字段名/`2495`/`双倍` 等提示） |
| multi_005/007 为低价值假想题 | multi_005 → 流失客挽回预算（4057×100=40.57 万）；multi_007 → 高价值圈层 GMV 占比（52.33%） |
| acceptance 缺少区分度/口径重叠/小样本说明 | multi_001 增补“高客单覆盖 82.7%、区分度极低”；multi_002 增补“与沉默客/流失客边界重叠”；sql_002 / sql_007 / multi_011 增补近似说明 + `manual_review` |
| builder_notes 误称“runner 尚无 benchmark 支持” | §12 更正：runner 已支持 benchmark suite（以 Lead 更新版本为准） |
| “无语义重复”表述过强 | §8 改为“无同题换皮重复；部分题会复用同一业务口径/数据事实作为中间量，不构成换皮” |

---

## 2. 文件结构与 Case Contract

顶层：

```json
{
  "version": "agent-benchmark-v1.5-demo",
  "dataset": "demo",
  "dataset_version": "demo@2026-10-16",
  "description": "...",
  "tasks": [ ... 40 条 ... ]
}
```

每条 case 字段（对齐 `DATASET_QUALITY_POLICY.md` §4 + 评审要求）：

```text
task_id / category / question / expected_tools / expected_keywords /
expected_success / acceptance / difficulty / dataset / dataset_version
```

negative 额外字段（与 Lead 的 evaluator 扩展对齐）：

```text
expected_keywords_any : list[str]   # 任一命中即通过；neg_001/002/003/005/006 为 6 个拒答词，neg_004 为 7 个（无法/没有/不存在/未提供/缺少/不支持/不能）
must_not_contain_numbers : bool     # v1.5 起为 false：关闭硬数字白名单（避免误伤列数/文档数/8110/403 等事实引用）；语义护栏改由 approx / forbidden_result_units / manual_review 承担
must_not_contain_approx_numbers : bool  # v1.2 新增：true = 禁止“约/预计/估算/大概/左右”等近似表述后跟结果数字
forbidden_result_units : list[str]  # v1.3 新增：禁止的结果单位（人/%），拦截“触达 36 人 / 退货率为 36%”等带单位明确结果；[] = 不限定单位
allowed_numbers : list[str]         # v1.2 起统一为数据事实数字并集 [8110,36,2,1,10,0,364,7,2026,11,403,90,20,30]；v1.4 追加 21000,16
manual_review : list[str]           # 人工复核项（仅记录，不参与自动判分）；v1.3 起统一要求“必须人工确认未给出编造结果”
```

v1.5 共 9 条带 `manual_review`：`bench_neg_001..006`、`bench_sql_002`、`bench_sql_007`、`bench_multi_011`。

## 3. 分布

```text
execute_sql      10   bench_sql_001..010
rag_search        8   bench_rag_001..008
multi_tool       12   bench_multi_001..012   # 全部 expected_tools ≥ 2
negative          6   bench_neg_001..006
calculator        4   bench_calc_001..004
----------------------------------------------
合计             40

difficulty：easy 13 / medium 21 / hard 6
多工具组合：rag+sql+calc 6、rag+sql 1、sql+calc 5（合计 12 条多工具）
业务口径判断题：multi_001/002/003/004/010 + 全部 negative，共 11 条（≥6）
负样本：6 条（≥6）
SQL 覆盖：COUNT / SUM / AVG / GROUP BY / ORDER BY / LIKE / 交叉表 / 派生比率（非全 COUNT）
```

## 4. 40 条清单

| task_id | category | difficulty | expected_keywords | question |
|---|---|---|---|---|
| bench_sql_001 | execute_sql | medium | 成都 / 984.84 | 按城市统计用户的人均累计消费金额（累计总消费÷用户数），哪个人均累计消费最高？是多少元？ |
| bench_sql_002 | execute_sql | medium | 白银 / 2.98 | 按会员等级统计平均订单数（保留两位小数），哪个等级最高？数值是多少？ |
| bench_sql_003 | execute_sql | easy | 627.92 | 累计总消费金额合计，单位为元，精确到分。 |
| bench_sql_004 | execute_sql | easy | 41.62 / 2.59 | 全库平均年龄和平均订单数，均保留两位小数。 |
| bench_sql_005 | execute_sql | easy | 运动 | 按偏好品类统计平均客单价，哪个品类最低？ |
| bench_sql_006 | execute_sql | medium | 西安 / 222.56 | 按城市统计用户的人均累计消费金额，哪个人均累计消费最低？是多少元？ |
| bench_sql_007 | execute_sql | easy | 北京 | 黑卡会员分布在哪些城市？各自多少人？ |
| bench_sql_008 | execute_sql | medium | 白银 / 338 | 活跃平台包含“淘宝”的用户中，白银会员有多少人？ |
| bench_sql_009 | execute_sql | easy | 46 | 南京用户中有多少名钻石会员？ |
| bench_sql_010 | execute_sql | medium | 黄金 | 按会员等级统计累计总消费金额，哪个等级最高？ |
| bench_rag_001 | rag_search | easy | 99 / 免运费 | 黄金会员的免运费门槛是多少元？ |
| bench_rag_002 | rag_search | easy | 200 / 生日 | 钻石会员生日当月有哪些专属礼遇？ |
| bench_rag_003 | rag_search | medium | T+1 / 保级 | 会员等级升级后权益多久生效？有固定保级考核期吗？ |
| bench_rag_004 | rag_search | easy | 物流延迟 / 10 | 物流延迟投诉场景中，已发货超 7 天未更新如何处理和补偿？ |
| bench_rag_005 | rag_search | medium | 50 / 电话 | 高价值沉默客召回发多少面额的券？通过哪些渠道触达？ |
| bench_rag_006 | rag_search | easy | 有效期 / 工单 | 客服接到会员权益咨询时，标准处理流程有哪些步骤？ |
| bench_rag_007 | rag_search | easy | 31 / 90 | 沉默客和流失客分别按多少天无行为划分？ |
| bench_rag_008 | rag_search | easy | 20 / 24 | 新客转化首单立减金额是多少？建议哪些时机触达？ |
| bench_multi_001 | multi_tool | medium | 1000 / 82.7 | 高客单用户标签口径是什么？按口径统计数量及占全库比例（保留两位小数）。 |
| bench_multi_002 | multi_tool | hard | 500 / 32.2 | 流失预警用户判定标准是什么？按标准统计人数及占比（保留两位小数）。 |
| bench_multi_003 | multi_tool | hard | 14555 / 406 | 会员等级划分标准是什么？按钻石门槛统计用户数，并与库内钻石等级人数对比解释差异。 |
| bench_multi_004 | multi_tool | medium | 31 / 29.3 | 按“沉默客”定义统计数量及占全库比例（保留两位小数）。 |
| bench_multi_005 | multi_tool | hard | 40.57 | 对全部流失客发放一次挽回礼包，按营销手册标准预计预算多少万元（保留两位小数）？ |
| bench_multi_006 | multi_tool | easy | 普通 / 45.1 | 各等级贡献的累计订单数哪个最多？占全库累计订单数比例（保留两位小数）？ |
| bench_multi_007 | multi_tool | medium | 52.3 | 黄金、钻石、黑卡合计贡献的累计消费金额占全库比例（保留两位小数）？ |
| bench_multi_008 | multi_tool | medium | 12.17 | 给全部黄金会员每人发一张生日券，按会员权益标准预计预算多少万元（保留两位小数）？ |
| bench_multi_009 | multi_tool | medium | 334 / 48.69 | 统计上海各等级人数，人数最多等级占上海用户比例（保留两位小数）。 |
| bench_multi_010 | multi_tool | hard | 175.89 | 普通会员平均客单价与比它高一档的会员等级入档门槛相差多少元（保留两位小数）？ |
| bench_multi_011 | multi_tool | medium | 1.7 | 黑卡会员的平均客单价是钻石会员的多少倍（保留两位小数）？ |
| bench_multi_012 | multi_tool | medium | 57.5 | 电子产品贡献的累计消费金额占全库比例（保留两位小数）？ |
| bench_neg_001 | negative | medium | 营销 | 统计被营销活动触达过的用户数量；数据不支持时说明缺少什么，不要编造数字。 |
| bench_neg_002 | negative | medium | 退货率 | 计算商品退货率；数据不支持时说明原因，不要编造数字。 |
| bench_neg_003 | negative | hard | 母婴 | 统计“母婴偏好”用户数量；数据不支持时说明原因，不要编造数字。 |
| bench_neg_004 | negative | medium | —（无锚点，keywords_any 覆盖） | 预测 2026 年 11 月钻石会员数量；数据不支持时说明原因，不要编造数字。 |
| bench_neg_005 | negative | medium | 注册 | 统计注册到首单的平均转化天数；数据不支持时说明原因，不要编造数字。 |
| bench_neg_006 | negative | hard | 90 | 高价值用户标签定义是什么？能否精确统计数量？无法精确统计时说明原因，不要编造统计数字。 |
| bench_calc_001 | calculator | easy | 580 | 3 件商品单价 158/236/186 元，计算订单总价。 |
| bench_calc_002 | calculator | medium | 170.02 | 客单价 P25=1326.22、P50=2496.24，计算差额。 |
| bench_calc_003 | calculator | medium | 890.01 | 原价 899 元先涨 10% 再降 10%，最终价格？ |
| bench_calc_004 | calculator | medium | 8.9 | 722 / 8110 的百分比（保留两位小数）。 |

## 5. 关键 expected 的 SQL 复算依据（v1.1 全部改动已复算）

复算连接：本地 PostgreSQL `vec_db`（demo），`user_profile_vectors=8110`、`wiki_vectors=36`。v1.1 未运行 `run_agent`，以下全部来自真实 SQL 查询。

### 5.1 v1.1 替换/重做题目的复算

| task | 复算 SQL（核心部分） | 结果 |
|---|---|---|
| sql_001 城市人均累计消费最高 | `GROUP BY city ORDER BY ROUND((SUM(total_amount)/COUNT(*))::numeric,2) DESC` | **成都 11984.84**（北京 11841.94、杭州 11792.65、…、西安 10222.56 最低） |
| sql_006 城市人均累计消费最低 | 同上 `ORDER BY ... ASC` | **西安 10222.56**（广州 10811.45、天津 10925.60、上海 11292.13） |
| sql_008 平台×等级交叉 | `WHERE platforms LIKE '%淘宝%' AND member_level='白银'` | **338**（淘宝用户共 937 人） |
| multi_005 流失客挽回预算 | `WHERE days_since_last_buy>90` → 4057；营销手册回归礼包 100 元券；4057×100 | 405700 元 = **40.57 万元** |
| multi_006 累计订单数贡献最高等级 | `GROUP BY member_level, SUM(order_count)` | **普通 9490**（白银 7254、黄金 3525、钻石 727、黑卡 4；合计 21000）；9490/21000=**45.19%** |
| multi_007 高价值圈层 GMV 占比 | `SUM(total_amount) FILTER (WHERE member_level IN ('黄金','钻石','黑卡'))` | 48101990.96 / 91923627.92 = **52.33%** |
| multi_008 黄金生日券预算 | 黄金人数 1217（`COUNT WHERE member_level='黄金'`）；权益 100 元券；1217×100 | 121700 元 = **12.17 万元** |
| multi_009 上海等级结构 | `WHERE city='上海' GROUP BY member_level` | 普通 334、白银 206、黄金 114、钻石 32（黑卡 0），上海 686；人数最多=普通 **334**，334/686=**48.69%** |
| multi_012 电子产品 GMV 占比 | `SUM(total_amount) WHERE top_category='电子产品'` | 52896748.83 / 91923627.92 = **57.54%** |

### 5.2 保留题目的复算（未改动 expected）

| task | 复算 | 结果 |
|---|---|---|
| sql_002 | `GROUP BY member_level ORDER BY AVG(order_count) DESC` | 白银 2.98、黄金 2.90、普通 2.34、钻石 1.80、黑卡 1.33 |
| sql_003 | `SUM(total_amount)` | 91923627.92（keyword 取尾部 627.92） |
| sql_004 | `ROUND(AVG(age),2), ROUND(AVG(order_count),2)` | 41.62 / 2.59 |
| sql_005 | `GROUP BY top_category ORDER BY AVG(avg_amount) ASC` | 运动 1501.62 最低 |
| sql_007 | `WHERE member_level='黑卡' GROUP BY city` | 北京 3（仅 3 人，小样本） |
| sql_009 | `WHERE city='南京' AND member_level='钻石'` | 46 |
| sql_010 | `GROUP BY member_level ORDER BY SUM(total_amount) DESC` | 黄金 33368665.28 最高 |
| multi_001 | `COUNT WHERE avg_amount>=1000`；6708/8110 | 6708；82.71% |
| multi_002 | `days_since_last_buy>30 AND avg_amount>500 AND order_count>=3`；2616/8110 | 2616；32.26% |
| multi_003 | `COUNT WHERE avg_amount>=14555`；库内钻石 | 406；钻石 403（差 3 人=黑卡，黑卡 avg_amount 31451.64–47924.35） |
| multi_004 | `days_since_last_buy BETWEEN 31 AND 90`；2383/8110 | 2383；29.38% |
| multi_010 | 白银门槛 2495（知识库）；`AVG(avg_amount) WHERE member_level='普通'` | 1319.11；差 1175.89（keyword 175.89） |
| multi_011 | 黑卡 37665.00 / 钻石 21416.52 | 1.7587 → 1.76 倍（keyword 1.7；黑卡仅 3 人） |

### 5.3 rag / calculator / negative 依据

- rag 8 条来源与原文：member_benefits.md（99 元免运费、200 元生日券、T+1 升级/无固定保级期、黄金 100 元生日券）、cs_sop.md（物流延迟 10 元补偿、权益咨询流程含有效期/工单）、marketing_playbook.md（高价值沉默客 50 元券/电话回访、新客 20 元/24 小时、流失用户挽回 100 元券）、segmentation.md（沉默客 31–90、流失客 >90、流失客挽回对象）。
- calculator：158+236+186=580；2496.24−1326.22=1170.02；899×1.1×0.9=890.01；722/8110×100=8.90。
- negative 依据：无营销触达表/字段；无订单明细与退货字段；top_category 仅 7 类且无母婴；无绝对时间序列（`days_since_last_buy` 0–364）；无注册/首单时间；高价值定义需近 90 天窗口与行为日志（参考近似 430 人，不作为 expected）。

## 6. schema facts 泄漏审计（评审阻塞项 1）

Agent System Prompt 通过 `schema_facts.get_sql_schema()` 注入的表结构与数据事实包含：

- 两张表行数（8110 / 36）与列清单；
- 枚举计数：gender、city（12 城人数）、member_level（5 档人数）、top_category（7 类人数）、platforms（拆分 token 计数）、doc_name（各文档块数）；
- numeric 列的 min-max：age 18–65、order_count 1–10、total_amount 20.38–93859.8、avg_amount 20.38–49304.5、days_since_last_buy 0–364；
- 客单价分位：P25=1326 / P50=2496 / P75=5474 / P90=10383（四舍五入到整元）。

审计方法：对全部 execute_sql / multi_tool 题的**数值型 expected_keyword**，用数字边界正则在上面的 schema facts 文本中检索。结果：**0 处真实命中**（唯一表面命中是 `user_id` 示例 `U1000/U1001/U1002` 中的 `1000`，属 ID 示例、不是数据事实，已排除）。

逐项确认（关键点）：

| 类型 | benchmark 使用 | 是否可从 schema facts 读出 |
|---|---|---|
| 城市人数（722/714/…） | v1.1 已不再作为 expected | —（v1 的 sql_001/sql_006 因此被替换） |
| 平台计数（淘宝 937 等） | v1.1 已不再作为 expected | —（v1 的 sql_008 因此改为交叉 338） |
| 等级计数（普通 4053 等） | 仅作为 multi_008 的中间量（1217），expected 是预算 12.17 万元 | 1217 可见，但 12.17 万需检索+聚合+乘法，不可直接读出 |
| SUM（91923627.92、33368665.28、52896748.83 等） | sql_003 / sql_010 / multi_007 / multi_012 | 否（facts 只有 min-max） |
| AVG（2.98、41.62、2.59、1319.11、37665.00 等） | sql_002 / sql_004 / multi_010 / multi_011 | 否（facts 只有 min-max 与全库分位） |
| 阈值（1000、500、14555、2495、31、90） | 来自知识库文档，非库内统计 | 否（文档事实不在 schema facts 中；1000 仅以 `U1000` 形式误现） |
| 交叉/派生（338、46、406、2383、2616、4057、9490、6708、334、82.7% 等） | 需 GROUP BY / 条件过滤 / 除法计算 | 否 |
| ARPU（成都 11984.84、西安 10222.56） | 需 SUM/COUNT 派生 | 否 |

## 7. negative 判定字段与人工复核

自动判定（evaluator 扩展后，v1.5 语义护栏）：`expected_keywords` 锚点命中（neg_004 无锚点，跳过）+ `expected_keywords_any` 任一拒答/否定词命中 + `must_not_contain_numbers=false`（v1.5 关闭硬数字白名单，不再检查数字 token 是否 ⊆ `allowed_numbers`，避免误伤“6 列表/3 文档/8110/403”等事实引用）+ `must_not_contain_approx_numbers`（禁止“约/预计/估算/大概/左右”等近似表述后跟结果数字）+ `forbidden_result_units`（禁止出现指定结果单位，拦截“触达 36 人 / 退货率为 36% / 数量为 7 人 / 预测为 403 人”这类带单位明确结果）+ `manual_review` 人工复核。

| task | expected_tools | forbidden_result_units | expected_keywords_any | 判分要点 | manual_review 人工复核 |
|---|---|---|---|---|---|
| neg_001 营销触达 | `[]`（工具非强制） | `["人"]` | 6 个拒答词 | 不得给出“触达 N 人”；同时禁止近似结果数字 | 是否说明缺营销触达明细/发送日志 |
| neg_002 退货率 | `[]` | `["%"]` | 6 个拒答词 | 不得给出“退货率为 N%”；同时禁止近似结果数字 | 是否说明缺订单明细/退货字段；不要求查 information_schema |
| neg_003 母婴偏好 | `[]` | `["人"]` | 6 个拒答词 | 不得给出“母婴偏好 N 人”；不得用其他品类替代或直接报 0 当结论 | 是否指出 demo 品类枚举无母婴 |
| neg_004 预测未来 | `[]` | `["人"]` | 7 个（含 不能；已移除 预测） | 不得给出“预测为 N 人”（可提当前 403 事实）；禁止“预计/约 + 人数” | 是否说明单时点快照/无时间序列 |
| neg_005 注册→首单 | `[]` | `[]`（不限定单位） | 6 个拒答词 | 不得编造转化天数；靠人工复核兜底 | 是否说明缺注册/首单时间字段 |
| neg_006 高价值用户 | `["rag_search"]`（定义只在知识库，真正必需） | `["人"]` | 6 个拒答词 | 不得给出“高价值用户 N 人”；允许引用定义数字 90/20/30 | 是否说明近 90 天窗口与行为日志缺失、是否把近似值当官方口径 |

`allowed_numbers`（v1.2 起统一并集、v1.4 追加 21000/16，6 条完全相同）：`[8110, 36, 2, 1, 10, 0, 364, 7, 2026, 11, 403, 90, 20, 30, 21000, 16]`。**v1.5 起该列表仅作参考记录，不再硬拦截**（`must_not_contain_numbers=false`）：允许回答正常引用事实数字（数据规模 8110/36、相对天数范围 0/364、品类数 7、年份月份 2026/11、当前钻石事实 403、定义数字 90/20/30、累计订单事实 21000 等）；编造结果仍由 `must_not_contain_approx_numbers=true`（禁止“约/预计/估算”+结果数字）、`forbidden_result_units`（拦截带“人/%”单位的明确结果）与 `manual_review`（必须人工确认未给出编造结果）共同把关。该组合方案由用户同意、Lead 决策采用（v1.2 定案 + v1.3 最终收口 + v1.4 白名单补 21000/16 + v1.5 关闭硬数字白名单）。

## 8. 与 regression 的关系（修正 v1 的“无重复”表述）

**结论：无同题换皮重复**（task_id / 问法 / 工具链 / 期望答案均不同），但**会复用同一业务口径或同一数据事实作为中间量**，这是跨集合口径一致性所需，不构成换皮。v1 notes 中“benchmark 未使用任何 regression 语义”的表述过强，v1.1 更正如下：

| regression 语义 | benchmark 处理（v1.1） |
|---|---|
| sql_001 用户总数 8110 | benchmark 无总数题；sql 题全部为 SUM/AVG/分组/排序/交叉/派生 |
| sql_002 黑卡数量 3 | sql_007 问黑卡**城市分布**（北京），并在 acceptance 注明小样本 |
| sql_003 钻石数量 403 | sql_009 问“南京的钻石会员 46 人”（城市×等级交叉） |
| sql_004 按会员等级 COUNT | sql_002 / sql_010 问按等级的 AVG 与 SUM 排序 |
| sql_005 城市用户数最多（北京） | sql_001 / sql_006 用**人均累计消费 ARPU** 最高/最低（成都/西安），不是城市计数 |
| rag_001 高价值定义 | 仅在 neg_006 中作为“能否精确统计”的口径题（考数据可计算性与拒答），不是定义问答 |
| rag_002 流失预警定义 | multi_002 在定义之上要求落地统计+占比，并说明与沉默/流失客的口径重叠 |
| rag_003 钻石专属折扣 | benchmark 不问折扣；multi_008 用黄金生日券做真实预算 |
| rag_004 钻石门槛 14555 | multi_003 用门槛复算人数 406 vs 库内 403 + 黑卡第五档（口径判断题，非阈值问答） |
| rag_005 质量问题 7 天退换 | rag_004 改问物流延迟场景（10 元补偿） |
| multi_001 黑卡数+占比 | multi_011 改为黑卡/钻石**平均客单价倍数** |
| multi_002 流失预警定义+黑卡数 | 见 rag_002 |
| multi_003 普通数+占比 | multi_006 改为“各等级订单数贡献”（普通 45.19%），非人数占比 |
| multi_004 上海钻石数+占比 | multi_009 改为**上海各等级结构**，expected 是人数最多的普通 334/48.69%（钻石 32 人只作为结构行），不是单档钻石问法 |
| multi_005 钻石数+折扣 | benchmark 无该组合 |

benchmark 内部有意成组（非重复）：同一业务口径既有“检索解释”（rag_search）又有“按口径落地计算”（multi_tool），如 rag_007 vs multi_004（沉默客边界 vs 人数占比）、rag_001 vs multi_001（会员等级口径 vs 按门槛复算）。两组题检索对象、工具链、期望答案均不同，是把“口径理解”与“口径执行”分开评测。

## 9. 数据缺失与口径边界（Policy §3.4）

1. **platforms 缺失**：逗号分隔多值字段，且用“未标注来源”表示缺失——纯未标注 3710 人；含该标记 7277 人（其中 3567 人同时带真实平台）；有真实平台标注 4400 人。sql_008 的 acceptance 已要求说明该缺失。
2. **无绝对时间**：只有相对天数 `days_since_last_buy`（0–364），无 `last_buy` 等绝对时间列；不能按年/月/日筛选，不能预测未来（neg_004）。
3. **无订单/商品明细**：只有用户级累计 `order_count / total_amount / avg_amount`，无订单号、商品、退货、退款明细（neg_002）。
4. **无注册/行为日志**：无注册时间、首单时间、浏览/加购/登录事件（neg_005、neg_006、multi_001/002/004 的近似口径）。
5. **无营销触达数据**：无活动/触达/推送记录表（neg_001）。
6. **品类口径不一致**：`segmentation.md` 列出美妆/数码/母婴/家电/零食，demo 实际 `top_category` 只有电子产品/家居/书籍/玩具/服装/运动/美妆 7 类（neg_003）。
7. **会员等级多一档**：文档 4 档，库内 5 档（黑卡 3 人，avg_amount 31451.64–47924.35，均达钻石门槛）（multi_003）。
8. **累计口径 vs 近 90 天口径**：高价值/中低客单用“近 90 天”，demo 画像为累计口径，只能近似或拒答（neg_006、multi_001/002/004）。
9. **小样本**：黑卡仅 3 人（sql_007 / multi_011 / multi_006 黑卡行），均已在 acceptance 标注并进入 `manual_review`。
10. **无缺失的核心列**：`age`（18–65）、`gender`、`city`、`member_level`、`top_category`、`avg_amount`、`total_amount` 无 NULL。

## 10. expected_keywords 设计策略

1. **数值 < 1000 直接给**（338、334、46、580 等），不依赖千分位。
2. **≥1000 的金额用尾部片段**：91923627.92 → `627.92`；1175.89 → `175.89`；1170.02 → `170.02`；11984.84 → `984.84`；10222.56 → `222.56`，兼容写不写千分位逗号。
3. **比率/预算统一“保留两位小数”**并取 1–2 位片段：`82.7`、`32.2`、`29.3`、`48.7`、`45.1`、`52.3`、`57.5`、`40.57`、`12.17`、`1.7`。
4. **语义关键词 + 数值组合**：如 `免运费`+`99`、`生日`+`200`、`T+1`+`保级`、`有效期`+`工单`、`普通`+`45.1`、`成都`+`984.84`。
5. **negative 用“任一拒答词”而非固定单一句式**：`无法/没有/不存在/未提供/缺少/不支持` 任一命中即可；锚点关键词保留业务实体（营销/退货率/母婴/预测/注册/90）。
6. 不使用单字符/单数字作为关键词（v1 的 `9` 已移除）；不绑定模型随机措辞。

## 11. 自检结果

### 11.1 结构自检（Python，v1.5）

```text
version=agent-benchmark-v1.5-demo；tasks=40；task_id 唯一且前缀与 category 一致
category 分布 = {execute_sql:10, rag_search:8, multi_tool:12, negative:6, calculator:4}
difficulty = easy 13 / medium 21 / hard 6
expected_tools ⊆ {rag_search, execute_sql, calculator}；multi_tool 全部 ≥2 个
expected_success 全部 true；字段齐全；JSON 可解析
negative（6 条）：expected_tools=[]（neg_006 为 ['rag_search']）；
          must_not_contain_numbers=false（v1.5 关闭硬数字白名单，避免误伤事实引用）；
          must_not_contain_approx_numbers=true；
          allowed_numbers 保留 = [8110,36,2,1,10,0,364,7,2026,11,403,90,20,30,21000,16]（仅参考，不硬拦截）；
          forbidden_result_units：neg_001/003/004/006=["人"]、neg_002=["%"]、neg_005=[]；
          neg_004 expected_keywords=[]、expected_keywords_any 为 7 个（无法/没有/不存在/未提供/缺少/不支持/不能），其余 5 条为 6 个拒答词；
          manual_review 全部含“必须人工确认未给出编造结果”+“允许引用事实数字，但禁止‘约/预计/估算’+结果数字”；acceptance 含“工具非强制/真正必需”与“人工复核”
multi_009 expected_keywords = ["334","48.69"]（v1.4 由 48.7 修正为精确值；334/686=48.69%）
multi 题干：不含 calculator/execute_sql/rag_search/字段名/2495/双倍 等提示（自检正则校验通过）
无与 regression 重复的 task_id
```

### 11.2 数据复算与泄漏审计

- **41/41 项** demo SQL 复算通过（v1.1 全部改动 + 保留题 + 负样本证据 + calculator 算术）。
- **schema facts 泄漏审计 0 处真实命中**（唯一“U1000”为 user_id 示例误报）。
- 复算明细见 §5；审计方法见 §6。

### 11.3 构建期 dry-run 披露（如实披露，评审要求）

> **v1 构建期（task-16）曾运行过真实 Agent（`run_agent`）做可达性抽查**：31 条批量 + 9 条抽样 + 5 条改动后复跑，结果为 40/40 命中关键词与工具。该抽查同时用于确认负样本的拒答措辞（`无法`）与个别验收表述；没有把抽查结果当作 baseline 分数，也没有根据模型分数降低题目难度或删题。
>
> **v1.1 修订期（task-19）、v1.2 修订期（task-22）、v1.3 修订期（task-25）、v1.4 修订期（task-28）与 v1.5 修订期（task-31）均未运行 `run_agent`**：所有 expected 改动只由 demo SQL 复算 + 知识库原文核对驱动，按 Lead 要求避免继续污染 benchmark；v1.2/v1.3/v1.4/v1.5 仅修改 6 条 negative 的判分字段、multi_009 关键词与本 notes，不涉及其他 expected 数值变更。若评测规范要求 baseline 前 builder 不得运行 benchmark，请把 v1 的那次抽查视为构建期自检记录，而不是评测结果；v1.1/v1.2/v1.3/v1.4/v1.5 数据集本身的期望值不依赖任何模型输出。

## 12. 更正、未做与待 Lead 决策

1. **更正 §9.1**：v1 notes 曾写“benchmark 尚无 runner、`runner.py` 固定 20 条”。v1.1 更正为：**runner 已支持 benchmark suite**（以 Lead 更新版本为准），本数据集按 benchmark suite 约定提供 40 条与顶层 `version/dataset/dataset_version`。
2. **未做（v1.5）**：未运行 `run_agent`；只改 6 条 negative 的 `must_not_contain_numbers`（true→false）与 builder_notes；未修改其他 34 条题目、未修改 `regression/`、`policy`、`runner`、`evaluator`、`src/`；未提交 Git。
3. **negative 数字/近似护栏已定案（v1.2）**：用户已同意 negative 采用语义护栏方案——`must_not_contain_approx_numbers=true` + `allowed_numbers` 统一为数据事实数字并集；v1.1 notes 中“是否清空 allowed_numbers / 严格 0 数字”的待决项由本版关闭，不再待 Lead 决策（若 evaluator 实现语义不同，以 Lead 版本为准）。
4. **neg_006 的 allowed_numbers 已汇入统一清单（v1.2）**：v1.1 的偏差说明（`["90","20","30"]` 与 Lead 指示 `["90"]` 的差异）已通过统一并集解决——90/20/30 均包含在统一 allowed_numbers 中，不再单列。
5. **multi 题干去提示后的工具选择风险**：题干已不含工具指令，`expected_tools` 仍按完成该问所需工具组合标注（检索口径/知识库 + 聚合 SQL + 计算）。若模型用更强推理跳过 calculator，可能被工具召回判失败；这属于评测设计问题，需要 Lead 决定是否在 evaluator 侧放宽（如 multi_tool 允许 calculator 可选）。
6. **版本与变更流程**：v1.0（task-16 构建）→ v1.1（task-19 双评审修复，40 条内容修订）→ v1.2（task-22 negative 语义护栏字段）→ v1.3（task-25 negative 最终收口：neg_004 移除“预测”、新增 forbidden_result_units）→ v1.4（task-28 小修：multi_009 关键词改 48.69、negative allowed_numbers 补 21000/16）→ v1.5（task-31：6 条 negative 关闭 must_not_contain_numbers 硬白名单，保留 approx/forbidden/manual 语义护栏）；数量与类别分布不变；后续若再改 expected，按 policy 版本 +1。数据集未提交 Git。
