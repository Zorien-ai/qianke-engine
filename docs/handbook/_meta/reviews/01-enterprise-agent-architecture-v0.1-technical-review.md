# 《企业级 Agent 架构概述》V0.1 技术审核报告

> 审核对象：`docs/handbook/01-agent-architecture/01-enterprise-agent-architecture.md`  
> 文档版本：V0.1（frontmatter 0.1.0）  
> 审核日期：2026-11-23  
> 审核方式：文档逐条核对 + 仓库代码/tests 核验 + 目标补丁建议  
> 本轮不改代码，不覆盖 V0.1

## 0. 审核结论

```text
结论：需修订后复审（Request Changes）
```

```text
技术错误：5 项
设计不完整：4 项
表达优化：2 项
```

文档方向、分层结构、学习路径和“实现状态/目标状态分离”的原则是正确的；
但当前 V0.1 有若干**会让读者误解 Qianke Engine 实际实现**的问题，必须先修正。

特别是：

```text
1. 把 Super-agent 队列画成主 Agent Runtime 的编排依赖
2. Tool 清单和角色权限矩阵已过期：文档写 3 个，代码实际 7 个
3. “失败请求记录 FAILED”与实际 execution_store 语义不一致
4. Checkpoint / Retry / 硬取消被混为一谈
5. HITL 边界过宽：受控草稿确认已实现，但通用 interrupt/HITL API 未接入
```

## 1. 审核范围与版本差异

### 1.1 文件版本差异（必须先说明）

审核时工作区文件：

```text
docs/handbook/01-agent-architecture/01-enterprise-agent-architecture.md
行数：814
字节：24,537
frontmatter version：0.1.0
```

审核意见提到“约 996 行”。两者可能不是同一快照。

```text
本报告以工作区当前 V0.1 为审核依据。
如果 996 行版本包含额外内容，需要先对齐版本；
不能用本报告替另一个快照背书。
```

### 1.2 核验依据

代码：

```text
src/rag_demo/agent/state.py
src/rag_demo/agent/loop.py
src/rag_demo/agent/service.py
src/rag_demo/agent/execution_store.py
src/rag_demo/agent/tool.py
src/rag_demo/agent/registry.py
src/rag_demo/agent/policy.py
src/rag_demo/agent/checkpoint.py
src/rag_demo/agent/actions.py
src/rag_demo/agent/tools/
src/rag_demo/superagent/runtime.py
src/rag_demo/superagent/queue_pg.py
src/rag_demo/c_end/agent.py
src/rag_demo/api/main.py
```

测试：

```text
tests/test_agent_execution_safety.py
tests/test_agent_checkpoint.py
tests/test_agent_architecture.py
```

核验命令：

```powershell
$env:QIANKE_CONTROL_BACKEND='sqlite'
$env:QIANKE_CEND_BACKEND='sqlite'
python -m pytest \
  tests/test_agent_execution_safety.py \
  tests/test_agent_checkpoint.py \
  tests/test_agent_architecture.py -q
```

结果：

```text
34 passed
```

注意：

```text
34 passed 证明这些已覆盖的路径可用，
不等于 V0.1 的每一个“已实现”结论都正确；
本报告仍以逐条代码核对为准。
```

## 2. 问题总表

