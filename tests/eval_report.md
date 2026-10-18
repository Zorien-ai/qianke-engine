# 离线评测报告（LLM-as-a-Judge）

- 评测时间：2026-10-18 20:08:50
- 数据集：`demo`（固定离线评测库，不经过前端 API）
- 题目文件：`src\rag_demo\tests\eval_questions.json`
- 裁判模型：`deepseek-chat`
- 运行命令：`uv run python scripts/run_eval.py`（可加 `--limit` / `--only` 做子集试跑）
- 题目数：**33**；成功判定：33；裁判异常：0；回答异常：0
- 总耗时：204.6s（平均 5.3s/题）

## 总体通过率

| 指标 | 数值 |
|---|---|
| 通过率（通过/成功判定） | **97.0%** （32/33） |
| 判定覆盖率（成功判定/总题数） | 100.0% |
| 来源召回率（宏平均） | 97.8%（23 题有期望来源） |
| 来源召回率（微平均：命中/期望） | 96.7% |

## 分模块通过率

| 模块 | 题数 | 已判定 | 通过 | 通过率 | 来源召回率 |
|---|---|---|---|---|---|
| 数据分析师/产品 | 7 | 7 | 7 | 100.0% | 100.0% |
| 管理层 | 3 | 3 | 3 | 100.0% | 100.0% |
| 边界 | 6 | 6 | 6 | 100.0% | 100.0% |
| 运营/市场 | 10 | 10 | 9 | 90.0% | 94.4% |
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

## 失败案例复盘（1 条）

### OPT-01 · 运营/市场 · 高客单、喜欢美妆的女性用户有哪些

- 裁判得分：**0**
- 裁判理由：验收标准要求列出符合高客单定义（累计客单价≥1000元）的美妆女性用户并含客单价数值。回答虽引用了定义，但列出的唯一用户U7508客单价为908元，明确不达标，且回答自己也承认按官方口径没有符合条件的用户。因此未列出任何符合标准的用户，反而列出了不符合标准的用户，属于答非所问/遗漏关键点。
- 验收标准：引用高客单定义（累计≥1000）+ 列出符合的美妆女性用户，含客单价数值
- 期望来源：user_profile、tag_definitions.md；实际来源：user_profile、tag_definitions.md、analysis_report_template.md、segmentation.md
- 路由：`rag`；耗时：27.6s
- 回答摘录：按「高客单用户」的官方口径（累计平均客单价 ≥ 1000 元）[来源4]，同时偏好美妆的女性用户，检索到的只有 **1 位**： | 用户 | 姓名 | 年龄 | 城市 | 会员等级 | 累计订单 | 总消费 | 平均客单价 | 偏好品类 | 最近购买 | |---|---|---|---|---|---|---|---|---|---| | U7508 | 高有明 | 45岁 | 深圳 | 普通会员 | 2笔 | 1816元 | **908元** | 美妆 | 2024-12-01 | **但这里有个关键问题要先说清楚：严格按「平均客单价 ≥ 1000 元」这条线，上面这位其实也不达标（908 元 < 1000 元）。** [来源1][来源4] 也就是说，**按官方高客单口径，资料里没有完全符合条件的女性美妆用户**。如果放宽到「客单价偏高 + 偏好美妆」来看，资料里这 3 位女性美妆用户都值得关注： | 用户 | 姓名 |…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求列出符合高客单定义（累计客单价≥1000元）的美妆女性用户并含客单价数值。回答虽引用了定义，但列出的唯一用户U7508客单价为908元，明确不达标，且回答自己也承认按官方口径没有符合条件的用户。因此未列出任何符合标准的用户，反而列出了不符合标准的用户，属于答非所问/遗漏关键点。"}`

## 评测口径

- 执行链路：直接调用 `rag_demo.pipeline.answer_question`（真实 RAG 检索 + SQL 路由），不走前端 HTTP，固定离线数据集。
- 判定方式：LLM-as-a-Judge，裁判只依据每题的 `acceptance` 判 0/1；要求拒答/说明缺失的题若编造数字直接 0 分。
- 来源召回：`expect_sources` 与回答返回的 `sources` 精确交集 / 期望数；无期望来源的题（负样本等）不计入召回率。
- 通过率分母是「成功判定的题数」；裁判/回答异常单独计数，不混进分母。
