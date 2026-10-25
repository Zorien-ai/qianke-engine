# Agent Benchmark v1 · Evaluator 独立审查报告

- 审查人：`benchmark-evaluator`（Eval 数据/技术审查，独立于 builder，不采信 builder_notes 的结论）
- 审查对象：`tests/evals/agent/benchmark/dataset.v1.json`（40 条）
- 审查日期：2026-10-24
- 数据版本：`demo` / `demo@2026-10-16`（实测 `search_index_meta.built_at = 2026-10-16 17:43:04`、`profile_count = 8110`、`wiki_count = 36`；`user_profile_vectors = 8110` 行、`wiki_vectors = 36` 行）
- 最终结论：**FAIL（5 条阻塞，35 条 PASS）**

> 一句话结论：**数据底座是正确的**（40 条的 expected 数值/原文、结构、分布、负样本真实性均通过独立复算），但 **3 条题的答案已经泄露在 Agent 系统提示词里**、**1 条与 regression 明显换皮**、**1 条 expected_tools 与题干自相矛盾**，因此按 `DATASET_QUALITY_POLICY.md` 的评测有效性要求不能直接交付。

---

## 1. 审查方法（可复现）

### 1.1 只读范围（本次审查未修改任何文件）

| 文件 | 用途 |
|---|---|
| `tests/evals/agent/benchmark/dataset.v1.json` | 审查对象（40 条） |
| `tests/evals/agent/benchmark/builder_notes.md` | 仅作为待验证线索，不作为结论依据 |
| `tests/evals/agent/DATASET_QUALITY_POLICY.md` | 验收规则（Case Contract / 分布 / 集合边界） |
| `tests/evals/agent/regression/dataset.v1.json` | 20 条语义查重基线 |
| `tests/evals/agent/evaluator.py` | 判定语义（`expected_keywords` 子串、`expected_tools` 覆盖、`status == COMPLETED`） |
| `tests/evals/agent/runner.py` | 确认 benchmark 可被实际 runner 加载 |
| `src/rag_demo/agent/loop.py`、`src/rag_demo/db/schema_facts.py`、`src/rag_demo/tools/sql_tool.py`、`src/rag_demo/agent/tools/*.py` | 确认真实运行时的系统提示词、schema 注入与工具名 |

### 1.2 复算环境与命令

```text
解释器：F:\workspace\python\rag-demo\.venv\Scripts\python.exe (3.12.4)
数据访问：from rag_demo.db.connection import use_dataset, get_conn; use_dataset("demo")
结构校验：python 脚本遍历 JSON（见 §2）
数值复算：直接对 demo 库执行 SQL（全部 40 条涉及的 SQL/算术均重新查询，不引用 builder_notes 数值）
检索复核：rag_demo.retrieval.hybrid_retriever.hybrid_search(question, top_k=5)，覆盖 18 条依赖知识库的题
runner 校验：python tests/evals/agent/runner.py --suite benchmark --validate-only
             → 输出 `suite=benchmark tasks=40 valid`
提示词泄露复核：rag_demo.db.schema_facts.get_sql_schema() 渲染出 Agent 系统提示词实际注入内容
```

### 1.3 判定口径

- 数据正确性：expected_keywords 中的数值/事实必须能从 demo 库或 wiki 原文复算/复现。
- 结构：总数、类别数、task_id 唯一、category 合法、工具名合法、multi_tool ≥2 工具、`expected_success=true`、字段齐全。
- 评测有效性（本次重点）：题目答案是否在真实 Agent 上下文中提前泄露；expected_tools 是否与题干一致；是否与 regression 换皮；negative 是否真不可回答；关键词是否可判定。
- **未运行完整 40 条真实 Agent**（避免把 benchmark 用于构建期调优；policy §6）。只做数据、检索、提示词上下文层面的独立验证。

---

## 2. 结构 / 契约校验（PASS）

| 检查项 | 结果 | 证据 |
|---|---|---|
| 总数 = 40 | ✅ | `len(tasks) == 40` |
| 类别分布 | ✅ | execute_sql 10 / rag_search 8 / multi_tool 12 / negative 6 / calculator 4 |
| task_id 唯一 | ✅ | 40 个 id 去重后仍 40 |
| task_id 前缀与 category 一致 | ✅ | `bench_sql_*`/`bench_rag_*`/`bench_multi_*`/`bench_neg_*`/`bench_calc_*` 全部对应 |
| category 合法 | ✅ | 只出现 5 个约定类别 |
| 工具名合法 | ✅ | `expected_tools ⊆ {rag_search, execute_sql, calculator}` |
| multi_tool ≥ 2 个工具 | ✅ | 12/12 满足（3 工具 4 条、2 工具 8 条） |
| expected_success 全 true | ✅ | 40/40 |
| 必需字段齐全 | ✅ | 10 个字段（含 acceptance/difficulty/dataset/dataset_version）全存在 |
| dataset / dataset_version | ✅ | 40 条均为 `demo` / `demo@2026-10-16` |
| difficulty | ✅ | easy 16 / medium 19 / hard 5（合法值） |
| 至少 12 条多工具 | ✅ | multi_tool 12 条 + neg_006 也是 2 工具 |
| 至少 6 条业务口径 | ✅ | multi_001/002/003/004/010 + neg_006（≥6） |
| 至少 6 条负样本 | ✅ | 6/6 |
| SQL 非全 COUNT、覆盖 SUM/AVG/GROUP BY/排序 | ✅ | SUM：sql_003/010；AVG：sql_002/004/006；GROUP BY/ORDER BY：sql_001/002/005/006/010 |
| 无安全类题目 | ✅ | 全文扫描“忽略/系统提示/密码/越权/注入/攻击/泄露”等 0 命中 |
| 关键词非空、无单字符/单数字关键词 | ✅ | 40 条均 1–2 个关键词，无 len==1 的值 |
| JSON 可解析 | ✅ | `json.load` 正常 |

