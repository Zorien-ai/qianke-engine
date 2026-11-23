# Agent Architecture 文章内容质量审计报告

> **批次**：`docs/handbook/01-agent-architecture/` 第 2–10 篇（共 9 篇，不含基线第 1 篇）
> **审计日期**：2026-11-23
> **基线文章**：`docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md`
> **审计依据**：基线文章；`AGENTS.md`（§10、§12、§13、§18、§19）；`docs/agent.md`；`docs/agent-design-current-vs-target.md`；`src/rag_demo/` 相关代码；`tests/` 相关测试；`docs/product/`、`docs/e2e/`、`docs/handbook/_meta/` 相关文档
> **代码快照**：Git `32ad31bc26365e8d0cefe503e6c09cfcd2876eaa`（分支 `b-end-2.0-p0`，2026-11-22 19:15 +08:00），与基线文章 §8.3.1 记录的前缀 `32ad31bc2636` 一致
> **审计边界**：只做审计，未修改任何文章正文、配置或代码；本文件是本次唯一新增文件。所有"已运行"的测试均在本报告中如实记录命令与结果，未运行的项目明确标"未核验"。

## 0. 结论统计

| 结论 | 篇数 | 文章 |
|---|---:|---|
| 通过 | 6 | 02、04、05、06、07、08 |
| 条件通过 | 3 | 03、09、10 |
| 不通过 | 0 | — |

问题分级统计：**P0 = 0，P1 = 5，P2 = 20**（P2 含批次级 1 项外，逐篇明细见第 4 节）。

结论口径：

- **通过**：无 P0/P1；实现状态声明与代码/测试/文档一致；仅有少量 P2 措辞、版本或跨文档一致性问题。
- **条件通过**：存在 P1（技术准确性/实现状态/证据问题），必须修正后才适合发布；文章主体结论仍成立。
- **不通过**：存在 P0，或核心结论被证伪、证据被补造。

批次整体判断：**9 篇文章的事实主线基本成立**——B 端 7 个 Tool、Tool Policy、request_id 幂等、Execution Record 与 Agent Result 的语义区分、wall timeout 的"调用方等待上限"性质、C 端独立 Graph、Super-agent 独立队列/审批/审计、离线 Eval 指标，均能在当前代码、测试或文档中核验。主要风险集中在三类：

1. **Tool 错误码示例与分类存在与代码不符的"补造"内容**（09 篇，P1×2）；
2. **少数代码语义/数字表述不准确**（03 篇终态列表含 `RUNNING`；10 篇 `run_agent_with_retry` 默认重试次数；09 篇受控草稿幂等状态标注）；
3. **旧文档漂移被当作证据引用**：`docs/agent.md`（3 Tool、`READ_ONLY_VIOLATION` 示例）、`docs/agent-design-current-vs-target.md`（2026-10-28，"没有 C/A 端、没有 interrupt/HITL"）与本批文章陈述的当前状态冲突，而 04/05/08 篇仍把它们列为证据。

## 1. 审计方法与证据基线

### 1.1 核验方式

| 方式 | 说明 |
|---|---|
| 只读代码审阅 | 逐条对照文章中的代码片段、函数名、配置默认值、状态机、错误码 |
| 测试核验 | 阅读测试文件确认测试存在与覆盖点；**复跑**基线文章 §8.3.1 指定的 3 个测试文件（见 1.2） |
| 文档核验 | 核对被引用文档是否存在、是否支持文章结论；核对 `_meta/information-architecture.md` 的 frontmatter/结构规范 |
| 文件存在性 | 对文章"证据"小节列出的每个代码/测试/文档路径做存在性检查 |

### 1.2 已实际执行的验证（如实记录）

```powershell
cd F:\workspace\python\rag-demo
$env:QIANKE_CONTROL_BACKEND='sqlite'
$env:QIANKE_CEND_BACKEND='sqlite'
$env:LANGSMITH_TRACING='false'
$env:LANGCHAIN_TRACING_V2='false'
.\.venv\Scripts\python.exe -m pytest tests/test_agent_execution_safety.py tests/test_agent_checkpoint.py tests/test_agent_architecture.py -q -p no:cacheprovider
```

结果：**34 passed, 1 warning in 17.68s**（与基线文章记录的 "34 passed" 一致；本次多加了 `-p no:cacheprovider`，未改变用例集合）。

其他已核验证据：

```text
Git HEAD                  = 32ad31bc26365e8d0cefe503e6c09cfcd2876eaa（分支 b-end-2.0-p0）
var/handbook_agent_review_tests.log  存在（1312 字节，2026-11-23 14:49），内容为 34 passed
tests/evals/agent/baselines/v2.2.json 存在，Regression/Benchmark 指标与 docs/agent.md §7.3 一致
```

本报告未执行：真实 LLM Agent 运行、Eval runner 全量跑分、前端/浏览器 E2E、外网链接抓取。相关结论均标"未核验"或"以代码/文档为准"。

### 1.3 未被本批次文章新增的测试数字

02、03、10 篇都只引用基线 01 篇的"34 passed / commit 32ad31bc2636"，**没有各自捏造新的跑分**，这一点符合"不补造证据"要求；09 篇没有引用数字。审计确认这些引用成立（间接证据：基线 01 §8.3.1 与本报告 1.2 的复跑结果）。

## 2. 批次级检查（frontmatter / 结构 / 证据索引 / 未核验）

### 2.1 二级章节结构

9 篇均为 **12 个 `##` 二级章节**，数量合规。但与 `docs/handbook/_meta/information-architecture.md` §6（规范写"严格按以下 11 节"）以及同批其他分类（如 `02-enterprise-governance/01-identity-and-access-management.md`、`06-human-in-the-loop.md` 为 12 节固定骨架：为什么/基本机制/总体架构/关键设计/工程实现/企业级要求/方案对比/Qianke 实践/评估验收/常见误区/总结/延伸阅读）相比：

- 本批 02–10 篇采用"主题定制"分节，普遍缺少固定的"企业级要求""方案对比""评估 / 验收"节；
- 10 篇把"总结"与"延伸阅读"合并为第 12 节，是批内唯一合并者（其余 8 篇为 11 总结 + 12 延伸阅读）。

