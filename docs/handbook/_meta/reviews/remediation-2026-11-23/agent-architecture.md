# Agent Architecture 批次 P1 修复复核报告（2026-11-23）

> **批次**：`docs/handbook/01-agent-architecture/`（P1 修复后复核）
> **涉及任务**：P1-01、P1-02、P1-03、P1-06、P1-07、M1-01
> **复核性质**：只读复核。未修改任何文章/配置/代码；本文件是本次唯一新增文件。
> **复核方式**：逐行阅读 6 篇正文 + V0.5.2 基线；与 V0.5.1 做 `Compare-Object` 对比；符号级 grep；逐条对照 `src/rag_demo/` 当前工作树与 `tests/`；检查 docs-site 配置、dist 产物与构建日志、文件 mtime 时间线。
> **运行边界**：本次**未运行** pytest / Regression Eval / Benchmark / `npm run build`，因此本报告不宣称任何测试或构建“已通过”。代码结论均来自静态审阅；既有产物仅作旁证。

## 1. 批次、范围、基线、代码快照

### 1.1 复核范围

| 对象 | 文件 | 本轮 mtime（参考） |
|---|---|---|
| 基线（新） | `01-enterprise-agent-architecture-v0.5.2.md` | 2026-11-23 17:50:06 |
| 基线（冻结） | `01-enterprise-agent-architecture-v0.5.1.md` | 2026-11-23 14:53:21（早于修复时段） |
| 本批正文 | `02-agent-vs-enterprise-agent.md` | 2026-11-23 17:50:06 |
| 本批正文 | `03-agent-runtime.md` | 2026-11-23 17:50:06 |
| 本批正文 | `06-agent-state-management.md` | 2026-11-23 14:57:34（本轮未改） |
| 本批正文 | `09-agent-tool-calling.md` | 2026-11-23 17:50:06 |
| 本批正文 | `10-agent-execution-reliability.md` | 2026-11-23 17:50:06 |
| 关联但不在指定清单 | `04-agent-orchestrator.md`、`01-agent-architecture/index.md` | 2026-11-23 17:46:42（本轮被改动，仅用于交叉观察） |

时间线旁证：V0.5.1 为 14:53；05/07/08 为 14:57–14:58；README 为 17:45；04/index 为 17:46；01-v0.5.2/02/03/09/10 为 17:50；docs-site dist 为 17:52:55。修复窗口约 17:45–17:52。

### 1.2 基线与代码快照

```text
基线          = docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md
                （V0.5.1 按 M1-01 冻结保留，docs-site srcExclude 排除）
代码快照      = Git HEAD 32ad31bc26365e8d0cefe503e6c09cfcd2876eaa（分支 b-end-2.0-p0）
                工作区含未提交修改（130 项，含 src/rag_demo/api/main.py 等）
文档版本状态  = docs/handbook/ 整体未纳入 Git（git ls-files docs/handbook = 0），
                因此无法用 git diff 复核文章改动；V0.5.1/V0.5.2 采用逐行 Compare-Object，
                正文修复前后差异无法直接 diff，只能以当前内容 + mtime 做旁证。
```

注意：P1-03 引用的 `src/rag_demo/api/main.py:623/1439` 位于**已修改的工作区文件**（mtime 2026-11-23 15:47，早于本轮文档修复），本报告行号均按当前工作树核对。

### 1.3 复核目标对应

1. P1 是否真正修复而非只改措辞 → 第 2 节逐项对照代码。
2. 修复后是否出现新跨篇矛盾 → 第 3、4 节。
3. 是否仍有旧结论/旧数字/旧错误码/旧状态 → 第 3 节 P2-1/P2-3、第 4 节状态口径表。
4. 未修复/修复不完整项分级与证据 → 第 3 节。
5. 未运行项 → 第 5 节，全部标“未核验”。

## 2. P1 任务逐项结论表