---

## 3. 数据复算（独立验证，全部通过）

> 复算连接：本地 PostgreSQL `vec_db`（dataset=demo）。以下数值均为本次审查重新查询的结果，与 benchmark expected 一致。

### 3.1 基础分布（多处题目的事实底座）

```text
user_profile_vectors = 8110 行；wiki_vectors = 36 行
城市(12)：北京 722 / 杭州 714 / 南京 694 / 上海 686 / 深圳 673 / 苏州 672 /
          天津 672 / 广州 671 / 重庆 665 / 武汉 663 / 成都 639 / 西安 639
会员等级(5)：普通 4053 / 白银 2434 / 黄金 1217 / 钻石 403 / 黑卡 3
品类(7)：电子产品 2235 / 家居 1794 / 书籍 854 / 玩具 838 / 服装 800 / 运动 797 / 美妆 792
无缺失：age(18–65)、city、member_level、top_category、avg_amount、total_amount、order_count(1–10) 均 0 空值
唯一缺失字段：platforms 有“未标注来源”标记（纯标记 3710 人、含标记混合 3567 人、纯真实平台 833 人）
```

### 3.2 逐项复算结果（摘要，详细证据见 §4 逐条表）

| 任务 | 复算 | 结果 |
|---|---|---|
| sql_001 | `GROUP BY city ORDER BY count DESC` 第三 | 南京 694 |
| sql_002 | `GROUP BY member_level ORDER BY AVG(order_count) DESC` | 白银 2.98（黄金 2.90 / 普通 2.34 / 钻石 1.80 / 黑卡 1.33） |
| sql_003 | `SUM(total_amount)` | 91,923,627.92 元 |
| sql_004 | `AVG(age)` / `AVG(order_count)` round 2 | 41.62 / 2.59 |
| sql_005 | `GROUP BY top_category ORDER BY AVG(avg_amount) ASC` | 运动 1501.62 最低（服装 1509.43 次低） |
| sql_006 | `GROUP BY city ORDER BY AVG(age) DESC` | 上海 42.58（深圳 42.42 / 杭州 42.08） |
| sql_007 | `WHERE member_level='黑卡' GROUP BY city` | 北京 3（其余城市 0） |
| sql_008 | `WHERE platforms LIKE '%淘宝%'` | 937 |
| sql_009 | `city='南京' AND member_level='钻石'` | 46 |
| sql_010 | `GROUP BY member_level ORDER BY SUM(total_amount) DESC` | 黄金 33,368,665.28 最高 |
| multi_001 | `avg_amount>=1000` | 6708；6708/8110 = 82.71% |
| multi_002 | `days_since_last_buy>30 AND avg_amount>500 AND order_count>=3` | 2616；32.26% |
| multi_003 | `avg_amount>=14555` vs `member_level='钻石'` | 406 vs 403，差 3 人均为黑卡（黑卡 avg_amount 31451.64–47924.35） |
| multi_004 | `days_since_last_buy BETWEEN 31 AND 90` | 2383；29.38% |
| multi_005 | 380×2 | 760 |
| multi_006 | 5×100 | 500 |
| multi_007 | 48−24 | 24 |
| multi_008 | 3×100 | 300 |
| multi_009 | 上海 686，黄金 114 | 114/686 = 16.62% |
| multi_010 | 普通 AVG(avg_amount)=1319.11；2495−1319.11 | 1175.89（keyword 取尾 175.89） |
| multi_011 | 黑卡 AVG=37665.00（3 人）、钻石 AVG=21416.52 | 37665/21416.52 = 1.7587 → 1.76 |
| multi_012 | 电子产品 2235；2235/8110 | 27.56% |
| calc_001 | 158+236+186 | 580 |
| calc_002 | 2496.24−1326.22（两输入与 demo P25/P50 实测值 1326.22/2496.24 一致） | 1170.02 |
| calc_003 | 899×1.1×0.9 | 890.01 |
| calc_004 | 722/8110 | 8.90% |
| neg_006 | P80(total_amount)=19254.54；`total_amount>=P80 AND days_since_last_buy<=30` | 430（acceptance 所说近似值可复算） |

### 3.3 RAG 原文核对（8 条 rag + multi 依赖事实）

逐条对照 `wiki_vectors` 原文（doc_name / chunk）：

- rag_001：`member_benefits.md` 黄金会员权益「单笔订单满 99 元免运费」→ 99、免运费 ✅
- rag_002：`member_benefits.md` 钻石会员权益「生日当月赠 200 元无门槛券」→ 200、生日 ✅
- rag_003：`member_benefits.md` 会员升级与保级「T+1 自动升级、权益次日生效；无固定保级考核期」→ T+1、保级 ✅
- rag_004：`cs_sop.md` 场景一「已发货且超过 7 天未更新…补偿 10 元无门槛券或积分…标记物流延迟」→ 物流延迟、10 ✅
- rag_005：`marketing_playbook.md` 二「大额无门槛券（50 元）；渠道：电话回访、专属客服企微、短信」→ 50、电话 ✅
- rag_006：`cs_sop.md` 场景三「查询会员等级和权益有效期…记录工单」→ 有效期、工单 ✅（另有 `member_benefits.md` 权益咨询流程同义，两个来源都含这两个片段）
- rag_007：`segmentation.md` 分群维度「沉默客（31–90 天无行为）、流失客（> 90 天无行为）」→ 31、90 ✅
- rag_008：`marketing_playbook.md` 一「首单立减 20 元；注册后 24 小时内、第 3 天、第 7 天」→ 20、24 ✅

