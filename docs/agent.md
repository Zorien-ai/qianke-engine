# Qianke Agent

> **Status:** Active · **Agent Runtime:** v0.2 · **Agent Eval:** v1.9  
> 本文描述 Agent 的实现、边界、评测与当前限制。项目工作协议见 [`AGENTS.md`](../AGENTS.md)。

## 1. 它是什么

Qianke Agent 是面向企业经营分析与策略决策的 **Decision Support Agent**。

它负责：

- 理解业务问题
- 规划调查步骤
- 调用 SQL / RAG / Calculator 获取证据
- 基于证据验证假设
- 给出可解释的分析和策略建议

它不负责：

- 自动执行营销活动
- 自动发送消息
- 自动修改或删除业务数据
- 无人工确认执行高风险写操作

## 2. 架构

```text
POST /api/agent/run
        ↓
LangGraph StateGraph
        ↓
   chatbot ──tool_calls──→ tools
      ↑                      │
      └──── ToolMessage ─────┘
        ↓
   Final Answer
```

实现位置：

| 模块 | 路径 | 作用 |
|---|---|---|
| Agent Loop | `src/rag_demo/agent/loop.py` | LangGraph 图、LLM 调用、终止条件 |
| State / Config | `src/rag_demo/agent/state.py` | `AgentState`、`AgentConfig`、`AgentStatus` |
| Tool Contract | `src/rag_demo/agent/tool.py` | `Tool`、`ToolResult`、结构化错误 |
| Tool Registry | `src/rag_demo/agent/registry.py` | LangChain Tools 与 JSON Contract 双入口 |
| Tools | `src/rag_demo/agent/tools/` | `rag_search`、`execute_sql`、`calculator` |
| API | `src/rag_demo/api/main.py` | `POST /api/agent/run` |

## 3. Runtime

### 3.1 默认配置

```python
AgentConfig(
    max_steps=5,
    max_tool_calls=10,
    timeout_seconds=60.0,
)
```

三个参数都会进入真正的运行时约束，不是展示字段。

### 3.2 状态字段

```python
{
    "messages": [...],
    "step_count": 0,
    "tool_call_count": 0,
    "status": "RUNNING",
    "error": None,
    "started_at": 0.0,
    "request_id": "req_...",
    "execution_id": "exec_...",
    "parent_execution_id": None,
}
```

### 3.3 Execution Trace

Runtime v0.2 通过 LangChain callbacks 旁路采集事件，不改 Graph：

```text
run_started
llm_started / llm_finished / llm_failed
tool_started / tool_finished / tool_failed
run_finished / run_failed
```

每个事件包含：

```text
timestamp
run_id
name
duration_ms
status / error
```

工具事件只记录输入/输出摘要，避免把完整 SQL 结果或用户数据写进 trace。

### 3.4 终态

| 状态 | 含义 |
|---|---|
| `COMPLETED` | 正常结束，且有最终回答 |
| `MAX_STEPS_EXCEEDED` | 超过推理步数上限 |
| `MAX_TOOL_CALLS_EXCEEDED` | 超过工具调用上限 |
| `TIMEOUT` | 超时 |
| `FAILED` | 执行异常或没有有效最终回答 |

终态会明确返回，不会把“超限”伪装成普通 AI 回答。

## 4. API

### `POST /api/agent/run`

请求：

```json
{
  "query": "统计 demo 数据集中被营销活动触达过的用户数量",
  "request_id": "可选；调用方幂等 ID",
  "parent_execution_id": "可选；父执行 ID"
}
```

约束：

- `query` 不能为空
- `query` 最长 500 字

响应：

```json
{
  "ok": true,
  "dataset": "demo",
  "user_query": "...",
  "final_reply": "...",
  "status": "COMPLETED",
  "request_id": "req_...",
  "execution_id": "exec_...",
  "parent_execution_id": null,
  "event_trace": [
    {"event": "run_started", "timestamp": 0.0},
    {"event": "tool_started", "name": "execute_sql", "timestamp": 0.0},
    {"event": "tool_finished", "name": "execute_sql", "duration_ms": 12.3},
    {"event": "run_finished", "status": "COMPLETED", "timestamp": 0.0}
  ],
  "tool_calls": [
    {"name": "execute_sql", "args": {"sql": "..."}}
  ],
  "steps": [],
  "profiles": {},
  "sop": {},
  "user_cards": []
}
```

`profiles` / `sop` / `user_cards` 是兼容旧前端的占位字段。

## 5. Tools

### 5.1 Tool Contract

每个 Tool 都有：