判断：属**批次结构不统一（P2，批次级）**，不影响事实正确性；若 Handbook 要统一导航/摘要抓取，建议后续统一模板。基线 01 篇本身也是主题定制分节，说明这是 Agent Architecture 分类的既定做法，因此不逐篇计为缺陷，只在 10 篇单列结构 P2。

### 2.2 frontmatter

9 篇 frontmatter 字段齐全（title/description/section/section_order/order/slug/doc_status/implementation_status/version/updated/reading_minutes/prerequisites/tags/related），`title` 与正文 H1 一致，`slug` 全局唯一（与 `_meta/versions/` 归档重复属预期），`order` 2–10 连续，`section_order = 1`，`updated = 2026-11-23` 与文件修改时间一致。

唯一不合规：**07 篇 `description` 为 72 字，低于规范"80–160 字"下限**（P2）。

### 2.3 被引用文件/测试存在性

对 9 篇"证据/延伸阅读"中出现的代码、测试、文档路径逐一检查，**全部存在**：

```text
src/rag_demo/agent/{state,loop,service,execution_store,tool,registry,policy,checkpoint,actions}.py     ✓
src/rag_demo/agent/tools/{rag,sql,calculator,action,chat_profile}.py                                   ✓
src/rag_demo/c_end/agent.py、src/rag_demo/superagent/{store,queue_pg,runtime,worker}.py                ✓
src/rag_demo/memory_context.py、src/rag_demo/chat_memory.py、src/rag_demo/b_end/identity.py            ✓
src/rag_demo/api/main.py、src/rag_demo/api/c_end.py                                                    ✓
tests/test_agent_{architecture,execution_safety,checkpoint,actions}.py                                 ✓
tests/{test_superagent.py,test_c_end_negotiation.py,test_memory_context.py,test_c_end_memory.py,...}    ✓
docs/{agent.md,agent-design-current-vs-target.md,architecture-diagrams.md,数据模型.md,接口文档.md}      ✓
docs/product/agent-memory-context.md、docs/e2e/dual-pet-negotiation.md、AGENTS.md                       ✓
tests/evals/agent/、tests/evals/agent/baselines/v2.2.json                                               ✓
```

### 2.4 跨文档漂移（批次级风险，P2）

本批多篇文章把旧文档列为证据，但旧文档内容与当前代码/文章冲突：

| 旧文档 | 旧文档说法 | 与本批冲突点 |
|---|---|---|
| `docs/agent.md`（Runtime v0.2.2） | §2 只有 3 个 Tool；§3.7 角色矩阵仍为 3 Tool；§3.8 "HITL API / C 端确认流程：尚未接入"；§10 "没有 Planner、Memory、多 Agent 协同"；§5.3 错误示例 `READ_ONLY_VIOLATION` | 02/09 篇写 7 Tool；07 篇写记忆已部分落地；C 端已有 `interrupt` + `resume_c_agent` |
| `docs/agent-design-current-vs-target.md`（2026-10-28） | "3 个原子 Tool"、"没有真实写操作、没有 C/A 端、没有 interrupt/HITL" | 04/05/08 篇写 C 端独立 Graph、Super-agent 已实现 |

结论：**文章自身的事实（以代码为准）基本正确，但证据索引指向的旧文档会削弱可复核性**。建议发布前在证据索引注明"该文档为旧版快照，以当前代码为准"，或更新旧文档（本次审计不修改）。

### 2.5 未联网核验项

- 所有官方外部链接（LangGraph/FastAPI/OWASP/NIST/PostgreSQL/OpenTelemetry）未做网络可达性核验，**未核验**。
- 文章中的生产 SLO、成本看板、前端体验类"缺失/部分实现"陈述（02 §3.6、§9；10 §10）未通过运行系统验证，**未核验**。

## 3. 逐篇审计

### 3.1 `02-agent-vs-enterprise-agent.md`

**结论：通过**（P0 0 / P1 0 / P2 4）

**实现状态声明是否成立：成立。** frontmatter `implementation_status: 已实现 + 已设计` 与正文 §8 的三分法（已实现 / 部分实现 / 已设计·规划中）基本准确；正文未把规划能力写成已实现，并明确"不要把目标架构图当作当前运行图"（§4.3）。

**证据核验**

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 认证/会话、企业 dataset 绑定、`dataset_scope`/`_tenant_scope` 已实现；前端不能传 dataset | `api/main.py:312-329`（`_tenant_dataset` 按账号推导）、`:358-374`（`_tenant_scope` finally 恢复）、`agent/context.py`；`AgentRunIn`（`:619-623`）无 dataset 字段 | 成立 |
| ToolPolicy.for_account、执行时复核 `TOOL_NOT_ALLOWED`、7 个注册 Tool、商家操作者 API 二次收口 | `agent/policy.py:17-25,68-77`；`agent/loop.py:278-286`；`agent/registry.py:18-27`；`api/main.py:1413-1421` | 成立 |
| 受控草稿 `prepare_followup_task` + 独立 `confirm_agent_action` | `agent/tools/action.py:22-47`；`agent/actions.py:135-215`；`api/main.py:1465-1471` | 成立 |
| request_id 幂等、execution_id/parent_execution_id、max_steps/max_tool_calls/timeout/token budget、retry、SqliteSaver（有限使用） | `agent/service.py:213-318`；`agent/execution_store.py:144-229`；`agent/state.py:25-42`；`agent/loop.py:501-576`；`agent/checkpoint.py:20-44` | 成立 |
| `wall timeout` 是调用方等待上限，不是硬取消 | `agent/service.py:41-68`；`api/main.py:1424-1426,1448-1449` | 成立 |
| Execution Record=COMPLETED ≠ Agent Result=COMPLETED | `agent/service.py:304-317`（runner 返回 dict 即 complete） | 成立 |
| 7 指标 Eval 已实现 | `tests/evals/agent/evaluator.py:332`、`runner.py:100-123`、`baselines/v2.2.json:15-20,72-77` | 成立 |
| Prompt Injection 专项测试未完成 | `tests/` 内无 prompt injection 专项测试（0 命中） | 成立 |

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §3.4 | "通用 HITL / interrupt resume API：未接入" | 表述未限定 B 端。C 端已实现 `interrupt(...)`（`c_end/agent.py:563`）与 `resume_c_agent`（`:751-780`），另有 Super-agent 独立审批；笼统写"未接入"会让读者低估已实现能力 | 改为"B 端主链路未接入通用 HITL；C 端已有专用 interrupt/resume；Super-agent 有独立审批链路" |
| P2 | §3.5 | "retry：已实现（默认 max_retries=0）" | 只对 API 请求模型成立（`api/main.py:623`），`run_agent_with_retry` 函数默认是 `max_retries=1`（`loop.py:505`） | 明确"API 默认 0、函数默认 1、上限 3" |
| P2 | §6.3 | "wall timeout 后：Execution Record 可能 FAILED" | 在超时路径上是确定行为：`AgentRunTimedOut` → `store.fail`（`service.py:309-311`），写成"可能"弱化了语义 | 改为"超时 → store.fail → FAILED"，并保留"worker 仍可能收尾"的说明 |
| P2 | §8.2 | "部分实现：C 端：独立 Agent Graph；Super-agent：独立队列/Worker" | C 端与 Super-agent 是"已实现但未统一"，放进"部分实现"清单会被读成能力本身未完成 | 拆为"已实现（独立链路）"与"未统一"两类，与基线 01 §8.3 的表格口径对齐 |

