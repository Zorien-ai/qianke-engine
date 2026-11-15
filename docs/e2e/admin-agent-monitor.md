# 管理员端本地 LangSmith：Agent 调用监控

日期：2026-11-15  
范围：系统管理员 A 端  
基线：`b-end-2.0-p0`（Agent 调用监控新增）

## 目标

在管理员端提供一个本地 LangSmith 风格的中台：

```text
Agent 调用列表
  → 状态 / 耗时 / Steps / Tools / Tokens / 问题
  → 点击查看 Trace 时间线
  → LLM / Tool / 错误 / 最终回答
```

不依赖外部 LangSmith，不需要 API Key；复用现有控制面 `ai_traces`。

## 采集

在 `rag_demo/agent/service.py::execute_agent` 统一埋点：

```text
begin_trace("agent.execute", account)
  ↓
runner 执行
  ↓
record_trace_usage(total_tokens)
finish_trace(
  status=success/error,
  total_ms=...,
  meta={
    question, request_id, execution_id, status,
    steps, tool_call_count, total_tokens, error,
    tool_calls, final_answer, agent_events,
    attempts, retried
  }
)
```

- 采集失败由 `ai_monitor._safe` 吞掉，不阻断 Agent 主链路。
- 不新增表，复用 `ai_traces` / `ai_spans`。
- `agent_events` 来自 Agent Runtime 的 `event_trace`，保留 LLM / Tool 开始、结束、错误与耗时。

## API（仅系统管理员）

```text
GET /api/admin/agent-traces
  query: range=1h|24h|7d|30d
         status=success|error
         q=问题/request_id/trace_id
         limit / offset

GET /api/admin/agent-traces/{trace_id}
  返回 trace + meta + agent_events
```

权限实测：

```text
匿名：401
企业管理员 / 非系统管理员：403
```

## 页面

路由：

```text
/admin/agent-monitor
```

导航：平台 → Agent 调用监控（仅系统管理员可见）。

页面能力：

```text
概览：调用数 / 成功率 / P95 / Token / 工具调用
列表：时间、入口、问题、状态、耗时、Steps、Tools、Tokens
筛选：1h / 24h / 7d / 30d、状态、关键词
详情：LangSmith 式时间线 + trace/request/execution ID + 错误 + 最终回答
窄屏：详情抽屉全宽，无横向溢出
```

截图：

![Agent 调用列表](docs/design/admin-agent-monitor-list.png)

![Trace 详情](docs/design/admin-agent-monitor-detail.png)

![移动详情](docs/design/admin-agent-monitor-detail-mobile.png)

## 验证

```text
pytest tests/ -q
  → 830 passed, 6 skipped

新增：
  tests/test_agent_monitoring.py
  tests/test_admin_agent_monitor_api.py

web build：PASS

真实写入验证：
  execute_agent 假 runner 写入 1 条 agent.execute trace
  question / total_tokens=123 / tool_call_count=1 可被 agent_traces 查出

页面验证（mock 系统管理员 + mock trace API）：
  列表 2 行、详情 6 个时间线事件
  1440 / 390 无横向溢出
```

## 已知限制

```text
1. 本轮用 mock 管理员验证页面；真实系统管理员账号口令未在本地留存，
   上线前需用真实系统管理员再点一次列表/详情/筛选。
2. Agent 事件明细保存在 ai_traces.meta.agent_events；
   本轮未单独写 ai_spans，后续如需 span 级查询可补。
3. 暂未做 prompt/response 全文回放、导出、采样与告警；
   属于下一阶段，不影响本次只读监控 MVP。
```

## Phase A：Trace Tree + 节点级 I/O

日期：2026-11-15  
目标：从“事件时间线”升级到 LangSmith 核心的层级 trace 视图。

### 1. 数据模型

`ai_spans` 扩展：

```text
parent_span_id
run_type
started_at / ended_at
input_json / output_json
prompt_tokens / completion_tokens / total_tokens
latency_ms / status / error_text
```

迁移兼容旧库：

```text
ALTER TABLE ai_spans ADD COLUMN IF NOT EXISTS ...
```

### 2. 采集

`TraceCallbackHandler` 现在记录：

```text
LLM：
  prompt 全文（上限 12KB）
  response 全文（上限 12KB）
  prompt/completion/total tokens
  parent_run_id

Tool：
  args 全文（上限 12KB）
  result 全文（上限 12KB）
  parent_run_id

Chain：
  on_chain_start / end / error
  用来还原 LangGraph 的父子层级
```

根节点：

```text
agent.execute
  input: question
  output: final_answer
  status / duration / total_tokens
```

### 3. 详情页

```text
Trace Tree
  agent.execute
    chain
      llm chat_model
      chain
        tool search_chat_user_profiles
      ...

点击任意节点：
  Input / Output / Metadata 三个 tab
  显示该节点的真实输入、输出、token、耗时、错误
```

真实 trace 验证：

```text
trace：统计用户总数
节点数：10
agent.execute → chain → chain → LLM / TOOL
tool：search_chat_user_profiles
input：所有买家用户画像...
tool 耗时：7.81s
root 总耗时：15.42s
root tokens：5,661
```

