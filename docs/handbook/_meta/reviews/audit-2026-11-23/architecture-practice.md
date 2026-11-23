# Architecture Practice 批次内容质量审计报告

> **批次：** 06 · Architecture Practice（10 篇）
> **审计日期：** 2026-11-23
> **基线文章：** `docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md`（V0.5.1）
> **审计范围：**
> 1. `docs/handbook/06-architecture-practice/01-requirements-analysis.md`
> 2. `docs/handbook/06-architecture-practice/02-architecture-design-method.md`
> 3. `docs/handbook/06-architecture-practice/03-module-decomposition.md`
> 4. `docs/handbook/06-architecture-practice/04-module-dependencies.md`
> 5. `docs/handbook/06-architecture-practice/05-technology-selection.md`
> 6. `docs/handbook/06-architecture-practice/06-architecture-decision-records.md`
> 7. `docs/handbook/06-architecture-practice/07-architecture-review.md`
> 8. `docs/handbook/06-architecture-practice/08-performance-analysis.md`
> 9. `docs/handbook/06-architecture-practice/09-technical-debt.md`
> 10. `docs/handbook/06-architecture-practice/10-enterprise-architecture-case.md`
> **参考基线：** `AGENTS.md`（v3.28.0，重点 §10、§12、§13、§18、§19）、`docs/agent.md`、`docs/agent-design-current-vs-target.md`，以及相关 `src/`、`tests/`、`docs/` 文件
> **结论统计：** 通过 3 篇 / 条件通过 7 篇 / 不通过 0 篇；P0 = 0，P1 = 5，P2 = 13（另含 1 项批次共性 frontmatter 问题）

---

## 0. 审计说明

### 0.1 方法与边界

- 本次审计只读，未修改任何文章正文、配置或代码。
- **未运行** `pytest`、未启动浏览器、未发起 HTTP 请求；代码与文档事实通过阅读文件、`grep`/`Select-String` 与文件清单核对获得。
- 数字类结论以仓库中已有报告/文档/代码为准，**不把"报告写了"等同于"本次重跑验证"**；未重跑项在对应文章"未核验项"中注明。
- 外部链接（ISO、IEEE、Martin Fowler、web.dev 等）未逐一抓取，统一标为"未核验"。

### 0.2 证据快照与时效

- 仓库 HEAD：`32ad31bc26365e8d0cefe503e6c09cfcd2876eaa`（2026-11-22 19:15:14 +0800）。
- 工作区存在未提交修改（如 `AGENTS.md`、`src/rag_demo/api/main.py` 等），本报告以当前工作区事实为准。
- 10 篇文章均为**未纳入 git 跟踪**的工作区文件，mtime 为 2026-11-23 15:18–15:27。
- 审计时点（当日 17:20 左右）晚于文章生成时间：`src/rag_demo/api/main.py` 的 `/docs` 挂载与 `/api/docs` 迁移于 15:47 落地，`docs/handbook/README.md` 与 `docs-current-state-audit.md` 于 16:59 更新，`docs-site/.vitepress/dist` 构建产物于 17:16 生成。这解释了第 5 篇（技术选型）状态偏旧的原因，但审计仍按"当前工作区事实"判定。
- M0 收口早于文章生成：`docs/product/merchant-dashboard-v1.1-m0-closure.md`（2026-11-22）明确 `A-01～A-08` 全部 PASS、M0 = ACCEPTED、M1 未批准；这直接影响第 2、6 篇的 "M0 验收进行中" 标注。

### 0.3 批次共性辅助检查

| 检查项 | 结果 |
|---|---|
| 12 个二级章节结构 | **10/10 通过**：均为 `1 为什么… / 2 基本机制 / 3 总体架构 / 4 关键设计 / 5 工程实现 / 6 企业级要求 / 7 方案对比 / 8 Qianke Engine 实践 / 9 评估·验收 / 10 常见误区 / 11 总结 / 12 延伸阅读`，与 `docs-site/README.md` 声明的"每篇保留 12 个二级章节"一致。 |
| frontmatter 必填字段 | **10/10 齐全**：`title`、`description`、`section`、`section_order`、`order`、`slug`、`doc_status`、`implementation_status`、`version`、`updated`、`reading_minutes`、`prerequisites`、`tags`、`related` 均存在；`title` 与 H1 一致；`slug` 与文件名一致；`order` 1–10 连续；`updated: 2026-11-23`；`related` 均指向存在的同批文章。 |
| frontmatter `section` 值 | **P2（批次共性，10/10 命中）**：本批全部写 `section: "06 · Architecture Practice"`，与 `docs/handbook/_meta/information-architecture.md` §5 规范及基线文章 `section: Agent Architecture` 的写法不一致（应写分类英文名 `Architecture Practice`，编号由 `section_order` 表达）。建议全批统一。 |
| 状态词表 | `information-architecture.md` §3.5 定义 5 个写作状态（已实现/开发中/已设计/规划中/理论知识），未定义"部分实现"；但 `docs-site/README.md`、`docs/handbook/README.md` 与本批正文大量使用"部分实现"，且本批 frontmatter 采用"理论知识 + 已实现"式组合状态。属元数据规范文档之间不一致，建议以一处为准并回写信息架构文档。 |
| 明显自相矛盾 | 仅第 10 篇发现批次内自相矛盾（"两套 Agent/任务链路" vs "三条链路"）；第 2 篇与第 8 篇存在跨文章口径冲突（性能门禁是否已具备测试证据），详见对应条目。 |
| 过时状态 | 第 2、6 篇 "M0 验收进行中" 已过时（M0 已于 2026-11-22 ACCEPTED）；第 5 篇 VitePress 状态偏旧（构建与挂载已在文章生成后落地）。 |