| ID | 严重级别 | 位置 | 问题 |
|---|---|---|---|
| R-01 | 技术错误 | 4.1 | 把 Super-agent Queue 画成主 Agent Runtime 的编排依赖 |
| R-02 | 技术错误 | 4.1 / 4.2 | 目标架构与当前实现混在一张图，Execution Store/Queue/Worker 边界不清 |
| R-03 | 技术错误 | 5.1 / 5.5 / 8.2 | 文档写 3 个 Tool、旧权限矩阵；代码实际 7 个 Tool，矩阵已变化 |
| R-04 | 技术错误 | 5.4 | “失败请求记录 FAILED”与实际 `execute_agent` / `execution_store` 语义不符 |
| R-05 | 技术错误 | 6.6 | Checkpoint、Retry、硬取消混为一谈；JSON checkpoint 与 LangGraph saver 未区分 |
| R-06 | 设计不完整 | 4.2 | Execution Store、Runtime、Queue、Worker 的职责边界需要单独定义 |
| R-07 | 设计不完整 | 7.2 | LangGraph 框架能力与 Qianke 实际采用能力未分列，容易混淆 |
| R-08 | 设计不完整 | 6.1 | Prompt Injection、Tool 输出不可信、租户隔离/脱敏边界展开不足 |
| R-09 | 设计不完整 | 8.2 / 8.3 | 证据表缺少可执行验证路径；C/A/Queue/HITL 状态粒度不够 |
| R-10 | 表达优化 | 全文 | “单 Agent”“HITL”“Checkpoint”等术语未先定义，易产生歧义 |
| R-11 | 表达优化 | 11 | 外部链接与适用性需按版本重新标注；本地版本与 996 行版本不一致 |

## 3. 详细审核

### R-01 · 技术错误：Queue 被错误画进主 Agent 编排链

#### 原文位置

V0.1 §4.1 总体分层图：

```text
QUEUE --> ORCH
```

#### 实际代码

```text
src/rag_demo/superagent/runtime.py
  - 独立 Super-agent Worker 队列
  - claim / lease / retry / action job
  - run_work_item() 走 sa_worker（Deep Agents）
  - 与主 /api/agent/run 的 LangGraph Runtime 是两条链路

src/rag_demo/superagent/queue_pg.py
  - sa_job 队列
  - 只服务 Super-agent work item / action
```

#### 结论

```text
Super-agent Queue 不是主 Agent Runtime 的 Orchestrator 上游。
主 Agent 的交互式请求走：
  /api/agent/run → Execution Store → execute_agent → LangGraph
Super-agent 的异步调查/审批走：
  WorkItem → queue → Worker → Deep Agents / actions
```

V0.1 的 `QUEUE --> ORCH` 会让读者误以为：

```text
所有 Agent 请求都先入队，再由 Orchestrator 调度。
```

这与当前实现不符。

#### 修订要求

```text
1. 把当前架构拆成“交互式 Agent Runtime”和“异步 Super-agent 链路”
2. 不要用一条箭头把两条链路连起来
3. 如要画目标态，另画“统一任务编排”并明确标注“已设计/规划中”
```

### R-02 · 技术错误/设计不完整：当前态与目标态混图，模块边界不清

#### 原文位置

V0.1 §4.1 的单一分层图同时包含：

```text
B/C/A 接入
Execution Store
Agent Runtime
Queue
HITL
Audit
Eval
Observability
```

但正文没有明确哪些是当前实现、哪些是目标设计。

#### 实际问题

```text
Execution Store：请求级幂等，不是消息队列
Runtime：进程内 LangGraph 执行
Queue/Worker：Super-agent 异步任务链路
HITL：受控草稿确认 + Super-agent 审批，不是统一中间件
Eval/Observability：旁路，不改变主控制流
```

#### 修订要求

```text
1. 4.1 先画“当前已实现架构”
2. 再画“目标架构”，并标注差异
3. 4.2 表增加“边界”列，明确：
   - Execution Store：request_id 幂等/回放，不负责排队
   - Runtime：状态、预算、循环、终态
   - Queue/Worker：异步任务，不参与交互式 /api/agent/run
   - HITL：受控写审批，不是 LLM 自动执行
```

### R-03 · 技术错误：Tool 清单和权限矩阵过期

#### 原文位置

V0.1：

```text
§5.1 当前目录结构只列 rag_search / execute_sql / calculator
§5.5 默认 B 端矩阵：
  admin / ent_admin / exec / analyst / ops → 3 tools
  cs → rag_search + calculator
```

