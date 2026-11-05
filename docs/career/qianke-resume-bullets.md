# 千客引擎 · 简历项目描述（2026-11 更新）

> GitHub：https://github.com/q93304989-bit/qianke-engine
> 口径：数字来自仓库当前可复现结果；控制面 PostgreSQL 迁移已完成 schema/回填/运行时开关与隔离预演，生产切换尚未执行。

## 项目一句话

设计并实现千客引擎（Qianke Engine）：以 RAG + Text2SQL 为分析底座、LangGraph Agent Runtime 为执行内核的电商 AI 平台，覆盖 B 端经营分析、C 端导购/模拟订单、IM 店宠与 Super-agent 审批执行。

## 技术栈

```text
Python / FastAPI / LangGraph / LangChain
PostgreSQL + pgvector / SQLite
DeepSeek ChatOpenAI
Vue 3 / Vite
GitHub Actions / LangSmith / pytest / 自建 Agent Eval
```

## 简历 Bullet（推荐 5 条）

- **RAG + Text2SQL 多路聚合**：设计 BERT 二分类入口路由 + LLM 多路规划，串联稠密/BM25 双路召回、RRF 融合与分来源精排；入口路由准确率 0.61→0.99，GPU p50 18.7ms。Text2SQL 采用只读账号 + SELECT-only/表白名单/LIMIT 预检 + 10s 超时 + 100 行截断，生成后由 answer_guard 按句拦截预测类幻觉。

- **混合记忆多轮对话**：设计“近 6 轮原文 + ≤100 字摘要 + 业务实体 JSONB”的混合记忆；短追问触发指代改写，改写失败回退原问题，长会话中业务条件不丢失。

- **Agent Runtime 与 Super-agent**：实现可恢复 Runtime（request/execution ID、step/tool-call 预算、timeout、retry、checkpoint、interrupt），并扩展 Router → Thread/WorkItem → Deep Agents Worker → HITL 审批 → 动作白名单执行的 Super-agent；企业微信原生按钮卡片审批已跑通真实回调闭环。

- **安全边界与多租户**：建立只读 SQL、RAG 检索隔离、Calculator 安全 AST、Tool allowlist 的纵深防御；实现商家租户隔离、owner/admin/staff 角色、动作策略（允许动作/补偿/退款上限）、执行审计与补偿；C 端未确认不下单，B 端高风险动作必须人工审批。

- **评测与工程化**：搭建 33 题（5 角色 × 13 题型）LLM-as-a-Judge 黄金集 + 来源召回并接入 GitHub Actions，通过率 75.8%→93.9%（历史最佳 97.0%）；补充 Super-agent 24 场景 × 2 采样动作评测，case 级 24/24、平均分 0.990；累计 657 个 pytest。

## 备选 Bullet（按岗位取舍）

- **PostgreSQL 控制面迁移**：完成 28 表 schema、SQLite→PostgreSQL 幂等回填、运行时 backend 开关、sa_queue `SKIP LOCKED` 队列与 `/ready`、`/metrics`、备份保留、Grafana 看板；隔离预演校验 371 Threads / 372 WorkItems 数据一致，PG 审批流达到 DONE/EXECUTED。

- **C 端与 IM 闭环**：跑通“导购推荐 → 订单草稿 → 用户确认 → 模拟订单”的浏览器流程；支持 IM 好友/群聊、店宠 Agent、结构化报价与双宠谈判，成交仍以用户逐单确认为唯一入口。

## 面试讲述结构

1. **问题**：企业分析 Agent 容易退化成“LLM 查库 + 编答案”，缺安全边界、可复现评测与运行时可观测。
2. **方案**：单体 ReAct + 确定性 Tool；RAG/Text2SQL 多路聚合；混合记忆；Tool Contract、只读 SQL、租户上下文、幂等、checkpoint、interrupt；Super-agent 负责长任务与人工审批。
3. **评测**：33 题黄金集 + 24 场景 Super-agent Eval；区分 Task Success、Business Correctness、Tool Policy、安全边界。
4. **结果**：657 tests；RAG 路由 0.61→0.99；动作评测 case 级 24/24、avg 0.990；企业微信审批真实闭环。
5. **反思**：公开 Benchmark 仍是 development set；控制面 PG 迁移只完成预演，生产切换与高可用仍需继续验证。

## 不要这样写

避免：

```text
“实现多智能体自由博弈”
“Agent 自动完成交易”
“生产级高可用平台”
“全量 PostgreSQL 已上线”
```

当前真实状态：

```text
单体 Agent 编排 + 三端产品形态
C 端为 mock 交易
B 端经营分析为主
Super-agent 已具备审批/执行/审计闭环
控制面 PG 迁移完成 P1/P2 与隔离预演，生产切换待执行
```
