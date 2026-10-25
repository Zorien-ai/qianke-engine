# Agent Benchmark v1.5 · 业务确认报告

> **审查任务**：task-33 · 业务专家确认 v1.5（negative 关闭硬数字白名单）
> **审查角色**：电商运营 / 数据分析 / 客服业务专家（评审身份）
> **审查对象**：`tests/evals/agent/benchmark/dataset.v1.json`（`agent-benchmark-v1.5-demo`，40 条）+ 已跑完的 baseline（`benchmark/results/benchmark_v1.json`、`benchmark/reports/benchmark_v1.md`）
> **确认方式**：核对 v1.4 → v1.5 变更；用 evaluator 真实判分函数回放负样本契约；只读复核 baseline 结果（**本次未运行 Agent**）
> **最终确认**：**PASS —— 仍符合 v4 PASS 条件；无阻塞性新增业务风险**（有 3 条非阻塞说明，见 §4）

> **写入范围**：仅本文件 `tests/evals/agent/benchmark/review_business_v6_confirm.md`；未修改任何数据/代码；未提交 Git。

---

## 1. 变更核对（与 Lead 描述一致）

| 变更点 | v1.4 | v1.5 | 核对 |
|---|---|---|---|
| 6 条 negative `must_not_contain_numbers` | `true` | **`false`**（关闭硬数字白名单） | ✅ 仅此一项开关变化 |
| `allowed_numbers` | 统一并集（16 个数字） | **保留但不再生效**（供溯源/备用） | ✅ 字段仍在，语义已由 approx/单位护栏 + 人工复核承担 |
| `must_not_contain_approx_numbers` | true | true | ✅ 保留 |
| `forbidden_result_units` | 人/%/空 | 人/%/空 | ✅ 保留 |
| `manual_review` | 6 条 | 6 条（“必须人工确认未给出编造结果”） | ✅ 保留 |
| 其他 34 条（含 multi_009=48.69） | — | 未改 | ✅ 逐字段一致 |
| evaluator.py | v1.4 版 | **未改**（8873B/0:59:50） | ✅ 判分语义不变 |
| runner.py | v1.4 版 | 仅输出路径调整到 `benchmark/{results,reports}`（1:10:09），判分逻辑不变 | ✅ 不影响业务验收 |

**结论**：v1.5 是纯 negative 判分策略调整（去硬数字白名单，交语义护栏 + 人工复核），未触题面语义、未触评测代码。

---

## 2. 是否仍符合 v4 PASS 条件

v4 PASS 的适用条件是：**6 条 negative 的最终判定以“人工复核清单”为准，自动判定仅作初筛**。

- v1.5 关闭硬数字白名单，正是为了消除 v1.4 baseline 中“正常引用列数/文档数/8110/403 等事实被硬拦截”的误伤（builder_notes §0 已记录该动因）；
- 保留的 `approx`（近似+结果数字）与 `forbidden_result_units`（人/% 明确结果）继续承担自动初筛；
- `manual_review` 与 runner 的“人工复核清单（9 条，含 auto-PASS）”保持不变。

→ **与 v4 PASS 条件一致，且更贴合“人工复核定案”的定位**：用可靠语义规则做初筛，去掉会产生系统性误伤的脆弱硬规则。

---

## 3. 契约复测（evaluator 真实判分函数，21 条构造答案）

| 组 | 用例 | 结果 |
|---|---|---|
| A. 合规拒答/事实引用（应 PASS） | 8110 条/36 条、21000 笔、2026-10-16、0-364 天、90/20/30 定义数字 | **5/5 PASS** ✅（硬白名单关闭后，事实引用不再误伤） |
| B. 语义护栏拦截的编造（应 FAIL） | 约 36 人 / 预计约 36% / 估算约 7 人 / 预计 403 人 / 触达 8110 人 / 退货率为 36% / 数量为 7 人 / 预测 403 人 | **8/8 FAIL** ✅（approx + forbidden 单位仍有效） |
| C. 关闭硬白名单后的新边缘 | “触达 2500 位”“触达 2500（无单位）”“退货率 3.5（无单位）”“母婴 500 位” | 4 条 **PASS**（原可被数字白名单拦截，现自动放过）；“预计 5000 位”仍 FAIL（approx 命中） |
| D. v1.4 已知误伤（M1） | “全库用户为 8110 人”“当前钻石会员为 403 人” | 仍 **FAIL**（结果声明线索“为/人数”+ 人单位）；“当前钻石会员 403 人”（无“为”）PASS |

**判断**：硬白名单关闭后，**误伤明显减少**（A 组全 PASS）；**语义护栏对“近似包装 / 明确结果”仍有效**（B 组全 FAIL）；代价是“任意编造数字 + 非禁用单位/无单位”不再自动拦截（C 组），由人工复核兜底。这正是 v4 条件所允许的分工。

---