| 任务 | 结论 | 核心证据（当前工作树 / 当前文档） |
|---|---|---|
| P1-01 Tool 错误码示例 | **已修复**（任务验收范围内） | `09:83` 与 `V0.5.2:656-657` 均为 `SQL_VALIDATION_ERROR`，message 与 `src/rag_demo/tools/sql_tool.py:152-153,169-170` 逐字一致；两文件中 `READ_ONLY_VIOLATION` 命中 0；`V0.5.1:655` 仍保留旧示例（符合“历史保留”）。残留：`docs/agent.md:358` 未清理（P2-3）。 |
| P1-02 Tool 错误码分类 | **已修复**（表内每个码均可溯源；完整性见 P2-4） | `09:171-178` 8 个码全部命中源码：`INVALID_ARGUMENTS`/`TOOL_ERROR`=`tool.py:68,72,74`；`SQL_VALIDATION_ERROR`/`SQL_EXECUTION_ERROR`=`sql_tool.py:152-153`；`IDENTITY_RESOLVE_FAILED`=`chat_profile.py:75`；`PROFILE_*`=`chat_profile.py:90,131,171`。`READ_ONLY_VIOLATION`/`LIMIT_REQUIRED`/`TENANT_SCOPE` 在 09 与 V0.5.2 中均为 0。 |
| P1-03 retry 默认值 | **已修复** | `10:154-156` 写清“函数默认 1 / API 请求默认 0 / API clamp 0–3”；代码：`loop.py:505` 函数默认 `max_retries=1`，`api/main.py:623` 请求模型默认 `0`，`api/main.py:1439` `max(0, min(req.max_retries, 3))`；`V0.5.2:1357`、`02:302` 已同步。残留：`03:330` 只写“API 默认 max_retries=0”，未写函数默认 1（P2-8）。 |
| P1-06 把 RUNNING 移出终态 | **已修复** | `03:154-169` 改为“初始/中间态：RUNNING”“终态：8 个”；与 `state.py:11-22`、`loop.py:139-148 _TERMINAL_STATUSES`（不含 RUNNING）集合完全一致；`06:96-104` 状态图、`10:107-116` 终态清单均同步一致，批内未再出现“RUNNING 是终态”。 |
| P1-07 受控草稿幂等状态 | **已修复** | `09:205` 改为“没有幂等键/唯一约束；retry 或重复调用可能生成多条 DRAFT；需补幂等键与回归测试”。代码核对：`actions.py:135-189` 每次 `uuid4` 新建 `action_id` 后 INSERT，建表仅普通索引 `actions.py:80-83`，无 UNIQUE/去重；`tests/test_agent_actions.py` 4 个用例均无重复草稿幂等覆盖。`actions.py` mtime 为 2026-11-11，本轮未改代码（符合“不顺手实现写路径”）。 |
| M1-01 发布 V0.5.2 | **已修复**（构建项仅部分核验；范围偏差见 P2-2） | V0.5.1 未被改动（mtime 14:53 + 仍含 `version: 0.5.1` 与旧示例）；V0.5.2 无 `READ_ONLY_VIOLATION`；docs-site 首篇入口/导航已指 v0.5.2（`config.mjs:9,154`）、v0.5.1 已 srcExclude（`:122`）、dist 无 v0.5.1 页面；README 版本说明已改（`README.md:5,59,73-74,88,107`）。构建：dist 17:52:55 已含修复后内容，但该次构建无日志/退出码（P2 见 §3），历史日志 16:37/16:39 早于修复。 |

### 2.1 逐项核验细节

**P1-01 / P1-02**

- 09 篇失败示例结构与真实 `ToolResult.dump()`（`tool.py:42-51`，失败时 `{ok,data,error{code,message}}`）一致，未再出现旧示例的字段缺失问题。
- V0.5.2 §4.1 与 09 §2 的错误码、message 完全相同，基线↔正文已同源。
- 旧符号扫描：`READ_ONLY_VIOLATION` 仅存在于 `V0.5.1`、`_meta/versions/*` 历史归档、以及审计/任务记录文档；未出现在 6 篇正文与 V0.5.2。
- 缺口：09 §7 表只列 8 个码，未列 `RAG_SEARCH_ERROR`（`tools/rag.py:52`）、`INVALID_EXPRESSION`/`DIVISION_BY_ZERO`（`calculator.py:119,123`）、`ACTION_*`/`DEMO_READ_ONLY`/`INVALID_TITLE` 等（`actions.py`）。表内无假码，属完整性 P2，不影响 P1-02 验收条件“表内码均可溯源、不存在码为 0”。

