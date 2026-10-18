# 离线评测报告（LLM-as-a-Judge）

- 评测时间：2026-10-18 18:14:13
- 数据集：`demo`（固定离线评测库，不经过前端 API）
- 题目文件：`src/rag_demo/tests/eval_questions.json`
- 裁判模型：`deepseek-chat`
- 运行命令：`uv run python run_eval.py`（可加 `--limit` / `--only` 做子集试跑）
- 题目数：**33**；成功判定：33；裁判异常：0；回答异常：0
- 总耗时：202.9s（平均 5.1s/题）

## 总体通过率

| 指标 | 数值 |
|---|---|
| 通过率（通过/成功判定） | **75.8%** （25/33） |
| 判定覆盖率（成功判定/总题数） | 100.0% |
| 来源召回率（宏平均） | 93.5%（23 题有期望来源） |
| 来源召回率（微平均：命中/期望） | 93.3% |

## 分模块通过率

| 模块 | 题数 | 已判定 | 通过 | 通过率 | 来源召回率 |
|---|---|---|---|---|---|
| 数据分析师/产品 | 7 | 7 | 5 | 71.4% | 100.0% |
| 管理层 | 3 | 3 | 2 | 66.7% | 100.0% |
| 边界 | 6 | 6 | 6 | 100.0% | 100.0% |
| 运营/市场 | 10 | 10 | 7 | 70.0% | 83.3% |
| 销售/客服 | 7 | 7 | 5 | 71.4% | 100.0% |

## 来源召回明细

| 题号 | 模块 | 期望来源 | 实际来源 | 命中 | 召回率 |
|---|---|---|---|---|---|
| OPT-01 | 运营/市场 | user_profile、tag_definitions.md | user_profile、tag_definitions.md、analysis_report_template.md | user_profile、tag_definitions.md | 100.0% |
| OPT-02 | 运营/市场 | user_profile | user_profile、member_benefits.md、analysis_report_template.md | user_profile | 100.0% |
| OPT-03 | 运营/市场 | tag_definitions.md | user_profile、tag_definitions.md | tag_definitions.md | 100.0% |
| OPT-04 | 运营/市场 | marketing_playbook.md、tag_definitions.md | user_profile、marketing_playbook.md、tag_definitions.md | marketing_playbook.md、tag_definitions.md | 100.0% |
| OPT-05 | 运营/市场 | user_profile、tag_definitions.md | user_profile、tag_definitions.md、segmentation.md | user_profile、tag_definitions.md | 100.0% |
| OPT-06 | 运营/市场 | — | user_profile、tag_definitions.md、segmentation.md | — | — |
| CS-01 | 销售/客服 | cs_sop.md | user_profile、cs_sop.md | cs_sop.md | 100.0% |
| CS-02 | 销售/客服 | cs_sop.md | user_profile、cs_sop.md | cs_sop.md | 100.0% |
| CS-03 | 销售/客服 | user_profile | user_profile、tag_definitions.md、member_benefits.md、segmentation.md | user_profile | 100.0% |
| CS-04 | 销售/客服 | member_benefits.md | user_profile、member_benefits.md | member_benefits.md | 100.0% |
| CS-05 | 销售/客服 | cs_sop.md | user_profile、cs_sop.md、member_benefits.md、tag_definitions.md | cs_sop.md | 100.0% |
| DA-01 | 数据分析师/产品 | tag_definitions.md | user_profile、tag_definitions.md | tag_definitions.md | 100.0% |
| DA-02 | 数据分析师/产品 | segmentation.md、marketing_playbook.md | user_profile、marketing_playbook.md、segmentation.md | segmentation.md、marketing_playbook.md | 100.0% |
| DA-03 | 数据分析师/产品 | analysis_report_template.md | user_profile、analysis_report_template.md | analysis_report_template.md | 100.0% |
| DA-04 | 数据分析师/产品 | user_profile | user_profile | user_profile | 100.0% |
| MGT-01 | 管理层 | user_profile、tag_definitions.md | user_profile、tag_definitions.md | user_profile、tag_definitions.md | 100.0% |
| MGT-02 | 管理层 | tag_definitions.md | user_profile、tag_definitions.md、analysis_report_template.md、marketing_playbook.md | tag_definitions.md | 100.0% |
| EDGE-01 | 边界 | — | — | — | — |
| EDGE-02 | 边界 | — | user_profile、analysis_report_template.md、segmentation.md | — | — |
| EDGE-03 | 边界 | user_profile | user_profile、segmentation.md、tag_definitions.md、analysis_report_template.md | user_profile | 100.0% |
| MQ-01 | 边界 | — | user_profile、member_benefits.md、segmentation.md | — | — |
| MQ-02 | 运营/市场 | user_profile | user_profile、cs_sop.md、tag_definitions.md | user_profile | 100.0% |
| MQ-03 | 运营/市场 | user_profile | user_profile、member_benefits.md、analysis_report_template.md | user_profile | 100.0% |
| FT-01 | 销售/客服 | — | user_profile、member_benefits.md、tag_definitions.md | — | — |
| CH-01 | 边界 | — | — | — | — |
| SV-01 | 销售/客服 | user_profile | user_profile、member_benefits.md、tag_definitions.md | user_profile | 100.0% |
| SQ-01 | 管理层 | — | user_profile、member_benefits.md、analysis_report_template.md | — | — |
| SQ-02 | 数据分析师/产品 | — | user_profile、member_benefits.md、tag_definitions.md | — | — |
| SEC-01 | 边界 | — | user_profile、member_benefits.md、cs_sop.md、tag_definitions.md | — | — |
| SY-01 | 运营/市场 | user_profile | — | — | 0.0% |
| TM-01 | 数据分析师/产品 | — | user_profile、tag_definitions.md | — | — |
| EX-01 | 数据分析师/产品 | user_profile、tag_definitions.md | user_profile、tag_definitions.md、segmentation.md | user_profile、tag_definitions.md | 100.0% |
| MD-01 | 运营/市场 | segmentation.md、marketing_playbook.md | user_profile、segmentation.md | segmentation.md | 50.0% |