### 0.4 结论统计

| 文章 | 结论 | P0 | P1 | P2 |
|---|---|---:|---:|---:|
| 01 需求分析 | 条件通过 | 0 | 0 | 2 |
| 02 架构设计方法 | 条件通过 | 0 | 2 | 1 |
| 03 模块拆分 | 条件通过 | 0 | 1 | 1 |
| 04 模块依赖 | 通过 | 0 | 0 | 1 |
| 05 技术选型 | 条件通过 | 0 | 0 | 2 |
| 06 ADR | 条件通过 | 0 | 1 | 1 |
| 07 架构评审 | 通过 | 0 | 0 | 0 |
| 08 性能分析 | 通过 | 0 | 0 | 0 |
| 09 技术债务 | 条件通过 | 0 | 1 | 0 |
| 10 企业级架构案例 | 条件通过 | 0 | 0 | 5 |
| **合计** | — | **0** | **5** | **13** |

判定口径：`通过` = 无 P0/P1 且未发现事实/证据/状态错误；`条件通过` = 存在 P1，或存在需要修正的事实/证据/状态类 P2；`不通过` = 存在 P0。

---

## 1. `01-requirements-analysis.md` — 条件通过

**实现状态声明是否成立：** frontmatter 标 `implementation_status: 理论知识 + 已实现`，正文 §1 另列"理论知识 / 已实现 / 部分实现 / 规划中"四类。逐项核对：需求文档类资产（项目背景、MVP 非目标、M0 计划、性能验收报告）确实存在，"需求条目无统一编号与追踪矩阵"也成立；总体判断基本成立，但有两处证据归因/口径偏宽。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| `docs/项目背景.md` 写出不能做的预测、多跳关系推理、真实时效语义，以及口径错配、SQL 路判定漂移等灰区 | **成立**：`docs/项目背景.md:264-274` 列"当前不能做的"与"已知的、待收敛的灰区"；`:387` 再次总结能力边界。 |
| `docs/MVP产品目标.md` 专设"不做什么（明确边界）"一节 | **成立**：`docs/MVP产品目标.md:99` 为"六、不做什么（明确边界）"，`:121` 为"七、验收标准"。 |
| M0 架构文档明确"只做架构审查与计划，不修改业务代码" | **成立**：`docs/product/merchant-dashboard-v1.1-m0-architecture-plan.md:4`。 |
| M0 用八项验收条件约束 M1 实施边界 | **成立**：`docs/decisions/merchant_dashboard_v1_1_m0_adr.md:36`（五项决策/八项验收）、`:210`（三项边界）、`:260`（A-01～A-08）。 |
| `AGENTS.md` §4.1、§4.3、§14 作为架构变更前确认规则 | **成立**：三节均存在（Understand/Plan、歧义处理、核心架构修改前必答）。 |
| "未见单一需求登记册" | **部分核验**：按文件名 `docs/**/*requirement*`、`docs/**/*需求*` 检索未命中登记册；未做全仓库语义检索。 |
| 性能门禁作为"需求到验收的可执行口径" | **部分成立**：`docs/e2e/b-end-performance-2026-11-14.md:101-107` 有"性能门禁建议"与通过/不通过判定，但为人工报告口径，**不是自动化门禁**。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | L100 | "M0 架构文档把范围、非范围、验收条件、风险、待确认决策分节列出" | M0 架构计划有 §1 目标与范围（含"不实现"）、§9 测试与验收、§10 风险与兼容性、§11 M0 退出标准，但**没有"待确认决策"独立分节**（仅有零散的"确认"清单）。该归因不准确。 | 改为"M0 计划/ADR 分别列出范围、非范围、验收条件、风险与退出条件"；如要提"待确认决策"，改引 `docs/decisions/three_agent_platform_architecture_decisions_v0.1.md` §16。 |
| P2 | L155 | "需求到验收的可执行口径 \| `docs/e2e/b-end-performance-2026-11-14.md` 性能门禁 \| 已实现" | 报告提供的是"性能门禁建议 + 本次通过/不通过判定"，不是可持续执行的自动化门禁；标"已实现"口径偏宽。 | 标为"已实现（人工门禁报告，未自动化）"，或与第 8 篇"生产 SLO/门禁未完整建立"的口径对齐。 |

**未核验项：**

- 外部链接（ISO/IEC 25010、IEEE 29148、INVEST、C4 model）未抓取，未核验可访问性。
- "需求散落在 docs/、docs/product/、docs/design/"为全局性描述，未逐文件统计。
- `docs/项目背景.md` 中统计数字（如实测耗时 6~20s）未重跑。

**一句话总评：** 方法论与 Qianke 证据整体扎实，仅两处证据归因/口径需要收紧，属可快速修订的条件通过。

---

## 2. `02-architecture-design-method.md` — 条件通过