**P1-03**

- `run_agent_with_retry` 函数默认 `max_retries=1` 意味着直接调用最多执行 2 次；`10:154` 表述准确。
- API clamp `max(0, min(req.max_retries, 3))` 与“0–3”一致；请求模型默认 0，`10:155` 准确。
- 02 篇 §3.5 已同步为“API 请求默认 max_retries=0；run_agent_with_retry 函数默认 1”，与 10 篇不矛盾。
- `03:330` 仍只有“→ API 默认 max_retries=0”。该句本身不假，但与 02/10/V0.5.2 的口径不齐，读者可能误以为 retry 默认关闭（P2-8）。

**P1-06**

- `_TERMINAL_STATUSES` 实测集合：`COMPLETED / MAX_STEPS_EXCEEDED / MAX_TOOL_CALLS_EXCEEDED / TIMEOUT / CANCELLED / BUDGET_EXCEEDED / TOOL_NOT_ALLOWED / FAILED`（`loop.py:139-148`）；03 §2.3、10 §5、06 §3 的终态集合与之逐项一致。
- `state.py:14` 的 `RUNNING` 只作为初始/中间状态；06 状态图 `[*] → RUNNING`、RUNNING → 8 个终态，未把 RUNNING 列为终态。

**P1-07**

- 真实写入路径无幂等：`create_followup_draft` 每次生成新 `action_id`（`actions.py:165`）并 INSERT；表 DDL 无 UNIQUE（`:50-73`），唯一相关索引是非唯一索引 `idx_agent_action_request`（`:80-83`）；`request_id` 只作为普通列写入（`:169-176`），不参与去重。
- 测试侧：`tests/test_agent_actions.py` 仅覆盖 DRAFT→CONFIRMED→COMPLETED、demo 拒写、跨账号拒绝、非法状态查询；无“同 request_id/重复调用产生单条 DRAFT”用例。文章“需要先补幂等键与回归测试”与事实一致。
- 措辞问题：`09:205` 的“再把状态标为‘已实现’”容易被读成“受控草稿整体未实现”，与 frontmatter `implementation_status: 已实现 + 部分实现`（`09:9`）、§9 已实现清单中的“受控草稿”（`09:218`）存在口径歧义（P2-6）。

**M1-01**

`Compare-Object(V0.5.1, V0.5.2)` 的完整差异行：

```text
+ version: 0.5.2
+ 版本说明新增 4 行（V0.5.2 勘误、历史保留、只改错误码、V0.5.1 冻结不入公开站）
- version: 0.5.1
- 旧版本说明 3 行（V0.5.1 · 三个 P2 微调、历史保留、只处理 V0.5 的 P2）
+ "code": "SQL_VALIDATION_ERROR"
+ "message": "SQL 校验失败：仅允许 SELECT/WITH、必须带 LIMIT、仅白名单表"
- "code": "READ_ONLY_VIOLATION"
- "message": "只允许执行只读查询"
+ | attempt 级 retry | 已实现 | ... 函数默认 1；API 请求默认 0、上限 3 |
- | attempt 级 retry | 已实现 | ...；默认 max_retries=0 |
```

- 验收 1（V0.5.1 保留不变）：通过 mtime（14:53，早于修复时段）与内容签名（仍是 0.5.1 版说明、旧错误码、旧 retry 行）间接核验；因 docs/handbook 未入 Git，无法做版本库 diff，故标注“间接核验”。
- 验收 2（V0.5.2 无 READ_ONLY_VIOLATION）：grep 为 0，通过。
- 验收 3（只改错误码示例，不重写正文）：**未完全满足**——除错误码示例外还改了 §8.3 的 retry 默认值行；V0.5.2 版本说明 `:35` 却写“本稿只处理……错误码示例”，与自身 diff 不一致（P2-2）。该改动内容本身正确且与 P1-03 一致，属范围/说明问题，不属内容错误。
- 验收 4（`npm run build` 通过）：仅产物旁证（dist 17:52:55 含修复后内容、无 v0.5.1 页面），无该次构建日志/退出码，**未核验**（标注于第 5 节）。

## 3. 新发现问题

