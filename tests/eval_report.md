# 离线评测报告（LLM-as-a-Judge）

- 评测时间：2026-11-11 22:30:03
- 数据集：`demo`（固定离线评测库，不经过前端 API）
- 题目文件：`src\rag_demo\tests\eval_questions.json`
- 裁判模型：`deepseek-chat`
- 运行命令：`uv run python scripts/run_eval.py`（可加 `--limit` / `--only` 做子集试跑）
- 题目数：**33**；成功判定：33；裁判异常：0；回答异常：0
- 总耗时：654.5s（平均 18.5s/题）

## 总体通过率

| 指标 | 数值 |
|---|---|
| 通过率（通过/成功判定） | **90.9%** （30/33） |
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
| 销售/客服 | 7 | 7 | 7 | 100.0% | 100.0% |

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
| CS-05 | 销售/客服 | cs_sop.md | user_profile、cs_sop.md、member_benefits.md、segmentation.md、tag_definitions.md | cs_sop.md | 100.0% |
| DA-01 | 数据分析师/产品 | tag_definitions.md | user_profile、tag_definitions.md | tag_definitions.md | 100.0% |
| DA-02 | 数据分析师/产品 | segmentation.md、marketing_playbook.md | user_profile、marketing_playbook.md、segmentation.md | segmentation.md、marketing_playbook.md | 100.0% |
| DA-03 | 数据分析师/产品 | analysis_report_template.md | user_profile、analysis_report_template.md | analysis_report_template.md | 100.0% |
| DA-04 | 数据分析师/产品 | user_profile | user_profile | user_profile | 100.0% |
| MGT-01 | 管理层 | user_profile、tag_definitions.md | user_profile、tag_definitions.md、segmentation.md | user_profile、tag_definitions.md | 100.0% |
| MGT-02 | 管理层 | tag_definitions.md | user_profile、tag_definitions.md、analysis_report_template.md、segmentation.md、marketing_playbook.md | tag_definitions.md | 100.0% |
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

## 失败案例复盘（3 条）

### OPT-04 · 运营/市场 · 给流失预警用户推荐召回方案

- 裁判得分：**0**
- 裁判理由：回答未引用验收标准要求的「大额无门槛券50元 + 电话回访 + 新品优先体验」这一具体召回方案组合，仅泛泛提到大额优惠券、电话回访和回归礼包100元券，遗漏关键点。
- 验收标准：引用「大额无门槛券50元 + 电话回访 + 新品优先体验」
- 期望来源：marketing_playbook.md、tag_definitions.md；实际来源：user_profile、marketing_playbook.md、tag_definitions.md、segmentation.md
- 路由：`rag`；耗时：23.2s
- 回答摘录：先给结论：**这三位里只有吕时辰（U5985）符合「流失预警用户」的严格口径，应作为重点召回对象；危世（U5441）接近但差在购买次数，可作次级观察；郁波超（U5513）不符合，不建议按流失预警方案投入。** 依据是流失预警的定义：近30天未活跃 + 历史客单价>500元 + 累计购买次数≥3次 [来源5]。 **三人是否符合流失预警口径** | 用户 | 客单价 | 累计购买次数 | 近30天未活跃 | 是否符合 | |---|---|---|---|---| | 吕时辰 U5985 | 4110元 | 6笔 | 最近购买2024-11-30 | 符合 | | 危世 U5441 | 3363元 | 2笔 | 最近购买2024-04-27 | 差在购买次数（2<3） | | 郁波超 U5513 | 180元 | 1笔 | 最近购买2024-03-10 | 客单价和次数都不达标 | 说明：资料里没有「今天」的绝对日期，也没有 da…
- 裁判原始输出：`{"score": 0, "reason": "回答未引用验收标准要求的「大额无门槛券50元 + 电话回访 + 新品优先体验」这一具体召回方案组合，仅泛泛提到大额优惠券、电话回访和回归礼包100元券，遗漏关键点。"}`

### DA-03 · 数据分析师/产品 · 用户分析报告有哪些板块