**实现状态声明是否成立：** frontmatter `理论知识 + 已实现`；§8 表格逐行基本成立（架构文档、三端决策、迁移方案、Dashboard ADR 均存在且状态与文档一致），但两处关键状态/证据不成立：把人工性能门禁写成"测试中已有"，以及 M0 状态已过时。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| `docs/architecture-diagrams.md` 五层结构且自述"部分内容已落后" | **成立**：`docs/architecture-diagrams.md:3` 自述落后；`:20-51` 为 L1–L5 五层。 |
| `docs/agent-design-current-vs-target.md` 分开写当前/目标并列出 7 个决策 | **成立**：该文 §4 列 7 条"开发前需要确认的决策"。 |
| 三端决策 §3.3 要求 Monorepo 依赖方向与 CI 检查 | **成立**：`docs/decisions/three_agent_platform_architecture_decisions_v0.1.md:98-110`。 |
| 控制面迁移盘点 28 张表 / 437 处占位符 / 31 处 `BEGIN IMMEDIATE` | **成立**：`docs/decisions/control_plane_postgres_migration_v0.1.md:46,86-89`。 |
| 控制面迁移 P1–P3 已实施、生产观察待补 | **成立**：迁移主文档 `:3` 状态与 P1/P2-A/P2-B/P3-A/P3-B 五个实施记录链接。 |
| Dashboard M0 ADR 冻结五项决策、三项边界、八项验收条件 | **成立**：`docs/decisions/merchant_dashboard_v1_1_m0_adr.md:36,210,260`。 |
| "测试中已有…性能门禁等架构约束验证" | **不成立**：`tests/` 中无 LCP/CLS/p95/性能门禁测试（grep 无命中）；`.github/workflows/ci.yml:76-111` 仅含单测 + 离线 Eval 快照门禁，无性能门禁。性能门禁仅存在于 `docs/e2e/*performance*` 报告的人工判定中。 |
| "M0 验收进行中" | **不成立**：`docs/product/merchant-dashboard-v1.1-m0-closure.md:3-15` 记 M0 ACCEPTED（2026-11-22，A-01～A-08 全 PASS），`merchant-dashboard-v1.1-m0-acceptance-report.md:3` 同。 |
| Tool Policy 测试、租户隔离测试、SQLite/PostgreSQL schema 契约测试 | **成立**：`tests/test_agent_execution_safety.py:238-248`、`tests/test_b_chat_profile.py:108` 等；`tests/test_control_repository_contract.py:91`、`tests/test_c_reco_schema_parity.py`。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | L123、L184 | "测试中已有租户隔离、Tool Policy、schema 双端契约、性能门禁等架构约束验证" / "…B/C 端性能门禁" | 把报告级、人工判定的性能门禁混入"测试"证据。实际无性能测试/CI 性能门禁；第 8 篇也明确"生产 SLO、CI 性能门禁尚未完整建立"。 | 改为"性能门禁以 B/C 端性能报告的人工判定形式存在，尚未进入测试/CI"；或删去"测试中已有…性能门禁"。 |
| P1 | L161 | "Dashboard V1.1 架构基线 \| … \| 已实现（决策冻结，M0 验收进行中）" | 状态过时：M0 已于 2026-11-22 ACCEPTED，M1 未批准。 | 改为"已实现（M0 ACCEPTED 2026-11-22；M1 未批准）"，并在证据列补 closure/acceptance report。 |
| P2 | L157 | "企业级 Agent 六层架构 \| … \| 已实现（文档 + 部分代码对应）" | 六层是逻辑分层模型，代码中并非六层落地；标"已实现"易被读成能力已具备，尽管括注已提示"部分代码对应"。 | 建议"已设计（文档）+ 部分实现（代码映射）"，或"理论知识（分层模型）+ 部分实现"。 |

**未核验项：**

- 外部链接未抓取。
- "Qianke 实际做法是文档 + 代码结构 + 测试三者并用"的完整覆盖度未逐项穷举。
- 迁移方案中"维护窗口切换与回滚路径"只核验了文档存在，未核验回滚演练记录。

**一句话总评：** 架构方法论述清晰，但"性能门禁=测试证据"与 M0 状态两处必须修正，否则会让读者误判架构验证成熟度。

---

## 3. `03-module-decomposition.md` — 条件通过

**实现状态声明是否成立：** frontmatter `理论知识 + 部分实现`；模块清单、Repository 抽象、双后端、迁移映射等主要声明成立，但核心"已核验的盘点结论"使用了 2026-11-05 的过时行数，当前代码已显著增长。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| 当前包结构 `agent/ api/ b_end/ c_end/ superagent/ merchant/ control/ retrieval/ generation/ db/ storage/ tools/` | **成立**：`src/rag_demo/` 下均存在。 |
| 目标 Monorepo 映射（`agent/loop.py`→`packages/agent-runtime/`+`agents/b_agent/graph.py`；`agent/tools/sql.py`→`services/merchant-data-access/`+B Tool adapter） | **成立**：`docs/decisions/monorepo-migration-inventory-v0.1.md:54-66`。 |
| 三端决策 §14 给出 Monorepo 目录建议 | **成立**：该文 `:537` 为"## 14. 建议的 Monorepo 目录结构"。 |
| `merchant/` Repository 协议 + SQLite/PG adapter | **成立**：`merchant/repository.py`（`MerchantRepository`/`MerchantWriteRepository`）、`factory.py`、`sqlite_repository.py`、`postgres_repository.py`。 |
| 控制面双后端 | **成立**：`control/factory.py`、`sqlite_repository.py`、`postgres_repository.py`。 |
| 大文件"约 2,744 行 / 约 1,044 行，已核验" | **不成立（过时）**：当前 `src/rag_demo/c_end/store.py` 为 6,578 行、`src/rag_demo/superagent/store.py` 为 1,198 行（按 `Get-Content().Count`）。文章数字来自 `docs/decisions/control_plane_postgres_migration_v0.1.md:86-87`（2026-11-05 快照）。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | L131 | "`c_end/store.py` 约 2,744 行、`superagent/store.py` 约 1,044 行…这是已核验的盘点结论" | 数字已过时，且"已核验"与实际当前文件不符；来源是 11-05 迁移方案快照。 | 按当前代码重新计数（6,578 / 1,198 行，或写"截至 2026-11-23 约 6.5k / 1.2k 行"），并注明计数方法；删去"已核验的"或改为"迁移方案 v0.1 盘点值，当前已变化"。 |
| P2 | L164 | "控制面存储抽象 \| `control/repository`、`factory.py`、双后端 \| 已实现" | `src/rag_demo/control/` 下不存在 `repository` 文件/目录；实际为 `factory.py`、`sqlite_repository.py`、`postgres_repository.py`、`superagent_repository.py`。 | 改为 `control/factory.py`、`control/sqlite_repository.py`、`control/postgres_repository.py`。 |