```json
{
  "name": "execute_sql",
  "description": "...",
  "input_schema": {"type": "object", "properties": {}},
  "fn": "..."
}
```

统一返回：

```json
{"ok": true, "data": {}}
```

或：

```json
{
  "ok": false,
  "data": {},
  "error": {"code": "INVALID_SQL", "message": "..."}
}
```

调用方应依赖 `error.code`，不要依赖 `error.message` 字符串匹配。

### 5.2 RAG Tool

```text
rag_search(query, top_k)
```

- 用于企业知识、活动规则、KPI 定义、业务口径、运营 SOP
- 只返回检索结果，不生成答案
- `top_k` 范围 1–20，默认 5

### 5.3 SQL Tool

```text
execute_sql(sql)
```

- 只允许只读 `SELECT / WITH`
- 必须带 `LIMIT`
- 只读连接、表白名单、超时和 fetch limit
- 禁止 `DROP / DELETE / UPDATE / INSERT / ALTER / TRUNCATE`

错误示例：

```json
{
  "ok": false,
  "error": {"code": "READ_ONLY_VIOLATION", "message": "只允许 SELECT"}
}
```

### 5.4 Calculator Tool

```text
calculator(expression)
```

- 只接受数字、括号和 `+ - * / // % **`
- 用 AST 解释，不使用裸 `eval`
- 对操作数和结果做数值上限检查

## 6. 数据与演示环境

Agent Eval 当前使用：

```text
dataset: demo
users: 8110
tables:
  - user_profile_vectors
  - wiki_vectors
```

评测数据版本在运行时会被固定记录，避免“换了数据再比较分数”。

## 7. Agent Eval

### 7.1 两套题

| 集合 | 题量 | 用途 |
|---|---:|---|
| Regression | 20 | 防止已有能力回归 |
| Benchmark | 60 | 衡量真实任务完成能力 |

题目位置：

```text
tests/evals/agent/regression/
tests/evals/agent/benchmark/
```

### 7.2 指标

旧复合口径保留：

```text
Task Success Rate（v1）
= 状态 COMPLETED
+ 期望工具满足
+ 期望关键词/任一关键词通过
```

v1.6 新增两个独立指标：

| 指标 | 含义 |
|---|---|
| Business Correctness | 只看状态 + 业务答案，不看工具路径 |
| Tool Policy Compliance | 只看必需工具是否满足、禁用工具是否出现 |

这样可以区分：

```text
答案对，但工具路径不符合要求
```

### 7.3 当前基线

v1.9 基线（当前，Runtime v0.2；指标沿用 v1.8.2 真实运行）：

```text
Regression 20
  Task Success（v1）      100.0%
  Business Correctness    100.0%
  Tool Policy Compliance  100.0%
  Tool Execution          100.0%

Benchmark 60
  Task Success（v1）       95.0%
  Business Correctness    100.0%
  Tool Policy Compliance  100.0%
  Tool Selection          95.0%
  Tool Execution          97.2%
  Error Recovery          100.0%
  Input Tokens            353,534
  Output Tokens            28,524
  Total Tokens             382,058
  平均 Tokens / 任务       6,368
```

v1.8.3 基线（保留对比）：

```text
Benchmark 60    Task Success 95.0% / Business 100.0% / Tool Policy 100.0%
```

v1.8.1 基线（保留对比）：

```text
Benchmark 60    Task Success 93.3% / Business 100.0% / Tool Policy 98.3%
```

v1.8 基线（保留对比）：

```text
Regression 20    Task Success 100.0%
Benchmark 60     Task Success 93.3% / Business 96.7% / Tool Policy 98.3%
```

v1.7 基线（保留对比）：

```text
Regression 20    Task Success 100.0%
Benchmark 40     Task Success 97.5% / Business 100.0% / Tool Policy 100.0%
```

v1.6.1 基线（保留对比）：

```text
Regression 20    Task Success 100.0% / Tool Execution 100.0%
Benchmark 40     Task Success 97.5% / Business 100.0% / Tool Policy 97.5%
```

v1.6 基线（保留对比）：

```text
Regression 20    Task Success 100.0%
Benchmark 40     Task Success 97.5%
```

v1.5 旧基线：

```text
Regression  95.0%
Benchmark   92.5%
```

基线文件：

```text
tests/evals/agent/baselines/v1.5.json
tests/evals/agent/baselines/v1.6.json
tests/evals/agent/baselines/v1.6.1.json
tests/evals/agent/baselines/v1.7.json
tests/evals/agent/baselines/v1.8.json
tests/evals/agent/baselines/v1.8.1.json
tests/evals/agent/baselines/v1.8.2.json
tests/evals/agent/baselines/v1.8.3.json
tests/evals/agent/baselines/v1.9.json
```