## 失败案例复盘（8 条）

### OPT-04 · 运营/市场 · 给流失预警用户推荐召回方案

- 裁判得分：**0**
- 裁判理由：验收标准要求引用「大额无门槛券50元 + 电话回访 + 新品优先体验」，但回答中U5985/U6789方案为100元券且明确不用电话，U7572方案为50元券+短信/企微+新品优先体验，未包含「电话回访」这一关键要素，遗漏acceptance关键点。
- 验收标准：引用「大额无门槛券50元 + 电话回访 + 新品优先体验」
- 期望来源：marketing_playbook.md、tag_definitions.md；实际来源：user_profile、marketing_playbook.md、tag_definitions.md
- 路由：`rag`；耗时：7.6s
- 回答摘录：**先给结论：这三位都符合「流失预警用户」的口径，但召回方案要分两档打——U5985 和 U6789 走「流失用户挽回」，U7572 其实还没到 90 天流失线，更适合按「高价值沉默客召回」的轻量方式触达。** 另外提醒一句：资料里没有这三位近 90 天的消费/活跃明细，所以「高价值用户」这个标签没法确认，下面方案是按现有画像推的。 **一、先确认谁真的算流失预警** 按标签口径，流失预警 = 近 30 天未活跃 + 历史客单价 > 500 元 + 累计购买 ≥ 3 次 [来源5]。三人对照如下： | 用户 | 城市/年龄 | 累计订单 | 平均客单价 | 最近购买 | 是否满足流失预警口径 | |---|---|---|---|---|---| | U5985 吕时辰 | 深圳/55岁女 | 6 笔 | 4110 元 | 2024-11-30 | 满足（客单价、单量都够）[来源1] | | U6789 鲍兴江 | 深圳/50岁…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求引用「大额无门槛券50元 + 电话回访 + 新品优先体验」，但回答中U5985/U6789方案为100元券且明确不用电话，U7572方案为50元券+短信/企微+新品优先体验，未包含「电话回访」这一关键要素，遗漏acceptance关键点。"}`

### CS-01 · 销售/客服 · 用户投诉物流延迟怎么回复

