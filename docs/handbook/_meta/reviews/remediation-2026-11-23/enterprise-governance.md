# Enterprise Governance 批次 · P1 修复复核审计（2026-11-23）

> **批次：** enterprise-governance（`docs/handbook/02-enterprise-governance/`，共 10 篇）
> **本批 P1 任务：** P1-04、P1-05、P1-08（来源：`_meta/reviews/2026-11-23-p1-fix-tasks.md`）
> **复核文件：** 01 身份认证与权限管理、03 多租户隔离架构、09 操作审计与追踪
> **生效基线：** `docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md`（V0.5.2 基线错误码勘误）
> **历史冻结：** V0.5.1 保留在仓库、`docs-site` 排除、不进入公开站
> **审计性质：** 只读。除本报告外，未修改任何文章、配置或代码；未运行 pytest、评测、浏览器 E2E。
> **复核方式：** 当前文本逐条对照代码/测试/文档；对照原审计报告引用原文；查看既有构建与测试日志。文中"已核验"均指静态代码/文件核对，不等于运行时验证。

## 0. 代码快照与审计边界

| 项 | 值 |
|---|---|
| Git HEAD | `32ad31bc2636`（2026-11-22 19:15:14 +0800，分支 `b-end-2.0-p0`） |
| 工作区 | 含未提交修改：`git diff --stat` 共 15 个文件（AGENTS.md、docs/career、package.json、`api/b_workbench.py`、`api/main.py`、`static/login.*`、`web/*`） |
| 本报告引用代码 | `agent/loop.py`、`api/security.py`、`agent/actions.py`、`ai_monitor.py`、`superagent/store.py`、`api/superagent.py`、`tools/sql_tool.py`、`config.py`、`auth.py` 均未在未提交清单中 |
| 唯一相关未提交文件 | `src/rag_demo/api/main.py`（diff 统计 31 行，含 API 文档挂载、Agent Eval V2 注册、`/docs` Handbook 挂载）；本报告引用的 `main.py:122-147,623,1439` 不在任何 hunk 范围内，且与 HEAD 版本一致 |
| handbook 版本控制状态 | `git ls-files docs/handbook` = 0，整个目录未跟踪 |

**由此产生的核验限制：** 无法取得修复前后的 git diff。本报告用三类替代证据判断"确实修复"：

1. 当前文本与代码逐条一致（不是只看措辞）；
2. 原审计报告/任务清单引用的"原文"已不在文中（反证已改）；
3. 修复文件 mtime 均为 `2026-11-23 17:50:06`，且原审计点名的相邻行行号未漂移，说明是局部编辑而非整篇重写。

这三类证据能证明"当前状态与代码一致"，但不能替代逐行 diff；如需要严格的"只改了这几行"结论，应在 Git 跟踪 handbook 后补做。

## 1. 前置基线检查（M1-01，本批次复核的前提）

| 检查项 | 结果 | 证据 |
|---|---|---|
| V0.5.2 已发布且版本头更新 | 通过 | `01-enterprise-agent-architecture-v0.5.2.md:33-36`（`版本：V0.5.2 · 基线错误码勘误`，声明 V0.5.1 冻结保留、不进公开站） |
| §4.1 错误码示例勘误 | 通过 | V0.5.2:653-659 `SQL_VALIDATION_ERROR` + `SQL 校验失败：仅允许 SELECT/WITH、必须带 LIMIT、仅白名单表`；与 `src/rag_demo/tools/sql_tool.py:152,169-171` 完全一致 |
| V0.5.2 不再出现旧错误码 | 通过 | 全文检索 `READ_ONLY_VIOLATION` = 0；`LIMIT_REQUIRED` = 0；`TENANT_SCOPE`（错误码语境）= 0 |
| V0.5.1 保留不变 | 通过（仅内容核对） | `01-enterprise-agent-architecture-v0.5.1.md:655` 仍保留 `READ_ONLY_VIOLATION`，未被覆盖 |
| 公开站入口指向 V0.5.2 | 通过 | `docs-site/.vitepress/config.mjs:9,154`；`srcExclude` 含 `...v0.5.1.md`（config.mjs:122）；`docs/handbook/index.md:11`、`README.md:5,59,73,88,107` |
| 构建产物 | 通过（以既有日志/产物为凭，本次未复跑） | `dist` 有 `agent-architecture/01-enterprise-agent-architecture-v0.5.2.html`、无 v0.5.1 页（`Test-Path`=False）；`var/m1-docs-build2.log`（17:48:07）、`var/m2-docs-build.log`（17:52:55，晚于修复 17:50:06）均 `build complete`；`var/m1-docs-build.log`（17:46:28）曾因 4 个 v0.5.1 dead link 失败，后续已修复 |
| 基线内部一致性（Trace 名称） | 通过 | V0.5.2:1571-1572 使用 `llm_finished.duration_ms` / `tool_finished.duration_ms`，与代码一致；全文无 `llm_start/llm_end/tool_end` 旧名 |