**结论：未发现任何 expected 与 demo 数据/文档矛盾。**

### 3.4 可执行性 / 检索可达性复核

- 工具名与真实注册一致：`{rag_search, execute_sql, calculator}`（`agent/registry.py`）。
- SQL 白名单表 = `{user_profile_vectors, wiki_vectors}`（`tools/sql_tool.py:40`）；所有 benchmark SQL 均可在此范围内完成；`execute_sql` 要求 SQL 带 LIMIT，题目均可满足。
- 对 18 条依赖知识库的题做了真实 `hybrid_search(..., top_k=5)` dry-run：**18/18 的 expected 来源 chunk 均进入 top-5**（详见附录 B）。说明题目在检索层面可完成。
- 说明：multi_005 / multi_006 的 top-1 是同文档的“更低等级权益”chunk（白银），但正确 chunk 分别在 #3 / #2，Agent 读取 top-5 即可拿到；属于检索排序问题，不是数据不可达。

---

## 4. 40 条逐条审查表

> Verdict 判定：PASS = 该条本身数据/契约/可验收性无阻塞问题；FAIL = 必须由 builder 修改或替换（见 §5.1）。
> 证据中的数值均为本次独立复算结果。

| # | task_id | category | verdict | 证据（一句） |
|---:|---|---|---|---|
| 1 | bench_sql_001 | execute_sql | **FAIL** | 数据正确（北京722/杭州714/南京694，第三=南京 694）；但 **南京 694 已原样出现在 Agent 系统提示词的 city 枚举**里（E1），且与 regression sql_005 是同一条城市计数查询、仅把 top1 改成 top3。 |
| 2 | bench_sql_002 | execute_sql | PASS | 复算白银 2.98 最高（黄金2.90/普通2.34/钻石1.80/黑卡1.33）；数据正确，注意白银与黄金仅差 0.08、黑卡 n=3（acceptance 已提示样本量）。 |
| 3 | bench_sql_003 | execute_sql | PASS | SUM(total_amount)=91,923,627.92 元，keyword 627.92 是 91,923,627.92 的子串；题目已要求精确到分，格式假设成立。 |
| 4 | bench_sql_004 | execute_sql | PASS | AVG(age)=41.62、AVG(order_count)=2.59，两列 0 空值、age 18–65、order_count 1–10，与 acceptance 一致。 |
| 5 | bench_sql_005 | execute_sql | PASS | 运动 1501.62 最低（服装1509.43/美妆1533.72/书籍1559.26/玩具1574.04/家居5244.71/电子产品8978.73）；注意前两名差 7.81 元（0.5%），且 keyword 仅“运动”，列举全品类时可能误命中（M5）。 |
| 6 | bench_sql_006 | execute_sql | PASS | 上海 42.58 最大（深圳42.42/杭州42.08）；数据正确，但第一与第二仅差 0.16 岁，业务上是噪声级差异（见 §5.2 M9，与业务评审 H6 一致）。 |
| 7 | bench_sql_007 | execute_sql | PASS | 黑卡共 3 人且全部在北京、其余城市 0；keyword 仅“北京”，无法机器验证“其余城市 0/集中分布”（M5/M3）。 |
| 8 | bench_sql_008 | execute_sql | **FAIL** | 937 复算正确；但 **“淘宝(937)”已原样出现在 Agent 系统提示词的 platforms 枚举**里（E1），且 acceptance 要求的“说明字段缺失”不被 keyword 判定（M3）。 |
| 9 | bench_sql_009 | execute_sql | PASS | 南京用户 694 中钻石 46，复算一致；与 regression multi_004（上海钻石计数+占比）属同模板切片，见 §5.2 M6 建议复核。 |
| 10 | bench_sql_010 | execute_sql | PASS | 黄金累计 33,368,665.28 最高（白银30,210,859.90/钻石14,586,711.70/普通13,610,777.06/黑卡146,613.98）；keyword 仅“黄金”，结论方向靠单实体词弱验证（M5）。 |
| 11 | bench_rag_001 | rag_search | PASS | 原文“黄金会员：单笔订单满 99 元免运费”，关键词 99+免运费；检索验证正确 chunk 在 top-1。 |
| 12 | bench_rag_002 | rag_search | PASS | 原文“钻石会员生日当月赠 200 元无门槛券、当月消费双倍积分”，关键词 200+生日；检索 top-1。 |
| 13 | bench_rag_003 | rag_search | PASS | 原文“达到门槛后 T+1 自动升级、权益次日生效；无固定保级考核期”，关键词 T+1+保级；检索 top-1。 |
| 14 | bench_rag_004 | rag_search | PASS | 原文“已发货且超过 7 天未更新，主动致歉；补偿 10 元无门槛券或积分；标记物流延迟”，关键词物流延迟+10；检索 top-1。 |
| 15 | bench_rag_005 | rag_search | PASS | 原文“高价值沉默客召回：大额无门槛券 50 元；渠道电话回访/专属客服企微/短信”，关键词 50+电话；检索 top-1。 |
| 16 | bench_rag_006 | rag_search | PASS | 原文 cs_sop 场景三 5 步流程含“权益有效期”“记录工单”；关键词 有效期+工单；检索 top-1。注意两处相似文档，关键词取公共片段，可验收但信息量偏低（M5）。 |
| 17 | bench_rag_007 | rag_search | PASS | 原文“沉默客 31–90 天无行为、流失客 >90 天无行为”，关键词 31+90；检索 top-1。 |
| 18 | bench_rag_008 | rag_search | PASS | 原文“首单立减 20 元；注册后 24 小时内、第 3/7 天”，关键词 20+24；检索 top-1。 |
| 19 | bench_multi_001 | multi_tool | PASS | tag_definitions 高客单=累计平均客单价≥1000；count=6708；6708/8110=82.71%；三工具链路合理。注意系统提示词另有“高客单/低客单按分位理解、不要用固定绝对金额”的冲突指引（M8）。 |
| 20 | bench_multi_002 | multi_tool | PASS | 流失预警定义原文为“近30天未活跃+历史客单价>500+累计购买≥3”；近似 count=2616、32.26%；检索 top-1 为 tag_definitions 流失预警。与 regression rag_002 的定义问句前缀相同（M6，非阻塞）。 |
| 21 | bench_multi_003 | multi_tool | PASS | 四档门槛原文核对一致；avg_amount≥14555 人数=406 vs 库内钻石 403，差 3 人恰为黑卡（3 人 avg 31451.64–47924.35），逻辑闭环；检索正确 chunk 在 #2。14555 与 regression rag_004 同事实（M6）。 |
| 22 | bench_multi_004 | multi_tool | PASS | 沉默客 31–90 → 2383、29.38%；检索 top-1 为 segmentation 分群维度。题干括号已给出 31–90 定义，rag_search 可能非必需（M7）。 |
| 23 | bench_multi_005 | multi_tool | PASS | 钻石积分加速 2 倍（原文核对）；380×2=760；检索正确 chunk 在 #3（top-1 为白银 1.2 倍），top-5 内可完成。 |
| 24 | bench_multi_006 | multi_tool | PASS | 黄金生日 100 元券（原文核对）；5×100=500；检索正确 chunk 在 #2（top-1 白银 50）。keyword 100/500 存在 100⊂1000、500⊂5000 的宽泛风险（M4）。 |
| 25 | bench_multi_007 | multi_tool | PASS | 钻石 48h / 黄金 24h（原文核对）；48−24=24；检索两 chunk 均在 top-2。 |
| 26 | bench_multi_008 | multi_tool | PASS | 流失挽回 100 元券（限7天，原文核对）；3×100=300；检索 top-1。与 multi_006 同为“券面额×N=总额”模板（M9），keyword 100/300 偏宽（M4）。 |
| 27 | bench_multi_009 | multi_tool | **FAIL** | 数据正确（上海686、黄金114、16.62%）；但与 regression multi_004（上海钻石数量+占比，32/4.6%）**同城市、同维度、同指标、同工具链，仅等级由钻石换成黄金**，属 policy §3.5/§5 禁止的换皮（E2）。 |
| 28 | bench_multi_010 | multi_tool | **FAIL** | 数据正确（普通 AVG=1319.11，2495−1319.11=1175.89）；但题干已给出“白银门槛 2495 元”，`expected_tools` 却要求 rag_search，按题干做正确的最小轨迹（execute_sql+calculator）会因缺 rag_search 被判 tool 失败（E3）。 |
| 29 | bench_multi_011 | multi_tool | PASS | 黑卡 AVG=37665.00、钻石 AVG=21416.52，比值 1.7587→1.76；acceptance 要求提示 n=3 的样本风险但 keyword 不校验（M3），且 n=3 本身业务上不稳定。 |
| 30 | bench_multi_012 | multi_tool | **FAIL** | 数据正确（电子产品 2235、2235/8110=27.56%）；但 **“电子产品(2235)”已原样出现在系统提示词的 top_category 枚举**中（E1），count 可直接抄；expected_tools=execute_sql 可能误伤只用 calculator 的合规 Agent。 |
| 31 | bench_neg_001 | negative | PASS | 数据只有 user_profile_vectors/wiki_vectors 两表，无任何营销触达/推送字段；`profile_text` 对“营销/触达/推送/优惠券/活动”正则命中 0；问题明确“不支持请说明、不要编造”，acceptance 表达不得编造 ✅。工具强制 execute_sql 与 schema 已提示全部字段存在矛盾（M1）；“无法”关键词脆弱（M2）。 |
| 32 | bench_neg_002 | negative | PASS | 无订单明细/退货字段，只有用户级累计 order_count/total_amount；退货率确实不可算；acceptance 要求说明无法计算、不得编造 ✅。M1/M2 同 neg_001。 |
| 33 | bench_neg_003 | negative | PASS | `top_category` 实测仅 7 类（电子/家居/书籍/玩具/服装/运动/美妆），无“母婴”，profile_text 母婴关键词 0；acceptance 明确“不得用其他品类替代、不得直接报 0 当结论”✅；是最真实的负样本之一。M1/M2 同前。 |
| 34 | bench_neg_004 | negative | PASS | 单时点静态快照，无时间序列表；`days_since_last_buy` 0–364 只是相对天数；系统提示词也明确“无时间序列、无法回答未来时点”，负样本成立 ✅。M1（正确拒答可零工具）最典型。 |
| 35 | bench_neg_005 | negative | PASS | 无注册时间、首单时间、订单明细；只有 days_since_last_buy，无法算“注册→首单”转化天数；acceptance 要求说明缺失、不得编造 ✅。M1/M2 同前。 |
| 36 | bench_neg_006 | negative | PASS | tag_definitions 高价值=近90天消费前20%+近30天有活跃行为；demo 无近 90 天窗口/行为日志，无法精确统计；近似 430 人可复算（P80=19254.54，430 人），acceptance 允许近似但要求“无法精确” ✅。定义与 regression rag_001 同事实、keyword“90”相同（M6）。 |
| 37 | bench_calc_001 | calculator | PASS | 158+236+186=580，纯算术可复算。 |
| 38 | bench_calc_002 | calculator | PASS | 题干输入 P25=1326.22/P50=2496.24 与 demo 实测分位一致；2496.24−1326.22=1170.02，keyword 170.02 为其子串。 |
| 39 | bench_calc_003 | calculator | PASS | 899×1.1×0.9=890.01，正确；属经典连续百分比考法（业务价值低但技术正确）。 |
| 40 | bench_calc_004 | calculator | PASS | 722/8110=8.9026→8.90%，keyword 8.9 兼容；输入数字也在系统提示词中（722、8110），但本题为纯 calculator 类别，不影响 expected 工具语义。 |