#### 实际代码

`src/rag_demo/agent/registry.py` 注册 7 个 Tool：

```text
rag_search
execute_sql
calculator
prepare_followup_task
resolve_customer_identity
get_chat_user_profile
search_chat_user_profiles
```

`src/rag_demo/agent/policy.py` 实际矩阵：

```text
admin / ent_admin / exec / analyst / ops
  → 全部 7 个 Tool

cs
  → rag_search
     calculator
     resolve_customer_identity
     get_chat_user_profile
     search_chat_user_profiles

guest / disabled / demo
  → 无
```

另外：

```text
agent/tools/ 目录实际包含 action.py、chat_profile.py 等，
不只 rag.py / sql.py / calculator.py。
```

#### 结论

V0.1 的这一节不是“表达不够清楚”，而是**事实错误**。

同时要指出：`docs/agent.md` 本身也已经落后于代码（仍写 3 个 Tool）。  
这说明 Handbook 不能直接以旧文档为准，必须以代码/注册表/策略为准。

#### 修订要求

```text
1. 按 registry.py 更新 7 个 Tool
2. 按 policy.py 更新角色矩阵
3. 把 prepare_followup_task 标注为“受控写草稿 Tool”，不是普通只读 Tool
4. 明确 B 商家成员还会在 API 层被进一步限制为画像 Tool
5. 在证据表标注代码路径
```

### R-04 · 技术错误：失败请求的幂等语义写错

#### 原文位置

V0.1 §5.4：

```text
执行失败：记录 FAILED，同 request_id 不再自动重跑
```

#### 实际代码

`src/rag_demo/agent/service.py`：

```text
- runner 抛异常 / wall timeout：
  execute_agent 捕获 → store.fail(...) → 记录 FAILED
- runner 正常返回 result：
  即使 result["status"] 是 FAILED / TIMEOUT / MAX_STEPS_EXCEEDED，
  execute_agent 仍调用 store.complete(...)
  → execution_store 中记录为 COMPLETED
  → 重复 request_id 会回放该失败结果，而不是返回 409
```

`src/rag_demo/agent/execution_store.py`：

```text
claim 的状态：
  claimed / in_progress / completed / failed / conflict
只有 store.fail 才会把记录置为 FAILED。
```

#### 结论

文档把两种“失败”混在一起：

```text
A. 执行层异常 / wall timeout → execution_store = FAILED
B. Runtime 正常返回终态 FAILED / TIMEOUT / MAX_STEPS_EXCEEDED
   → execution_store = COMPLETED（保存该失败响应）
```

这会误导读者以为重复 request_id 一定会被拒绝或不会回放失败结果。

#### 修订要求

```text
1. 明确区分“执行记录状态”和“Agent 终态”
2. 说明 store.complete 也会保存 Runtime 失败终态
3. 说明目前没有 stale RUNNING TTL；进程崩溃可能留下 in_progress
4. 把“失败请求换 request_id”限定为实际行为，不要泛化
5. 建议后续增加测试：runner 返回 status=FAILED 时记录状态是什么
```

### R-05 · 技术错误：Checkpoint / Retry / 硬取消混淆

#### 原文位置

V0.1 §6.6：

```text
已实现：retry / checkpoint / 终态
已知限制：Python 线程不能安全强杀...
```

#### 实际代码

有两个不同机制：

```text
1. LangGraph SqliteSaver
   src/rag_demo/agent/checkpoint.py
   API 通过 get_checkpointer() 传入 run_agent
   thread_id 默认 execution_id
   保存 Graph state，可读 snapshot
   但当前 /api/agent/run 没有“恢复某次 interrupt 并继续”的对外 API

2. run_agent_with_retry(checkpoint_dir=...)
   src/rag_demo/agent/loop.py
   每次 attempt 写一个 JSON 文件，内容是失败复盘快照
   /api/agent/run 当前没有传 checkpoint_dir
   它不是可恢复的 LangGraph checkpoint
```