**基线流程偏差（P2-15）：** V0.5.2 相对 V0.5.1 的 diff 除错误码示例外，还修改了 §8.3 的 retry 一行（`默认 max_retries=0` → `函数默认 1；API 请求默认 0、上限 3`）。该改动与 P1-03 口径、代码事实一致（`agent/loop.py:505` 函数默认 1；`api/main.py:623` API 默认 0；`api/main.py:1439` clamp 0–3），但严格超出了 M1-01 验收中"只改错误码示例"的表述，属流程/记录问题而非事实错误，建议在批次记录中说明。

## 2. P1 任务逐项结论

| 任务编号 | 文章 / 位置 | 结论 | 一句证据 |
|---|---|---|---|
| P1-04 | 01-identity-and-access-management.md §5（L133） | **通过（真正修复）** | 现文 `QIANKE_LOGIN_RATE_BACKEND`，缺省推断与失败回退描述均与 `api/security.py:150-161` 一致 |
| P1-05 | 09-operation-audit-tracing.md §4.2（L94-100） | **通过（真正修复）** | 现文 `*_started/_finished/_failed` + `run_*`，与 `agent/loop.py:42-62,391-475` 生成逻辑一致 |
| P1-08 | 03-multi-tenancy-isolation.md §6（L153） | **通过（真正修复）** | 现文"部分实现 + 缺口"，与本文 §4.6/§8 及代码缺口（sa_job 无 merchant_id、队列观测全局、Webhook merchant_id 调用方声明、单应用单商家）一致 |

### 2.1 P1-04 登录限流环境变量

- **修复位置：** 01 篇 §5 工程实现，L133。
- **当前文本：** `QIANKE_LOGIN_RATE_BACKEND=postgres # 不设置时按控制面后端推断；失败回退内存`
- **代码证据（`src/rag_demo/api/security.py:150-161`）：**

  ```text
  mode    = QIANKE_LOGIN_RATE_BACKEND          # L151
  control = QIANKE_CONTROL_BACKEND             # L152
  mode == "memory" 或（未设置且 control 非 pg）→ LoginRateLimiter（内存）
  否则 → PostgresLoginRateLimiter；构造失败 → logger.warning + 回退内存
  ```

- **关联证据：** `docs/e2e/security-hardening.md:129-133` 同样使用 `QIANKE_LOGIN_RATE_BACKEND=postgres` 与"PG 不可用回退内存"，与文章一致。
- **旧符号检索：** 全仓库（`src/`、`tests/`、公开 `docs/`）检索 `RAG_LOGIN_RATE_BACKEND` = 0；仅历史审计/任务清单文档保留旧名，符合"历史文档不改"的预期。
- **验收对照：**
  - "文中无 `RAG_LOGIN_RATE_BACKEND`"：通过。
  - "设置该变量能按文章描述生效"：代码路径核对通过；**未做进程级实测**（见 §5）。
- **判定：** 不是只改文字。变量名、缺省推断（按 `QIANKE_CONTROL_BACKEND`）、失败回退三层语义均与代码一致；原文"RAG_ 前缀导致静默失效"的问题已消除。

### 2.2 P1-05 Trace 事件名