**未核验项：**

- "单文件同时承担 schema、查询、状态迁移"：仅核验 `_SCHEMA` 与查询代码存在；"状态迁移"具体范围未逐段核查。
- `docs/decisions/monorepo-migration-inventory-v0.1.md` 当前状态为"待评审"，且文中"当前仓库真实结构"部分仍是 3 Tool、无 C 端的旧快照；文章只引用其目标映射，未引用其现状，但读者若顺链阅读会被旧现状误导（建议在引用处加"该文档为历史盘点"提示）。
- 外部链接未抓取。

**一句话总评：** 拆分方法与目标映射成立，唯一硬伤是把两个月前的盘点行数当作当前已核验结论，修订数字并校正 `control/repository` 路径即可。

---

## 4. `04-module-dependencies.md` — 通过

**实现状态声明是否成立：** frontmatter `理论知识 + 部分实现`；§8 依赖设计表与 §5 跨层 import 表全部可核验，状态标注（已实现 / 已设计未实施 / 部分实现）与实际一致。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| `control/factory.py` 按 `backend()` 返回 PG/SQLite repository | **成立**：代码与文中摘录一致。 |
| `merchant/context.py::run_in_merchant_scope` 在线程入口建立 scope | **成立**：函数存在（`merchant/context.py:52-55`），并有 `tests/test_merchant_scope.py:86` 覆盖。 |
| `agent/service.py` 在 Agent 执行前同时建立 `dataset_scope` 与 `merchant_scope` | **成立**：`agent/service.py:256-260` 在 `invoke()` 内重新建立（正是为规避 deadline 线程不传播 ContextVar）。 |
| 跨层 import：`agent/tools/chat_profile.py`→`b_end.identity`/`c_end.store` | **成立**：`agent/tools/chat_profile.py:19-20`。 |
| `b_end/user_pool.py`→`c_end.store` | **成立**：`b_end/user_pool.py:19,39`。 |
| `control/sqlite_repository.py`→`c_end`、`superagent` | **成立**：`control/sqlite_repository.py:6-7,21`。 |
| M0 计划记录 ContextVar 线程传播风险与修法 | **成立**：`docs/product/merchant-dashboard-v1.1-m0-architecture-plan.md:104-115,642-646`。 |
| 三端决策 §3.3 要求 CI 检查跨端依赖 | **成立**：`three_agent_platform_architecture_decisions_v0.1.md:98-110`。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | L163 | "线程边界重新建立上下文 \| `run_in_merchant_scope`；M0 计划记录 deadline 线程风险 \| 已实现（基础设施）/ 部分实现（全链路验证）" | 该 helper 目前只在测试中被调用，`src/` 生产路径（`agent/service.py`）实际直接使用 `merchant_scope(...)`，未调用 `run_in_merchant_scope`。把该函数作为"线程边界重新建立上下文"的实现证据略偏。 | 证据改写为"`agent/service.py::invoke` 内重建 `merchant_scope`；`run_in_merchant_scope` 为通用入口 helper（测试覆盖）"，状态保持"部分实现（全链路验证）"。 |

**未核验项：**

- §9 的 `rg` 检查命令作者已声明"本次未运行"；我未执行该命令，仅用等效 grep 核验 import。
- 是否有环依赖（DAG）未做全量 import 图分析。
- 外部链接未抓取。

**一句话总评：** 依赖方向、运行时上下文与现存跨层依赖都经得起核对，仅一处理解性表述建议收紧，可视为通过。

---

## 5. `05-technology-selection.md` — 条件通过

**实现状态声明是否成立：** frontmatter `理论知识 + 已实现`；技术栈事实基本成立，但"文档站"状态在审计时点已过时（VitePress 已构建并挂载 `/docs`），且"固定版本 4.2.6"与实际 `^4.2.6` 不符。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| Python 3.12 + uv，`requires-python = ">=3.12,<3.13"`、`uv sync --frozen` | **成立**：`pyproject.toml:9`；`docs/部署指南.md:57` 使用 `uv sync --frozen`。 |
| FastAPI + uvicorn、LangGraph + LangChain Core、DeepSeek OpenAI 兼容接口 | **成立**：`pyproject.toml:17-45`；`docs/项目背景.md:402`。 |
| PostgreSQL 16 + pgvector、SQLite 本地回退 | **成立**：`docker-compose.yml:30`（`pgvector/pgvector:pg16`）、`docs/部署指南.md:12,30`；`control/`、`merchant/` 双后端。 |
| BGE-M3 + bge-reranker-v2-m3 + jieba | **成立**：`docs/项目背景.md:399-401`。 |
| Vue 3 + Vite + Ant Design Vue（4.2.6） | **部分成立**：`web/package.json:16` 为 `"ant-design-vue": "^4.2.6"`（caret 范围，非固定）；`docs/product/b-ant-design-adoption.md:16` 记为 `ant-design-vue@4.2.6`。 |
| B 端订单页 chunk 约 686 KB / gzip 205 KB | **成立**：`docs/product/b-ant-design-adoption.md:110`。 |
| 控制面迁移"继续使用 PostgreSQL，不换数据库" | **成立**：`docs/decisions/control_plane_postgres_migration_v0.1.md:14-16`。 |
| `/api/docs` 迁移 + `/docs` 静态挂载 | **成立**：`src/rag_demo/api/main.py:521,523,756-758`。 |
| 文档站"已设计，构建/上线待核验" | **过时**：`docs/handbook/README.md` 称"官网 Docs 模块：已实现，/docs 可访问"；`docs-current-state-audit.md:7` 记"已用 VitePress 落地并挂载到 /docs"；`docs-site/.vitepress/dist` 存在；`docs-site/build-check.log` 记 `build complete in 92.24s`（2026-11-23）。线上公网可访问性我未验证。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | L143、L161、L167 | "VitePress（已选型，构建与上线待核验）" / "已设计，构建/上线待核验" / "构建产物与线上可访问性尚未核验" | 审计时点构建产物已存在、`/docs` 已挂载、README 已声明可访问；文章状态过时（文章 mtime 15:26 早于 Docs 落地 15:47–17:16，但文章 updated 标 2026-11-23，仍应按当前事实更新）。 | 改为"已实现（VitePress 构建 + FastAPI /docs 挂载；线上公网可访问性待核验）"，并补 `docs/handbook/README.md`、`docs-site/README.md` 证据。 |
| P2 | L140 | "采用（B 端），固定版本 4.2.6" | `web/package.json` 实际为 `^4.2.6`（允许 4.x 升级），不是固定版本。 | 改为"选定 4.2.6（package.json 当前为 ^4.2.6 范围，如需锁定应写死）"。 |