硬取消：

```text
run_agent 有 cancel_event 协作式取消
wall timeout 在 service.py 中只保证“调用方不再等待”
没有强杀线程
```

#### 结论

V0.1 把三者写成同一个“checkpoint/retry”能力，读者会误以为：

```text
超时后可以恢复执行；
checkpoint 可以继续 Agent；
retry 是恢复而非重新执行。
```

#### 修订要求

```text
1. 分三节：Graph Checkpoint / Attempt Snapshot / Wall Timeout
2. 明确 retry 是重新执行，不是 resume
3. 明确 /api/agent/run 当前没有 HITL resume 对外 API
4. 明确 SQLite saver 只保存状态，不等于硬取消
5. 明确进程崩溃后的 RUNNING 记录没有 TTL 回收
```

### R-06 · 设计不完整：Execution Store / Runtime / Queue 职责边界

#### 原文位置

V0.1 §4.2 表：

```text
Execution Store：request_id 幂等
Runtime：状态/预算/超时/重试
异步任务：superagent/job queue
```

方向正确，但缺少“不负责什么”的边界说明。

#### 需要补充

| 模块 | 负责 | 不负责 | 当前限制 |
|---|---|---|---|
| Execution Store | request_id 幂等、claim、回放、失败记录 | 排队、执行、重试决策 | 无 stale TTL；失败终态语义需澄清 |
| Agent Runtime | Graph、State、预算、终态、协作取消 | 进程外调度、写审批 | wall timeout 不硬杀线程 |
| Queue/Worker | 异步 WorkItem、lease、retry、action job | 交互式 /api/agent/run | 与主 Runtime 是两条链路 |
| HITL | 受控写草稿确认/审批 | 自动执行所有写操作 | 通用 interrupt API 未接入 |

### R-07 · 设计不完整：LangGraph 对比把“框架能力”和“项目采用”混在一起

#### 原文位置

V0.1 §7.2：

```text
LangGraph：状态/检查点、HITL/interrupt、可观测
自研 while 循环：需要自建
```

#### 问题

这些是 LangGraph 的**框架能力**，不等于 Qianke 全部采用并对外提供：

```text
Qianke 当前采用：
  LangGraph StateGraph
  SqliteSaver checkpointer
  interrupt_before_tools 原语（测试覆盖）
  callbacks trace

Qianke 当前未对外提供：
  通用 HITL resume API
  interrupt 驱动的用户确认接口
  checkpoint 恢复 API
```

#### 修订要求

对比表增加两列：

```text
框架能力 | Qianke 当前采用 | 对外状态
```

### R-08 · 设计不完整：安全边界展开不足

#### 原文位置

V0.1 §6.1。

#### 需要明确的边界

```text
1. SQL Tool：只读 + SELECT/WITH + LIMIT + 表白名单 + 超时
2. Tool Policy：角色级白名单；API 还会对商家成员再收口
3. Tool 返回内容：视为不可信数据，不应作为指令执行
4. answer_guard：是输出后置审查，不是 Prompt Injection 防火墙
5. Prompt Injection：当前没有独立、可验证的运行时防护层
6. 租户隔离：依赖 dataset_scope / _tenant_scope / 每企业库，不是仅 prompt 约束
7. HITL：受控草稿 + 独立确认 API 已存在；不是所有动作都自动执行
```

#### 结论

不要把：

```text
“有 Tool Policy”
等同于
“已完成 Prompt Injection 防护”
```

#### 修订要求

增加“已实现 / 未实现 / 风险”三列，并明确：

```text
工具输出不可信
检索文档不可信
写动作必须人工确认
模型不能成为授权者
```

### R-09 · 设计不完整：8.2 “已实现”缺少证据路径

#### 原文位置

V0.1 §8.2 表。

#### 问题

