# 千客引擎 · 简历项目描述

> 可直接用于简历/面试讲述。数字均来自仓库当前可复现结果；不要把“目标态”写成已上线能力。

## 项目一句话

设计并实现一个面向企业经营的 LangGraph Agent 平台：以 B 端经营分析为主入口，逐步扩展到 C 端导购/模拟订单与 IM 社交电商，强调租户隔离、Tool 授权、可观测与离线评测。

## 技术栈

```text
Python / FastAPI / LangGraph / LangChain
PostgreSQL + pgvector / SQLite
DeepSeek ChatOpenAI
Vue 3 / Vite
LangSmith / pytest / 自建 Agent Eval
```

## 简历 Bullet 版本

- 设计并实现可恢复的 LangGraph Agent Runtime，支持 request/execution ID、step/tool-call 预算、timeout、token budget、retry、SQLite checkpointer 与 interrupt，单次 Agent 执行可追踪、可恢复。
- 建立 Tool Contract 与权限边界：SQL 只读账号 + 白名单、RAG 检索隔离、Calculator 安全 AST、Tool allowlist 与执行时二次校验，避免 LLM 越权和高风险写操作。
- 实现 Agent 请求幂等与租户绑定：`request_id + scope + request_hash` 唯一记录、Postgres ExecutionStore、租户 dataset contextvar 绑定与恢复，防止重复执行和跨租户读取。
- 从 0 到 1 搭建 Agent Eval：20 条 Regression、80 条 Public Benchmark、20 条 Private Holdout，覆盖 SQL/RAG/multi-tool/negative/calculator；当前全量测试 176 passed，Regression 20/20。
- 实现 C 端 mock 商品/订单闭环：商品推荐、订单草稿、confirmation token、库存/价格快照校验、request_id 幂等、LangGraph interrupt 人工确认与 resume，确保未确认不下单。
- 用 Vue 3 实现 C 端商城页面，完整跑通“导购推荐 → 订单草稿 → 用户确认 → 模拟订单”的真实浏览器流程；控制台 0 错误，移动端无横向溢出。
- 设计三端（C/B/Admin）平台架构：共享 Runtime/Tool/鉴权底座，独立 Agent Graph 与数据边界；明确“单 Agent 优先，工具超过 10 个且路由混乱才考虑 Supervisor”的演进原则。
- 将 LangSmith 接入 Agent 执行链，补充 trace、token、latency 与失败复盘；同时保留轻量 event_trace 供 API/Eval 使用。

## 面试讲述结构

1. **问题**：企业分析 Agent 容易变成“LLM 查库 + 编答案”，缺安全边界、可复现评测和运行时治理。
2. **方案**：单体 ReAct + 3 个确定性 Tool；Tool Contract、只读 SQL、租户上下文、幂等、checkpointer、interrupt。
3. **评测**：Regression/Benchmark/Private Holdout 三层；区分 Task Success、Business Correctness、Tool Policy。
4. **结果**：176 tests；Regression 20/20；真实 C 端浏览器闭环。
5. **反思**：公开 Benchmark 是 development set，不是独立泛化结论；private holdout 仍是下一阶段重点。

## 不要这样写

避免：

```text
“实现多智能体自由博弈”
“Agent 自动完成交易”
“生产级高可用平台”
```

当前真实状态是：

```text
单 Agent 编排 + 多端产品形态
C 端为 mock 交易
B 端为经营分析
A 端待建设
```