**未核验项：**

- `/docs` 线上公网可访问性：未做浏览器/HTTP 验证。
- "DeepSeek、BGE-M3、LangGraph 候选方案对比文档仓库中未见"：仅按目录与关键词检索，未做全仓库穷举；作者已标"待核验"，我维持该标注。
- 外部链接未抓取。

**一句话总评：** 技术栈事实与选型案例大体可靠，需同步 VitePress 已落地的新状态并修正"固定版本"表述。

---

## 6. `06-architecture-decision-records.md` — 条件通过

**实现状态声明是否成立：** frontmatter `理论知识 + 部分实现`；ADR 结构、编号现状、三端决策状态分类等判断成立，但 M0 状态已过时，待确认清单数量写错。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| `docs/decisions/` 只有 ADR-0002 使用编号 | **成立**：目录 9 个文件中仅 `merchant_dashboard_v1_1_m0_adr.md` 标题为 `ADR-0002`。 |
| ADR-0002 含五项决策、三项不可违反边界、八项 M0 验收条件、M1 边界、备选方案 A/B/C/D、状态说明 | **成立**：该文 `:36,38,210,260,423,497,530`。 |
| 状态说明写明"决策冻结与验收定义，不代表 M0 验收完成、不代表可开始 M1 编码" | **成立**：该文 `:530-546`。 |
| 控制面迁移主文档 + P1/P2/P3 独立实施记录 | **成立**：`control_plane_postgres_migration_v0.1.md:3-9` 链接 5 份实施记录，主文档无编号。 |
| 三端决策把决策分为"已确认 / 第一版约束 / 待验证"三类 | **成立**：`three_agent_platform_architecture_decisions_v0.1.md:34-40`。 |
| "保留 16 项待确认决策清单" | **不成立**：该文 §16"待确认决策清单"实际为 **12 项**（`:643-658`）；"16"疑似与章节号 §16 混淆。 |
| "M0 验收进行中" | **不成立**：`merchant-dashboard-v1.1-m0-closure.md:3-15` 记 M0 ACCEPTED（2026-11-22）。 |
| 统一 ADR 模板/编号规则/索引"仓库中未见" | **成立**：`docs/decisions/` 无 index/template 文件；全 docs 关键词检索无 ADR 模板文件。 |
| `monorepo-migration-inventory-v0.1.md` 状态"已设计（待评审）" | **成立**：该文 `:3` 状态"待评审"。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | L163 | "`merchant_dashboard_v1_1_m0_adr.md` … \| 已实现（决策冻结，M0 验收进行中）" | 状态过时：M0 已 ACCEPTED、M1 未批准；表格结论会让读者误判项目阶段。 | 改为"已实现（M0 ACCEPTED 2026-11-22；M1 未批准）"，证据补 `merchant-dashboard-v1.1-m0-closure.md`。 |
| P2 | L170 | "保留 16 项待确认决策清单" | 实际 §16 清单为 12 项；数字与文档不符。 | 改为"保留 12 项待确认决策清单（原文 §16）"，或改为"保留 §16 的待确认决策清单"避免数字。 |

**未核验项：**

- "部分决策散落在 `docs/product/` 与 `docs/design/`"未逐文件统计。
- "ADR 与代码/测试的自动关联"属未来规划，无仓库证据可核验。
- 外部链接未抓取。

**一句话总评：** 对 ADR 实践的判断准确，但 M0 状态与待确认清单数量两处需要按当前文档修正。

---

## 7. `07-architecture-review.md` — 通过

