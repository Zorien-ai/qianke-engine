# 离线评测报告（LLM-as-a-Judge）

- 评测时间：2026-10-18 18:33:46
- 数据集：`demo`（固定离线评测库，不经过前端 API）
- 题目文件：`src\rag_demo\tests\eval_questions.json`
- 裁判模型：`deepseek-chat`
- 运行命令：`uv run python run_eval.py`（可加 `--limit` / `--only` 做子集试跑）
- 题目数：**33**；成功判定：33；裁判异常：0；回答异常：0
- 总耗时：213.9s（平均 5.4s/题）

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
| 管理层 | 3 | 3 | 2 | 66.7% | 100.0% |
| 边界 | 6 | 6 | 6 | 100.0% | 100.0% |
| 运营/市场 | 10 | 10 | 9 | 90.0% | 94.4% |
| 销售/客服 | 7 | 7 | 6 | 85.7% | 100.0% |

## 来源召回明细

| 题号 | 模块 | 期望来源 | 实际来源 | 命中 | 召回率 |
|---|---|---|---|---|---|
| OPT-01 | 运营/市场 | user_profile、tag_definitions.md | user_profile、tag_definitions.md、analysis_report_template.md、segmentation.md | user_profile、tag_definitions.md | 100.0% |
| OPT-02 | 运营/市场 | user_profile | user_profile、member_benefits.md、analysis_report_template.md、tag_definitions.md | user_profile | 100.0% |
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
| MQ-02 | 运营/市场 | user_profile | user_profile、cs_sop.md、tag_definitions.md | user_profile | 100.0% |
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

### CS-01 · 销售/客服 · 用户投诉物流延迟怎么回复

- 裁判得分：**0**
- 裁判理由：验收标准要求引用物流延迟SOP的5个步骤，但回答只列出了4个步骤，遗漏了关键步骤，未满足验收要求。
- 验收标准：引用物流延迟 SOP 的 5 个步骤
- 期望来源：cs_sop.md；实际来源：user_profile、cs_sop.md、member_benefits.md
- 路由：`rag`；耗时：3.9s
- 回答摘录：按SOP处理，物流延迟投诉的回复分四步走： **1. 先查订单状态，确认是否已发货** [来源4] **2. 若已发货且超过7天未更新，主动致歉** [来源4] **3. 给补偿方案（二选一）** [来源4] - 10元无门槛券 - 或积分补偿 **4. 用户坚持退款就引导到自助退款入口；最后记录工单，标记"物流延迟"** [来源4] --- **关于具体用户背景**：资料里检索到的三位投诉相关用户（U5810、U6778、U9175）都是普通会员 [来源1][来源2][来源3]，普通会员权益只有基础售后服务、7天无理由退换、1倍积分 [来源5]，没有专属客服或运费特权可额外承诺。所以回复时按SOP标准补偿走即可，不用套用高等级权益。 **推断**：这三位用户的"活跃平台"字段均标注"未标注来源" [来源1][来源2][来源3]，属于数据未提供，无法判断他们从哪个渠道投诉，回复渠道需另行确认——这块资料里没有，建议直接问用户或查…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求引用物流延迟SOP的5个步骤，但回答只列出了4个步骤，遗漏了关键步骤，未满足验收要求。"}`

### DA-01 · 数据分析师/产品 · 哪些标签跟美妆相关

- 裁判得分：**0**
- 裁判理由：验收标准要求对照已定义标签给出明确结论，不得只答无法确定；回答虽列出通用标签口径，但对美妆相关标签的核心问题仅给出「没有专门的美妆标签体系」「无法给出完整的美妆相关标签列表」，未按已定义标签给出明确结论，且大量输出用户明细与推断，属于未满足关键点。
- 验收标准：对照 tag_definitions.md 已定义的标签（高客单/流失预警/高价值等）给出明确结论，不得只答「无法确定」
- 期望来源：tag_definitions.md；实际来源：user_profile、tag_definitions.md
- 路由：`rag`；耗时：5.2s
- 回答摘录：跟美妆相关的标签，资料里能直接对上的只有**「偏好品类为美妆」**这一个画像字段，没有专门的美妆标签体系。具体涉及的用户和情况如下： | 用户 | 年龄/城市 | 会员等级 | 偏好品类 | 累计订单 | 总消费 | 平均客单价 | 最近购买 | 活跃平台 | |---|---|---|---|---|---|---|---|---| | U5618（云发中） | 40岁女/成都 | 普通会员 | 美妆 | 3笔 | 1902元 | 634元 | 2024-05-05 | 未标注来源、淘宝 | | U1424（莫安星） | 30岁女/苏州 | 普通会员 | 美妆 | 1笔 | 190元 | 190元 | 2024-11-30 | 京东 | | U7044（杨思海） | 34岁女/苏州 | 普通会员 | 美妆 | 4笔 | 1511元 | 378元 | 2024-10-26 | 未标注来源、淘宝 | [来源1][来源2][来源3]…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求对照已定义标签给出明确结论，不得只答无法确定；回答虽列出通用标签口径，但对美妆相关标签的核心问题仅给出「没有专门的美妆标签体系」「无法给出完整的美妆相关标签列表」，未按已定义标签给出明确结论，且大量输出用户明细与推断，属于未满足关键点。"}`