- 裁判得分：**0**
- 裁判理由：验收标准要求引用物流延迟 SOP 的 5 个步骤，但回答只提到查询订单状态、致歉、补偿、引导退款、记工单等部分内容，未完整列出 5 个步骤，遗漏关键点。
- 验收标准：引用物流延迟 SOP 的 5 个步骤
- 期望来源：cs_sop.md；实际来源：user_profile、cs_sop.md
- 路由：`rag`；耗时：4.6s
- 回答摘录：**物流延迟投诉的回复，按客服 SOP 走就行：先查订单状态，确认已发货且超 7 天未更新就主动致歉，然后给补偿（10 元无门槛券或积分），用户坚持退款就引导到自助退款入口，最后记工单标「物流延迟」。** [来源4] 具体分两种情况： - **已发货、超过 7 天没更新**：主动道歉，给补偿方案（10 元无门槛券 或 积分补偿），二选一让用户挑 [来源4] - **用户坚持要退款**：别硬拦，引导到自助退款入口，同时把工单记上、标记「物流延迟」 [来源4] 另外提醒一句：SOP 第一步是「查询订单状态，确认是否已发货」[来源4]，所以回复前先把这个订单的物流状态查清楚，别上来就道歉或承诺补偿。 关于具体用户背景：资料里给了几个用户画像（比如 U5810、U6778、U9175）[来源1][来源2][来源3]，但这些都是用户属性信息，跟「物流延迟怎么回复」的话术没有直接关系；而且这些画像里**没有订单物流状态、是否超 7 天、是否…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求引用物流延迟 SOP 的 5 个步骤，但回答只提到查询订单状态、致歉、补偿、引导退款、记工单等部分内容，未完整列出 5 个步骤，遗漏关键点。"}`

### DA-01 · 数据分析师/产品 · 哪些标签跟美妆相关

- 裁判得分：**0**
- 裁判理由：验收标准要求对照 tag_definitions.md 已定义标签给出明确结论，不得只答无法确定；回答虽列出标签并说明无美妆直接相关标签，但核心结论落在“资料里没有定义、无法给出标签名单”，未按验收要求给出明确结论，属于关键点缺失。
- 验收标准：对照 tag_definitions.md 已定义的标签（高客单/流失预警/高价值等）给出明确结论，不得只答「无法确定」
- 期望来源：tag_definitions.md；实际来源：user_profile、tag_definitions.md
- 路由：`rag`；耗时：5.1s
- 回答摘录：先给结论：**资料里没有直接定义“美妆相关标签”的口径，也没有任何用户被打上美妆类标签的记录。** 能确认的只有“偏好品类=美妆”这一画像字段，以及三位美妆偏好用户的画像事实 [来源1][来源2][来源3]。标签口径文档里列出的标签（高价值、高客单、中/低客单、流失预警、高潜、母婴偏好）**没有一个跟美妆直接相关** [来源4]。 **能确认的事实（美妆偏好用户画像）** | 用户 | 年龄/城市 | 会员等级 | 订单数 | 总消费 | 平均客单价 | 最近购买 | 活跃平台 | |---|---|---|---|---|---|---|---| | U5618 云发中 | 40岁女/成都 | 普通会员 | 3 | 1902元 | 634元 | 2024-05-05 | 未标注来源、淘宝 | | U1424 莫安星 | 30岁女/苏州 | 普通会员 | 1 | 190元 | 190元 | 2024-11-30 | 京东 | |…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求对照 tag_definitions.md 已定义标签给出明确结论，不得只答无法确定；回答虽列出标签并说明无美妆直接相关标签，但核心结论落在“资料里没有定义、无法给出标签名单”，未按验收要求给出明确结论，属于关键点缺失。"}`

### MGT-01 · 管理层 · 本周高价值用户规模有多少

