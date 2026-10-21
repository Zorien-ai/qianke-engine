# 离线评测报告（LLM-as-a-Judge）

- 评测时间：2026-10-20 19:37:07
- 数据集：`demo`（固定离线评测库，不经过前端 API）
- 题目文件：`src\rag_demo\tests\eval_questions.json`
- 裁判模型：`deepseek-chat`
- 运行命令：`uv run python scripts/run_eval.py`（可加 `--limit` / `--only` 做子集试跑）
- 题目数：**33**；成功判定：33；裁判异常：0；回答异常：0
- 总耗时：216.1s（平均 5.5s/题）

## 总体通过率

| 指标 | 数值 |
|---|---|
| 通过率（通过/成功判定） | **93.9%** （31/33） |
| 判定覆盖率（成功判定/总题数） | 100.0% |
| 来源召回率（宏平均） | 97.8%（23 题有期望来源） |
| 来源召回率（微平均：命中/期望） | 96.7% |

## 分模块通过率

| 模块 | 题数 | 已判定 | 通过 | 通过率 | 来源召回率 |
|---|---|---|---|---|---|
| 数据分析师/产品 | 7 | 7 | 6 | 85.7% | 100.0% |
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
| DA-02 | 数据分析师/产品 | segmentation.md、marketing_playbook.md | user_profile、marketing_playbook.md、segmentation.md、tag_definitions.md | segmentation.md、marketing_playbook.md | 100.0% |
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

## 失败案例复盘（2 条）

### OPT-01 · 运营/市场 · 高客单、喜欢美妆的女性用户有哪些

- 裁判得分：**0**
- 裁判理由：回答虽引用了高客单定义（累计平均客单价≥1000元），但未列出符合该定义的美妆女性用户，反而列出不符合门槛的用户（U7508客单价908元等），并明确结论无人符合，未满足acceptance中“列出符合的美妆女性用户，含客单价数值”的关键要求。
- 验收标准：引用高客单定义（累计≥1000）+ 列出符合的美妆女性用户，含客单价数值
- 期望来源：user_profile、tag_definitions.md；实际来源：user_profile、tag_definitions.md、analysis_report_template.md、segmentation.md
- 路由：`rag`；耗时：24.3s
- 回答摘录：按「高客单用户」的官方口径（累计平均客单价 ≥ 1000 元）来筛，资料里符合「女性 + 偏好美妆 + 高客单」的只有 1 位： | 用户 | 姓名 | 年龄 | 城市 | 会员等级 | 累计订单 | 总消费 | 平均客单价 | 偏好品类 | 最近购买 | |---|---|---|---|---|---|---|---|---|---| | U7508 | 高有明 | 45岁 | 深圳 | 普通会员 | 2笔 | 1816元 | **908元** | 美妆 | 2024-12-01 | **结论：严格按「平均客单价 ≥ 1000 元」的定义，这三位里一个都不符合。** U7508 的 908 元是三人中最高的，但没到 1000 元门槛 [来源1][来源4]。 另外两位偏好美妆的女性用户情况： - **U5644（茅榕）**：27岁，深圳，普通会员，6笔订单、总消费3443元、平均客单价574元，最近购买2024-06-13，活…
- 裁判原始输出：`{"score": 0, "reason": "回答虽引用了高客单定义（累计平均客单价≥1000元），但未列出符合该定义的美妆女性用户，反而列出不符合门槛的用户（U7508客单价908元等），并明确结论无人符合，未满足acceptance中“列出符合的美妆女性用户，含客单价数值”的关键要求。"}`

### DA-01 · 数据分析师/产品 · 哪些标签跟美妆相关

- 裁判得分：**0**
- 裁判理由：验收标准要求对照 tag_definitions.md 已定义标签给出明确结论，不得只答无法确定；回答虽列出部分推断，但对高潜、高价值、母婴偏好等标签明确表示无法判断，且整体以资料缺失为主，未按已定义标签给出完整明确结论。
- 验收标准：对照 tag_definitions.md 已定义的标签（高客单/流失预警/高价值等）给出明确结论，不得只答「无法确定」
- 期望来源：tag_definitions.md；实际来源：user_profile、tag_definitions.md
- 路由：`rag`；耗时：5.0s
- 回答摘录：跟美妆相关的标签，资料里能直接对上的只有**「偏好品类为美妆」**这一个。三位用户都带这个标签 [来源1][来源2][来源3]。 具体是这三位： | 用户 | 年龄/城市 | 会员等级 | 偏好品类 | 累计订单 | 总消费 | 平均客单价 | 最近购买 | 活跃平台 | |---|---|---|---|---|---|---|---|---| | U5618（云发中） | 40岁女/成都 | 普通会员 | 美妆 | 3笔 | 1902元 | 634元 | 2024-05-05 | 未标注来源、淘宝 | | U1424（莫安星） | 30岁女/苏州 | 普通会员 | 美妆 | 1笔 | 190元 | 190元 | 2024-11-30 | 京东 | | U7044（杨思海） | 34岁女/苏州 | 普通会员 | 美妆 | 4笔 | 1511元 | 378元 | 2024-10-26 | 未标注来源、淘宝 | [来源1][来源2…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求对照 tag_definitions.md 已定义标签给出明确结论，不得只答无法确定；回答虽列出部分推断，但对高潜、高价值、母婴偏好等标签明确表示无法判断，且整体以资料缺失为主，未按已定义标签给出完整明确结论。"}`

## 评测口径

- 执行链路：直接调用 `rag_demo.pipeline.answer_question`（真实 RAG 检索 + SQL 路由），不走前端 HTTP，固定离线数据集。
- 判定方式：LLM-as-a-Judge，裁判只依据每题的 `acceptance` 判 0/1；要求拒答/说明缺失的题若编造数字直接 0 分。
- 来源召回：`expect_sources` 与回答返回的 `sources` 精确交集 / 期望数；无期望来源的题（负样本等）不计入召回率。
- 通过率分母是「成功判定的题数」；裁判/回答异常单独计数，不混进分母。
