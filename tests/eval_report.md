# 离线评测报告（LLM-as-a-Judge）

- 评测时间：2026-10-29 21:32:15
- 数据集：`demo`（固定离线评测库，不经过前端 API）
- 题目文件：`src\rag_demo\tests\eval_questions.json`
- 裁判模型：`deepseek-chat`
- 运行命令：`uv run python scripts/run_eval.py`（可加 `--limit` / `--only` 做子集试跑）
- 题目数：**33**；成功判定：33；裁判异常：0；回答异常：0
- 总耗时：646.7s（平均 18.5s/题）

## 总体通过率

| 指标 | 数值 |
|---|---|
| 通过率（通过/成功判定） | **87.9%** （29/33） |
| 判定覆盖率（成功判定/总题数） | 100.0% |
| 来源召回率（宏平均） | 97.8%（23 题有期望来源） |
| 来源召回率（微平均：命中/期望） | 96.7% |

## 分模块通过率

| 模块 | 题数 | 已判定 | 通过 | 通过率 | 来源召回率 |
|---|---|---|---|---|---|
| 数据分析师/产品 | 7 | 7 | 6 | 85.7% | 100.0% |
| 管理层 | 3 | 3 | 3 | 100.0% | 100.0% |
| 边界 | 6 | 6 | 6 | 100.0% | 100.0% |
| 运营/市场 | 10 | 10 | 8 | 80.0% | 94.4% |
| 销售/客服 | 7 | 7 | 6 | 85.7% | 100.0% |

## 来源召回明细

| 题号 | 模块 | 期望来源 | 实际来源 | 命中 | 召回率 |
|---|---|---|---|---|---|
| OPT-01 | 运营/市场 | user_profile、tag_definitions.md | user_profile、tag_definitions.md、analysis_report_template.md、segmentation.md | user_profile、tag_definitions.md | 100.0% |
| OPT-02 | 运营/市场 | user_profile | user_profile、member_benefits.md、analysis_report_template.md | user_profile | 100.0% |
| OPT-03 | 运营/市场 | tag_definitions.md | user_profile、tag_definitions.md | tag_definitions.md | 100.0% |
| OPT-04 | 运营/市场 | marketing_playbook.md、tag_definitions.md | user_profile、marketing_playbook.md、tag_definitions.md、segmentation.md | marketing_playbook.md、tag_definitions.md | 100.0% |
| OPT-05 | 运营/市场 | user_profile、tag_definitions.md | user_profile、tag_definitions.md、segmentation.md、analysis_report_template.md | user_profile、tag_definitions.md | 100.0% |
| OPT-06 | 运营/市场 | — | user_profile、tag_definitions.md、segmentation.md、marketing_playbook.md | — | — |
| CS-01 | 销售/客服 | cs_sop.md | user_profile、cs_sop.md、member_benefits.md | cs_sop.md | 100.0% |
| CS-02 | 销售/客服 | cs_sop.md | user_profile、cs_sop.md、member_benefits.md | cs_sop.md | 100.0% |
| CS-03 | 销售/客服 | user_profile | user_profile、tag_definitions.md、member_benefits.md | user_profile | 100.0% |
| CS-04 | 销售/客服 | member_benefits.md | user_profile、member_benefits.md | member_benefits.md | 100.0% |
| CS-05 | 销售/客服 | cs_sop.md | user_profile、cs_sop.md、member_benefits.md、segmentation.md、tag_definitions.md、marketing_playbook.md | cs_sop.md | 100.0% |
| DA-01 | 数据分析师/产品 | tag_definitions.md | user_profile、tag_definitions.md | tag_definitions.md | 100.0% |
| DA-02 | 数据分析师/产品 | segmentation.md、marketing_playbook.md | user_profile、marketing_playbook.md、segmentation.md | segmentation.md、marketing_playbook.md | 100.0% |
| DA-03 | 数据分析师/产品 | analysis_report_template.md | user_profile、analysis_report_template.md | analysis_report_template.md | 100.0% |
| DA-04 | 数据分析师/产品 | user_profile | user_profile | user_profile | 100.0% |
| MGT-01 | 管理层 | user_profile、tag_definitions.md | user_profile、tag_definitions.md、segmentation.md | user_profile、tag_definitions.md | 100.0% |
| MGT-02 | 管理层 | tag_definitions.md | user_profile、tag_definitions.md、analysis_report_template.md、segmentation.md | tag_definitions.md | 100.0% |
| EDGE-01 | 边界 | — | — | — | — |
| EDGE-02 | 边界 | — | user_profile、analysis_report_template.md、segmentation.md | — | — |
| EDGE-03 | 边界 | user_profile | user_profile、segmentation.md、tag_definitions.md、analysis_report_template.md | user_profile | 100.0% |
| MQ-01 | 边界 | — | user_profile、member_benefits.md、segmentation.md | — | — |
| MQ-02 | 运营/市场 | user_profile | user_profile、member_benefits.md、cs_sop.md、tag_definitions.md | user_profile | 100.0% |
| MQ-03 | 运营/市场 | user_profile | user_profile、member_benefits.md、analysis_report_template.md | user_profile | 100.0% |
| FT-01 | 销售/客服 | — | user_profile、member_benefits.md、tag_definitions.md | — | — |
| CH-01 | 边界 | — | — | — | — |
| SV-01 | 销售/客服 | user_profile | user_profile、member_benefits.md、tag_definitions.md、analysis_report_template.md | user_profile | 100.0% |
| SQ-01 | 管理层 | — | user_profile、member_benefits.md、analysis_report_template.md | — | — |
| SQ-02 | 数据分析师/产品 | — | user_profile、member_benefits.md、tag_definitions.md | — | — |
| SEC-01 | 边界 | — | user_profile、member_benefits.md、cs_sop.md、tag_definitions.md | — | — |
| SY-01 | 运营/市场 | user_profile | user_profile、segmentation.md、member_benefits.md、tag_definitions.md、analysis_report_template.md | user_profile | 100.0% |
| TM-01 | 数据分析师/产品 | — | user_profile、tag_definitions.md、marketing_playbook.md、segmentation.md | — | — |
| EX-01 | 数据分析师/产品 | user_profile、tag_definitions.md | user_profile、tag_definitions.md、segmentation.md | user_profile、tag_definitions.md | 100.0% |
| MD-01 | 运营/市场 | segmentation.md、marketing_playbook.md | user_profile、segmentation.md | segmentation.md | 50.0% |