- **修复位置：** 09 篇 §4.2，L94-100。
- **当前文本：**

  ```text
  run_started / run_failed / run_finished
  llm_started / llm_finished / llm_failed（含 token usage、耗时）
  tool_started / tool_finished / tool_failed（含工具名、参数、结果、耗时）
  chain 事件（还原 LangGraph 父子层级）
  ```

- **代码证据：**
  - 事件名统一由 `f"{kind}_started" / f"{kind}_finished" / f"{kind}_failed"` 生成：`agent/loop.py:42-62`（`_start/_finish/_error`），kind 取 `llm` / `tool` / `chain`；
  - `run_started` / `run_failed` / `run_finished`：`agent/loop.py:391-397, 427-432, 468-475`；
  - `llm` 事件携带 `prompt_chars`、`input_text`、`prompt_tokens/completion_tokens/total_tokens`、`output_text`、`duration_ms`（loop.py:70-105）；
  - `tool` 事件携带 `name`、`input_preview/input_text`、`output_preview/output_text`、`duration_ms`（loop.py:107-120）；
  - `chain` 事件带 `parent_run_id`，与"还原父子层级"一致（loop.py:122-136）。
- **跨文档一致性：**
  - `docs/agent.md:86-89` 事件名一致；`docs/agent.md:281-284` 示例使用 `tool_started/tool_finished`；
  - V0.5.2 基线 L1571-1572 使用 `llm_finished.duration_ms` / `tool_finished.duration_ms`；
  - `05-reliability-evaluation/05-agent-observability.md:137` 使用 `run_started / llm_* / tool_* / run_finished`；
  - 旧名检索：公开 handbook 中 `llm_start /`、`llm_end`、`tool_end` = 0。05 篇中的 `on_llm_start/end`、`on_tool_start/end` 是 LangChain 回调方法名（不是 event_trace 事件名），语境正确，不计为旧名残留。
- **验收对照：**
  - "`rg 'llm_start /|llm_end /|tool_end /'` 为 0"：通过；
  - "过滤示例可命中真实事件"：文中清单与代码事件字符串逐项可命中；未做真实 Trace 过滤查询（见 §5）。
- **遗留精度问题（P2-09）：** L94 的引导语"`TraceCallbackHandler` 记录"涵盖 `run_*` 事件，但代码中 `run_*` 由 `run_agent` 直接 append 到 `tracer.events`（loop.py:391/427/468），并非 `TraceCallbackHandler` 方法产生；事件名本身正确。
- **判定：** 不是只改文字。六个核心事件名与真实代码完全一致，原文"按文过滤 Trace 全部落空"的问题已消除；`docs/agent.md` 原本已使用正确名称（git 未修改），P1-05 的"同步 docs/agent.md"实际无需改动、现状一致。

### 2.3 P1-08 多租户隔离强度

- **修复位置：** 03 篇 §6 企业级要求，L153。
- **当前文本：** `| 隔离强度 | 跨租户不可见、不可写、不可推断 | 部分实现（读侧切库 + 写侧 merchant_id 校验；队列/Webhook/单应用单商家缺口见 §4.6） |`
- **代码证据（逐条）：**

  | 本文声明 | 代码/文档证据 | 结果 |
  |---|---|---|
  | 读侧：账号推导 dataset + contextvar 切库 + 失败 403 | `api/main.py::_tenant_dataset`（L239-329）、`_tenant_scope`（L332-374）、`db/connection.py` 的 `use_dataset/reset_dataset` | 成立 |
  | 写侧：仓储强制 `merchant_id` + 作用域 | `merchant/repository.py`；`superagent/worker.py:22,393`（`_CURRENT_MERCHANT`） | 成立 |
  | 缺口 1：`sa_job` 无 `merchant_id` | `superagent/store.py:82-95` 建表列无 `merchant_id` | 成立 |
  | 缺口 2：队列观测全局 | `api/superagent.py:374-399` `/jobs`、`/jobs/stats` 仅系统管理员可看全局；`superagent/store.py:842` `job_stats()` 无 merchant 过滤 | 成立 |
  | 缺口 3：企业微信单应用单商家 | `superagent/wecom_approval.py:73` 只读 `QIANKE_WECOM_MERCHANT_ID` 单值 | 成立 |
  | 缺口 4：Webhook merchant_id 由调用方声明 | `api/superagent.py:333-355`（入口有共享密钥 `X-Superagent-Secret`，但 merchant_id 仍来自请求体） | 成立（描述不完整，见 P2-06） |

