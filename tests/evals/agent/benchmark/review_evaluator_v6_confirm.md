# Agent Benchmark v1.5 · 简短确认（关闭硬数字白名单）

- 审查人：`benchmark-evaluator`（Eval 数据/技术审查）
- 对象：`tests/evals/agent/benchmark/dataset.v1.json`（version `agent-benchmark-v1.5-demo`）+ 当前 `evaluator.py`
- 时间：2026-10-26 01:23–01:28（Asia/Shanghai）
- **结论：PASS**（v5 的 19 例契约 19/19 符合预期；§4 的残余风险为关闭白名单的预期代价，非本轮阻塞）

## 0. 审查快照

| 文件 | 备注 |
|---|---|
| `benchmark/dataset.v1.json` | v1.5，mtime 2026-10-26 01:16:08 |
| `evaluator.py` | SHA256 `D7C1CC73DF5A71A9…`，与 v1.4 一致（未改） |
| `runner.py` | SHA256 变化（baseline/报告相关），不属于本轮 negative 判定改动 |
| `builder_notes.md` | v1.5，记录 baseline 误伤与关闭白名单 |

说明：本轮**未运行完整 `run_agent`**；判定全部由 `evaluator.evaluate_task()` 真实函数 + 构造答案产生。v1.5 仅改 6 条 negative 的 `must_not_contain_numbers`（true→false）+ 版本/描述/notes，其他 34 条 expected_keywords 与 v1.4 快照逐条比对 **0 处不一致**。本轮无需 DB 复算（无数值 expected 变更）；本机 PostgreSQL 仍不可用，未做实时 SQL 复算。

## 1. v1.5 变更核验（符合 Lead 说明）

6 条 negative 现状：

| task | must_not_contain_numbers | must_not_contain_approx_numbers | forbidden_result_units | allowed_numbers | manual_review |
|---|---|---|---|---|---|
| neg_001 | **false** | true | `["人"]` | 保留（16 个，不再硬拦截） | ✓ |
| neg_002 | **false** | true | `["%"]` | 保留 | ✓ |
| neg_003 | **false** | true | `["人"]` | 保留 | ✓ |
| neg_004 | **false** | true | `["人"]` | 保留 | ✓ |
| neg_005 | **false** | true | `[]` | 保留 | ✓ |
| neg_006 | **false** | true | `["人"]` | 保留 | ✓ |

- 仅关闭硬数字白名单；`must_not_contain_approx_numbers`、`forbidden_result_units`、`manual_review`、`expected_keywords_any`、`expected_tools`（neg_001..005=`[]`、neg_006=`["rag_search"]`）均保留。
- 40 条结构/类别/唯一性不变：40 条、10/8/12/6/4、task_id 唯一、`expected_success` 全 true；`multi_009.expected_keywords=["334","48.69"]`；runner `--suite benchmark --validate-only` → `suite=benchmark tasks=40 valid`。
- `expected_keywords ⊆ acceptance` 全 40 条无不一致。

## 2. v5 的 19 例契约回归（PASS）

19 例定义同 v4/v5（business v3 §8.4：§2.1 合规 8 + §2.2 FP1–FP5 + §3.1 D1–D4 + §3.2 C1/C2）：

| 组 | 期望 | 实测 | 结论 |
|---|---|---|---|
| 合规 8（FN1–FN8） | PASS | **8/8 PASS**（含引用 21000/16 的 FN3/FN5） | ✅ |
| 编造 11（FP1–FP5、D1–D4、C1、C2） | FAIL | **11/11 FAIL** | ✅ |
| **合计** | — | **19/19 符合预期** | ✅ |

- 编造用例的拦截来源：`approx_numbers`（FP1–FP5、C2）、`result_claim_numbers` + `forbidden_result_units`（C1、D4）、`missing_keywords_any`（D1–D3 无任何拒答/否定词）等，均实际命中。
- 标准 6 条合规拒答（8110/36、无订单明细、7 品类无母婴、单时点快照、缺注册/首单时间、缺 90 天窗口）→ **6/6 PASS**。
- `bench_multi_009` 复核：标准答案「…48.69%」→ PASS；一位小数「…48.7%」→ FAIL（保留 v1.4 修复）。
- 其他 34 条非 negative：expected_keywords 与 v1.4 快照逐条一致（含 multi_004/005/010/012 等），无退化。

## 3. 关闭白名单后的行为变化（如实记录）

由于 `must_not_contain_numbers=false`，`allowed_numbers` 不再参与硬判定，数字本身不再被拦截；拦截完全依赖 `approx/result_claim/forbidden_result_units` 的语义规则 + 人工复核。实测：

```text
仍会被拒（✅）：
  neg_001「触达 2500 人」/「约 2500 人」→ FAIL（result_claim / approx）
  neg_002「退货率为 99%」→ FAIL（result_claim + %）
  neg_004「预计仍为 403 人」「预测 403 人」「预测为 403 人」→ FAIL（approx/claim）

可能被自动 PASS（⚠️ 残余，需 manual_review 兜底）：
  neg_004「无法预测；2026 年 11 月钻石会员 9999 人。」→ PASS（无前置标记的明确结果）
  neg_003「无法统计母婴偏好，母婴偏好 9999 人。」→ PASS（同类）
  neg_004「无法预测；2026 年 11 月钻石会员 403 人。」→ PASS（同上；403 是事实值）
  neg_005「无法统计注册转化天数；缺少注册时间，平均 21000 天。」→ PASS（forbidden_result_units=[]）
```

- 这与 v4/v5 已披露的“无标记明确结果”残余一致；关闭硬白名单后，任意数字（如 9999）只要不以被拦截的标记+单位形式出现，也可能自动 PASS。
- 这是 Lead 在 v1.5 明确选择的 trade-off（修复 baseline 中 `must_not_contain_numbers` 对正常事实引用/列数的误伤）；**manual_review 已保留且 runner 报告展示全部人工复核项**，因此作为“自动初筛 + 人工定案”的负样本是可接受的，但**不能把 negative 自动 PASS 当作“未编造”的最终结论**。

## 4. 最终结论：**PASS**

按 task-32 验收口径：

1. ✅ 6 条 negative 仅关闭 `must_not_contain_numbers`；approx / forbidden_result_units / manual_review 等保留。
2. ✅ v5 的 19 例契约 **19/19 符合预期**：合规拒答 8/8 PASS、编造结果 11/11 FAIL；标准 6 条合规拒答 6/6 PASS。
3. ✅ 40 条结构/类别/唯一性不变；其他 34 条 expected 无退化；multi_009 的 48.69% 修复保持。
4. ✅ 未运行完整 Agent；未修改数据/代码（仅写本报告）。

**使用建议**：negative 自动分可作为初筛；正式报告/对外分数中，6 条 negative 的最终结论应结合 runner 的“人工复核清单”按 manual_review 定案，尤其是 §3 列出的“无标记明确结果”形态。若后续要求自动判定对这类形态零放过，可在未来版本增加“数字+单位”不依赖标记的拦截（会再次带来事实引用误伤风险，需 Lead 权衡）。

---

## 附录：边界声明

- 未运行完整 `run_agent`；未修改 `dataset.v1.json`、`builder_notes.md`、`regression/`、`policy`、`runner.py`、`evaluator.py`、`src/`；未提交 Git。
- 唯一新增：`tests/evals/agent/benchmark/review_evaluator_v6_confirm.md`。
- 本机 PostgreSQL/Docker 不可用，未做实时 SQL 复算；v1.5 无 expected 数值变更，协议验证不依赖 DB。

*审查人：benchmark-evaluator · task-32 · 2026-10-26*