### 7.4 运行

```bash
# 回归
python tests/evals/agent/runner.py --suite regression

# Benchmark
python tests/evals/agent/runner.py --suite benchmark

# 只校验数据
python tests/evals/agent/runner.py --suite benchmark --validate-only
```

报告：

```text
tests/evals/agent/regression/reports/regression_v1.md
tests/evals/agent/benchmark/reports/benchmark_v1.md
```

### 7.5 版本对比与成本

```bash
python tests/evals/agent/compare.py v1.8.1 v1.8.2
```

成本单价不写死在仓库里；需要时配置：

```bash
export EVAL_INPUT_COST_PER_1M=...
export EVAL_OUTPUT_COST_PER_1M=...
```

未配置时报告显示 `N/A`。

## 8. Eval 设计原则

- 不让 Builder 在构建 Benchmark 时运行 Agent，避免污染 held-out
- Benchmark 不用于 Prompt 调参
- 自动评测只做初筛；负样本结论以人工复核清单为准
- 允许引用事实数字；禁止编造预测/结果
- 工具路径与业务答案分开报告
- 每次核心逻辑变化都要对比旧基线，而不是只看绝对分

## 9. 安全边界

- SQL 只读、只允许 SELECT/WITH、必须 LIMIT
- 工具错误结构化，不依赖字符串判断
- 工具返回内容视为数据，不作为指令执行
- Agent 不直接写库、不执行 DDL/DML
- 真实业务状态变化必须有人工确认
- 不伪造测试、Eval、浏览器验证结果

## 10. 当前已知限制

1. `bench_multi_001` / `multi_004` / `multi_014` 的旧 Task Success 仍因缺少 calculator 失败，但业务答案正确；v1.8.2 已让 Tool Policy Compliance 达到 100%。
2. Benchmark 的 Tool Execution Success 为 97.2%，剩余错误为少量 SQL / calculator 参数错误，均被 Agent 恢复，Error Recovery 为 100%。
3. Agent 仍是单 Agent、固定工具集；没有 Planner、Memory、多 Agent 协同。
4. 第一阶段不做自动业务执行，只做分析与建议。
5. 评测依赖本地 demo 数据库和模型 API；环境不可用时不能伪造跑分。

## 11. Runtime v0.2 方向

```text
Agent Runtime
├── State
├── Request ID
├── Execution ID
├── Timeout
├── Budget
├── Event Trace
├── Retry
├── Checkpoint
└── Observability
```

重点：

- `request_id` 幂等
- `execution_id` 执行身份
- retry 使用新的 `execution_id`
- `parent_execution_id`
- timeout / budget / cancellation
- checkpoint / event trace

## 12. 相关文档

- 项目工作协议：[`AGENTS.md`](../AGENTS.md)
- Dataset Quality Policy：[`tests/evals/agent/DATASET_QUALITY_POLICY.md`](../tests/evals/agent/DATASET_QUALITY_POLICY.md)
- Eval 使用说明：[`tests/evals/agent/README.md`](../tests/evals/agent/README.md)
- v1.6 基线对比：[`tests/evals/agent/benchmark/baseline_v1.6.md`](../tests/evals/agent/benchmark/baseline_v1.6.md)
- v1.6.1 小修对比：[`tests/evals/agent/benchmark/baseline_v1.6.1.md`](../tests/evals/agent/benchmark/baseline_v1.6.1.md)
- v1.7 工具策略：[`tests/evals/agent/benchmark/baseline_v1.7.md`](../tests/evals/agent/benchmark/baseline_v1.7.md)
- v1.8 60 题扩展：[`tests/evals/agent/benchmark/baseline_v1.8.md`](../tests/evals/agent/benchmark/baseline_v1.8.md)
- v1.8.1 收口：[`tests/evals/agent/benchmark/baseline_v1.8.1.md`](../tests/evals/agent/benchmark/baseline_v1.8.1.md)
- v1.8.2 Token 指标：[`tests/evals/agent/benchmark/baseline_v1.8.2.md`](../tests/evals/agent/benchmark/baseline_v1.8.2.md)
- v1.8.3 对比与成本：[`tests/evals/agent/benchmark/baseline_v1.8.3.md`](../tests/evals/agent/benchmark/baseline_v1.8.3.md)
- v1.9 Runtime v0.2：[`tests/evals/agent/benchmark/baseline_v1.9.md`](../tests/evals/agent/benchmark/baseline_v1.9.md)
- Agent 实现：[`src/rag_demo/agent/`](../src/rag_demo/agent/)
