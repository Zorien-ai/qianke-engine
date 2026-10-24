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
├── dataset.json          # 20 个任务
├── runner.py             # 真实运行 Agent
├── evaluator.py          # 轨迹与任务指标
├── README.md
├── results/              # 原始结果 JSON
└── reports/              # Markdown 报告
```

## 任务集

```text
calculator     5
execute_sql    5
rag_search     5
multi_tool     5
-----------------
合计          20
```

数据集固定为 `demo`（8110 个用户画像），不再使用 9 用户的 `test` 小样本。
安全类暂不纳入 v0.1。

## 指标

| 指标 | 定义 |
|---|---|
| Task Success Rate | 状态 COMPLETED + 期望工具全部调用 + 期望关键词全部出现 |
| Tool Selection Accuracy | 期望工具全部被选中的任务占比 |
| Tool Execution Success | 工具结果 `ok=true` 数 / 工具结果总数 |
| Error Recovery | 出现工具错误但仍 Task Success 的比例 |
| Avg Steps | 平均 Agent step |
| Avg Tool Calls | 平均工具调用次数 |

## 运行

校验任务集：

```bash
python tests/evals/agent/runner.py --validate-only
```

真实全量：

```bash
DEEPSEEK_API_KEY=... python tests/evals/agent/runner.py
```

子集：

```bash
python tests/evals/agent/runner.py --only calc_001,multi_001
python tests/evals/agent/runner.py --limit 5
```

默认输出：

```text
tests/evals/agent/results/agent_eval_v0.1.json
tests/evals/agent/reports/agent_eval_v0.1.md
```

## 结果判定

```text
task_success =
    status == COMPLETED
    AND expected_tools ⊆ actual_tools
    AND expected_keywords ⊆ final_answer
```

这版是确定性评测，不引入 LLM Judge；后续再增加 groundedness / judge。