截图：

![Trace Tree](docs/design/admin-agent-trace-tree.png)

![Tool 节点](docs/design/admin-agent-trace-tree-tool.png)

### 4. 性能修复

发现 `ai_monitor._connect()` 在 Windows 下走 `localhost` 会先尝试 IPv6，单次连接约 **5 秒**，导致 Trace 详情很慢。

已固定监控连接使用 `127.0.0.1`：

```text
Trace 详情：约 5,000ms → 22-64ms
```

### 5. 验证

```text
pytest tests/ -q
  → 831 passed, 6 skipped

web build
  → PASS

真实 Agent 调用
  → trace tree 10 个节点
  → LLM / Tool 的 input/output/token 可查看
```

## Phase B / C（未做）

```text
Phase B：
  trace 对比
  标签 / 搜索增强
  人工评分 / feedback

Phase C：
  数据集
  Eval / 实验管理
  trace 回流评测
```

## Phase B：对比、标签、人工评分

日期：2026-11-15  
目标：在 Phase A Trace Tree 上补齐 LangSmith 常用的质量协作能力。

### 1. 标签

管理员可给单条 trace 打标签：

```text
PATCH /api/admin/agent-traces/{trace_id}/tags
body: {"tags": ["回归", "慢查询"]}
```

规则：

```text
最多 10 个标签
单个标签最多 32 字符
列表展示标签芯片
支持按标签筛选
```

### 2. 人工评分

```text
POST /api/admin/agent-traces/{trace_id}/feedback
body: {"score": 1-5, "comment": "可选反馈"}
```

支持：

```text
1-5 星
可选评论
清除评分
按好评 / 差评 / 已评分 / 未评分筛选
列表展示星级
```

截图：

![标签与评分](docs/design/admin-agent-trace-feedback-tags.png)

### 3. Trace 对比

列表勾选两条 trace 后点击“对比 Trace”：

```text
状态
耗时
Tokens
Steps
Tools
评分
标签
最耗时节点 Top 6
```

对比视图：

![Trace 对比](docs/design/admin-agent-trace-compare.png)

移动端：

![对比移动端](docs/design/admin-agent-trace-compare-mobile.png)

### 4. 增强筛选

列表支持：

```text
时间范围
状态
评分：好评 / 差评 / 已评分 / 未评分
标签
关键词：问题 / request_id / trace_id / 标签
```

### 5. 验证

```text
pytest tests/ -q
  → 836 passed, 6 skipped

web build
  → PASS

真实 admin 页面验证：
  标签保存成功
  1-5 星评分保存成功
  两条 trace 对比打开
  390 宽度无整页横向溢出
```

## Phase C（未做）

```text
数据集
Eval / 实验管理
trace 回流评测
```

## Phase C：数据集与评测实验

日期：2026-11-15  
入口：`/v2/#/admin/agent-evals`（平台 → Agent 数据集与评测）

### 1. 从 Trace 建数据集

```text
GET  /api/admin/agent-traces?range=7d&limit=30
POST /api/admin/agent-datasets
  {name, description, trace_ids[]}
```

行为：

```text
读取选中 trace 的 meta.question / meta.final_answer
为每条 trace 生成一个 case
单次最多 50 条 trace
```

### 2. 运行评测实验

```text
POST /api/admin/agent-experiments
  {dataset_id, name}
GET  /api/admin/agent-experiments
GET  /api/admin/agent-experiments/{experiment_id}
```

执行：

```text
后台线程逐条调用真实 Agent
request_id = experiment_id + case 序号
记录：状态 / 通过 / 耗时 / Tokens / 工具 / 回答 / 监控 trace_id
```

判定（当前 deterministic）：

```text
Agent status == COMPLETED
expected_keywords 全部命中（若配置）
expected_tools 是实际调用子集（若配置）
```

不通过或异常都落结果，实验最终状态为 COMPLETED。

### 3. 页面

```text
数据集：
  最近 7 天 Trace 勾选
  创建数据集
  查看用例列表

评测实验：
  选择数据集
  启动评测
  运行中每 2 秒轮询
  查看通过数 / 成功率 / 平均耗时
  逐条结果表
```

截图：

![数据集](docs/design/admin-agent-evals-datasets.png)

![数据集详情](docs/design/admin-agent-evals-dataset-detail.png)

![实验详情](docs/design/admin-agent-evals-experiment.png)

### 4. 真实验证

```text
创建数据集 Phase C Smoke（1 条 Trace）
运行 smoke experiment
结果：
  status COMPLETED
  1/1 通过
  success_rate 100%
  avg latency 3.11s
  avg tokens 2,294
```

### 5. 当前限制

```text
1. 评测判定是确定性的，没有 LLM Judge
2. 用例目前只由 Trace 自动生成，尚未做手工增改/期望关键词编辑
3. 实验在前台 API 进程的后台线程执行，服务重启会中断 RUNNING 实验
4. 数据集/实验暂时只在系统管理员范围内使用
```

## Phase C 验证

```text
pytest tests/ -q
  → 844 passed, 6 skipped

web build
  → PASS

移动 390：
  数据集/实验详情无整页横向溢出
```