**未核验项**：LangSmith 实际 tracing 效果（仅确认 `config.py:45-47` 自动开关存在）；`ai_monitor`/Eval 报告的运行时表现；外部链接可达性。

**一句话总评**：一篇结构清楚、状态分层诚实的对比文章，代码证据基本成立；只需把 HITL、retry 默认值与"部分实现"标签限定到 B 端/API 口径，即可直接发布。

---

### 3.2 `03-agent-runtime.md`

**结论：条件通过**（P0 0 / P1 1 / P2 4）

**实现状态声明是否成立：基本成立。** `已实现 + 已设计` 与正文 §8 的清单一致；已实现项均能指向代码。唯一实质问题是 §2.3 把 `RUNNING` 列入"终态"，属状态语义错误。

**证据核验**

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| `AgentConfig` frozen dataclass，四字段与默认值；`max_steps/max_tool_calls` 不允许 0，`timeout>0`，`max_total_tokens>=0` | `agent/state.py:25-42` | 成立 |
| `max_total_tokens=0` 关闭预算检查；检查发生在 LLM 返回后；`usage` 缺失可能为 0 | `loop.py:293-299`；`TraceCallbackHandler.on_llm_end`（`:81-102`） | 成立 |
| `AgentState` 字段与文章逐字一致 | `state.py:45-61` | 成立 |
| 终态清单（除 RUNNING 外 8 个） | `state.py:11-22` | 成立（RUNNING 非终态，见问题） |
| 幂等 `request_id + scope(dataset:account) + request_hash`；回放/409/失败语义 | `service.py:213-254`；`execution_store.py:59-76,144-184` | 成立 |
| runner 正常返回 FAILED → `store.complete`；抛异常/超时 → `store.fail` | `service.py:304-317` | 成立 |
| retry 只重试 FAILED/TIMEOUT/超步数/超工具数；不重试 BUDGET/CANCELLED；每次新 execution_id、parent 指向上一 attempt；API 默认 0 | `loop.py:493-576`；`api/main.py:623,1439` | 成立（"API 默认"表述正确） |
| checkpointer：SqliteSaver、thread_id 默认 execution_id、API 传入 `get_checkpointer()`、无通用 resume | `agent/checkpoint.py:20-44`；`loop.py:422-424`；`api/main.py:1437` | 成立（B 端口径；C 端另有 resume，见问题） |
| `_run_with_deadline`：线程 + Event，超时抛 `AgentRunTimedOut`，API 504，`store.fail` | `service.py:41-68`；`api/main.py:1448-1449` | 成立 |
| 证据：34 passed / commit 32ad31bc2636 | 本报告 §1.2 复跑 34 passed；`var/handbook_agent_review_tests.log` | 成立 |

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| **P1** | §2.3 | 标题为"终态"，代码块首行列出 `RUNNING` | `RUNNING` 是初始/中间态，不是终态（`state.py:14`；`loop.py:139-148` 的 `_TERMINAL_STATUSES` 不含 RUNNING）。在讲状态语义的核心小节里混淆终态，会误导读者对状态机的理解 | 把 `RUNNING` 移出终态列表，单列"初始/中间态：RUNNING"；终态仅保留 COMPLETED/FAILED/TIMEOUT/CANCELLED/超限/BUDGET/TOOL_NOT_ALLOWED |
| P2 | §4.3 | 伪代码 `if next_tool_count > config.max_tool_calls: _terminate(...)` | 实际代码不是 `_terminate`，而是在返回 dict 上设置 `status=MAX_TOOL_CALLS_EXCEEDED`（`loop.py:287-292`）；且节点入口还有 `tool_count >= max_tool_calls` 前置检查（`:268`）。伪代码还漏了 token 检查的 `tracer is not None and config.max_total_tokens` 守卫（`:293`） | 标注为"伪代码/简化"，或按 `loop.py:249-306` 重写 |
| P2 | §4.1/§4.2 | 正常路径写 `→ run_agent` | 实际 API 走 `execute_agent → run_agent_with_retry → run_agent`（`service.py:237`），retry 层被省略；与 §6.3 自述不一致 | 路径补上 retry 层，或注明"单次执行" |
| P2 | §1.2/§5 | "Runtime 不负责业务权限决策（Tool Policy / Data Access）" | Runtime 的 chatbot 节点确实执行了 ToolPolicy 复核并产生 `TOOL_NOT_ALLOWED`（`loop.py:278-286`）。"不定义策略"成立，"不负责"过宽 | 改为"Runtime 不定义权限策略，但执行时复核 ToolPolicy 结果" |
| P2 | §6.4 | "没有通用对外 resume API" | 对 B 端主链路成立；C 端已有 `resume_c_agent`（`c_end/agent.py:751-780`） | 限定为"B 端/通用 resume API 未提供；C 端已有专用 resume" |