**汇总：PASS 35 / FAIL 5。FAIL = `bench_sql_001`、`bench_sql_008`、`bench_multi_009`、`bench_multi_010`、`bench_multi_012`。**

---

## 5. 问题清单（按严重程度）

### 5.1 阻塞（FAIL，必须修后才能冻结）

#### E1（3 条）· 答案已泄露在 Agent 系统提示词，题目测量效度失效

- 涉及 task：`bench_sql_001`、`bench_sql_008`、`bench_multi_012`
- 事实（本次实测 `schema_facts.get_sql_schema()` 渲染结果，该文本由 `loop.build_system_prompt()` 注入每次 `run_agent` 的 SystemMessage）：
  - `city：北京(722) / 杭州(714) / 南京(694) / 上海(686) / …` → `bench_sql_001` 问“第三多城市及人数”，答案南京 694 直接可读。
  - `platforms：未标注来源(7277) / 拼多多(959) / 京东(955) / 苏宁易购(952) / 天猫(947) / 1688(943) / 淘宝(937)` → `bench_sql_008` 答案 937 直接可读。
  - `top_category：电子产品(2235) / 家居(1794) / …` → `bench_multi_012` 的数量 2235 直接可读。
- 影响：
  1. 一个按上下文直接作答、不调用 SQL 的 Agent 会因 `expected_tools` 缺失被判 `tool_selection` 失败（假失败）；
  2. 一个抄上下文再随便跑一条 SQL 的 Agent 能通过，题目**不测量 SQL 计算能力**，只测量“是否会写一条 SQL”；
  3. 与 `DATASET_QUALITY_POLICY.md` 的 benchmark 定位（“更难、更独立”）冲突。