- **内部一致性：** §6 状态行 ↔ §4.6 已知缺口（L127-133） ↔ §8 实践表（L175-187，`sa_job` 无 merchant_id、企业微信单应用单商家、RLS 规划中）三处一致；L189 "不能写成多租户已完备" 与 §6 新口径一致。
- **跨篇一致性：**
  - `03-system-architecture/05-message-queue-event-driven.md:150`："多租户隔离 | 部分实现（work item 有 merchant_id；队列层未隔离）" — 与本篇一致；
  - `03-system-architecture/06-distributed-task-scheduling.md:149`："隔离/容量 | 部分实现（数据有 merchant_id；资源未隔离）" — 一致；
  - `02-enterprise-governance/10-enterprise-security-architecture.md:36,150,188`：明确"租户切库有了但队列 Job 没有 merchant_id"、多租户状态"已实现 + 部分实现" — 一致（未把机制行按整体隔离判为已完成）。
- **验收对照：**
  - "状态表与本文缺口表一致"：通过；
  - "不再宣称'不可见/不可写/不可推断'整体已实现"：通过（L153 为唯一出现处，状态为部分实现）。
- **判定：** 不是只改文字。新状态与代码缺口逐条可核对；同批/关联文章无需改动即保持一致。

## 3. 新发现问题

### 3.1 P0 / P1

```text
P0：0
P1：0
```

本批 3 项 P1 任务均已真正修复，且未发现修复引入的新 P0/P1 级错误、未发现新的 P1 级跨篇矛盾。

### 3.2 P2（遗留 / 旁路发现）

> 说明：P2-01 ~ P2-09 为原审计已列、但不在本批 P1 清单内的遗留项（本轮按"只修 P1"边界未改，属预期）；P2-10 ~ P2-15 为本轮旁路检查发现。以上均不阻断本批 P1 验收，但文章尚不能视为定稿。