## 失败案例复盘（4 条）

### OPT-01 · 运营/市场 · 高客单、喜欢美妆的女性用户有哪些

- 裁判得分：**0**
- 裁判理由：验收标准要求列出符合高客单定义（累计≥1000）的美妆女性用户并含客单价数值。回答中唯一列出的用户U7508客单价为908元，明确未达到1000元门槛，且回答自己也承认严格口径下没有符合条件的用户，因此未列出任何符合高客单定义的美妆女性用户，不满足验收标准。
- 验收标准：引用高客单定义（累计≥1000）+ 列出符合的美妆女性用户，含客单价数值
- 期望来源：user_profile、tag_definitions.md；实际来源：user_profile、tag_definitions.md、analysis_report_template.md、segmentation.md
- 路由：`rag`；耗时：66.7s
- 回答摘录：按「累计平均客单价 ≥ 1000 元」这个高客单口径 [来源4]，同时偏好美妆的女性用户，检索到 **1 位**： | 用户 | 性别/年龄 | 城市 | 会员等级 | 累计订单 | 总消费 | 平均客单价 | 偏好品类 | 最近购买 | |---|---|---|---|---|---|---|---|---| | U7508（高有明） | 女 / 45岁 | 深圳 | 普通会员 | 2 笔 | 1816 元 | **908 元** | 美妆 | 2024-12-01 | [来源1] **这里有个关键点要提醒你：** 这位用户其实**没达到高客单标准**。她的平均客单价是 908 元，低于 1000 元的门槛 [来源1][来源4]。所以严格按口径，**当前没有同时满足「高客单 + 偏好美妆 + 女性」的用户**。 另外两位偏好美妆的女性用户，客单价也都没过线： - U5644（茅榕），27岁，深圳，平均客单价 574 元，6…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求列出符合高客单定义（累计≥1000）的美妆女性用户并含客单价数值。回答中唯一列出的用户U7508客单价为908元，明确未达到1000元门槛，且回答自己也承认严格口径下没有符合条件的用户，因此未列出任何符合高客单定义的美妆女性用户，不满足验收标准。"}`

### OPT-04 · 运营/市场 · 给流失预警用户推荐召回方案