- 要求 builder 修复（二选一，推荐前者）：
  - 换成答案**不能**由枚举计数/范围直接读出的题，例如：跨维度交叉聚合（某城市×等级的过滤计数）、AVG/SUM 类、需要 HAVING/占比计算但输入未在上下文给出的题；
  - 或由 Lead/runner 侧决定 benchmark 运行时不注入 schema 取值分布（但这超出 builder 写范围，且与现有 runner 行为不符）。
- 注：`bench_sql_001` 另与 regression `sql_005`（按城市计数、哪个最多）同一条查询，仅把 top1 换成 top3，模板重复，一并建议替换。

#### E2（1 条）· 与 regression 明显换皮：`bench_multi_009` ↔ `regression/multi_004`

- regression `multi_004`（`regression/dataset.v1.json`）：“统计上海用户中**钻石**用户的数量，并计算其占上海用户的比例”，tools `[execute_sql, calculator]`，expected 32 / 4.6%。
- benchmark `bench_multi_009`：“统计上海用户中**黄金会员**的数量，并用 calculator 计算其占上海用户的百分比（保留两位小数）”，tools `[execute_sql, calculator]`，expected 114 / 16.62%。
- 判定：同城市、同维度、同指标、同工具链、同答案结构，仅把会员等级从“钻石”换成“黄金” → 违反 `DATASET_QUALITY_POLICY.md` §3.5“不允许同一条任务在不同集合里换皮重复”与 §5“不允许把 regression 的 20 条简单改问法后重复提交”。
- 要求：替换为不同城市×不同指标/不同分析动作的题（例如“上海各会员等级人数与结构占比”“北京 vs 上海会员结构差异”），不能只换等级。

#### E3（1 条）· expected_tools 与题干矛盾：`bench_multi_010`

- 题干：“普通会员的平均客单价与白银会员门槛（累计平均客单价 2495 元）相差多少元？请先查库内普通会员平均客单价，再用 calculator 计算差额。”
- 问题：门槛 2495 已在题干给出，`rag_search` 没有必要的检索动作，但 `expected_tools = ["rag_search","execute_sql","calculator"]`。`evaluator.py` 的 `tool_selection_ok = expected - actual 为空`，因此一个**完全按题干执行**的正确轨迹（execute_sql + calculator）会因缺 `rag_search` 被判 task_success=false（数据 1319.11 / 1175.89 本身已复算正确）。
- 要求（二选一）：
  - 去掉题干中的“（累计平均客单价 2495 元）”，让 Agent 必须从 `member_benefits.md` 检索门槛（检索实测 top-1 命中等级划分标准）；
  - 或把 `expected_tools` 改为 `["execute_sql","calculator"]` 并同步修改 acceptance。

### 5.2 中风险（建议在冻结前一并处理；是否阻塞由 Lead/业务评审决定）

#### M1 · negative 5 条的 expected_tools 与“正确拒答”冲突（neg_001–005）

- 本次实测系统提示词已列出两表全部列/枚举，且明确写“时间口径：没有绝对时间列……无法回答未来时点问题（无时间序列）”。因此 neg_001/002/005 的字段缺失、neg_004 的不可预测，Agent **零工具也能正确拒答**；但 `expected_tools` 强制 `execute_sql`，零工具拒答会被判 tool_selection 失败。
- 影响：5 条负样本考的是“会不会为了走流程跑一条无意义 SQL”，而不是“能不能识别数据不可用”，与 negative 类别本意（拒答/无数据）有偏差。业务评审 H2 也独立指出。
- 建议：negative 的 `expected_tools` 改为 `[]`（evaluator 对空期望返回 tool_recall=1.0，可正常判过），或在 acceptance 明示“工具调用非强制”；若坚持检查工具，则须把题目改成“从 schema 看不出结论、必须实际查询才能判断”的形态。

