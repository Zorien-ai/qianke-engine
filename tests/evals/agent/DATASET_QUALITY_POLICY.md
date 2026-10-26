# Agent Eval Dataset Quality Policy v1

## 1. 目的

把 Agent 评测从“临时凑题”变成可维护的数据资产：

- **Regression Set**：20 条稳定任务，每次 Agent 变更必跑，防退化。
- **Benchmark Set**：40 条更难、更独立的评测任务，用于阶段评测，不参与日常 Prompt 调优。

## 2. 数据来源

- 当前统一使用 `demo` 数据集。
- `demo` 快照：8110 个用户画像，构建时间 `2026-10-16 17:43:04`。
- 禁止使用 `test`（9 用户）小样本做比例、分布、排名类评测。
- 任务必须记录 `dataset` 和 `dataset_version`；数据更新后旧 expected 必须重算。

## 3. 数据质量底线

1. 用户量 ≥ 5000，避免 1/1、0/1 这种无意义比例。
2. 会员等级、城市分布不能只覆盖单一类别。
3. expected 数值必须能由 SQL 从当前 demo 数据复算。
4. 有缺失值的字段必须在 acceptance 里说明。
5. 不允许同一条任务在不同集合里换皮重复。

## 4. Case Contract

每条 benchmark case 必须包含：

```json
{
  "task_id": "bench_sql_001",
  "category": "execute_sql",
  "question": "...",
  "expected_tools": ["execute_sql"],
  "expected_keywords": ["..."],
  "expected_success": true,
  "acceptance": "可验收、可复算的说明",
  "difficulty": "easy|medium|hard",
  "dataset": "demo",
  "dataset_version": "demo@2026-10-16"
}
```

规则：

- `task_id` 唯一，前缀与 category 对应。
- `expected_tools` 必须来自 `rag_search / execute_sql / calculator`；negative 允许 `[]`。
- 工具策略可选字段：`required_tools`（必需）、`optional_tools`（可选）、`forbidden_tools`（禁用）。未提供时，`required_tools` 默认等于 `expected_tools`；旧 `expected_tools` 仍用于 Task Success v1 和 Tool Selection，`Tool Policy Compliance` 使用 required/optional/forbidden。
- `expected_keywords` 只放稳定、可从真实结果推出的片段；不要放模型随机措辞。
- `expected_success` v1 只允许 `true`；负样本用“拒答/无数据”作为正常完成。
- 禁止安全类任务进入 v1（安全评测单独建集）。
- 负样本可选字段：
  - `expected_keywords_any`: 任意拒答同义词命中即可（无法/没有/不存在/未提供/缺少/不支持）
  - `must_not_contain_numbers`: true 时禁止编造数字
  - `must_not_contain_approx_numbers`: true 时禁止“约/预计/估算 + 数字”的结果型表达；事实数字仍可引用
  - `forbidden_result_units`: 禁止指定结果单位（人/%），拦截“触达 36 人 / 退货率为 36%”
  - `allowed_numbers`: 允许出现的上下文事实数字（如定义中的 90/30）
  - `manual_review`: 人工复核项，不参与自动判分；runner 报告必须单独列出所有人工复核项（无论自动 PASS/FAIL）
- 任何“必须说明…”但 evaluator 无法自动校验的要求，必须写入 `manual_review`，不能只写在 acceptance。

## 5. Benchmark 40 条分布

```text
execute_sql      10
rag_search        8
multi_tool       12
negative          6   # 无数据 / 不可回答 / 应拒答
calculator        4
----------------------
合计             40
```

要求：

- 至少 12 条需要两个或以上工具。
- 至少 6 条需要真实业务口径判断。
- 至少 6 条是负样本，最终回答不得编造。
- 不允许所有 SQL 题都是 COUNT；至少覆盖 SUM / AVG / GROUP BY / 排序。
- 不允许把 regression 的 20 条简单改问法后重复提交。

## 6. 集合边界

| 集合 | 用途 | 是否可用来调 Prompt |
|---|---|---|
| Regression | 每次变更必跑，防退化 | 可以，用于定位回归 |
| Benchmark | 阶段评测、对外汇报 | 不可以；不参与日常调优 |

Benchmark case 在最终跑分前只允许 evaluator / 业务专家 / Lead 查看；builder 不得根据评审反馈“定向修改”到过拟合，修订必须针对数据或逻辑错误。

## 7. 评审门禁

Builder 提交 40 条后，必须同时通过：

1. **evaluator 评审**：独立复算 expected、检查数据、工具名、关键词、重复项。
2. **业务专家评审**：检查业务问题是否合理、acceptance 是否可验收、覆盖是否均衡。
3. **Lead 审核**：检查集合边界、泄漏风险、与 regression 的重复度。

任一方不通过，builder 只修复被指出的问题，不重写整个集合。

## 8. 版本与报告

报告必须记录：

```text
dataset=demo
dataset_version=demo@2026-10-16
regression_version=v1
benchmark_version=v1
agent_commit=<sha>
model=<model>
run_at=<timestamp>
```

Benchmark 未通过项必须逐条给出 task_id、实际工具、缺失关键词、实际回答摘要。

## 9. 变更流程

- 新增 case：追加，版本号 minor +1。
- 修改 expected：必须说明数据版本变化或题目错误，version +1。
- 删除 case：必须给出原因，禁止因为“跑不过”删除。
- Benchmark 首次基线跑完后冻结；后续只允许补题和修正事实错误。