**未核验项**：真实运行下 token usage 缺失时的统计表现；LangGraph SqliteSaver 并发行为；外部链接可达性。

**一句话总评**：Runtime 机制讲得扎实、默认值与代码对得上，但"终态"小节把 RUNNING 混进去是硬伤，修掉这一处、再把伪代码与 B/C 端口径标注清楚即可发布。

---

### 3.3 `04-agent-orchestrator.md`

**结论：通过**（P0 0 / P1 0 / P2 3）

**实现状态声明是否成立：成立。** `已设计 + 部分实现` 与事实一致：当前没有独立 Orchestrator 类，B 端由 LangGraph 图承担，C 端独立图，统一三端 Orchestrator 未上线。

**证据核验**

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 当前无独立 `Orchestrator` 类，B 端为 `chatbot↔tools` 图 | `src/` 全量检索无 Orchestrator 实现；`loop.py:322-358` | 成立 |
| `should_continue`：终态 → END；有 tool_calls → tools；否则 END | `loop.py:311-319` | 成立（snippet 简化，见问题） |
| Execution Store 在 Graph 外 | `service.py:244-254,304-317` | 成立 |
| Tool Policy 在 bind_tools 与执行前检查 | `loop.py:203-205,278-286`；`api/main.py:1413` | 成立 |
| Runtime 限制在 chatbot 节点内检查 | `loop.py:249-273` | 成立 |
| Super-agent 队列不在主图 | `superagent/runtime.py`、`superagent/store.py` | 成立 |
| C 端 Graph 独立、不是统一 Orchestrator 选择 | `c_end/agent.py:527-606`；无跨端路由代码 | 成立 |
| A 端审计/监控、不是 Agent Graph | 未发现 A 端 StateGraph；A 端为管理页/审计 API | 成立 |
| 证据文件均存在 | `loop.py`、`service.py`、`c_end/agent.py`、`superagent/runtime.py`、`tests/test_agent_architecture.py` | 成立 |

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §2 表格 | "Queue/Worker：长任务如何异步执行？—— WorkItem、claim、lease、retry" | 把 WorkItem 划给 Queue/Worker 与 08 篇的边界划分（WorkItem=业务任务，Job=执行任务）不一致；WorkItem 实际由 `superagent/store.py` 维护，队列只认领 Job（`sa_job`） | 改为"Queue/Worker 管理 Job 的 claim/lease/retry；WorkItem 由任务存储维护" |
| P2 | §3 | `def should_continue(state): ... last = state["messages"][-1]; return "tools" if last.tool_calls else END` | 实际实现有 `messages` 为空守卫并使用 `getattr(last, "tool_calls", None)`（`loop.py:315-319`）；伪代码过于简化 | 标注"伪代码"，或与实现对齐 |
| P2 | §5.1 表格 | chatbot："调 LLM、检查预算/取消/终态、决定 tool call 或结束" | 漏了 chatbot 节点内的 ToolPolicy 执行时复核（`denied → TOOL_NOT_ALLOWED`），而这是"未授权 Tool 不执行"的落点 | 在 chatbot 职责中补"复核未授权 tool call" |

**未核验项**：A 端监控页面的实际数据来源与覆盖范围；外部链接可达性。

**一句话总评**：一篇职责边界讲得很清楚的编排文章，正确指出"LangGraph 图 ≠ 企业级统一 Orchestrator"这一常见误区；仅需修正 WorkItem 归属与伪代码细节。

---

### 3.4 `05-multi-agent-collaboration.md`

**结论：通过**（P0 0 / P1 0 / P2 2）

**实现状态声明是否成立：基本成立，但清单不完整。** "B 端主 Agent 仍是单 Agent、通用 Multi-Agent 协作属于规划"的核心判断成立；遗漏了项目已有的 C/B 双宠谈判 v1（两个 Agent 人设的确定性协议交互），需要补充边界说明。

**证据核验**

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| B 端主 Agent 单 Agent | `agent/loop.py` 单图；AGENTS.md §18.4 | 成立 |
| C 端导购 Agent 独立 Graph | `c_end/agent.py:527-606`（`build_c_graph`、`CAgentState`） | 成立 |
| Super-agent 独立 WorkItem/Queue/Worker + 审批动作 | `superagent/{store,queue_pg,runtime,worker,actions}.py`；`tests/test_superagent.py` | 成立 |
| 多 Agent 协作/共享证据板/跨 Agent 权限模型规划中 | 无通用 Supervisor/多 Agent 编排代码；三端目标见 AGENTS.md §18 | 成立 |
| 证据：`docs/agent-design-current-vs-target.md`、AGENTS.md §18 | 文件存在；但该 docs 文档日期 2026-10-28，仍写"没有 C/A 端"，不支持文章"当前已实现"部分 | 部分支持（见问题） |

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §8"已实现"清单 | 只列 B 端单 Agent / C 端独立 Graph / Super-agent | 遗漏已落地的 C/B 双宠谈判 v1：`c_end/negotiation.py:337` 明确"两个独立 Agent 的确定性多轮报价"，`docs/e2e/dual-pet-negotiation.md`（2026-10-31）有真实 E2E，AGENTS.md 变更记录 1.9.0 记录"双宠谈判 v1"。文章"Multi-Agent 属于规划"若不加限定，会与项目其他文档冲突 | 在"已实现"中补充"双宠谈判 v1：C/B 两个 Agent 人设的确定性协议交互（E2E 已验证），不等于通用 Multi-Agent 编排；自由 LLM 双 Agent 博弈仍是刻意不做" |
| P2 | §8"证据" | `docs/agent-design-current-vs-target.md` | 该文档是 2026-10-28 的目标设计快照，正文仍写"3 个原子 Tool、没有 C/A 端、没有 interrupt/HITL"（`:4,26,30`），不能支撑文章的"当前已实现"陈述 | 证据改为 `src/rag_demo/c_end/agent.py`、`superagent/`、`AGENTS.md` §18/§19 与 `docs/e2e/dual-pet-negotiation.md`；旧文档仅用于目标态 |

**未核验项**：双宠谈判在公网/生产环境的稳定性（只核验了代码、E2E 文档与测试文件存在）；外部链接可达性。