**P0：无。P1：无。** 未发现修复引入的 P0/P1 级事实错误；6 篇正文的 P1 级旧错误均已消除。

### P2 级（不阻塞本批 P1 结论，但建议发布前清理）

| 编号 | 问题 | 证据 | 影响/建议 |
|---|---|---|---|
| P2-1 | 旧版本 V0.5.1 引用未随 M1-01 更新：链接标签写 V0.5.1 却指向 v0.5.2；正文仍称“第一篇 V0.5.1” | `02:689`、`03:475`、`04:325` 均为 `[企业级 Agent 架构设计 V0.5.1](01-enterprise-agent-architecture-v0.5.2.md)`；`02:518`“见第一篇 V0.5.1 §6.4”、`02:616`“第一篇 V0.5.1 已记录…”；`03:419`“V0.5.1 记录的核验结果”。公开站已渲染该错误标签（dist: `02-…html`、`03-…html`、`04-…html`）。疑为把 href 改为 v0.5.2 时未同步标签/正文（docs/handbook 未入 Git，无法确认改动前后差异） | 公开站会向读者提供“V0.5.1→v0.5.2”错误版本指引，且 V0.5.1 已明确“不进入公开站”。建议统一改为“V0.5.2”并同步 §6.4→§6.4/§8.3.1 引用 |
| P2-2 | M1-01 范围偏差 + V0.5.2 版本说明与自身 diff 不一致 | `V0.5.2:33-35` 声明“只处理……错误码示例”；但 `Compare-Object` 显示 `:1357` retry 行也被改（旧 `默认 max_retries=0` → 函数默认 1/API 默认 0/上限 3） | 内容正确、与 P1-03 一致，可解释为“关联修正”；但版本说明未如实记录第二处改动。建议补一句勘误说明，或在 P1-03 diff 中处理该行 |
| P2-3 | 批次审计要求清理的 `docs/agent.md:358` 旧错误码仍在；该文档仍被三篇文章列为证据 | `docs/agent.md:358` `"code": "READ_ONLY_VIOLATION"`；`:240` 仍写“HITL API / C 端确认流程：尚未接入”；被 `V0.5.2:1732`、`02:690`、`03:477` 引用。批次审计报告 `audit-2026-11-23/agent-architecture.md` §5“必须修正项 1”要求“同时清理 docs/agent.md:358 与基线 01 的同类旧示例”，P1 任务清单 P1-01 的“关联”列了该文档但“文件”列仅 09 篇，实际未清理 | 文章自身引用代码、结论正确；但证据链仍指向含错误码的旧快照，削弱可复核性。建议下批同步 `docs/agent.md` 或在其引用处标注“旧版快照”，并纠正 `:240` 的过时 HITL 状态 |
| P2-4 | 09 §7 错误码表不完整（无假码） | 未列出的真实码：`RAG_SEARCH_ERROR`（`tools/rag.py:52`）、`INVALID_EXPRESSION`/`DIVISION_BY_ZERO`（`calculator.py:119,123`）、`ACTION_NOT_FOUND`/`ACTION_FORBIDDEN`/`ACTION_NOT_DRAFT`/`DEMO_READ_ONLY`/`INVALID_TITLE` 等（`actions.py:145-252`） | P1-02 验收条件满足；但 §7 标题为“Tool 错误处理”，读者易把 8 行当完整码表。建议补全或注明“常用码示例” |
| P2-5 | README 版本说明已更新，但仍有旧路径与旧状态段 | `README.md:71-72` 列 `01-agent-architecture/01-enterprise-agent-architecture.md`“第一篇审核基线”，该路径不存在（Test-Path=False；实际在 `_meta/versions/`）；`README.md:147-151` 仍写“本目录内容尚未发布到官网/等待人工审核”，与 `:4`、`:61`“官网 Docs 模块已实现，/docs 可访问”及已产出的 dist 不一致（至少为历史残留） | M1-01 验收项“README 版本说明”已完成；旧路径/旧状态属残留 P2。建议修正交付路径与审核状态段 |
| P2-6 | P1-07 修复引入的措辞歧义 | `09:205`“再把状态标为‘已实现’” vs `09:9` `implementation_status: 已实现 + 部分实现`、`09:218` 已实现清单含“受控草稿” | 读者可能误读为“受控草稿整体未实现”。建议限定主语为“草稿写入幂等能力”，如“再把该幂等能力标为已实现” |
| P2-7 | 批内既有状态口径不一致（原审计已列 P2，本批未处理） | ① 通用 HITL：`02:273,305` 写“未接入/未完成”；`03:406`、`10:205` 写“部分实现”；`09:251` 甚至写“规划中”。② Prompt Injection：`09:227` 写“部分实现”，而 `V0.5.2:1364` 写“未完成”、`02:587` 写“已设计/规划中”。③ 统一 Tool Gateway：`09:225` 写“部分实现”，`02:586` 写“已设计/规划中” | 不属于 5 个 P1 任务范围（P1 清单 §6 明确不批量重写 P2），但“跨篇一致性”本轮判为不通过项（见 §4）。建议下批统一状态词与限定语 |
| P2-8 | 03 篇 retry 口径不齐 | `03:330` 仅“API 默认 max_retries=0”；`02:302`、`10:154-156`、`V0.5.2:1357` 已写全“函数默认 1 / API 默认 0 / 上限 3” | 非错误，但同源表述未完全对齐；建议 03 补“函数默认 1”一句 |

