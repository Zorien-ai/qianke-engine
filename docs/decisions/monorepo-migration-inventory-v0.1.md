# Monorepo 迁移清单与 MVP 计划校准 v0.1

> 目的：在按三端架构开始开发前，把当前 `agent` 分支的真实状态与目标目录逐项对照。  
> 本文只做盘点与计划校准，不改代码。  
> 状态：待评审

## 1. 结论先说

方向同意：

```text
渐进式模块化 Monorepo
先模块化、后拆部署
先修 B 端安全与幂等，再建 C / 管理端
```

但不建议直接按原计划 19–31 个工作日排期开工，因为有三个硬前置缺口：

1. 当前 `/api/agent/run` 虽然算出了租户 dataset，但**没有把 dataset 应用到 Agent 执行上下文**。
2. 当前没有 Tool 级授权、没有 request_id 幂等存储、没有 `interrupt` / checkpointer。
3. C 端推荐、订单和管理端纠纷证据所需的数据模型与数据源当前不存在。

这三个缺口会让“先做 C 端”变成在没有安全边界和数据底座上堆 UI。

## 2. 当前仓库真实结构

```text
src/rag_demo/
├── agent/                 # 现有 LangGraph Agent
│   ├── loop.py            # Graph + Runtime + TraceCallbackHandler
│   ├── state.py           # AgentState / AgentConfig / AgentStatus
│   ├── registry.py        # 3 个 Tool 注册
│   ├── tool.py            # ToolResult
│   └── tools/
│       ├── rag.py
│       ├── sql.py
│       └── calculator.py
├── api/main.py            # FastAPI，含 /api/agent/run
├── auth.py                # 账号、企业、session
├── permissions.py         # 角色 / 等级 / capability
├── db/connection.py       # dataset contextvar + 分库连接
├── retrieval/             # RAG
├── tools/sql_tool.py      # SQL 校验 + 只读执行
└── ...

tests/evals/agent/        # Regression / Benchmark / Holdout
tests/test_agent_*.py     # Agent 单测
```

当前不是 Monorepo 的 `apps/packages/agents/services` 结构，而是单包 `src/rag_demo/`。

## 3. 目标模块映射

| 当前代码 | 目标位置 | 状态 | 迁移方式 |
|---|---|---|---|
| `agent/loop.py` | `packages/agent-runtime/` + `agents/b_agent/graph.py` | 部分已有 | 先抽 Runtime，再保留 B Graph |
| `agent/state.py` | `packages/agent-state/` + B 扩展 State | 部分已有 | 公共字段 / 端字段分离 |
| `agent/registry.py` | `packages/tool-framework/` | 部分已有 | 保留注册机制，补权限契约 |
| `agent/tools/sql.py` | `services/merchant-data-access/` + B Tool adapter | 部分已有 | SQL 执行与 Agent Tool 分离 |
| `agent/tools/rag.py` | RAG 服务 + 各端 adapter | 部分已有 | 检索与授权分离 |
| `api/main.py` | `apps/b-api/` 等 | 未拆 | 先拆路由，保留兼容入口 |
| `auth.py` | `packages/auth-core/` | 已有主体 | 先抽接口，避免大搬家 |
| `permissions.py` | `packages/policy-engine/` | 部分已有 | 增加 Tool 级授权 |
| `db/connection.py` | `infra/database/` | 部分已有 | 保留 dataset contextvar，强化租户绑定 |
| `tests/evals/agent/` | `tests/eval/` | 已有 | 保留历史基线与报告 |
| `tests/test_agent_*.py` | `tests/unit` / `tests/integration` | 已有 | 随模块迁移调整 import |

## 4. 已有 / 部分 / 缺失

### 已有

- LangGraph `chatbot ↔ tools` 主循环
- AgentState / AgentConfig / AgentStatus
- `rag_search` / `execute_sql` / `calculator`
- ToolResult 结构化错误
- SQL 只读账号与只读校验
- RAG 混合检索与关键词降级
- 企业 / 用户 / 角色 / 数据集模型
- 每企业 dataset 与数据库命名机制
- 回归集 20、Public Benchmark 80、Private Holdout 20
- LangSmith tracing 接入
- `pytest` 基线：150 passed, 1 skipped
- Regression 最新：20/20，100%
- Public Benchmark：96.2% Task Success / 100% Business（development set）
- Private Holdout：85% Task Success / 85% Business

### 部分已有

1. **租户上下文**
   - 有 `enterprise.dataset`、`DATASETS`、`use_dataset` contextvar
   - 但 `/api/agent/run` 只调用 `_agent_dataset()` 拿到 dataset 名，**没有 `use_dataset` / `_tenant_scope` 包裹执行**
   - 结果：返回体显示正确 dataset，SQL/RAG 可能仍在默认 `demo` 上下文

2. **Tool 权限**
   - `permissions.py` 主要做响应裁剪和能力等级
   - 没有每次 Tool 调用前的 `ToolPolicy.authorize`
   - 没有 Tool 暴露前过滤

3. **幂等与执行记录**
   - 有 `request_id` / `execution_id` 字段
   - 没有 `ExecutionStore.claim_request`
   - 没有唯一约束；重复请求会重复执行