**一句话总评**：对"多 Agent 是复杂度工具"的论证站得住，但实现清单需要补上双宠谈判这一既有协议交互，并把旧目标文档换成语义正确的证据。

---

### 3.5 `06-agent-state-management.md`

**结论：通过**（P0 0 / P1 0 / P2 2）

**实现状态声明是否成立：成立。** `已实现` 对应 `AgentState`、终态、request/execution identity、SqliteSaver checkpointer 均可核验；§8 的"部分实现：跨端统一 State、通用 State 恢复 API"也与事实一致。

**证据核验**

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| `AgentState` 字段与代码逐字一致 | `state.py:45-61` | 成立 |
| 状态机：RUNNING → COMPLETED/超限/TIMEOUT/CANCELLED/BUDGET/TOOL_NOT_ALLOWED/FAILED | `state.py:11-22`；`loop.py:139-148,249-306` | 成立 |
| 终态只能进入一次、终态后不再执行工具、不被后续节点覆盖 | `loop.py:311-319`（终态 → END）；`loop.py:209-215`（`_terminate`） | 成立 |
| SqliteSaver、thread_id 默认 execution_id、API 传 `get_checkpointer()`、可读 snapshot、无通用 resume | `agent/checkpoint.py`；`loop.py:420-424`；`api/main.py:1437`；`tests/test_agent_checkpoint.py:31-48` | 成立 |
| retry 每次新 execution_id、parent 指向上次、不是 checkpoint 继续 | `loop.py:525-570`；`tests/test_agent_architecture.py:238-271` | 成立 |

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §4 表格 | "全量 SQL 结果：不直接放 State，只放摘要/引用" | 这不是当前实现：LangGraph `ToolNode` 默认把工具返回（含 SQL `rows`，受 `SQL_FETCH_MAX=100` 截断）写入 `messages`（`loop.py:344`；`config.py:114`）。读者会把目标边界当成现状 | 标注为"目标边界/建议"；并说明现状是"工具结果进 messages，靠 fetch limit 截断" |
| P2 | §2/§3 | "Qianke 当前的 AgentState" / 通用标题 | 只描述 B 端 `AgentState`；项目另有 C 端 `CAgentState`（`c_end/agent.py:221`），跨端 State 尚未统一（文章 §8 也承认） | 标题与正文注明"B 端主 Agent 的 State" |

**未核验项**：C 端 `CAgentState` 的字段与生命周期（未纳入本次逐字段比对）；checkpointer 在并发线程下的行为（测试为单线程 tmp_path）。

**一句话总评**：State 的边界与生命周期讲得干净，但"全量 SQL 结果不放 State"是设计目标而非现状，需补一句实现说明，避免读者误解。

---

### 3.6 `07-agent-memory.md`

**结论：通过**（P0 0 / P1 0 / P2 3）

**实现状态声明是否成立：基本成立。** `已实现 + 部分实现` 与 `docs/product/agent-memory-context.md` 的"Phase 1 + 2A + 2B + 3A + 3B + 3C 已落地"一致；正文 §8 每一项都能在代码/文档中找到对应入口，"统一 Memory Runtime 仍是目标"的限定也正确。

**证据核验**

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 身份解析/歧义判定；租户/客户/DELETED 过滤；来源/更新时间/置信度 | `memory_context.py:20-45,169-228,251-263`；`tests/test_memory_context.py` | 成立 |
| B 端会话记忆接入 | `chat_memory.py:29-130,170-219`（Phase 2A） | 成立 |
| C 端候选记忆状态机；确认/拒绝/写回；版本/审计字段 | `c_end/store.py:3918`（create_memory_candidates）；`api/c_end.py:388-410`；`tests/test_c_memory_candidates.py`、`test_c_memory_conflict_version.py` | 成立 |
| C 端自动复盘候选 / 常驻脚本 | `c_end/memory_review.py:119`；`scripts/c_memory_review.py` 存在；`docs/product/agent-memory-context.md:49-73` | 成立 |
| 身份消歧生产入口 | `b_end/identity.py`；`agent/tools/chat_profile.py:19,67-75`；`tests/test_b_identity.py` | 成立 |
| CApp 待确认记忆 UI | `web/src/views/CApp.vue:2772,2832` | 成立 |
| 候选确认接口路径 | `api/c_end.py:388-410`（挂载在 `/api/c` 下） | 成立 |
| 文档依据 `docs/product/agent-memory-context.md` | 存在，`:7-30` 为落地进度表 | 成立 |

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | frontmatter `description`（第 3 行） | "区分会话记忆、用户长期记忆、业务状态和审计记录，解释身份解析、读写边界、候选记忆、版本与冲突；对照 Qianke Engine 已落地的记忆链路" | 72 字，低于 `information-architecture.md` 规定的 80–160 字 | 扩写至 80 字以上（补"租户隔离/时效过滤"等要点） |
| P2 | §12 延伸阅读 | "多租户隔离架构（规划中，见信息架构）" | 该文章已存在：`docs/handbook/02-enterprise-governance/03-multi-tenancy-isolation.md`，frontmatter 为 `implementation_status: 已实现 + 部分实现`（`:9`）。写成"规划中"既过时又不是可点击链接 | 改为真实相对链接并沿用其"已实现 + 部分实现"状态 |
| P2 | §4 写路径 | "不能：LLM 直接写长期记忆；用户未确认的推断直接生效" | 未说明 B 端例外：`chat_memory.update_memory` 由 LLM 生成摘要/实体后直接写 `chat_sessions.context_state`（`chat_memory.py:170-219`），无候选确认。该数据是会话记忆而非长期记忆，但文章读写路径未区分，易被读成"所有记忆都先候选确认" | 注明"会话记忆（B 端摘要/实体）可由 LLM 直接写并带来源/时效元数据；长期记忆必须候选确认" |

**未核验项**：CApp 记忆 UI 的实际交互（只核验代码引用）；`memory_review` 常驻脚本的实际调度（systemd/watch 方式未运行）；`docs/product/agent-memory-context.md` 中"Phase 3C 冲突 supersede"的完整链路（只核验文档与测试文件存在）。