#### M2 · negative 的“无法”关键词脆弱，且“不得编造”无法机器验收（6 条）

- `evaluator.py` 只做 `expected_keywords ⊆ final_answer` 子串判定。负样本关键词 = “无法 + 实体词”，因此：
  - 正确拒答若写成“没有/不存在/未提供相关字段”，不含“无法”→ 判失败；
  - “无法精确统计，但按活跃用户推算约 2500 人”这类**先编造再免责**的回答会通过（含“无法”）。
- 影响：6/40 的负样本验收声明高于实际可验收能力（builder_notes §9.2 也自认该风险）。属于 evaluator 能力问题，repository 侧需 Lead 决定是否增加 forbidden-digits/同义词判定或转人工复核；**仅改 dataset 的 builder 无法单独解决**，但应在交付说明中如实标注。

#### M3 · acceptance 中的附加要求不被关键词覆盖（7 条）

| task | acceptance 要求 | 机器实际只验证 |
|---|---|---|
| sql_007 | 须指出“全部集中在北京，其余城市 0” | “北京” |
| sql_008 | 须说明 platforms 存在缺失标记 | “937” |
| multi_002 | 须说明用最后购买天数近似“活跃” | “500”“32.2” |
| multi_003 | 须解释黑卡第五档 | “14555”“406” |
| multi_004 | 须说明近似口径 | “31”“29.3” |
| multi_011 | 须提示黑卡仅 3 人、样本不稳定 | “1.7” |
| multi_009/sql_001 等 | — | （同属此模式，但被 §5.1 覆盖） |

- 影响：报告可能显示 PASS，但 acceptance 的业务要求未达成；业务评审 M11 也独立指出。
- 建议：把“必须提示/必须说明”类要求标为**人工复核项**（不参与自动判分），或在 acceptance 明确“自动验收只看 keyword，附加说明为人工项”；不要留下“看起来可验收、实际验收不到”的表述。

#### M4 · 部分关键词偏宽（2–3 位数字可被更长数字包含）

- `multi_006`：`["100","500"]` —— 答案写“1000 元券 / 5000 元”也会命中（1000⊃100、5000⊃500）；
- `multi_008`：`["100","300"]` —— 同理 1000/3000；
- 同类：rag_004 `"10"`（100 含 10）、rag_007 `"31"/"90"`、rag_008 `"20"/"24"`、multi_007 `"48"/"24"`、multi_002 `"500"`、sql_009 `"46"`、calc_001 `"580"` 等。
- 判定：没有单字符/单数字关键词（policy 底线满足），实际误命中风险低（错误答案很少恰好含目标数字串），但属于可改进项；可在不牺牲格式兼容的前提下优先用“带单位/上下文”的片段（注意“100 元”带空格会造成格式假失败，需 evaluator 支持才建议）。

#### M5 · 单实体关键词无法验证“结论方向”（sql_005 / sql_007 / sql_010 / rag_006）

- sql_005 仅“运动”、sql_010 仅“黄金”、sql_007 仅“北京”、rag_006 仅“有效期/工单”：一个列举全部品类/等级/城市/流程的答案会顺带命中关键词，即使结论说反也能 PASS。
- 这是 keyword 子串判定的系统性限制；建议在 acceptance 中标注“结论方向需人工复核”，或对可安全格式化的题补一个稳定的结论数值片段。

#### M6 · 与 regression 的“部分复用”需 Lead 明确口径（非全部阻塞）

| benchmark | regression | 重叠形态 | 评价 |
|---|---|---|---|
| multi_009 | multi_004 | 上海+等级计数+占比，仅换等级 | **明显换皮，阻塞 E2** |
| sql_001 | sql_005 | 按城市计数，top1→top3 | 同一查询仅改名次；建议替换（同时属 E1） |
| sql_009 | multi_004 / sql_003 | 城市×等级计数（南京钻石 46；无占比） | 同模板切片，新事实；建议复核是否保留 |
| multi_002 | rag_002 | 问句前缀“流失预警用户的判定标准是什么”逐字相同，后接统计/占比 | 增加了真实执行与计算，属“同定义延伸”，可接受但需注明 |
| multi_003 | rag_004 | 共用 14555 门槛；本题做 406 vs 403 口径对比 | 可接受（考题动作不同） |
| neg_006 | rag_001 | “高价值用户”定义+关键词“90”相同；本题考不可精确统计 | 可接受（负样本核心不同） |
| multi_012 | multi_003 | “数量+占比”模板（维度不同） | 模板相似、任务不同，可接受 |

- 注意：dataset 顶层 `description` 声称“与 regression 的 20 条无语义重复”，这一表述不准确（至少 multi_009 明确违反；multi_002/sql_001 等有重叠）。建议同步修正描述，避免评审误判。

#### M7 · `bench_multi_004` 的 rag_search 也可能“绕开”

- 题干括号已给出“用 days_since_last_buy 对应‘31–90 天无行为’”，即沉默客定义已告知；`expected_tools` 仍要求 `rag_search`。虽然题干同时要求“按分群文档的定义”，保留 rag 尚可解释，但存在与 E3 同类风险。
- 建议：去掉括号中的“31–90 天无行为”，只保留“用 days_since_last_buy 近似无行为”，强制检索定义；或在 acceptance 说明 rag_search 为质量要求而非最小必要工具。

#### M8 · `bench_multi_001` 与系统提示词的客单口径指导存在冲突