| 编号 | 文件 / 位置 | 问题 | 证据 | 归属建议 |
|---|---|---|---|---|
| P2-01 | 01 篇 §4.1 L100 | "登录开启时请求头身份直接降级为 guest"少一个条件：`_auth_enforced() = AUTH_ENABLED and not ALLOW_HEADER_AUTH`；显式 `RAG_ALLOW_HEADER_AUTH=1` 时登录开启仍接受请求头 | `api/main.py:122-147`；`auth.py:54,56` | 本批后续 P2 清理 |
| P2-02 | 01 篇 §2 L72 | "过期、退出、改密时删除记录"不准确：过期会话在读取时被拒绝，删除发生在登录时顺手清理或 `purge_expired_sessions` | `auth.py:1084`（create_session 清理）、`auth.py:1122-1124`（purge） | 同上 |
| P2-03 | 01 篇 §2 L63-70 | "四条认证链路"漏 `POST /api/auth/demo-login`（无密码演示会话）与离线请求头模式 | `api/main.py:556,1146` | 同上 |
| P2-04 | 01 篇 §8 L178 | "权限变更 / 登录审计表｜仅配置版本 + 日志"与本文 §4.3 冲突：登录失败已有结构化 `c_login_attempt` 限流记录 | `api/security.py:56-147` | 同上 |
| P2-05 | 03 篇 §6 L156 | "Trace 有 dataset/merchant"错误：`ai_traces/ai_spans` 只有 `tenant_id`/`dataset`，无 `merchant_id`；商家维度在 `sa_thread`/`sa_work_item`/`agent_action` 等业务表 | `ai_monitor.py:36-64`（`ai_traces` 列含 tenant_id/dataset）；`superagent/store.py:18-26`（`sa_thread.merchant_id`） | 同上 |
| P2-06 | 03 篇 §4.6 L130 | Webhook 缺口描述省略了入口鉴权：入口校验共享密钥 `X-Superagent-Secret`；准确缺口是"merchant_id 未绑定可信身份，仅受共享密钥保护" | `api/superagent.py:333-338,348-355` | 同上 |
| P2-07 | 09 篇 §4.6 L132 | "保存上限 12KB"与代码不符：代码按**字符**截断 `[:12000]`（另存 300 字符 preview）；与 05-observability"12000 字符"表述不一致 | `agent/loop.py:71,94,111,117`；`05-agent-observability.md:79` | 同上（含跨篇统一） |
| P2-08 | 09 篇 §4.1 L90 | "Agent 返回、Trace、审计记录都带这三个 ID"过强：`agent_action` 只有 `request_id`；`sa_approval`/`sa_work_item` 无 `execution_id`/`parent_execution_id` | `agent/actions.py:56-86`；`superagent/store.py:65-75` | 同上 |
| P2-09 | 09 篇 §4.2 L94 | `run_*` 事件由 `run_agent` 直接 append，不是 `TraceCallbackHandler` 产出；事件名正确，归属表述可再精确 | `agent/loop.py:388-397,425-475` vs L42-62 | 同上（低优先） |
| P2-10 | 07 篇 §1 L48（同批旁路） | 引用 `01-enterprise-agent-architecture-v0.5.1.md`；V0.5.2 已生效，该引用为旧版本路径（所述结论在 V0.5.2:L1364 仍成立） | `02-enterprise-governance/07-prompt-injection-defense.md:48`；V0.5.2:1364 | 本批 P2 清理（改指 V0.5.2 或改引"架构基线"） |
| P2-11 | 10 篇 §2.2 L59（同批旁路） | "边界层：……API 文档关闭"易被读成默认关闭；代码默认 `RAG_ENABLE_API_DOCS=1`，生产才关闭；01 篇已写"取决于配置"，两篇口径不一致 | `config.py:218-222`；`01-identity-and-access-management.md:137`；`10-enterprise-security-architecture.md:59` | 本批 P2 清理 |
| P2-12 | `docs/agent.md` L358（跨文档） | 官方 Agent 文档仍保留旧错误码示例 `READ_ONLY_VIOLATION`（Trace 事件名 L86-89 已正确）；P1-01/02 在任务清单"关联"中提到该文档但未列入修改文件 | `docs/agent.md:358` vs `sql_tool.py:152,169` | 建议由 agent-architecture 批次或单独文档修订处理 |
| P2-13 | 01-agent-architecture 02/03/04 篇 + 06-architecture-practice 02/09/10 篇（跨批） | V0.5.1 残留：链接**文字**仍写"V0.5.1"但 href 已指向 v0.5.2（02:L689、03:L475、04:L325）；02 篇正文 L518/L616 仍称"第一篇 V0.5.1"；06 批多处把 V0.5.1 路径当现行证据引用（02:L157、09:L112/159/211、10:L210）。v0.5.1 dead link 构建失败已通过改 href 修复（见 `var/m1-docs-build.log`），但 label/正文/证据路径未同步 | `01-agent-architecture/02-agent-vs-enterprise-agent.md:518,616,689`；`03-agent-runtime.md:419,475`；`04-agent-orchestrator.md:325`；`06-architecture-practice/02-architecture-design-method.md:157`；`09-technical-debt.md:112,159,211`；`10-enterprise-architecture-case.md:210` | 非本批，转 agent-architecture 与 architecture-practice 批次；历史性表述可保留但应注明"历史版本" |
| P2-14 | `docs/handbook/README.md`（手册级） | 状态词表 L18-24 仍用"开发中"，与正文"部分实现"不一致；L145-150 仍写"本目录内容尚未发布到官网/本次未修改官网代码"，与 L61、L136-137 的 `/docs` 已实现矛盾 | `README.md:18-24,61,136-137,145-150` | 手册级 P2，由负责全站收尾的批次统一 |
| P2-15 | V0.5.2 基线（流程项） | M1-01 验收写"只改错误码示例"，实际 diff 还改了 §8.3 retry 一行（内容正确、与 P1-03 一致）；建议在基线修订记录中登记，避免"只改一处"的验收记录与事实不符 | `git diff --no-index` V0.5.1/V0.5.2；V0.5.2:1357；`agent/loop.py:505`、`api/main.py:623,1439` | 基线流程记录 |