**一句话总评**：记忆的分层、候选与版本链路与项目文档高度一致，是 9 篇中"实现状态"写得最贴实际的一篇；只需修 frontmatter 字数与两处状态/边界表述。

---

### 3.7 `08-task-lifecycle-management.md`

**结论：通过**（P0 0 / P1 0 / P2 3）

**实现状态声明是否成立：成立。** `已实现 + 部分实现` 与 Super-agent 代码/测试一致：WorkItem/Job、原子 claim、lease、retry、DEAD、Worker 恢复、审批动作、执行审计均可核验；"与主 Agent Runtime 的统一任务抽象"确实未完成。

**证据核验**

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| WorkItem / Job 表与状态机 | `superagent/store.py:369-526`（PENDING/RUNNING/WAITING_APPROVAL/DONE/CANCELLED/FAILED/EXECUTING/REJECTED/STUCK/EXECUTION_FAILED）；`superagent/queue_pg.py:54-85`（`sa_job`，PENDING/RUNNING/DONE/FAILED/DEAD） | 成立 |
| `claim_next_job`/`renew_lease`/`requeue_expired_jobs`/`scan_stuck_work_items` | `queue_pg.py:229-249`；`store.py:1115-1130`；`control/job_queue.py:163-204,262,294` | 成立 |
| 多 Worker 并发/FOR UPDATE SKIP LOCKED | `control/job_queue.py:184`（`FOR UPDATE SKIP LOCKED`） | 成立 |
| max_attempts 后 DEAD、可人工重放 | `control/job_queue.py:171-174,294-318`；`queue_pg.py:202-220`（`replay_job` 仅允许 DEAD/FAILED） | 成立 |
| Worker 恢复 | `superagent/runtime.py:193`（`recover_jobs`） | 成立 |
| 审批 → ACTION Job → 执行 → 审计 | `superagent/store.py:459-526`；`runtime.py:44`（`kind="ACTION"`）；`actions.py:180-220`；`store.py:585`（`list_action_audit`） | 成立 |
| Watchdog 标记 STUCK、不伪造完成 | `superagent/watchdog.py`；`store.py:1115-1130`；`tests/test_superagent.py:180-198` | 成立 |
| 证据文件均存在 | `superagent/{store,queue_pg,runtime,worker}.py`、`docs/agent-design-current-vs-target.md` | 存在（后者不支持，见问题） |

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §4 原则 | "终态不能被后续 Worker 覆盖" | Worker 主路径成立（`finish_work_item` 有 `AND status='RUNNING'` 守卫，`:404`；`cancel_work_item` 有状态守卫，`:434`），但 `complete_execution`（`:508-519`）与 `fail_work_item`（`:443-456`）的 UPDATE 无状态守卫；`fail_work_item` 目前无调用点，属于潜在缺口 | 标为"Worker 主路径保证"，或注明"complete_execution/fail_work_item 尚无状态守卫，补写前需复核" |
| P2 | §4 状态清单 | WorkItem 状态列出 9 个 | 实际还有 `EXECUTING`（审批通过后，`store.py:474`）；清单自称"常见状态"可不穷举，但读者会误以为状态机只有 9 个 | 补 `EXECUTING`，或明确写"非穷举" |
| P2 | §8 证据 | `docs/agent-design-current-vs-target.md` | 该文档（2026-10-28）早于 Super-agent（AGENTS.md 变更 2.1.0 / 2026-11-02），内容不包含 WorkItem/Job/审批/审计，不能作为本节证据 | 换为 `superagent/store.py`、`queue_pg.py`、`tests/test_superagent.py`、`AGENTS.md` §18；旧文档只保留为目标态参考 |

**未核验项**：Super-agent 在 PostgreSQL 队列模式下的真实并发/租约行为（本次只读代码与 SQLite 测试；PG 测试需真实 PG）；"跨任务统一看板 / 统一任务资源配额"（未找到明确实现证据，文中已列为部分实现，本次未核验）。

**一句话总评**：任务生命周期是 9 篇中代码证据最充分的一篇（claim/lease/DEAD/watchdog 均有测试），只需修正"终态不被覆盖"的绝对化措辞并把旧文档证据换掉。

---

### 3.8 `09-agent-tool-calling.md`

**结论：条件通过**（P0 0 / P1 3 / P2 2）

**实现状态声明是否成立：部分成立。** 7 Tool 注册、Tool Contract、Tool Policy、执行时复核、SQL 只读、Calculator AST、受控草稿均可核验；但 **Tool 错误码示例与错误分类与代码不符（近乎补造）**，且受控草稿的幂等风险被降级为"缺测试"。