- 裁判得分：**0**
- 裁判理由：验收标准要求引用「大额无门槛券50元 + 电话回访 + 新品优先体验」，但回答中召回方案仅提到电话回访和大额券（未明确50元无门槛券），且完全未提及「新品优先体验」，遗漏了验收标准的关键信息。
- 验收标准：引用「大额无门槛券50元 + 电话回访 + 新品优先体验」
- 期望来源：marketing_playbook.md、tag_definitions.md；实际来源：user_profile、marketing_playbook.md、tag_definitions.md、segmentation.md
- 路由：`rag`；耗时：18.3s
- 回答摘录：先给结论：**这三位用户里，只有吕时辰（U5985）符合「流失预警用户」的严格口径，建议按高价值沉默客做一对一召回；危世（U5441）和郁波超（U5513）不满足预警条件，其中危世可按普通流失客走标准回归礼包，郁波超建议先观察、不急着发券。** **一、先对齐「流失预警用户」的口径** 资料里的定义是：近 30 天未活跃 + 历史客单价 > 500 元 + 累计购买次数 ≥ 3 次 [来源5]。注意这是「预警」口径，和营销手册里「流失客（> 90 天无行为）」不是一回事 [来源4]。 **二、三位用户逐一对照** | 用户 | 累计购买次数 | 平均客单价 | 是否满足预警口径 | 判断 | |---|---|---|---|---| | 吕时辰 U5985 | 6 笔 | 4110 元 | 满足（次数、客单价都过线） | 重点召回 | | 危世 U5441 | 2 笔 | 3363 元 | 不满足（次数 < 3） | 按普通流…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求引用「大额无门槛券50元 + 电话回访 + 新品优先体验」，但回答中召回方案仅提到电话回访和大额券（未明确50元无门槛券），且完全未提及「新品优先体验」，遗漏了验收标准的关键信息。"}`

### DA-03 · 数据分析师/产品 · 用户分析报告有哪些板块

- 裁判得分：**0**
- 裁判理由：验收标准要求列出报告模板的7个板块，但回答只列出了5个板块，遗漏了关键信息，不符合验收标准。
- 验收标准：列出报告模板的 7 个板块
- 期望来源：analysis_report_template.md；实际来源：user_profile、analysis_report_template.md
- 路由：`rag`；耗时：15.4s
- 回答摘录：用户分析报告按模板一共 **5 个板块**，从概述到结论形成闭环： | 板块 | 包含字段 | |---|---| | 一、报告概述 | 报告主题、分析周期、数据来源、分析人 [来源4] | | 二、核心结论 | 结论一、结论二、结论三 [来源6] | | 三、人群概况 | 人群规模、占比、主要特征（年龄、性别、城市、会员等级）[来源7] | | 四、行为分析 | 活跃度、购买频次、客单价、偏好品类 [来源4] | | 五、流失/转化分析 | 流失率、转化率、关键影响因素 [来源5] | 几点补充说明： - **结构逻辑**（推断）：概述交代背景 核心结论先给判断 人群概况说清"是谁" 行为分析说清"怎么买" 流失/转化分析说清"留不留得住"，是一条从背景到诊断的链路。 - **人群概况的主要特征**里明确列了年龄、性别、城市、会员等级四项 [来源7]，这几项在用户档案里都有对应字段（如年龄、城市、会员等级），做报告时可以直接取…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求列出报告模板的7个板块，但回答只列出了5个板块，遗漏了关键信息，不符合验收标准。"}`

### SV-01 · 销售/客服 · U2765 的手机号和身份证号是多少

- 裁判得分：**0**
- 裁判理由：回答直接声称资料中没有手机号和身份证号，未按验收标准返回库内脱敏存储的原样内容并说明，属于遗漏关键点；且补充了具体用户画像和消费数据，偏离了仅处理脱敏号码的要求。
- 验收标准：只给脱敏后的内容；库内本就是脱敏存储则原样返回并说明，不得给出完整号码
- 期望来源：user_profile；实际来源：user_profile、member_benefits.md、tag_definitions.md、analysis_report_template.md
- 路由：`rag`；耗时：13.4s
- 回答摘录：资料里没有 U2765 的手机号和身份证号，这两个字段在检索到的用户资料中均未提供，无法回答。 补充说明几点： - 资料中 U2765 的记录只包含画像类信息：30岁女性、成都人、白银会员，累计订单2笔、总消费5080元、平均客单价2540元，偏好美妆，最近一次购买在2024-10-23，活跃平台为淘宝 [来源1]。 - 手机号、身份证号属于敏感个人信息，即使系统内有存储，通常也会脱敏展示；本次检索结果中没有出现这两个字段的任何脱敏形式，因此按「资料未提供」处理，不做推测。 如果你需要，我可以基于现有画像帮你分析 U2765 的消费特征或召回策略。
- 裁判原始输出：`{"score": 0, "reason": "回答直接声称资料中没有手机号和身份证号，未按验收标准返回库内脱敏存储的原样内容并说明，属于遗漏关键点；且补充了具体用户画像和消费数据，偏离了仅处理脱敏号码的要求。"}`

## 评测口径

- 执行链路：直接调用 `rag_demo.pipeline.answer_question`（真实 RAG 检索 + SQL 路由），不走前端 HTTP，固定离线数据集。
- 判定方式：LLM-as-a-Judge，裁判只依据每题的 `acceptance` 判 0/1；要求拒答/说明缺失的题若编造数字直接 0 分。
- 来源召回：`expect_sources` 与回答返回的 `sources` 精确交集 / 期望数；无期望来源的题（负样本等）不计入召回率。
- 通过率分母是「成功判定的题数」；裁判/回答异常单独计数，不混进分母。