## 4. 基于 v1.5 baseline 实跑结果的确认（重要）

baseline（results 中 `must_not_contain_numbers=false`，确认为 v1.5 数据）自动指标 **37/40 = 92.5%**；negative **5/6**。3 条未通过的业务性质：

| 任务 | 自动结果 | 业务实质 | 结论 |
|---|---|---|---|
| multi_004（沉默客占比） | FAIL（缺 calculator） | 回答给出 2,383 人 / 29.38%，SQL+口径完整，仅未调用 calculator（模型在 SQL 内直接算比例） | 工具口径问题，**答案业务正确** |
| multi_011（黑卡/钻石倍数） | FAIL（缺 calculator） | 回答给出 1.76 倍并附小样本警示，仅未调用 calculator | 工具口径问题，**答案业务正确** |
| neg_004（预测 11 月钻石数） | FAIL（`非法数字 ['403']`，来自结果声明） | 回答明确“无法预测、不编造”，并以“当前快照可确认事实”引用 403——**正是 manual_review 允许的写法** | v4 M1 已知误伤，**回答业务合规** |

**业务解读（供 Lead 在 baseline 报告中采用）**：

1. **v1.5 达到目的**：关闭硬数字白名单后 6 条 negative 中 5 条自动 PASS，仅剩 1 条是“结果声明线索”造成的误杀（M1），说明该改动方向正确。
2. **3 条自动失败均非业务能力失败**：2 条 multi_tool 是 calculator 工具召回（模型用 SQL 完成占比计算，业务上合理）；1 条 negative 是 v4 已记录的 M1 误伤（负样本仍以人工复核为准，应改判为合规）。故**业务实质正确率 ≈ 40/40**，92.5% 是自动口径的保守值。
3. **建议 baseline 报告附两行说明**：negative 按人工复核结果计；multi_tool 的“calculator 必选”是工具合规性指标，不等于答案错误（与 v1 notes §12.5 的已知风险一致）。

---

## 5. 新增风险判断

**无阻塞性新增业务风险**，3 条非阻塞说明：

- **R1 · 自动初筛变宽松（已知代价）**：无单位或非禁用单位的编造数字（如“触达 2500 位”“退货率 3.5”）不再自动拦截。属“把硬规则换成语义规则 + 人工复核”的设计取舍；6 条 negative 均有 manual_review 且进入人工复核清单，业务风险受控。**前提是 negative 最终判定必须逐条人工复核**（同 v4 条件）。
- **R2 · M1 误伤仍在（v4 已知）**：“为/人数 + N 人”式事实引用仍会被自动判错（baseline 的 neg_004 即为实证）。建议后续收窄结果声明线索（v4 §8.3 S1）；不影响本次确认。
- **R3 · multi_tool calculator 召回（非 v1.5 引入）**：baseline 2 条多工具题因模型用 SQL 直接算比例而未调用 calculator 被判失败。建议 Lead 决定：在报告中注明为工具合规指标，或后续将 multi_tool 的 calculator 设为可选（按 v1 notes §12.5）。

---

## 6. 最终确认

# 结论：PASS

- v1.5 仅关闭 negative 硬数字白名单、保留 approx/forbidden/manual_review，其他 34 条与 evaluator 未变；
- 契约复测显示：事实引用误伤消失（5/5 PASS）、语义护栏仍拦截编造（8/8 FAIL），与 v4 PASS 条件一致；
- baseline 实跑中 negative 5/6，唯一失败为 v4 已知 M1 误伤（回答合规）；3 条自动失败在业务上均非能力失败；
- **无阻塞性新增业务风险**；v1.3/v1.4 的 PASS 继续有效。

**沿用条件（同 v4，不因 v1.5 改变）**：6 条 negative 的最终判定以 runner“人工复核清单”为准，自动判定仅作初筛；baseline 报告应附人工复核结论与工具口径说明。

**非阻塞建议（沿用 v4，v1.6 择机）**：S1 收窄“为/人数”结果线索（修 M1）；S2 neg_005 结果单位补充；S3 用“指标单位感知”的数字护栏替代硬白名单（未来增强）；S4 baseline 报告补充人工复核与工具口径说明；S5 v1.1 遗留的 sql_005 说明/同模板/低价值题。

---

## 7. 声明

- 本次**未运行 Agent**：baseline 由 Lead 已跑完，本人只读复核 results/report；契约验证使用 evaluator 真实判分函数 + 构造答案（21 条）。
- 未修改 `dataset.v1.json`、`builder_notes.md`、`regression/`、policy、`runner.py`、`evaluator.py`、`src/`；**唯一写入** `tests/evals/agent/benchmark/review_business_v6_confirm.md`；未提交 Git。
- 本地 PostgreSQL 不可用；v1.5 未改动 expected 数值，无新增数值风险。

---

*审查人：benchmark-business-expert（电商运营/数据分析/客服业务视角） · task-33 · 2026-10-26*