**实现状态声明是否成立：** frontmatter `理论知识 + 部分实现`；§8 评审实践表与 §5 三种形态的引证均可核验，状态标注与仓库文档一致。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| V0.1 技术审核结论"需修订后复审"，5 项技术错误 / 4 项设计不完整 / 2 项表达优化 | **成立**：`docs/handbook/_meta/reviews/01-enterprise-agent-architecture-v0.1-technical-review.md:12,16-18`。 |
| 审核报告 R-01～R-11 编号、逐条代码依据 | **成立**：该报告 `:109-124` 问题总表，正文逐条含代码位置。 |
| 审核报告把"34 passed"限定为只覆盖已运行测试 | **成立**：该报告 `:95-107`。 |
| 审核报告声明版本/行数不一致（约 996 行 vs 工作区 814 行） | **成立**：该报告 `:36-53`。 |
| 编码前代码审查文档存在，指出命名冲突、schema 双来源、队列复用边界 | **成立**：`docs/product/merchant-dashboard-v1.1-code-review.md:12-20`（5 个真实缺口）、G-01/G-03/G-07（`:100,150,275`）。 |
| M0 计划与 ADR-0002 定义八项验收条件、每项要求证据 | **成立**：`merchant_dashboard_v1_1_m0_adr.md:260-421`。 |
| "M0 架构计划完成不等于 M0 验收完成"被明确写出 | **成立**：ADR `:262-263`。 |
| "评审有条件通过不等于用户批准上线"出自 Qianke 设计评审文档 | **成立**：`docs/design/b-end-2.0-multistore-role-mapping.md:7`。 |
| "未见评审自动化门禁" | **成立**：`.github/workflows/ci.yml` 无评审门禁，仅有单测 + 离线 Eval 快照门禁。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| — | — | — | 未发现 P0/P1/P2 级事实、证据或状态问题。注：`merchant-dashboard-v1.1-code-review.md` 自身"5 个真实缺口"与 §4 列出的 G-01～G-10 存在计数口径差异，但文章引用与原文标题一致，不算文章错误。 | 可保留；如追求严谨，可在引用处写"文档结论称 5 个真实缺口（正文列 G-01～G-10 十个问题）"。 |

**未核验项：**

- "评审效果可用指标观察"未实际采集数据。
- 统一评审模板/记录索引"仓库中未见"：按目录与关键词检索确认，未做全仓库穷举。
- 外部链接（Google eng-practices、SEI ATAM、arc42、NIST）未抓取。

**一句话总评：** 证据链完整、结论克制，是本批中质量最稳的一篇。

---

## 8. `08-performance-analysis.md` — 通过

**实现状态声明是否成立：** frontmatter `理论知识 + 部分实现`；案例数字全部能在仓库报告中找到出处，且明确区分"已修复并复测""已设计未落地""规划中"，未发现把规划写成已实现。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| B 端售后 N+1：29 条、p50 726ms/p95 870ms/并发 5 p95 2,139ms；改后 p50 56.5ms/p95 71.5ms/并发 83.5ms | **成立**：`docs/e2e/b-end-performance-2026-11-14.md:64`；`docs/e2e/b-end-acceptance-2026-11-14.md:21-44`。 |
| 根因：逐条 `get_order` + 逐条商家校验，改法 `c_after_sale JOIN c_order` 按 merchant_id 过滤 | **成立**：`b-end-acceptance-2026-11-14.md:21-35`；`b-end-performance-2026-11-14.md:70-90`。 |
| 测试 `tests/test_b_workbench_api.py::test_after_sales_only_for_bound_merchant` 存在 | **成立**：`tests/test_b_workbench_api.py:240`。 |
| C 端 CLS 0.17/0.576 → 0.03/0.00；首屏 1.59MB → 约 104KB；Fast 3G LCP 8,004ms → 870ms | **成立**：`docs/e2e/c-end-performance-2026-11-14.md:17-18,59-68,158-170,235-240`。 |
| 26 个视图路由级动态 import；`GZipMiddleware(minimum_size=1024)` | **成立**：该报告 `:177-178`。 |
| 提交 `e40b704` | **成立**：`git log` 存在该提交。 |
| 测量方法：Chrome DevTools trace + Playwright；快网/慢网、20 次顺序 + 5 并发 × 50 次 | **成立**：B/C 性能报告环境与接口表（B 报告 `:55-64`、C 报告 `:63` 等）。 |
| `/qa` 典型 9–17s、生成占 92–96% | **成立**：`docs/接口文档.md:825`。 |
| RAG LLM 92%–99%、本地计算 <1s | **成立**：`docs/项目背景.md:311,369`。 |
| Agent Eval 平均耗时：Regression 3.8s、Benchmark 4.0–4.1s | **成立**：`docs/e2e/agent-eval-2026-11-14.md:34,52`。 |
| 页面性能门禁 LCP≤2.5s/CLS≤0.1/TTFB≤0.8s 为报告建议 | **成立**：B/C 性能报告"性能门禁建议/判定"章节。 |
| 生产 SLO/告警、持续性能门禁、容量基线未完整建立 | **成立**：文章自身状态小结与报告口径一致；`tests/` 与 CI 无性能门禁。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| — | — | — | 未发现 P0/P1/P2 级事实、证据或状态问题。 | 建议保留现有"数字来自报告、未重跑"的口径。 |

**未核验项：**

- 所有性能数字引用自报告，本次未重跑测量；未打开 `var/b_perf_api.json` 等原始数据文件。
- 未验证报告截图的浏览器现场状态。
- 外部链接（web.dev、Brendan Gregg、PostgreSQL EXPLAIN）未抓取。

**一句话总评：** 性能案例数字与因果链全部有出处，状态边界清楚，是本批证据质量最高的文章之一。

---

## 9. `09-technical-debt.md` — 条件通过