## 4. 跨篇一致性检查

### 4.1 本批 3 篇与关联文章

| 关联对 | 检查点 | 结果 |
|---|---|---|
| 09 ↔ `05-reliability-evaluation/05-agent-observability.md` | Trace 事件名 | 一致（`run_started / llm_* / tool_* / run_finished`）；截断口径 12000 字符 vs "12KB" 不一致 → P2-07 |
| 09 ↔ V0.5.2 基线 | Trace 事件名、指标口径 | 一致（L1571-1572 使用 `llm_finished` / `tool_finished`；无旧名） |
| 09 ↔ `docs/agent.md` | Trace 事件名 | 一致（L86-89、L281-284）；但 agent.md 错误码示例仍旧 → P2-12 |
| 01 ↔ `docs/e2e/security-hardening.md` | 登录限流环境变量与回退 | 一致（`QIANKE_LOGIN_RATE_BACKEND`、PG 不可用回退内存） |
| 03 ↔ `03-system-architecture/05-message-queue-event-driven.md` | 队列层租户隔离 | 一致（均写"部分实现/队列层未隔离"） |
| 03 ↔ `03-system-architecture/06-distributed-task-scheduling.md` | 隔离/容量状态 | 一致（"部分实现（数据有 merchant_id；资源未隔离）"） |
| 03 ↔ `02-enterprise-governance/10-enterprise-security-architecture.md` | 多租户汇总状态 | 一致（"已实现 + 部分实现；缺口见专题"，L36 明写队列缺 merchant_id） |
| 01 ↔ 09 | 账号/登录审计缺口 | 一致（01 §8"账号变更只有日志"；09 §4.5 同口径） |
| 01 ↔ 10 | API 文档入口表述 | 不一致：01 写"取决于配置、不能仅凭本文认定线上可访问"；10 写"API 文档关闭" → P2-11 |
| 07 ↔ V0.5.2 基线 | 基线版本引用 | 07 仍引用 V0.5.1 路径 → P2-10 |

**结论：** 三项 P1 修复未引入新的跨篇矛盾；上述不一致均为原审计已登记或旁路检查发现的 P2，不改变各篇 P1 级结论。

### 4.2 旧版本 / 旧审计引用检查

- **本批 3 篇复核文件：** 未发现对 V0.5.1 或 `audit-2026-11-23` 旧审计报告的引用（0 命中）。
- **本批 10 篇内：** 仅 07 篇引用 V0.5.1 路径（P2-10）；不存在把旧审计报告当正文证据的引用。
- **整个公开 handbook：** 除 07 外，01-agent-architecture 02/03/04 篇与 06-architecture-practice 02/09/10 篇仍引用 V0.5.1（链接文字或证据路径，P2-13）；README:L89 的"V0.5 → V0.5.1 微调记录"链接属合法历史记录。
- **公开站：** V0.5.1 已被 `srcExclude` 排除，`dist` 中无 v0.5.1 页面；README/index 已指向 V0.5.2。
- **越出本批的旧版本残留：** 见 P2-13，需对应批次处理（历史性表述可保留，但应注明"历史版本"或改指 V0.5.2）。

## 5. 未核验项（明确未运行）