**证据核验**

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| `ToolError`/`ToolResult` 结构 | `agent/tool.py:10-51` | 成立 |
| 7 个 Tool 注册；每个 Tool 有 name/description/schema/fn | `agent/registry.py:18-27,30-75`；`agent/policy.py:17-25` | 成立（LangChain 层是 `args_schema`，Contract 层是 `input_schema`，见 P2） |
| Tool Policy 只暴露子集 + 执行时复核 | `loop.py:275-286`；`api/main.py:1413-1421` | 成立 |
| SQL 只读、必须 LIMIT、表白名单、只读连接、statement timeout、fetch limit | `tools/sql_tool.py:34-40,76-113,116-136`；`config.SQL_FETCH_MAX=100` | 成立 |
| Calculator 用 AST、无裸 eval | `tools/calculator.py:1-60` | 成立 |
| 受控草稿 DRAFT + requires_confirmation + 独立 confirm | `tools/action.py:22-47`（`:43`）；`actions.py:135-215` | 成立 |
| 画像 Tool 租户/客户边界 | `tools/chat_profile.py:29-56` | 成立 |
| 测试证据 `tests/test_agent_architecture.py` | 存在，含 Tool Contract/注册/SQL/Calculator 用例（`:22-391`） | 成立 |
| **失败示例 `error.code = READ_ONLY_VIOLATION`** | 全仓库 `src/` 检索 0 命中；SQL 安全实际返回 `SQL_VALIDATION_ERROR`（`tools/sql_tool.py:152,169`） | **不成立（补造）** |
| **§7 错误码分类** | 实际码：`INVALID_ARGUMENTS`/`TOOL_ERROR`（`tool.py:68-74`）、`SQL_VALIDATION_ERROR`/`SQL_EXECUTION_ERROR`（`sql_tool.py:152-153`）、`RAG_SEARCH_ERROR`（`tools/rag.py:52`）、`INVALID_EXPRESSION`/`DIVISION_BY_ZERO`（`calculator.py:119-123`）、`PROFILE_*`/`IDENTITY_*`（`chat_profile.py`）、`ACTION_*`/`DEMO_READ_ONLY`（`actions.py`）。`LIMIT_REQUIRED` 全仓库 0 命中；`TENANT_SCOPE` 是函数名 `_tenant_scope` 而非错误码；`NOT_FOUND`/`FORBIDDEN` 只作为 `ORDER_NOT_FOUND`/`ACTION_FORBIDDEN` 等后缀存在 | **部分不成立** |
| "缺少对 retry 重复草稿的专项测试" | `create_followup_draft`（`actions.py:135-189`）每次 `uuid4` 新建 action_id，无 request_id 唯一约束/去重（`:80-83` 是普通索引）；重复调用会产生多条 DRAFT | 状态标注不准确（不只是测试缺口） |

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| **P1** | §2 Tool Contract 失败示例 | `{"ok": false, "data": {}, "error": {"code": "READ_ONLY_VIOLATION", "message": "只允许 SELECT"}}` | 当前代码不存在 `READ_ONLY_VIOLATION` 错误码；SQL 安全校验失败实际是 `SQL_VALIDATION_ERROR`（message 为"仅允许 SELECT/WITH、必须带 LIMIT、仅白名单表"）。该示例在"Qianke 当前"语境下会被当成真实契约。来源可追溯到旧文档 `docs/agent.md:358` 与基线 01 §4.1 的同类示例 | 改为真实错误码示例：`SQL_VALIDATION_ERROR`；并在基线/旧文档层面统一清理该虚构码 |
| **P1** | §7 错误分类 | "参数错误 → INVALID_ARGUMENTS / SQL 安全 → READ_ONLY_VIOLATION / LIMIT_REQUIRED / 数据不存在 → NOT_FOUND / 越权 → FORBIDDEN / TENANT_SCOPE / 工具异常 → TOOL_ERROR" | 与代码不符：`READ_ONLY_VIOLATION`、`LIMIT_REQUIRED` 不存在（前者只出现在文档，后者只出现在本文）；`TENANT_SCOPE` 是函数名；`NOT_FOUND`/`FORBIDDEN` 在 Tool 层只是复合码后缀。真实码见上表。若这是"行业通用分类"，必须明确标注"示例/通用"，不能放在 Qianke 实现语境 | 二选一：①改为当前真实码表；②明确写"以下是通用错误分类建议，Qianke 当前码见附录"，并给出真实码清单 |
| **P1** | §8 幂等与重试 | "当前仍缺少对 retry 重复草稿的专项测试，属于待补强项" | 低估了缺口：`prepare_followup_task`/`create_followup_draft` 没有幂等键或唯一约束，重复调用会产生多条 DRAFT（`actions.py:135-189`；`agent_action` 表只在 `:80-83` 建普通索引）。读者会以为"机制已有、只缺测试" | 改为"当前草稿写入无幂等键/唯一约束，retry 或重复调用可能产生多条 DRAFT；需补幂等键与回归测试"，或实现后按实现状态标注 |
| P2 | §3 | "每个 Tool 有 name / description / input_schema / fn" | LangChain 工具层实际用 `args_schema`（`LangChain @tool`），`input_schema` 是 `Tool` Contract（`tool.py:54-65`）的字段；两种表示未区分 | 写"LangChain 层 args_schema；JSON Contract 层 input_schema" |
| P2 | §12 | "Human-in-the-loop 人工审批（规划中，见信息架构）" | 该文章已存在：`docs/handbook/02-enterprise-governance/06-human-in-the-loop.md`，frontmatter 为 `implementation_status: 已实现 + 部分实现`（`:9`）；写成"规划中"过时且无链接 | 改为真实链接并沿用其状态 |

**未核验项**：画像 Tool 在真实 B 账号下的跨租户拒绝路径（只核验代码与 policy 测试）；`prepare_followup_task` 的端到端 retry 行为（未运行 Agent）；外部链接可达性。

**一句话总评**：Tool 治理主线（契约/授权/只读/计算/草稿）讲得对，但错误码部分是"旧文档污染 + 补造"，且幂等缺口被轻描淡写——这三处必须改完才可发布。

---

### 3.9 `10-agent-execution-reliability.md`

**结论：条件通过**（P0 0 / P1 1 / P2 3）

**实现状态声明是否成立：基本成立。** `已实现 + 部分实现` 与代码一致：幂等 claim/replay/conflict、执行/结果状态分离、wall timeout、attempt retry、event_trace、checkpointer 均可核验；"通用 HITL resume/硬取消/生产 SLO"未完成也属实。

**证据核验**