- 系统提示词注入的数据口径写明：“客单价分位……「高客单/低客单」按这些分位理解，不要用固定的绝对金额”；
- 而 multi_001 的 expected 采用 tag_definitions 的固定门槛 `avg_amount≥1000`（6708 人 / 82.71%）。
- 影响：一个遵循系统提示词、按分位理解“高客单”的 Agent 可能给出不同定义/数值；本题的“正确口径”依赖“文档优先于提示词”的约定。建议在 acceptance 注明“以 tag_definitions.md 文档口径为准，分位仅供参考”，或由 Lead 调整系统提示词措辞。

#### M9 · 模板集中（业务评审已覆盖，数据侧记录）

- multi_005/006/007/008 都是“权益数值 + 四则运算”的组合；其中 multi_006 与 multi_008 是同一“券面额×N=总额”模板；multi_005 题干“计算双倍积分”甚至直接泄露第一问答案（2 倍）。
- SQL 10 条中 5 条是 `GROUP BY 维度 + ORDER BY 聚合` 模板（sql_001/002/005/006/010）。
- 不是数据错误，但会降低 benchmark 的能力覆盖度；建议替换 1–2 条为更真实的业务链路（真实人数×券面额=预算、HAVING/CTE/分位等）。

### 5.3 低风险 / 文档与流程问题

#### L1 · builder_notes 有失实/过时陈述（不影响数据，但需修正）

- §9.1 “benchmark 尚无 runner；runner.py 的 load_tasks 固定要求 20 条，当前 40 条不能直接用 runner 跑” —— **不实**：`runner.py` 已内置 `benchmark` suite（count=40），本次 `--suite benchmark --validate-only` 输出 `suite=benchmark tasks=40 valid`。
- §6 “benchmark 未使用其任何一条的答案/问法” / 顶层 description “无语义重复” —— 与 E2/multi_002/sql_001 的实际情况不符（见 M6）。
- §5.2 “没有绝对时间列” —— 表述不严谨：`user_profile_vectors.update_time` 是 timestamp 列，`profile_text` 中也含“最近一次购买在 YYYY-MM-DD”；但 demo 确实没有业务时间序列，题目涉及的负样本结论仍然成立，故仅作文字修正。

#### L2 · builder 在构建期用真实 Agent 跑过最终 40 条（自述），存在过拟合/污染风险

- `builder_notes.md` §8.3 自述：为确认关键词可达性，用真实 `run_agent` 对最终 40 条做了 dry-run（31 条批量 + 9 条抽样 + 5 条改动后复跑，40/40 命中），并“构建期曾用 `9`（折扣），自检发现过宽后改为 `积分`+`760`”。
- `DATASET_QUALITY_POLICY.md` §6 规定 benchmark 不用于日常 Prompt 调优，且 builder 不得按评审反馈“定向修改”到过拟合；在构建期用被评测 Agent 反复试跑并调整关键词，存在把 case 拟合到特定模型措辞的风险。
- 本次未在仓库中找到该 dry-run 的持久化产物（`data/eval/` 仅有 2026-10-21 的旧 run，与本次 benchmark 无关），无法独立复核其规模与影响；**建议 Lead 在最终报告中披露该操作，并考虑冻结前更换/重写至少部分被 dry-run 覆盖的 case，或明确声明该风险**。
- 另外，本次审查刻意**没有**运行完整 40 条 Agent，以避免进一步污染 benchmark。

#### L3 · 关键词格式稳定性提示

- `rag_003` 的 `T+1`：若模型输出“T + 1”“T+1（次日生效）”前者会失败、后者可过；`rag_004` 的 `10` 等数字也有类似格式假设。建议 acceptance 已写明的格式要求（如“保留两位小数”“精确到分”）是合理的，但“T+1”式符号需在验收说明里注明“按原文格式”。

---

## 6. 最终结论：**FAIL**

### 6.1 判定

- **不通过，不能按当前版本冻结/交付。**
- 数据本身：**40 条 expected 无事实性错误**（全部 SQL/算术/原文复核通过；negative 6 条均为真实“无数据/不可回答”场景；结构/分布完全符合 policy）。
- 不通过原因集中在**评测有效性/契约**：
  1. `bench_sql_001`、`bench_sql_008`、`bench_multi_012`：答案已出现在 Agent 系统提示词的 schema facts 中，题目失去测量意义，且会误伤不调用 SQL 的合规轨迹（E1）。
  2. `bench_multi_009`：与 regression `multi_004` 明显换皮，违反 policy §3.5/§5（E2）。
  3. `bench_multi_010`：题干已给门槛 2495，却把 `rag_search` 设为必需工具，正确最小轨迹会被判 tool 失败（E3）。

### 6.2 builder 必须修的 task（不得改其它文件）

| 优先级 | task_id | 动作 |
|---|---|---|
| P0 | `bench_sql_001` | 替换为答案无法从 schema 枚举计数直接读出的 SQL 题；同时避免与 regression sql_005 同查询（建议改成跨维度过滤计数/聚合，如“某城市某等级人数”“某等级 SUM/AVG”等需要真正计算的问题）。 |
| P0 | `bench_sql_008` | 替换：答案（淘宝 937）已在系统提示词 platforms 枚举中；可改为需要过滤/交叉计算的平台题（如“同时包含淘宝与京东标注的人数”“平台缺失用户占比”等），注意 platforms 缺失口径需写入 acceptance。 |
| P0 | `bench_multi_012` | 替换：count 2235 已泄露；可改为需要 SQL 聚合+calculator 且输入不在枚举中的题（如“电子产品用户的平均客单价/占比 vs 其他品类”）。 |
| P0 | `bench_multi_009` | 替换：不得只换等级；改为不同城市×不同指标的题，或“上海各等级人数与结构占比/北京 vs 上海结构差异”等新题。 |
| P0 | `bench_multi_010` | 二选一：去掉题干中的“（累计平均客单价 2495 元）”让 rag_search 成为必需；或将 `expected_tools` 改为 `["execute_sql","calculator"]` 并同步改 acceptance。 |