- 裁判得分：**0**
- 裁判理由：验收标准要求列出报告模板的7个板块，但回答只列出了5个板块，遗漏了关键板块，未满足acceptance要求。
- 验收标准：列出报告模板的 7 个板块
- 期望来源：analysis_report_template.md；实际来源：user_profile、analysis_report_template.md
- 路由：`rag`；耗时：15.1s
- 回答摘录：用户分析报告按标准模板一共 **5 个板块**，从概述到结论形成一条完整链路 [来源4][来源5][来源6][来源7][来源8]： | 序号 | 板块 | 包含内容 | |---|---|---| | 一 | 报告概述 | 报告主题、分析周期、数据来源、分析人 [来源8] | | 二 | 核心结论 | 结论一、结论二、结论三（先给判断，后面板块做支撑）[来源6] | | 三 | 人群概况 | 人群规模、占比、主要特征（年龄、性别、城市、会员等级）[来源7] | | 四 | 行为分析 | 活跃度、购买频次、客单价、偏好品类 [来源4] | | 五 | 流失/转化分析 | 流失率、转化率、关键影响因素 [来源5] | 几点使用建议： - **核心结论放第二位**是有意设计——先讲结论，再用人群、行为、流失三块数据去支撑，符合管理者阅读习惯 [来源6]。 - **人群概况**里的「主要特征」四个维度（年龄、性别、城市、会员等级）是模板…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求列出报告模板的7个板块，但回答只列出了5个板块，遗漏了关键板块，未满足acceptance要求。"}`

### MD-01 · 运营/市场 · 用户分群有哪几种，各自该怎么运营

- 裁判得分：**0**
- 裁判理由：验收标准要求列出分群类型并给出对应运营策略，且引用两篇文档。回答虽引用了两篇文档并列出分群类型，但明确表示除高价值活跃客外其他群体的运营策略资料未提供，未给出各分群对应的运营策略，遗漏验收关键点。
- 验收标准：列出分群类型并给出对应运营策略，引用两篇文档，不得只答一篇
- 期望来源：segmentation.md、marketing_playbook.md；实际来源：user_profile、segmentation.md
- 路由：`rag`；耗时：15.6s
- 回答摘录：用户分群主要按**生命周期、价值、品类偏好**三个维度来划分，每个群体配不同的运营打法 [来源4][来源6]。 **三个分群维度（事实）** [来源6] | 维度 | 分层 | 判定口径 | |---|---|---| | 生命周期 | 新客 / 活跃客 / 沉默客 / 流失客 | 新客：注册≤30天；活跃客：近30天有行为；沉默客：31–90天无行为；流失客：>90天无行为 | | 价值分层 | 高价值 / 中价值 / 低价值 | 高价值：近90天消费前20%；中价值：20%–70%；低价值：后30% | | 品类偏好 | 美妆、数码、母婴、家电、零食等 | 按偏好品类打标 | **运营策略（事实）** [来源5] 资料里明确给出的策略只有「高价值活跃客」这一组： - 专属客服 - 新品优先体验 - 生日礼遇 **其他群体的运营打法，资料里没有给出**——分群策略文档只写了高价值活跃客的策略，新客、沉默客、流失客、中低价值客具…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求列出分群类型并给出对应运营策略，且引用两篇文档。回答虽引用了两篇文档并列出分群类型，但明确表示除高价值活跃客外其他群体的运营策略资料未提供，未给出各分群对应的运营策略，遗漏验收关键点。"}`

## 评测口径

- 执行链路：直接调用 `rag_demo.pipeline.answer_question`（真实 RAG 检索 + SQL 路由），不走前端 HTTP，固定离线数据集。
- 判定方式：LLM-as-a-Judge，裁判只依据每题的 `acceptance` 判 0/1；要求拒答/说明缺失的题若编造数字直接 0 分。
- 来源召回：`expect_sources` 与回答返回的 `sources` 精确交集 / 期望数；无期望来源的题（负样本等）不计入召回率。
- 通过率分母是「成功判定的题数」；裁判/回答异常单独计数，不混进分母。