**实现状态声明是否成立：** frontmatter `理论知识 + 部分实现`；债务清单绝大多数可核验，但"超大存储文件"行使用了过时行数，低估了债务规模。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| 双 schema 来源：SQLite `c_end/store.py::_SCHEMA` + PG `control/schema_pg.sql` | **成立**：`c_end/store.py:385` 定义 `_SCHEMA`（`:386` 起为 `CREATE TABLE`）；`control/schema_pg.sql:3-7` 起定义 `c_*` 表（共 63 张）。 |
| 新表必须双端同步，否则契约测试失败 | **成立**：`tests/test_c_reco_schema_parity.py:4` 明确两套 DDL；`tests/test_control_repository_contract.py:91` 校验 PG schema 与 SQLite 一致。 |
| 跨层 import：`agent/tools/chat_profile.py`→`b_end`/`c_end`；`control/sqlite_repository.py`→`c_end`/`superagent` | **成立**（同第 4 篇核验）。 |
| `architecture-diagrams.md` 自述过期 | **成立**：该文 `:3`。 |
| `BOrders.vue` 保留为回滚备份；Ant 订单页 chunk 约 686KB | **成立**：`docs/product/b-ant-design-adoption.md:92,110`。 |
| 测试缺口：超时后 Worker 返回、同 request_id 重试等场景未覆盖（v0.5.1） | **成立**：基线文章 §6.4/§8.3 与 §8.3.1 测试表明确列出未覆盖项。 |
| 性能遗留：B 端商品列表并发 p95 862ms、C 端商家商品 5 并发 p95 870ms | **成立**：`docs/e2e/b-end-performance-2026-11-14.md:62`；`docs/e2e/c-end-performance-2026-11-14.md:112`。 |
| torch 必须锁定本地 cu126 wheel | **成立**：`pyproject.toml:39-62`。 |
| 偿还证据（售后 N+1、CLS/首屏、控制面迁移、request_id 幂等/scope/Tool Policy） | **成立**（分别见第 8 篇核验与基线文章）。 |
| "超大存储文件约 2,744 行 / 1,044 行" | **不成立（过时）**：当前为 6,578 行 / 1,198 行；2,744/1,044 来自 `control_plane_postgres_migration_v0.1.md:86-87`（11-05 快照）。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | L107 | "超大存储文件 \| `c_end/store.py` 约 2,744 行、`superagent/store.py` 约 1,044 行" | 行数已过时（当前约 6,578 / 1,198），恰好低估了本文要论证的"单文件膨胀"债务。 | 按当前代码更新行数；若坚持引用迁移方案旧值，需注明"2026-11-05 快照，当前已增长"。 |

**未核验项：**

- "统一债务登记册与季度复审""依赖边界 CI 与债务预算"属"仓库中未见/规划中"的缺失型声明，未做全仓库穷举检索。
- "单文件同时承担 schema、查询、状态迁移"未逐段核查状态迁移代码。
- 外部链接（Martin Fowler、Ward Cunningham、Google SRE）未抓取。

**一句话总评：** 债务分类与偿还证据可信，唯一硬伤同样是复制了旧快照行数，更新数字即可。

---

## 10. `10-enterprise-architecture-case.md` — 条件通过

**实现状态声明是否成立：** frontmatter `已实现 + 已设计`；§5 能力表与 §6 企业级状态表与代码/基线文章总体一致，未把规划写成已实现；问题集中在时间线证据、内部口径自相矛盾与一处数字口径。

**证据核验结果：**

| 声明 | 核验结果 |
|---|---|
| B 端 Agent Runtime（LangGraph/State/预算/超时/幂等） | **成立**：`agent/loop.py`、`agent/service.py`。 |
| 当前注册 7 个 Tool + ToolPolicy + Tool Contract | **成立**：`agent/registry.py` 注册 7 个；`agent/policy.py` 角色矩阵；`agent/tool.py`。 |
| 受控写草稿 `prepare_followup_task` + `confirm_agent_action` | **成立**：`agent/tools/action.py`、`api/main.py:1466`。 |
| C 端交易与 IM（商品/订单/售后/IM/推荐/模拟下单） | **成立**：`c_end/` 下 `agent.py`、`store.py`、`social.py`、`recommend/` 等。 |
| Super-agent 队列/Worker/审批/审计 | **成立**：`superagent/queue_pg.py`、`runtime.py`、`worker.py`、`approval_card.py`、`wecom_approval.py`。 |
| 商家数据层 Repository 协议 + SQLite/PG adapter + 幂等库存/订单 | **成立**：`merchant/repository.py:188,221,225` 明确幂等语义；`postgres_repository.py` 有 request_id 幂等索引与迁移。 |
| 控制面双后端 + 契约测试 | **成立**：`control/` 双后端；`tests/test_control_repository_contract.py`、`test_cend_pg_backfill.py` 等。 |
| `dataset_scope` / `merchant_scope` 由服务端注入、缺失失败关闭 | **成立**：`agent/context.py`、`merchant/context.py`、`agent/service.py:256-260`。 |
| `/ready`、`/metrics` 存在 | **成立**：`api/ops.py:108,114`。 |
| "tests/ 下 126 个 `test_*.py`" | **部分成立**：`tests/` 顶层 `test_*.py` = 126，递归（含 `tests/evals/`）= 130；文章未说明口径。 |
| AGENTS v3.28.0 记录 823 tests | **成立**：`AGENTS.md:648`。 |
| Regression 20/20 | **成立（引用）**：`docs/agent.md` v2.2 基线 Regression Task Success 100%（20 题）；未重跑。 |
| 时间线 "1.0 \| RAG 问答与评测基线" | **不成立**：`AGENTS.md:452` 变更记录中 `1.0` 是 AGENTS.md 文档版本"初版，29 节"，不是产品里程碑；仓库中未找到"1.0 = RAG 问答与评测基线"的出处。 |
| 时间线 "2.1–2.29 \| …审批、审计" | **部分成立**：审批在 2.1–2.11 区间成立，但"动作执行审计"里程碑在 `AGENTS.md:544` 的 2.30.0；"审计"放进来早了一格。 |
| "两套 Agent/任务链路"与后文"三条链路" | **自相矛盾**：L63 称"两套 Agent/任务链路"，L116 写"三条链路需要区分清楚"（主 B 端 / Super-agent / C 端），架构图也画了三条。 |
| "资金自动执行上限为 0" | **需标出处**：该表述出自 `three_agent_platform_architecture_decisions_v0.1.md` §1/§17 的"第一版约束"；当前代码中商家动作策略有 `compensation_max_amount`/`refund_max_amount` 默认 50/1000，属**审批后执行**的动作上限，并非"自动执行"。两者不冲突，但文章把它写成当前事实时缺少来源与口径说明。 |