### 既有 P2 残留（原审计列出、本批任务边界外，未核验是否应另批处理）

- `02:273`（HITL 未限定 B 端口径）、`02:514`（“Execution Record 可能 FAILED”弱化确定语义）、`02:577-578`（C 端/Super-agent 放在“部分实现”）。
- `03:239`（`_terminate` 伪代码与实现不符）、`03:342`（“没有通用对外 resume API”未限定 B 端口径）。
- `06:63`（标题未限定 B 端 AgentState）、`06:125`（“全量 SQL 结果不放 State”是目标而非现状）。
- `09:251`（HITL 链接“规划中”，实际 `02-enterprise-governance/06-human-in-the-loop.md` 已存在且 `implementation_status: 已实现 + 部分实现`）。
- `10:227`（总结/延伸阅读合并）、`10:205`（前端错误分类体验未核验）。

## 4. 跨篇一致性检查

| # | 检查项 | 结论 | 证据/说明 |
|---|---|---|---|
| 1 | 01↔09 错误码示例 | 一致 | `V0.5.2:656-657` 与 `09:83` 逐字一致，且与 `sql_tool.py:169-170` 一致 |
| 2 | 01↔02↔09 Tool 数量 | 一致 | `V0.5.2:1350`“7 个注册 Tool”、`02:213`“7 个注册 Tool”、`09:96,212`；`registry.py:23` 实际 7 个 |
| 3 | 01↔02↔10 retry 默认值 | 一致 | `V0.5.2:1357`、`02:302`、`10:154-156`；代码 `loop.py:505`、`api/main.py:623,1439` |
| 4 | 03↔06↔10 终态集合 | 一致 | 03 §2.3、06 §3 图、10 §5 均为 8 个终态且不含 RUNNING；与 `loop.py:139-148` 相同 |
| 5 | 09 草稿幂等 vs 02“受控草稿已实现” | 不矛盾（措辞需收敛） | 02 指草稿+确认机制，09 §8 指写路径幂等缺口；两者事实均成立 |
| 6 | 通用 HITL 状态 | **不一致（P2-7）** | 02“未接入/未完成”、03/10“部分实现”、09“规划中”，与 01“部分实现”四种口径 |
| 7 | Prompt Injection / Tool Gateway 状态 | **不一致（P2-7）** | 09“部分实现” vs 01“未完成”/02“已设计·规划中” |
| 8 | 版本引用（旧版本 V0.5.1） | **不一致（P2-1）** | 02/03/04 标签与正文称 V0.5.1，href 指 v0.5.2；V0.5.1 已被排除出公开站 |
| 9 | 证据索引指向的旧文档 | **不一致（P2-3）** | `docs/agent.md` 含 `READ_ONLY_VIOLATION`、旧 HITL 状态，仍被 01/02/03 引用；`02:691` 还引用 2026-10-28 的 `docs/agent-design-current-vs-target.md` |
| 10 | Execution Record / Agent Result 语义 | 一致 | `V0.5.2:1003-1025`、`02:497`、`03:303-320`、`10:84-103` 口径一致（02 的“可能 FAILED”为 P2 措辞） |
| 11 | 跨批次旧版本引用（不在本批文件） | 需后续批次处理 | `06-architecture-practice/02:157`、`06-architecture-practice/09:112,159,211`、`06-architecture-practice/10:210`、`02-enterprise-governance/07:48` 仍引用 `01-…-v0.5.1.md`；不属本批改动范围，建议随各批次同步 |
| 12 | 旧数字 | 未发现新错 | 批内数字（7 Tool、5/10/60/0、60s/70s、34 passed、commit 32ad31bc2636）均与当前代码/基线记录一致；“34 passed”为继承证据，本次未复跑 |