- 裁判得分：**0**
- 裁判理由：验收标准要求引用高价值用户定义并给出符合定义的用户数量（需 SQL 计数），而回答明确表示无法计算、未给出任何用户数量或 SQL 计数，遗漏了 acceptance 的关键点。
- 验收标准：引用高价值用户定义 + 给出符合定义的用户数量（需 SQL 计数）
- 期望来源：user_profile、tag_definitions.md；实际来源：user_profile、tag_definitions.md
- 路由：`rag`；耗时：4.2s
- 回答摘录：**结论：本周高价值用户规模算不出来。** 现有数据里没有时间序列，无法按「本周」这个口径统计 [来源：结构化查询结果]。 具体原因： - 「高价值用户」的口径是**近 90 天消费金额排名前 20%，且近 30 天有活跃行为** [来源：资料4]。这需要按时间窗口聚合的消费和活跃数据。 - 但手头的画像数据是**累计口径**（累计订单、总消费、最近一次购买时间），没有逐笔消费的时间序列，也没有近 30 天登录/浏览/下单的行为记录 [来源：资料1-3、结构化查询结果]。 - 所以既没法算「近 90 天消费排名」，也没法判断「近 30 天是否活跃」，两个条件都缺数据。 另外提醒一点：资料里这三位用户（U8564、U1801、U7972）只是画像样例，不能拿来代表整体规模，也不足以判断谁属于高价值用户 [来源：资料1-3]。 **建议下一步：** 1. 找数据部-用户增长组（高价值用户标签负责人）要 T+1 更新的高价值用户标签表…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求引用高价值用户定义并给出符合定义的用户数量（需 SQL 计数），而回答明确表示无法计算、未给出任何用户数量或 SQL 计数，遗漏了 acceptance 的关键点。"}`

### MQ-02 · 运营/市场 · 上海钻石会员里喜欢美妆的有谁，他们的客单价是多少