**问题列表：**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | L63 vs L116 | "多端入口 + 两套 Agent/任务链路" / "三条链路需要区分清楚" | 同文自相矛盾：后文与架构图均为三条链路（B 端 Agent、C 端 Graph、Super-agent）。 | 统一为"三条链路"或在 L63 说明"两套 Agent 编排（B/C）+ 一套异步任务链路（Super-agent）"。 |
| P2 | L155 | "1.0 \| RAG 问答与评测基线 \| 先验证'检索+生成+引用'闭环" | 引用来源 `AGENTS.md` 变更记录中 1.0 是 AGENTS.md 文档版本，未记录该产品里程碑；时间线有补造风险。 | 删除该行或改引有出处的文档（如 README/项目背景中的阶段描述）；若作为叙述性归纳，需标注"非变更记录原义"。 |
| P2 | L159 | "2.1–2.29 \| Super-agent、PG 队列、Worker、审批、审计" | "动作执行审计"属于 2.30.0（`AGENTS.md:544`），不在 2.1–2.29 区间。 | 区间改为 2.1–2.30，或将"审计"从该行移除。 |
| P2 | L114 | "`tests/` 下 126 个 `test_*.py`" | 顶层 126 个与递归 130 个不一致，口径未说明，读者无法复核。 | 写明"tests/ 顶层 126 个 `test_*.py`（含子目录共 130 个）"或直接按递归数更新。 |
| P2 | L95 | "高风险动作必须人工确认，资金自动执行上限为 0" | 该表述来自三端决策的"第一版约束"，文章作为当前实现事实陈述且未标来源；与代码中商家动作策略默认补偿 50 / 退款 1000 的上限（审批后执行）容易被误读为矛盾。 | 标注来源"三端决策 v0.1 第一版约束"，并说明"自动执行上限为 0"指无人工确认不得执行资金动作；审批后执行上限另由商家动作策略控制。 |

**未核验项：**

- "C 端 Mock 交易闭环"未实际运行验证；仅核验 `c_end/` 模块与文档存在。
- "大规模生产流量下的可用性与延迟""完整租户隔离（独立数据库/账号）"等"尚未被证明"的判断未实测。
- "资金自动执行上限为 0"与当前动作策略上限的关系依据文档阅读推断，未跑动作执行路径。
- 外部链接（AWS Well-Architected、C4、12-Factor）未抓取。
- 未做浏览器/接口 E2E。

**一句话总评：** 案例覆盖面与状态表基本可信，但时间线引证、链路数量口径和"资金上限"出处需要校正，属可修复的条件通过。

---

## 11. 批次汇总与修订优先级

**P1（建议本批修订前必须处理）：**

1. `02-architecture-design-method.md` L123/L184：性能门禁被写成"测试中已有"——无对应测试/CI，建议改为人工报告口径。
2. `02-architecture-design-method.md` L161：M0 状态过时（已 ACCEPTED）。
3. `06-architecture-decision-records.md` L163：M0 状态过时（同上）。
4. `03-module-decomposition.md` L131：`c_end/store.py` / `superagent/store.py` 行数过时（2,744/1,044 → 约 6,578/1,198）。
5. `09-technical-debt.md` L107：同一组行数过时。

**P2（建议同批修订）：**

- `01` L100 M0 文档"待确认决策分节"归因不准；L155 性能门禁"已实现"口径偏宽。
- `02` L157 六层架构标"已实现"。
- `03` L164 `control/repository` 路径不存在。
- `04` L163 `run_in_merchant_scope` 生产路径未被调用。
- `05` L143/L161/L167 VitePress 状态过时；L140 "固定版本 4.2.6" 与 `^4.2.6` 不符。
- `06` L170 "16 项"应为 12 项。
- `10` L63 vs L116 "两套 vs 三条"；L155 时间线 1.0 无出处；L159 审计区间；L114 测试数口径；L95 资金上限出处。

**批次共性（P2）：**

- 10 篇 frontmatter `section` 均写 `"06 · Architecture Practice"`，与信息架构规范及基线文章写法不一致，建议统一为 `Architecture Practice`。
- 状态词表在 `information-architecture.md` / `docs-site/README.md` / 正文之间不一致（"部分实现"是否合法、是否允许组合状态），建议统一后回写规范。
- 建议每篇在 §8 证据表或文末固定写"证据快照 / 核验日期 / 未核验项"，本批只有少数篇目（如第 4、5、8 篇）做到了局部标注。

**总体判断：** 本批 10 篇的 12 节结构、frontmatter 完整性与"Qianke 实践"证据意识整体较好，未发现把规划能力系统性写成已实现的情况，也没有 P0 级虚构证据。主要风险集中在两类：一是**复制旧快照数字/状态未更新**（第 2、3、6、9 篇），二是**把人工报告或设计决策写成测试/实现事实**（第 2、10 篇）。修订这些点后，本批可整体转为可发布草稿。