## 5. 未核验项

以下项目本次**未执行**，报告中未给出“通过/已验证”结论：

```text
1. pytest（含 tests/test_agent_actions.py、test_agent_architecture.py 等）未运行；
2. Regression Eval / Benchmark Eval 未运行；V0.5.2 §8.3.1 的 34 passed 为历史归档证据，
   本次未复跑，无法确认当前工作树（含未提交修改）下仍为 34 passed；
3. npm run build 未由本报告执行；仅确认 docs-site dist（17:52:55）含修复后内容且无 v0.5.1 页面，
   该次构建的退出码/日志缺失（build-check.log 16:37:44、build-npm.log 16:39:18 均早于正文修复），
   “构建通过”只能标为部分核验；
4. 60 篇公开路由与浏览器端渲染/交互未做 UI 验收；
5. 外部链接可达性未核验；
6. 生产 PostgreSQL、双宠谈判运行时、企业微信投递、SLO/成本看板未核验；
7. V0.5.1“保留不变”为 mtime + 内容签名间接核验（docs/handbook 未入 Git，无法 diff）；
8. 正文修复前后的精确 diff 无法从版本库取得（docs/handbook 未跟踪），
   除 V0.5.1↔V0.5.2 外，02/03/09/10 的“改了什么”只能依据当前内容与任务清单推定。
```

## 6. 批次结论

**条件通过。**

判定依据：

```text
1. 5 个 P1 与本批 M1-01 的实质修复均成立，且与当前代码证据一致，不是只改表面措辞：
   P1-01/02 错误码已可逐条溯源；P1-03 retry 三个数字与代码一致；
   P1-06 终态集合与 _TERMINAL_STATUSES 一致；P1-07 正确写出无幂等键/唯一约束的实现缺口；
   M1-01 的 V0.5.2 基线、公开站入口、README 版本说明均已完成。
2. 未发现修复引入的 P0/P1；无伪造测试/构建结果。
3. 不满足“无条件通过”的原因：
   - P2-1：V0.5.1 旧版本标签/正文引用仍残留在 02/03（及清单外的 04），并已渲染进公开站；
   - P2-2：M1-01 版本说明与实际 diff 不一致（retry 行被一并修改）；
   - P2-3：批次审计 must-fix #1 要求清理的 docs/agent.md 旧错误码仍在，且仍被 3 篇文章引用；
   - P2-5：README 仍含不存在路径与“未发布/已实现”自相矛盾；
   - M1-01 验收中的“npm run build 通过”只有产物旁证，无日志/退出码，标为部分核验。
```

建议的通过条件（任一批次收口前完成）：

```text
A. 把 02:518/616/689、03:419/475（以及 04:325）统一改为 V0.5.2，并核对 §6.4/§8.3.1 引用；
B. 修正 V0.5.2 版本说明，如实记录“错误码示例 + retry 默认值”两处勘误（或把 retry 行放回 P1-03 的 diff）；
C. 同步 docs/agent.md:358 错误码与 :240 HITL 状态，或在 01/02/03 的证据索引注明其旧版快照属性；
D. 清理 README 旧交付路径与审核状态段；
E. 为最近一次 docs-site 构建留存日志/退出码，或在本批复核记录中明确“dist 产物构建时间 17:52:55，未留日志”；
F. P2-4/P2-6/P2-7 可随下批统一处理（补全错误码表、收敛“已实现”措辞、统一 HITL/Prompt Injection/Tool Gateway 状态词）。
```