### 6.3 建议在冻结前一并处理（非本次 FAIL 的硬性项，但影响验收质量）

1. negative `expected_tools`（M1）：至少 `neg_001/002/004/005` 考虑改为 `[]` 或在 acceptance 注明“工具非强制”，否则正确拒答可能假失败；`neg_003` 可保留 `execute_sql`（需要确认数据无母婴品类）。
2. negative 防编造（M2）：由 Lead/evaluator 决定是否增加“最终回答不得出现数字/不得出现具体人数”的 forbidden 规则，或改为人工复核。
3. acceptance 与自动验收对齐（M3）：把“须说明缺失/须提示样本/须解释差异”标为人工复核项，避免“PASS 但业务要求未达成”。
4. `bench_multi_004` 去掉括号内 31–90 定义（M7）；`bench_multi_001` acceptance 注明“以 tag_definitions 文档口径为准”（M8）。
5. `builder_notes.md` 修正 §9.1 runner 陈述、§6/description 的“无语义重复”表述（L1），并披露构建期 dry-run（L2）。
6. 关键词加严建议（M4/M5）：只在不会引入格式假失败的前提下补充结论数值；否则在验收说明中标注“结论方向人工复核”。
7. 数据版本/版本号：按 policy §9，任何 expected/题目修改后 benchmark 版本号 +1（建议 v1.1），并在修复后重新提交 evaluator 复审。

### 6.4 复审通过条件

- 5 条 P0 修复完成，且修改后的 expected 经 SQL/wiki 复算一致；
- 复查系统提示词 `get_sql_schema()`，确认剩余 40 条中没有任何 expected 答案可直接从 schema facts 的枚举计数/范围读出（或 Lead 明确批准修改 benchmark 运行配置）；
- 用 `runner.py --suite benchmark --validate-only` 通过（当前已通过）；
- 重新比对 regression 20 条语义，确认无 pending 换皮；
- 更新版本号 + builder_notes 修订说明。

---

## 附录 A：关键验证输出（摘要）

```text
# 结构校验
n tasks: 40
category counts: {'execute_sql': 10, 'rag_search': 8, 'multi_tool': 12, 'negative': 6, 'calculator': 4}
unique ids: True | n ids: 40
expected_success: Counter({True: 40})
contract violations: NONE

# runner 加载校验
suite=benchmark tasks=40 valid
suite=regression tasks=20 valid

# 系统提示词注入（get_sql_schema() 实际渲染，节选）
city：北京(722) / 杭州(714) / 南京(694) / 上海(686) / ...
platforms：未标注来源(7277) / 拼多多(959) / 京东(955) / ... / 淘宝(937)
top_category：电子产品(2235) / 家居(1794) / ...
时间口径：没有绝对时间列，只有一个相对天数 days_since_last_buy（实测 0 ~ 364 天）...
客单价分位（本库实测）：P25=1326 / P50=2496 / P75=5474 / P90=10383 元；
「高客单/低客单」按这些分位理解，不要用固定的绝对金额
```

## 附录 B：知识库检索 dry-run（top-5 内 expected 来源位置）

| task | expected 来源 chunk 在 top-5 的位置 | 备注 |
|---|---|---|
| rag_001 | #1 member_benefits.md 黄金会员权益 | |
| rag_002 | #1 member_benefits.md 钻石会员权益 | |
| rag_003 | #1 member_benefits.md 会员升级与保级 | |
| rag_004 | #1 cs_sop.md 场景一 物流延迟 | |
| rag_005 | #1 marketing_playbook.md 二 高价值沉默客召回 | |
| rag_006 | #1 cs_sop.md 场景三 会员权益咨询 | |
| rag_007 | #1 segmentation.md 分群维度 | |
| rag_008 | #1 marketing_playbook.md 一 新客转化 | |
| multi_001 | #1 tag_definitions.md 高客单用户 | |
| multi_002 | #1 tag_definitions.md 流失预警用户 | |
| multi_003 | #2 member_benefits.md 等级划分标准 | top-1 是无关用户画像 |
| multi_004 | #1 segmentation.md 分群维度 | |
| multi_005 | #3 member_benefits.md 钻石会员权益 | top-1 是白银权益（1.2 倍），top-5 内可纠正 |
| multi_006 | #2 member_benefits.md 黄金会员权益 | top-1 是白银权益（50 元） |
| multi_007 | 钻石权益 #1、黄金权益 #2 | 两个 chunk 均在 top-2 |
| multi_008 | #1 marketing_playbook.md 四 流失用户挽回 | |
| multi_010 | #1 member_benefits.md 等级划分标准 | 含 2495 门槛 |
| neg_006 | #2 tag_definitions.md 高价值用户 | top-1 是高客单（1000），top-5 内可纠正 |

**结论：18/18 的知识库题所需的原文 chunk 均能进入 top-5 检索结果，题目在检索层面可完成。**

---

## 附录 C：本次审查未做的事（边界声明）

- 未运行完整 40 条真实 Agent（避免 benchmark 被构建期/审查期反复试跑污染，policy §6）；因此本报告不提供 baseline 分数。
- 未修改 `dataset.v1.json`、`regression/`、`builder_notes.md`、`DATASET_QUALITY_POLICY.md`、`runner.py`、`evaluator.py`、`src/`；未提交 Git。
- 唯一新增文件：本报告 `tests/evals/agent/benchmark/review_evaluator.md`。
