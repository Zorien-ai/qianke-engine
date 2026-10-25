# Agent Eval v0.1

这是 Agent 的**任务级评测**，不是 Agent 架构单测。

它真实调用：

```text
DeepSeek
  ↓
LangGraph run_agent
  ↓
execute_sql / rag_search / calculator
  ↓
Trajectory + Final Answer
  ↓
Evaluator
  ↓
Metrics + Report
```

## 目录

```text
tests/evals/agent/
├── DATASET_QUALITY_POLICY.md
├── runner.py                 # regression / benchmark 共用 runner
├── evaluator.py              # 轨迹与任务指标
├── README.md
├── regression/
│   ├── dataset.v1.json
│   ├── results/
│   └── reports/
├── benchmark/
│   ├── dataset.v1.json
│   ├── builder_notes.md
│   ├── review_evaluator*.md
│   ├── review_business*.md
│   ├── results/
│   └── reports/
```

## 两个集合

| 集合 | 数量 | 用途 | 是否用于日常调优 |
|---|---:|---|---|
| regression | 20 | 每次 Agent 变更必跑，防退化 | 可以 |
| benchmark | 40 | 阶段评测、对外汇报 | 不可以 |

数据集固定为 `demo`（8110 个用户画像）。禁止使用 9 用户的 `test` 小样本做比例/分布评测。

## 指标

| 指标 | 定义 |
|---|---|
| Task Success Rate | 状态 COMPLETED + 期望工具全部调用 + 期望关键词/任一关键词通过 |
| Tool Selection Accuracy | 期望工具全部被选中的任务占比 |
| Tool Execution Success | 工具结果 `ok=true` 数 / 工具结果总数 |
| Error Recovery | 出现工具错误但仍 Task Success 的比例 |
| Avg Steps | 平均 Agent step |
| Avg Tool Calls | 平均工具调用次数 |

负样本额外支持：

```text
expected_tools: []
expected_keywords_any: ["无法", "没有", "不存在", ...]
must_not_contain_numbers: true
must_not_contain_approx_numbers: true
forbidden_result_units: ["人", "%"]
allowed_numbers: ["8110", "36", "2", ...]
manual_review: ["必须说明数据缺失"]
```

`must_not_contain_approx_numbers` 会拦截“约/预计/估算 + 数字”的结果型表达；`forbidden_result_units` 拦截“触达 36 人 / 退货率为 36%”这类带单位结果；事实数字仍可引用。`manual_review` 不参与自动判分，但 runner 报告会单独列出所有人工复核项（无论自动 PASS/FAIL）。

## 运行

校验任务集：

```bash
python tests/evals/agent/runner.py --suite regression --validate-only
python tests/evals/agent/runner.py --suite benchmark --validate-only
```

真实全量：

```bash
DEEPSEEK_API_KEY=... python tests/evals/agent/runner.py --suite regression
DEEPSEEK_API_KEY=... python tests/evals/agent/runner.py --suite benchmark
```

子集：

```bash
python tests/evals/agent/runner.py --suite regression --only calc_001,multi_001
python tests/evals/agent/runner.py --suite benchmark --limit 5
```

默认输出：

```text
tests/evals/agent/regression/results/regression_v1.json
tests/evals/agent/regression/reports/regression_v1.md
tests/evals/agent/benchmark/results/benchmark_v1.json
tests/evals/agent/benchmark/reports/benchmark_v1.md
```

基线人工复核说明：[benchmark/baseline_notes.md](benchmark/baseline_notes.md)。

## 结果判定

```text
task_success =
    status == COMPLETED
    AND expected_tools ⊆ actual_tools
    AND expected_keywords ⊆ final_answer
    AND (expected_keywords_any 为空 OR 至少一个出现)
    AND (must_not_contain_numbers 为 false OR 未出现非法数字)
```

这版是确定性评测，不引入 LLM Judge；后续再增加 groundedness / judge。