- **pytest：未由本次审计执行。** 仓库存在既有运行日志：`var/audit-baseline-tests.log`（17:21:30，"34 passed, 1 warning in 20.66s"，与 2026-11-23 审计报告一致）、`var/handbook_agent_review_tests.log`（"34 passed, 1 warning in 7.50s"）。这些是既有记录，不代表本次复核复跑，也不覆盖本批文章声明的全部行为（环境为 SQLite 控制面/数据面）。
- **docs-site 构建：未由本次审计复跑。** 仅核对既有日志与产物：`var/m1-docs-build.log`（17:46:28 失败，4 个 v0.5.1 dead link）、`var/m1-docs-build2.log`（17:48:07 通过）、`var/m2-docs-build.log`（17:52:55 通过，晚于 17:50:06 的修复）；`dist` 产物时间 17:52:55 且包含修复后字符串、无 v0.5.1 页面。构建结论为"以既有日志/产物为凭"。
- **P1-04 验收"设置该变量能按文章描述生效"：** 仅静态核对 `_build_login_rate_limiter` 逻辑，未在真实进程设置 `QIANKE_LOGIN_RATE_BACKEND` 后验证限流后端选择/回退。
- **P1-05 验收"过滤示例可命中真实事件"：** 仅逐项对照代码事件字符串，未调用 Trace 查询/过滤接口做端到端验证。
- **P1-08：** 未验证真实跨租户攻击面、未连接 PostgreSQL 核对 `sa_job`/`ai_traces` 线上结构、未验证 RLS 缺失的实际暴露面；仅按代码建表与查询路径核对。
- **未运行：** 浏览器/E2E、`/docs` 60 条路由可达性、真实 LLM Eval、企业微信投递、生产部署（cloudflared、监控、备份恢复）。
- **未重审：** 3 篇文章中与 P1 无关的全部声明（依赖 2026-11-23 审计报告 + 本轮抽查代码）；`docs/e2e/*` 历史运行记录只做存在性与关键词级核对。
- **无法核验：** 修复前后逐行 diff（handbook 目录未被 Git 跟踪）；V0.5.1"保留不变"的历史版本内容（只能确认当前 V0.5.1 仍含旧错误码且未进站）。

## 6. 批次结论

### 6.1 文章结论统计

| 文章 | 原审计结论 | 本批 P1 | 复核后结论 | 遗留 P2 |
|---|---|---|---|---|
| 01 身份认证与权限管理 | 条件通过（P1×1） | P1-04 | **通过**（P1 已修复） | 4（P2-01~04） |
| 03 多租户隔离架构 | 条件通过（P1×1） | P1-08 | **通过**（P1 已修复） | 2（P2-05~06） |
| 09 操作审计与追踪 | 条件通过（P1×1） | P1-05 | **通过**（P1 已修复） | 3（P2-07~09） |
| **合计** | 条件通过 3 / 通过 0 | 3 | **通过 3 / 不通过 0** | 9 |

按原审计判定规则（"通过"允许 P2），3 篇文章在 P1 修复后达到"通过"；遗留 P2 另行清理，不阻断本批 P1 验收。

### 6.2 批次裁决

**通过（P1 修复验收范围）。**

依据：

1. P1-04 / P1-05 / P1-08 均为"真正修复"：新文本与代码逐条一致（环境变量读取与回退、事件名生成逻辑、多租户缺口清单），不是只改措辞；
2. 未发现新增 P0/P1；未发现修复引入的跨篇矛盾；关联文章（System 05/06、Enterprise 10、05-observability、docs/agent.md）在本批 3 处修复点上保持一致；
3. 基线 V0.5.2 前置条件满足：错误码勘误生效、旧码仅存于冻结的 V0.5.1、站内入口与构建产物指向 V0.5.2；
4. 遗留 P2（本批 9 项 + 旁路 6 项）均不影响本批 P1 事实结论，但意味着"文章定稿/发布"仍需后续清理；其中 P2-12（docs/agent.md 旧错误码）、P2-13（跨批 V0.5.1 链接文字）需要跨批次或单独文档修订。

**后续建议：**

- 保持 V0.5.2 为唯一公开基线，不再新增对 V0.5.1 的正文引用；
- 按批次清理 P2-01~P2-11（其中 03/09 两篇的 P2 可与本批 P1 同批做小修，避免"P1 修好、旁边仍错"的观感）；
- P2-12/P2-13/P2-14 转对应批次或全站收尾任务，避免在本批扩大范围；
- 如需严格证明"只改了 P1 指定行"，先把 `docs/handbook/` 纳入 Git 跟踪，再对后续修复做逐任务 diff 验收。