### MGT-01 · 管理层 · 本周高价值用户规模有多少

- 裁判得分：**0**
- 裁判理由：回答给出了具体数字2028，但未提供SQL计数过程，无法验证该数字是否符合高价值用户定义；acceptance明确要求给出符合定义的用户数量需SQL计数，回答仅声称来自结构化查询结果，缺少SQL计数依据，属于未满足关键点。
- 验收标准：引用高价值用户定义 + 给出符合定义的用户数量（需 SQL 计数）
- 期望来源：user_profile、tag_definitions.md；实际来源：user_profile、tag_definitions.md、segmentation.md
- 路由：`rag`；耗时：4.2s
- 回答摘录：本周高价值用户规模是 **2028**。[来源：结构化查询结果] 需要说明两点： - 这个数字来自结构化查询结果，是**事实**。 - 但资料里没有给出这 2028 人的明细画像，也没有说明统计截止到哪一天。高价值用户的定义是「近 90 天消费金额排名前 20%，且近 30 天有活跃行为」，更新频率 T+1 [来源4]，所以这个数应该是按该口径跑出来的本周快照。 另外提醒一下：资料里那几位用户（U8564、U5861、U3740）只是检索时带出来的个体画像，**不能**用来推算整体规模，也不代表他们都属于高价值用户——比如 U8564 最近一次购买在 2024-03-31，按定义大概率不满足「近 30 天活跃」[来源1][来源4]。
- 裁判原始输出：`{"score": 0, "reason": "回答给出了具体数字2028，但未提供SQL计数过程，无法验证该数字是否符合高价值用户定义；acceptance明确要求给出符合定义的用户数量需SQL计数，回答仅声称来自结构化查询结果，缺少SQL计数依据，属于未满足关键点。"}`

### MQ-02 · 运营/市场 · 上海钻石会员里喜欢美妆的有谁，他们的客单价是多少

- 裁判得分：**0**
- 裁判理由：验收标准要求同时满足城市=上海、等级=钻石、品类=美妆三个条件并给出客单价数值。回答明确说明没有命中钻石会员，给出的3位用户均非钻石会员，未满足等级=钻石这一关键条件，也未给出符合条件的客单价数值，因此不合格。
- 验收标准：同时满足城市=上海、等级=钻石、品类=美妆三个条件，并给出客单价数值
- 期望来源：user_profile；实际来源：user_profile、cs_sop.md、tag_definitions.md
- 路由：`rag`；耗时：5.6s
- 回答摘录：先给结论：**资料里没有“上海钻石会员”这个人群的匹配结果。** 检索到的 3 位上海美妆偏好用户，会员等级分别是普通、白银、普通，没有一位是钻石会员 [来源1][来源2][来源3]。 具体名单和客单价如下： | 用户 | 姓名 | 年龄/性别 | 会员等级 | 偏好品类 | 累计订单 | 总消费 | 平均客单价 | 最近购买 | |---|---|---|---|---|---|---|---|---| | U7990 | 席广 | 63岁女 | 普通会员 | 美妆 | 1笔 | 81元 | 81元 | 2024-02-12 | | U8511 | 毛会 | 57岁女 | 白银会员 | 美妆 | 2笔 | 7000元 | 3500元 | 2024-09-07 | | U2480 | 胡子和 | 44岁女 | 普通会员 | 美妆 | 2笔 | 1424元 | 712元 | 2024-02-21 | [来源1][来源2][来源3]…
- 裁判原始输出：`{"score": 0, "reason": "验收标准要求同时满足城市=上海、等级=钻石、品类=美妆三个条件并给出客单价数值。回答明确说明没有命中钻石会员，给出的3位用户均非钻石会员，未满足等级=钻石这一关键条件，也未给出符合条件的客单价数值，因此不合格。"}`

## 评测口径

- 执行链路：直接调用 `rag_demo.pipeline.answer_question`（真实 RAG 检索 + SQL 路由），不走前端 HTTP，固定离线数据集。
- 判定方式：LLM-as-a-Judge，裁判只依据每题的 `acceptance` 判 0/1；要求拒答/说明缺失的题若编造数字直接 0 分。
- 来源召回：`expect_sources` 与回答返回的 `sources` 精确交集 / 期望数；无期望来源的题（负样本等）不计入召回率。
- 通过率分母是「成功判定的题数」；裁判/回答异常单独计数，不混进分母。