4. **取消 / 超时**
   - 有 timeout 检查和 cancel_event
   - 同步 `graph.invoke`，无法在 LLM / Tool 调用中立即中断

5. **Memory**
   - 有 `chat_memory` 短期对话记忆
   - 没有目标文档中的长期偏好 Memory 生命周期

6. **LangSmith**
   - 已接入 project `qianke-agent`
   - Trace 未统一注入 request_id / execution_id metadata
   - 默认可能采集输入输出正文，需要脱敏策略

### 缺失

- C 端 StateGraph
- 管理端 StateGraph
- 推荐服务 / Recommendation Engine
- 商品目录、库存、订单状态机、订单确认、幂等下单
- 纠纷证据服务
- 统计仓库 / 批处理
- `interrupt` + checkpointer + HITL 前端流程
- `ExecutionStore`
- Tool 级权限策略
- 三端独立 API 包
- Monorepo 依赖边界 CI

## 5. 必须先修的两个安全问题

### P0-A：Agent 租户绑定

现状：

```python
dataset = _agent_dataset()
result = run_agent_with_retry(...)   # dataset 没进入执行上下文
```

当前 `run_agent` / SQL / RAG 依赖 `db.connection` 的 contextvar。  
如果不在请求内切换 dataset，企业 A 的 Agent 可能读默认 demo 或上一个上下文。

这必须作为第一个任务修，并且加：

```text
企业 A / 企业 B 两租户隔离测试
系统管理员 test 库测试
demo 账号 403 测试
```

### P0-B：request_id 幂等

当前 `request_id` 只是透传字段，没有：

- 唯一约束
- claim / complete 状态
- 重复请求返回同一结果
- 失败重试与幂等的关系

C 端订单、通知、模拟下单都不能在幂等之前做。

## 6. 原计划缺失的前置任务

原计划从 B 端、C 端、管理端直接展开，建议补充：

| 新任务 | 原因 | 优先级 |
|---|---|---|
| 定义租户/商户数据模型（企业、库、账号、dataset 映射） | 现有 enterprise/dataset 只能算半成品 | P0 |
| 定义商品 / 库存 / 订单 Schema | C 端和模拟下单没有真实数据底座 | P0（C 端前） |
| 定义订单状态机与确认版本 | 确认必须绑定订单内容，不是前端按钮 | P1（C 端前） |
| 实现 LangGraph checkpointer / interrupt | 没有它无法做 HITL 订单确认 | P1（C 端前） |
| 定义纠纷数据源与访问契约 | 当前没有订单/支付/物流证据数据 | P2（管理端前） |
| Monorepo 打包 / CI / import 迁移 | `src/rag_demo` 改目录会直接破坏导入与 Docker | P1 |
| Eval 基线冻结 | Public 80 是 development set，不能用它单独当验收 | P0 |

## 7. 建议的修订开发顺序

```text
阶段 0（2–3 天）
  迁移清单 / ADR / 租户与幂等契约确认
  不写业务功能

阶段 1（P0，5–8 天）
  Agent 租户绑定
  request_id 幂等
  执行状态 / 取消 / trace 脱敏
  A/B 租户隔离测试 + 幂等测试

阶段 2（P1，5–8 天）
  Runtime / State / Tool Contract 抽取
  兼容层保留旧入口
  CI 依赖边界
  B 端回归不退化

阶段 3（P1，5–8 天）
  SQL / RAG Tool 权限策略
  查询预算 / 行数 / 时间限制
  Eval 基线门槛

阶段 4（P2，C 端前置）
  商品 / 订单 Schema + 推荐服务
  checkpointer / interrupt
  模拟订单 + 确认绑定 + 幂等

阶段 5（P2，管理端前置）
  监控 / 审计
  纠纷数据源与证据授权
  人工裁决流程

阶段 6（P3）
  E2E、安全、故障注入、备份恢复
```

## 8. 对原 19–31 天估算的判断

不建议把它当作 MVP 工期承诺。

原因：

- C 端缺少商品/订单数据模型
- 管理端缺少纠纷数据源
- 租户数据库与独立账号仍要补
- HITL/checkpointer 未实现
- Monorepo 迁移本身有回归风险

更稳妥的说法：

```text
第一个可验收里程碑 = 阶段 0 + 阶段 1 + 阶段 2
目标 = B 端安全、幂等、可追踪、不退化
不应把 C / 管理端算进同一个 MVP 承诺
```

## 9. 需要你确认的决策

1. 第一个里程碑是否只做 **B 端安全 + Runtime 抽取**，C/A 端后置？
2. 租户隔离采用现有方向：
   - `enterprise.dataset`
   - `vec_db_ent_<id>`
   - 独立数据库和独立账号
   是否确认继续沿用？
3. C 端商品/订单数据从哪里来：
   - 现有 demo 数据扩展
   - 新业务库
   - 先做 mock，后续接真实服务
4. 管理端纠纷证据第一阶段是否只做只读 mock/接口，不做真实案件数据？
5. 是否先修 `/api/agent/run` 租户绑定，再谈目录迁移？

确认后再开始编码。