| 文章声明 | 核验证据 | 结果 |
|---|---|---|
| 请求链路：claim → run → complete/fail | `service.py:244-317`；`api/main.py:1428-1461` | 成立 |
| 三类结束（正常/业务失败/执行异常）区分 | `loop.py:425-446`（异常 → FAILED dict）；`service.py:309-317` | 成立 |
| Execution Record ≠ Agent Result | `service.py:304-317` | 成立 |
| 终态清单 | `state.py:11-22` | 成立 |
| 60s 内部超时 / 70s wall timeout / 504 / store.fail / worker 可能收尾 | `state.py:31`；`loop.py:256-261`；`service.py:41-68`；`api/main.py:1424-1426,1448-1449` | 成立 |
| checkpoint：SqliteSaver + JSON attempt 快照，都不是副作用回滚；无通用 resume | `checkpoint.py`；`loop.py:552-565`；`api/main.py:1438-1441` 不传 `checkpoint_dir` | 成立（B 端口径；C 端另有 resume） |
| 审计要素：event_trace/request_id/execution_id/耗时/token | `loop.py:391-397,468-475`；`service.py:89-210`（`_build_agent_spans`、ai_monitor） | 成立 |
| 待补测试三项（runner 返回 FAILED 的 Record 语义、超时后 worker 覆盖、超时后 API 重提） | `tests/test_agent_execution_safety.py` 无对应用例；`test_agent_architecture.py:239` 只测 retry 状态集合 | 成立（确实缺） |
| **`run_agent_with_retry` 默认 max_retries=0** | `loop.py:505` 明确 `max_retries: int = 1`；只有 `api/main.py:623` 的请求模型默认为 0 | **不成立** |

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| **P1** | §7 重试 | "Qianke：run_agent_with_retry / 默认 max_retries=0" | 函数签名默认 `max_retries=1`（`loop.py:505`），即直接调用会跑 2 次；API 层默认 0（`api/main.py:623`）并 clamp 到 0–3（`:1439`）。文章把"API 默认"错挂到函数默认上，属代码行为事实错误 | 改为"`run_agent_with_retry` 函数默认 1；`/api/agent/run` 请求默认 0、上限 3" |
| P2 | §8/§10 | "当前没有通用 resume API" | B 端主链路成立；C 端已有 `resume_c_agent`（`c_end/agent.py:751-780`），Super-agent 也有审批恢复 | 限定"B 端/通用 resume 缺失；C 端与 Super-agent 有专用恢复链路" |
| P2 | §12 标题与结构 | "12. 总结与延伸阅读" | 批内其他 8 篇为"11 总结 + 12 延伸阅读"，本文合并两节，破坏统一结构（仍为 12 个 H2，但语义不同） | 拆回 11/12 两节，与批内一致 |
| P2 | §10 部分实现 | "前端错误分类体验" | 未核验前端是否按状态/错误码分类展示（本次未运行前端、未审阅相关视图） | 标注"未核验"或补前端证据（路由/组件/截图） |

**未核验项**：前端错误分类体验；生产 SLO 告警是否存在（"部分实现/未完成"的负向断言未穷尽核验）；wall timeout 后 worker 真实收尾行为（代码审阅结论，未构造并发实验）。

**一句话总评**：异常处理的状态语义讲得最细、与代码最贴近，但"默认 max_retries=0"这一处把 API 默认当成了函数默认，需要纠正；顺带拆开合并的总结/延伸阅读节。

---

## 4. 逐篇结论与问题统计

| # | 文件 | 结论 | P1 | P2 | 核心判断 |
|---|---|---:|---:|---:|---|
| 02 | `02-agent-vs-enterprise-agent.md` | 通过 | 0 | 4 | 状态分层诚实，代码证据成立 |
| 03 | `03-agent-runtime.md` | 条件通过 | 1 | 4 | 终态列表含 RUNNING；伪代码/口径需修 |
| 04 | `04-agent-orchestrator.md` | 通过 | 0 | 3 | 职责边界准确；WorkItem 归属需修 |
| 05 | `05-multi-agent-collaboration.md` | 通过 | 0 | 2 | 论点是"不要为了多而多"；漏双宠谈判 |
| 06 | `06-agent-state-management.md` | 通过 | 0 | 2 | State 边界清楚；SQL 结果现状需澄清 |
| 07 | `07-agent-memory.md` | 通过 | 0 | 3 | 与 memory 文档/代码高度一致 |
| 08 | `08-task-lifecycle-management.md` | 通过 | 0 | 3 | 队列/审批/审计证据最充分 |
| 09 | `09-agent-tool-calling.md` | 条件通过 | 3 | 2 | 错误码补造 + 草稿幂等状态不准 |
| 10 | `10-agent-execution-reliability.md` | 条件通过 | 1 | 3 | retry 默认值错误；其余语义正确 |

## 5. 必须修正项（按优先级）

1. **09 篇错误码**（P1×2）：删除/替换 `READ_ONLY_VIOLATION`、`LIMIT_REQUIRED`、`TENANT_SCOPE` 等不存在或不作错误码使用的符号，改为 `SQL_VALIDATION_ERROR` / `SQL_EXECUTION_ERROR` / `RAG_SEARCH_ERROR` / `INVALID_EXPRESSION` / `DIVISION_BY_ZERO` / `INVALID_ARGUMENTS` / `TOOL_ERROR` / `PROFILE_*` / `ACTION_*`；同时清理 `docs/agent.md:358` 与基线 01 的同类旧示例（跨文档）。
2. **09 篇草稿幂等**（P1）：把"缺测试"改为"缺幂等键/唯一约束 + 缺测试"，或补实现后再改状态。
3. **03 篇终态**（P1）：把 `RUNNING` 移出"终态"。
4. **10 篇 retry 默认值**（P1）：函数默认 1、API 默认 0、上限 3，三者分别写清；同步修正 02 篇 §3.5 的同源模糊表述（P2）。

## 6. 未核验项汇总

- 外部官方链接可达性（LangGraph/FastAPI/OWASP/NIST/PostgreSQL/OpenTelemetry）：**未核验**（未抓取网络）。
- 真实 LLM Agent 运行、Eval 全量跑分、Benchmark/Regression 口径数字：**未核验**（未运行 Eval runner）。
- 生产 SLO / 成本看板 / 安全指标看板 / 前端错误分类体验：**未核验**（未运行系统与前端）。
- C 端 `CAgentState` 全字段、CApp 记忆 UI 交互、`memory_review` 常驻调度：**未核验**（只核验代码/文档存在）。
- Super-agent PostgreSQL 队列模式的真实并发/租约/死信行为：**未核验**（本次只读代码与 SQLite 测试，未连真实 PG）。
- 双宠谈判的运行时稳定性：**未核验**（只核验代码、测试文件、E2E 文档）。
- 09 篇画像 Tool 的真实 B 账号跨租户拒绝路径：**未核验**（只核验代码与 policy 单测）。

## 7. 审计执行说明

- 本报告是本次任务唯一写入的文件；未修改任何文章正文、配置或代码。
- 已执行 1 条验证命令（见 §1.2），结果如实记录；未执行的其他验证在第 6 节列明。
- 引用基线文章的证据（34 passed / commit）已复跑核验；未把"代码审阅结论"冒充"测试结论"（例如 superagent 并发行为、wall timeout 后 worker 收尾均只做代码审阅）。 