部分状态与证据不一致，且表内没有测试/命令列。

#### 应改为

```text
能力 | 状态 | 代码位置 | 测试/证据 | 限制
```

并修正：

```text
1. Tool 数量 3 → 7
2. 权限矩阵
3. HITL 受控草稿确认已实现
4. C 端独立 Graph 存在，不等于统一三端 Runtime
5. Super-agent queue 独立，不等于主 Agent 编排
```

### R-10 · 表达优化：术语未先定义

建议在正文开头增加术语表：

```text
Agent Runtime
Execution Store
Tool Contract
Tool Policy
HITL
Checkpoint
Attempt Snapshot
Wall Timeout
```

并统一：

```text
“单 Agent”只指 B 端主 Agent，不指整个平台
“失败”必须区分执行异常 / Runtime 终态 / 业务结果不满足
“恢复”只用于 checkpoint resume；retry 不得写成恢复
```

### R-11 · 表达优化：外部链接与版本适用性

V0.1 的延伸阅读已有一轮替换：

```text
OWASP 旧路径 308 → 使用 genai.owasp.org
SRE 链接超时 → 已移除
OpenTelemetry / 12factor 已验证可访问
```

仍需在发布前做：

```text
1. 构建期链接检查
2. 标注“外部资料版本/访问日期”
3. 与 996 行版本对齐后再发布
```

## 4. 建议修订优先级

```text
P0（必须改，否则误导）：
  R-01 队列关系
  R-03 Tool 清单/权限矩阵
  R-04 幂等失败语义
  R-05 checkpoint/retry/cancel
  R-09 证据表

P1（应该改，否则不完整）：
  R-02 当前/目标分层
  R-06 模块边界
  R-07 LangGraph 对比
  R-08 安全边界

P2（体验/规范）：
  R-10 术语
  R-11 链接/版本
```

## 5. V0.2 回应映射

V0.2 修订稿：

```text
docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.2.md
```

对应修改：

| 审核项 | V0.2 位置 |
|---|---|
| R-01 Queue 关系 | §4.1 拆为当前/目标架构，移除 Queue→Orchestrator |
| R-02 模块边界 | §4.2 增加“负责/不负责/状态” |
| R-03 Tool 清单/权限 | §5.1、§5.5、§8.2 |
| R-04 幂等失败语义 | §5.4 A/B/C/D |
| R-05 Checkpoint/Retry/取消 | §6.6 五类机制分开 |
| R-06 Execution Store/Runtime/Queue | §4.2、§5.4、§6.6 |
| R-07 LangGraph 对比 | §7.2 增加框架能力/Qianke 采用/对外状态 |
| R-08 安全边界 | §6.1 已实现/未形成/原则 |
| R-09 实现证据 | §8.2 增加代码/测试/限制；§8.3 修正 HITL 等状态 |
| R-10 术语 | V0.2 开头修订说明 + 正文统一 |
| R-11 外部链接 | §11 使用已验证链接 |

## 6. 审核建议

```text
1. 不覆盖 V0.1
2. 新建 V0.2 修订稿
3. V0.1 保留为审核基线
4. V0.2 必须逐项回应 R-01～R-11
5. V0.2 通过复审后，再进入 Docs 模块实施和第二阶段内容
```

## 6. 复审检查清单

```text
[ ] 当前架构与目标架构分图
[ ] Queue 不再出现在主 Agent 编排链
[ ] Tool 清单为 7 个
[ ] 角色矩阵与 policy.py 一致
[ ] prepare_followup_task 标注受控写草稿
[ ] execution_store 状态机与失败语义准确
[ ] checkpoint 三种机制分开
[ ] LangGraph 框架能力/Qianke 采用分列
[ ] 安全边界含 Prompt Injection 缺口
[ ] 8.2 每个“已实现”有代码/测试证据
[ ] 外部链接验证
[ ] 版本/行数与评审快照对齐
```