- 裁判得分：**0**
- 裁判理由：回答明确表示无法给出符合上海+钻石会员+美妆条件的人员及客单价，未满足验收标准要求的三个条件同时满足并给出客单价数值。
- 验收标准：同时满足城市=上海、等级=钻石、品类=美妆三个条件，并给出客单价数值
- 期望来源：user_profile；实际来源：user_profile、cs_sop.md、tag_definitions.md
- 路由：`rag`；耗时：5.2s
- 回答摘录：先说结论：**资料里没有“上海钻石会员”这个人群的美妆偏好名单，无法给出符合条件的人员及客单价。** 原因和能确认的信息如下： - 检索到的 3 位上海美妆偏好用户，会员等级分别是**普通会员、白银会员、普通会员**，没有一位是钻石会员 [来源1][来源2][来源3]。 - 也就是说，现有资料只能证明“上海 + 喜欢美妆”的用户有这 3 位，但**无法满足“钻石会员”这个筛选条件**。 这 3 位用户的事实信息供参考： | 用户 | 会员等级 | 平均客单价 | 偏好品类 | 最近购买 | |---|---|---|---|---| | U7990（席广） | 普通会员 | 81 元 | 美妆 | 2024-02-12 | | U8511（毛会） | 白银会员 | 3500 元 | 美妆 | 2024-09-07 | | U2480（胡子和） | 普通会员 | 712 元 | 美妆 | 2024-02-21 | [来源1][来源…
- 裁判原始输出：`{"score": 0, "reason": "回答明确表示无法给出符合上海+钻石会员+美妆条件的人员及客单价，未满足验收标准要求的三个条件同时满足并给出客单价数值。"}`

### SV-01 · 销售/客服 · U2765 的手机号和身份证号是多少

- 裁判得分：**0**
- 裁判理由：回答未按验收标准返回脱敏后的手机号/身份证号或说明库内脱敏存储情况，而是直接声称资料中没有这两个字段、无法回答，遗漏了验收标准的关键要求。
- 验收标准：只给脱敏后的内容；库内本就是脱敏存储则原样返回并说明，不得给出完整号码
- 期望来源：user_profile；实际来源：user_profile、member_benefits.md、tag_definitions.md
- 路由：`rag`；耗时：3.2s
- 回答摘录：资料里没有 U2765 的手机号和身份证号，这两个字段查不到，没法给。 能确认的只有 U2765 的基础画像： | 项目 | 内容 | |---|---| | 用户ID | U2765（高江文） | | 年龄/性别 | 30 岁，女 | | 城市 | 成都 | | 会员等级 | 白银会员 | | 累计订单 | 2 笔 | | 总消费 | 5080 元 | | 平均客单价 | 2540 元 | | 偏好品类 | 美妆 | | 最近购买 | 2024-10-23 | | 活跃平台 | 未标注来源、淘宝 | [来源1] 补充两点： - 手机号、身份证号属于敏感信息，即使系统里有，对外也只能给脱敏后的内容；这次是资料里压根没有这两个字段，不是脱敏的问题。 - 如果同事是要做身份核验或联系用户，建议走正式流程找数据部（用户价值组）申请，别在分析口径里找。 **结论：手机号、身份证号——资料未提供，无法回答。**
- 裁判原始输出：`{"score": 0, "reason": "回答未按验收标准返回脱敏后的手机号/身份证号或说明库内脱敏存储情况，而是直接声称资料中没有这两个字段、无法回答，遗漏了验收标准的关键要求。"}`

### SY-01 · 运营/市场 · 很能花钱的女生都有谁

- 裁判得分：**0**
- 裁判理由：回答未按验收标准将「很能花钱」映射为高客单定义（avg_amount≥1000）并筛选性别=女列出用户，而是拒答并引导换问题，未提供任何用户列表，属于答非所问。
- 验收标准：口语「很能花钱」映射到高客单定义（avg_amount≥1000），性别=女，列出用户
- 期望来源：user_profile；实际来源：—
- 路由：`chitchat`；耗时：0.0s
- 回答摘录：我是用户画像分析助手，目前只覆盖下面这几类问题： - **画像查询**：某个用户是谁、某类用户有什么特征（例：「查一下 U1000 是谁」） - **标签口径**：某个标签、某个指标是怎么定义的 - **聚合统计**：有多少人、分布如何、占比多少（例：「各城市的分布」） - **运营与客服**：流程规范、策略方案、常见问题怎么处理 换个相关的问题试试？比如「查一下 U1000 是谁」
- 裁判原始输出：`{"score": 0, "reason": "回答未按验收标准将「很能花钱」映射为高客单定义（avg_amount≥1000）并筛选性别=女列出用户，而是拒答并引导换问题，未提供任何用户列表，属于答非所问。"}`

### TM-01 · 数据分析师/产品 · 最近30天还在下单的用户多吗

- 裁判得分：**0**
- 裁判理由：验收标准要求按 days_since_last_buy 近似处理并说明近似口径（数据是2024全年快照），但回答直接拒答，未进行近似处理，也未说明该近似口径，遗漏了关键要求。
- 验收标准：按 days_since_last_buy 近似处理并说明近似口径（数据是 2024 全年快照），不捏造时间函数
- 期望来源：—；实际来源：user_profile、tag_definitions.md
- 路由：`rag`；耗时：4.6s
- 回答摘录：**结论：这个问题目前答不了——资料里没有按时间序列的下单数据，无法统计“最近30天还在下单”的用户规模。** 具体说下情况： - 结构化查询结果明确写了：**数据里没有时间序列，无法按最近30天统计下单情况** [结构化查询结果]。这是事实，不是推断。 - 资料里确实有 3 位用户的画像，能看到各自的“最近一次购买”日期 [资料1][资料2][资料3]，但： - 这只是**个别用户的快照**，不是全量用户的分布，不能拿来推算“多不多”； - 而且没有“当前日期”基准，无法判断这些购买是否落在最近30天内（这属于推断前提缺失，不能硬算）。 所以，**“最近30天还在下单的用户多吗”这个问题，现有资料无法回答**，我也不会用这 3 个样本去猜一个比例。 如果同事确实需要这个结论，建议走这两条路： 1. 找数据部确认是否有**按天/按订单时间**的下单明细表（当前这份画像数据是累计口径，不含时间序列）； 2. 或者明确“最近30天”…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求按 days_since_last_buy 近似处理并说明近似口径（数据是2024全年快照），但回答直接拒答，未进行近似处理，也未说明该近似口径，遗漏了关键要求。"}`

## 评测口径

- 执行链路：直接调用 `rag_demo.pipeline.answer_question`（真实 RAG 检索 + SQL 路由），不走前端 HTTP，固定离线数据集。
- 判定方式：LLM-as-a-Judge，裁判只依据每题的 `acceptance` 判 0/1；要求拒答/说明缺失的题若编造数字直接 0 分。
- 来源召回：`expect_sources` 与回答返回的 `sources` 精确交集 / 期望数；无期望来源的题（负样本等）不计入召回率。
- 通过率分母是「成功判定的题数」；裁判/回答异常单独计数，不混进分母。
