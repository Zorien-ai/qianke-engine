# Qianke Engine Architecture Handbook · 批次内容质量审计报告

> **批次**：`03 · System Architecture`（system-architecture，共 10 篇）  
> **审计日期**：2026-11-23  
> **基线文章**：`docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md`（v0.5.1，§8.3.1 证据索引为本次审计的对照基准）  
> **审计范围**：`docs/handbook/03-system-architecture/` 下 10 篇文章（清单见 §1）  
> **结论统计**：通过 3 篇 / 条件通过 7 篇 / 不通过 0 篇  
> **报告性质**：只读审计。未修改任何文章正文、配置或代码；本次仅新增本报告文件。

---

## 1. 审计范围与依据

### 1.1 被审文件

| # | 文件 |
|---:|---|
| 1 | `docs/handbook/03-system-architecture/01-enterprise-system-design.md` |
| 2 | `docs/handbook/03-system-architecture/02-modular-monolith-vs-microservices.md` |
| 3 | `docs/handbook/03-system-architecture/03-api-gateway.md` |
| 4 | `docs/handbook/03-system-architecture/04-service-communication.md` |
| 5 | `docs/handbook/03-system-architecture/05-message-queue-event-driven.md` |
| 6 | `docs/handbook/03-system-architecture/06-distributed-task-scheduling.md` |
| 7 | `docs/handbook/03-system-architecture/07-database-architecture.md` |
| 8 | `docs/handbook/03-system-architecture/08-cache-system-design.md` |
| 9 | `docs/handbook/03-system-architecture/09-distributed-transactions-consistency.md` |
| 10 | `docs/handbook/03-system-architecture/10-system-scalability.md` |

### 1.2 审计依据

- 基线文章：`docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md`
- 项目协议：`AGENTS.md`（重点第 10、12、13、18、19 节）
- Agent 现状文档：`docs/agent.md`、`docs/agent-design-current-vs-target.md`
- Handbook 规范：`docs/handbook/_meta/information-architecture.md`、`docs/handbook/_meta/docs-current-state-audit.md`、`docs/handbook/README.md`
- 代码与测试：`src/rag_demo/**`、`tests/**`、`scripts/**`、`deploy/**`、`ops/**`、`infra` 配置（`docker-compose.yml`、`nginx.conf`、`Dockerfile`、`alembic.ini`、`pyproject.toml`、`.github/workflows/ci.yml`）
- 架构决策文档：`docs/decisions/*.md`、`docs/e2e/*.md`、`docs/design/*.md`、`docs/product/*.md`（按需）

### 1.3 审计标准（按任务要求收敛为三项）

- **A 技术准确性**：概念、架构职责、状态语义、代码行为、数字、因果关系是否成立。
- **B 实现状态**：文章标注的「已实现 / 部分实现 / 已设计 / 规划中 / 理论知识」是否与代码、测试、文档一致；是否把规划写成已实现。
- **C 证据真实性**：引用的文件、测试、命令、数字是否存在且能支撑结论；不能核验的标「未核验」。
- 辅助检查：12 个二级章节结构、frontmatter、自相矛盾、过时状态。

### 1.4 证据基线与方法

- **代码快照**：`git rev-parse HEAD` = `32ad31bc2636`（分支 `b-end-2.0-p0`，与基线文章 §8.3.1 记录的 commit 一致）。
- **工作区状态**：`git status` 显示 `AGENTS.md`、`docs/career/qianke-resume-bullets.md`、`src/rag_demo/api/main.py` 等 15 个文件有未提交改动；被审 10 篇为**未跟踪新文件**（`?? docs/handbook/03-system-architecture/`），无提交历史可核。
- **代码事实按工作区文件核验**，不按 `AGENTS.md` 变更记录或旧文档转述；AGENTS 变更记录只作为「历史声明」证据，需代码/文档二次确认。
- **未执行**：本次审计**没有运行 pytest、没有启动服务、没有使用浏览器**。报告中的「测试覆盖」仅指阅读测试文件与用例名，不代表执行结果；凡涉及运行行为（如 WebSocket 经 Nginx 是否可用、限流实际触发）均标注为「按配置/代码推断，未实测」。
- 行号均基于 2026-11-23 本机文件内容。

### 1.5 结论判定口径

| 结论 | 判定标准 |
|---|---|
| **通过** | 无 P0/P1；实现状态声明全部成立；证据可核验；P2 仅为表述优化，不影响状态与证据判断 |
| **条件通过** | 无 P0；但存在 P1，或存在会削弱实现状态/证据可信度的 P2；完成修正后可通过 |
| **不通过** | 存在 P0（编造证据、把规划系统性写成已实现、核心事实错误），或整体不可信 |

### 1.6 结论汇总

| # | 文件 | 结论 | P0 | P1 | P2 | 一句话 |
|---:|---|---|---:|---:|---:|---|
| 1 | 01-enterprise-system-design | 条件通过 | 0 | 0 | 2 | 方法论自洽、证据基本可核；但「现状 vs 目标」引用的文档已过时，需补注或换证据 |
| 2 | 02-modular-monolith-vs-microservices | 条件通过 | 0 | 1 | 1 | 形态判断与 Worker 证据成立；但「订单/库存/售后同一存储事务」与代码及第 9 篇冲突 |
| 3 | 03-api-gateway | 条件通过 | 0 | 1 | 3 | 边缘代理与应用内治理证据充分；但 WS 路径/代理配置与 `/docs` 路由已过时，`/ready` 路由表缺失 |
| 4 | 04-service-communication | 条件通过 | 0 | 1 | 2 | 超时/幂等/回调验签证据扎实；但 C 端 WS 路径少了 `/api/c` 前缀，通用 Webhook 不是报文签名 |
| 5 | 05-message-queue-event-driven | 通过 | 0 | 0 | 2 | 队列、租约、死信、重放均有代码依据；replay 位置归属写错，默认后端需补充说明 |
| 6 | 06-distributed-task-scheduling | 通过 | 0 | 0 | 0 | 三条任务路径与脚本/systemd 证据逐项可核，缺失项与未核验项标注诚实 |
| 7 | 07-database-architecture | 条件通过 | 0 | 2 | 2 | 分库/只读账号/迁移证据成立；但「28 表」过时、连接池状态写反，另有口径可收敛 |
| 8 | 08-cache-system-design | 通过 | 0 | 0 | 1 | 键设计、数据版本失效、PWA 边界全部可核；「容量上限可配置」略超实际 |
| 9 | 09-distributed-transactions-consistency | 条件通过 | 0 | 0 | 2 | 一致性机制清单可核、未核验项诚实；「不存在可覆盖两存储的本地事务」表述过强 |
| 10 | 10-system-scalability | 条件通过 | 0 | 0 | 2 | 扩展点与阻碍项基本准确；但连接池状态与「未见压测报告」两处需修正 |

### 1.7 辅助检查结论

**12 个二级章节结构**：10/10 通过。每篇正文均含编号 `## 1` – `## 12` 共 12 个二级章节；第 01 篇 §5 的 ADR 模板中的 `## 状态/背景/候选…` 位于 markdown 代码围栏内，不构成实际标题，不计入结构问题。

**frontmatter**：10/10 通过。
- 必填字段齐全：`title`、`description`、`section`、`section_order`、`order`、`slug`、`doc_status`、`implementation_status`、`version`、`updated`、`related`；
- `description` 长度 86–110 字，符合规范 80–160 字；
- `section` 均为 `03 · System Architecture`，`section_order` 均为 3，`order` 1–10 连续；
- `related` 中所有 slug 均能在仓库 handbook 内找到对应文章；
- `doc_status` 均为 `草稿`，`version` 均为 `0.1.0`，`updated` 均为 `2026-11-23`（与审计日期一致；因文件未提交 Git，无法用提交时间交叉核验）。

**自相矛盾**：发现 1 处跨篇事实冲突（第 02 篇 vs 第 09 篇，见 §4.1）；1 处篇内图文不一致（第 03 篇架构图含 `/ready`，路由表不含）；2 处「状态表 vs 代码」不一致（第 07、10 篇连接池）。

**过时状态**：4 处（第 07 篇「28 表」、第 03 篇 `/docs` 与 `/openapi.json`、第 01 篇引用的 `docs/agent-design-current-vs-target.md`、第 10 篇「仓库内未见统一压测报告」）。

---

## 2. 分篇审计

### 2.1 `docs/handbook/03-system-architecture/01-enterprise-system-design.md`

**结论：条件通过**

**实现状态声明是否成立**：基本成立。`implementation_status: 理论知识 + 部分实现` 与正文 §8 一致；「ADR/决策文档」「现状 vs 目标分栏」「迁移含回滚/验收」「仓储双后端契约测试」可核；「统一架构评审流程 / 场景库 / 依赖方向守护」标为规划中，与仓库现状基本相符。主要问题在证据的时效性与一处绝对化表述。

**证据核验结果**

成立：
- §4 称 `AGENTS.md` 已把「改核心架构前先说明影响面、迁移与回滚方案」写成硬规则：`AGENTS.md` §0 第 7 条确为「改核心架构前，先说明影响面、迁移和回滚方案」，成立。
- §4 称 Qianke 有 `tests/test_control_repository_contract.py`、`test_tenant_isolation_pg.py`、`test_control_job_queue.py`：三个文件均存在；前者当前断言 63 张表的双后端一致性（`EXPECTED_TABLES` 见 `tests/test_control_repository_contract.py:11-26`）。
- §5 称 `docs/decisions/control_plane_postgres_migration_v0.1.md` 具备「现状、目标架构、类型映射、切换策略、回滚、验收与风险」：该文档 `## 2/3/4/7/8/10/11` 章节标题正是现状、目标架构、表与类型映射、切换策略、回滚、验收标准、风险，成立。
- §5 称 `merchant_dashboard_v1_1_m0_adr.md` 是模块级样本：文件存在（`docs/decisions/merchant_dashboard_v1_1_m0_adr.md`，标题 `ADR-0002：Merchant Dashboard V1.1 M0 架构基线与 M1 边界`）。
- §8 称 `docs/architecture-diagrams.md`「自述部分过期」：该文件第 3 行明确写「部分内容已落后于当前实现：缺 `/qa/stream`、入口 BERT 路由、`search_index` 表、深度思考链路，待刷新」，成立。
- §7 称「单团队、2C4G 项目」：`docker-compose.yml` 文件头写明「目标机器：Ubuntu 22.04 / 2 核 4G」，成立。
- §8「迁移含回滚/验收」引用控制面迁移方案 §7–§10：§7 切换策略、§8 回滚、§10 验收标准，成立。

不成立 / 需修正：
- §8 表「现状 vs 目标分栏 | 已实现 | `docs/agent-design-current-vs-target.md`」：该文档确实存在且有「当前/目标/差距」三节，但内容停留在 **2026-10-28**，其中「只有 B 端一条 StateGraph」「没有 C/A 端、没有 interrupt/HITL」「写操作：无」等已与 `AGENTS.md` §18/§19（C 端 mock 闭环、HITL 草稿确认、Super-agent 队列）及当前代码不符。作为「已实现」证据只能证明文档形式存在，不能支撑「现状」判断，且会误导读者以为它就是当前现状基线。
- §8 表「统一架构评审流程 | 规划中 | 无模板化评审记录」：「无模板化评审记录」偏绝对——仓库存在零散的评审/验收记录，如 `docs/product/merchant-dashboard-v1.1-code-review.md`、`docs/product/merchant-dashboard-v1.1-m0-acceptance-report.md`。更准确的表述是「有零散代码评审/验收报告，但没有统一架构评审模板与流程」。

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §8 表（第 139 行） | 「现状 vs 目标分栏 \| 已实现 \| `docs/agent-design-current-vs-target.md`」 | 证据文档过时（2026-10-28），与 AGENTS §18/19 及代码现状冲突；读者会把它当作现状基线 | 改为「已实现（文档形式）；内容截至 2026-10-28，已知落后：C 端/A 端、HITL、Super-agent 均未纳入」；或换用 `docs/agent.md` + `docs/decisions/three_agent_platform_architecture_decisions_v0.1.md` 组合，并标注更新时间 |
| P2 | §8 表（第 143 行） | 「统一架构评审流程 \| 规划中 \| 无模板化评审记录」 | 仓库存在零散 code review/验收报告，「无评审记录」绝对化 | 改为「有零散评审/验收记录（docs/product/*code-review*、*acceptance-report*），但无统一架构评审模板与流程」 |

**未核验项**
- 「场景库/架构度量 | 规划中 | 无质量属性场景台账」为负向断言，未穷举仓库全部文档，未核验。
- 「依赖方向守护 | 规划中 | 仅 AGENTS 规则，无 CI 检查」：已确认 `.github/workflows/ci.yml` 只有「pytest + 离线评测门禁」两步、无 import 方向检查，该断言成立；但「无 CI 检查」不等于「无 CI」，建议正文补一句避免误读。

**一句话总评**：方法论与工程证据基本自洽、可核；扣分点集中在引用的「现状/目标」文档已过时与一处绝对化表述，属修正性问题。

---

### 2.2 `docs/handbook/03-system-architecture/02-modular-monolith-vs-microservices.md`

**结论：条件通过**

**实现状态声明是否成立**：形态判断成立。`已实现（模块化单体 + 独立 Worker） + 已设计（三端架构） + 规划中（微服务拆分）` 与代码/文档基本一致；但 §4 关于「订单、库存、售后写操作放在同一存储事务内」的判断与代码及第 9 篇冲突，需修正。

**证据核验结果**

成立：
- §3/§8 称 Qianke 是「模块化单体 + 独立 Worker」：`src/rag_demo/` 下 `agent/ api/ c_end/ merchant/ control/ superagent/ db/ retrieval/ generation/` 等目录均存在；`docker-compose.yml` 为 db + backend + frontend 三服务，`Dockerfile` 以 `uvicorn --workers 1` 启动（单进程），成立。
- §5 称 `python scripts/sa_worker.py` → `runtime.run_worker_loop(poll_seconds=2)`：`scripts/sa_worker.py:42` 调 `runtime.run_worker_loop(poll_seconds=float(os.environ.get("QIANKE_SA_WORKER_POLL", "2")), stop_event=stop)`；`superagent/runtime.py:229` 默认 `poll_seconds=2.0`，成立。
- §5 称 API 侧可设 `QIANKE_SUPERAGENT_QUEUE_DISPATCHER=0`、`QIANKE_QUEUE_BACKEND=postgres`：`superagent/runtime.py:24-30` 读取 dispatcher 开关（默认开）；`superagent/queue_pg.py:3` 说明 `QIANKE_QUEUE_BACKEND=postgres` 时启用 PG 队列，成立。
- §5 称 `web/dist` 由 FastAPI 挂到 `/v2`，也可由 Nginx 托管：`api/main.py:738-741` 在 `web/dist` 存在时 `app.mount("/v2", ...)`；`nginx.conf:96-100` 托管 `/v2/`，成立。
- §8 称「PG 队列（SKIP LOCKED）已实现 | `superagent/queue_pg.py`、`control/job_queue.py`」：`control/job_queue.py:163-203` 的 `claim_next` 使用 `FOR UPDATE SKIP LOCKED`；`superagent/queue_pg.py` 包装 `sa_queue.sa_job`，成立。
- §8 称「3 服务容器编排 | 已实现 | `docker-compose.yml`」：文件含 `db` / `backend` / `frontend` 三个 service，成立。
- §8 称「独立 Worker 与 API 共用同一套代码、数据库与配置」：`sa_worker.py` 只 import `rag_demo.superagent.runtime`，通过环境变量连接同一 DB，成立。

不成立 / 需修正：
- §4 第 104 行：「Qianke 现在把订单、库存、售后写操作放在同一存储事务内，这是不拆服务的重要收益。」与代码不符，且与第 09 篇「跨存储非原子」直接冲突。`c_end/store.py::confirm_order`（第 2272–2400 行）在控制面事务中先调用 `get_merchant_write_repository().create_order(...)` 与 `commit_reservation(...)`（商家库另一连接、另一事务，先提交），随后才写 `c_order`、扣 C 库存、消费报价、写奖励/回访并提交控制面事务；默认后端还是 `QIANKE_CEND_BACKEND=sqlite`（`c_end/store.py:309-311`）+ `QIANKE_MERCHANT_BACKEND=postgres`（`merchant/factory.py:76-78`），本就是两个存储。正确表述应是「同一进程内用两个仓储协作 + 补偿/对账兜底」，而不是「同一存储事务」。
- §8 表第 175 行「三端独立 Graph/数据隔离 | 已设计」：C 端独立 Graph 已实现（`src/rag_demo/c_end/agent.py`；基线文章 §8.3 亦标「C 端 Agent Graph | 已实现（独立链路）」）。把「三端独立 Graph」整体标「已设计」会掩盖 C 端已实现这一事实，应区分「C 端独立 Graph：已实现」「C/B/A 三端统一 Runtime：已设计」。

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | §4 第 104 行 | 「Qianke 现在把订单、库存、售后写操作放在同一存储事务内，这是不拆服务的重要收益。」 | 与代码事实不符：C 端控制面与商家库是两个仓储、两个事务；商家订单/预占先提交，C 端后提交，存在不一致窗口（这正是第 09 篇的主题）。也与第 09 篇互相矛盾 | 改为「订单/库存/售后在同进程内由两个仓储协作完成：控制面本地事务 + 商家库事务；跨存储非原子，靠补偿、幂等与对账兜底，拆服务不会改变这部分一致性成本」 |
| P2 | §8 表第 175 行 | 「三端独立 Graph/数据隔离 \| 已设计」 | C 端已有独立 Graph（`c_end/agent.py`），整体标「已设计」不准确 | 拆成两行：「C 端独立 Graph：已实现」「C/B/A 三端统一 Runtime：已设计」 |

**未核验项**
- §8「模块依赖方向检查 | 规划中 | 靠评审与 import 约定，无 CI」：已确认 CI 无 import 检查，但未穷举是否存在其它依赖检查脚本；按「规划中」引用可接受。
- §6 企业级要求中「微服务」列的成本判断为通用理论，不涉及 Qianke 实现，未核验。
- 「模块间无直接跨表写入」为验收清单项（未勾选），不构成事实声明。

**一句话总评**：部署形态与 Worker/队列证据扎实，但「同一存储事务」这一句把跨存储一致性问题说过头，必须修正，否则与第 9 篇打架。

---

### 2.3 `docs/handbook/03-system-architecture/03-api-gateway.md`

**结论：条件通过**

**实现状态声明是否成立**：基本成立。`部分实现 + 规划中` 的定位与「边缘代理已实现、应用内治理已实现、独立网关未引入」一致；但 WebSocket 路径与代理能力、`/docs` 与 `/openapi.json` 路由信息、`/ready` 路由覆盖三处需要修正。

**证据核验结果**

成立：
- §3 读图要点①：`ops/cloudflared.yml` 把 `qianke.qiankeagent.com` 指向 `http://127.0.0.1:8000`（第 4-7 行），即绕过 Nginx；`docker-compose.yml` 中 frontend 依赖 backend、`nginx.conf` upstream 为 `backend:8000`，两种拓扑确实都存在。
- §5 nginx 片段：`nginx.conf:132-143` 的 `location = /qa/stream` 确有 `proxy_buffering off`、`proxy_cache off`、`proxy_read_timeout 600s`；`/api/` 为 300s（第 110-119 行）；`client_max_body_size 50m`（第 81 行），成立。
- §5 代码片段：`api/main.py:729` `GZipMiddleware(minimum_size=1024)`、`:725-726` `install_security_headers` / `install_csp_report`；`api/ops.py:108/114` `/ready`、`/metrics`，`/metrics` 用 `QIANKE_METRICS_TOKEN` 鉴权（`api/ops.py:94-105`）；`GET /ready` 检查 `control_store` / `superagent_store` / `queue` / `merchant_store`（`api/ops.py:41-49`），成立。
- §5 登录限流：`api/security.py:18-50` 单进程滑动窗口（5 次/300 秒，默认参数）；`:56-147` PG 固定窗口；`:150-161` PG 不可用回退内存并打 warning，成立。
- §4「演示账号在入口只读兜底」：`api/main.py:542-564` `_attach_account` 对 `is_demo` 账号的非 GET 请求直接 403（问答/登录/登出白名单除外），成立。
- §8 表「TLS + 静态 + API 反代」「SSE 不缓冲」「会话解析与演示只读」「安全头/CSP 上报」「登录限流」「就绪探针/指标鉴权」均有上述代码证据。
- §6「身份：统一登录、会话吊销、回调验签 | 已实现」：`auth.py:1115` 有 `revoke_session`；企微回调验签见 `api/superagent.py:539-601`，成立。

不成立 / 需修正：
- **WebSocket 路径与代理**：§3 架构图（第 74 行）把 `R2` 写成 `/ws/chat /ws/group`，§4 第 99 行写「遗漏 `/ws/` 实时消息不可用」。实际路由前缀为 `/api/c`（`api/c_end.py:25` `APIRouter(prefix="/api/c")`；`:1422` `/ws/chat/{friend_id}`、`:1478` `/ws/group/{group_id}`），前端也请求 `/api/c/ws/...`（`web/src/views/CApp.vue:1388/1610`）。并且 `nginx.conf` 没有 `/ws/` location，`/api/` location 显式 `proxy_set_header Connection ""` 且无 `Upgrade`/`connection_upgrade` 配置——按配置推断，经「Nginx → backend」拓扑的 WebSocket 握手无法完成。文章既没有修正路径，也没有披露该配置缺口。
- **`/docs`、`/openapi.json` 路由过时**：§4 路由表（第 95 行）写 `/health /metrics /openapi.json /docs → 运维与文档`。当前代码 `docs_url="/api/docs"`、`openapi_url="/api/openapi.json"`（`api/main.py:519-523`），`/docs` 已改为挂载公开 Handbook（`api/main.py:756-759`；`docs/handbook/_meta/docs-current-state-audit.md` §6 亦记录「Swagger 迁到 `/api/docs`」）。§9 验收清单「生产 `/docs` 与 `/openapi.json` 关闭」与之冲突。
- **`/ready` 路由缺口**：§3 架构图把 `/ready` 列入应用路由（R3），§8 也标「就绪探针已实现」；但 §4 自称「路由表按客户端类型 + 资源前缀设计」的清单不含 `/ready`，`nginx.conf` 里也没有对应 location（正则 `^/(stats|health|metrics|openapi\.json|docs)` 不匹配 `/ready`）——经 Nginx 拓扑 `/ready` 不可达，只有 cloudflared 直连 8000 时可用。
- **「公网隧道入口 | 已实现」的证据强度不足**：`ops/cloudflared.yml` 的 `credentials-file` 是 Windows 本机路径（`C:\Users\Lenovo\.cloudflared\...`），更像开发机隧道配置；文件存在不等于生产公网入口已运行。

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | §3 架构图（第 74 行）、§4（第 99 行） | 「R2["/ws/chat /ws/group"]」「遗漏 `/ws/` 实时消息不可用」 | 实际路径为 `/api/c/ws/chat`、`/api/c/ws/group`；`nginx.conf` 无 WS Upgrade 配置，经 Nginx 拓扑无法代理 WS。文章未披露该缺口 | 路径改为 `/api/c/ws/chat/{friend_id}`、`/api/c/ws/group/{group_id}`；在 §8/§9 增加「Nginx 拓扑需为 `/api/c/ws/` 配置 `proxy_http_version 1.1` + `Upgrade`/`Connection` 升级头与更长 read timeout；当前 `nginx.conf` 未配置（按配置推断，未浏览器实测）」；并说明当前生产实际走 cloudflared→8000 |
| P2 | §4 路由表（第 95 行）、§9 清单（第 186 行） | 「`/openapi.json` `/docs` → 运维与文档」；「生产 `/docs` 与 `/openapi.json` 关闭」 | 与当前路由不一致：Swagger 迁到 `/api/docs`、OpenAPI 为 `/api/openapi.json`；`/docs` 现为公开 Handbook 挂载 | 更新路由表为 `/api/docs`、`/api/openapi.json`；清单改为「`RAG_ENABLE_API_DOCS=0` 关闭 `/api/docs` 与 `/api/openapi.json`；`/docs` 为 Handbook，需确认不暴露内部文档」 |
| P2 | §3 图 R3 / §4 路由表 | 图含 `/ready /metrics /health`；路由表未列 `/ready` | `/ready` 不在 nginx 代理范围内（无匹配 location），Nginx 拓扑下不可达；图文不一致 | 路由表补 `/ready`；在 §4 明确两种拓扑下 `/ready`、`/metrics` 的可达性差异，并提示 Nginx 需追加 location |
| P2 | §8 表第 168 行 | 「公网隧道入口 \| 已实现 \| `ops/cloudflared.yml`」 | 该 yml 的凭据路径是 Windows 本机路径，更像本地隧道配置；不能证明生产公网入口已实现 | 改为「配置存在（`ops/cloudflared.yml`），生产隧道与域名解析未核验」 |

**未核验项**
- 生产实际部署走 cloudflared 直连 8000 还是 Nginx：文章已自我标注「排障前必须确认实际部署」，本次亦未核验。
- WebSocket 经 Nginx 的可达性：以上结论是**按 `nginx.conf` 配置推断**，未用浏览器/`websocat` 实测。
- TLS 证书是否就位（`certs/` 目录存在但未检查内容与有效期）、`/metrics` 生产 token 是否配置：未核验。
- 「限流」除登录接口外是否有其他限流：文章标「部分实现（仅登录限流）」，未逐一扫描全部写接口确认，但代码层面未见通用限流中间件，方向一致。

**一句话总评**：边缘代理与应用内治理的证据链基本完整，但 WS 路径/代理与 `/docs`–`/ready` 路由细节已落后于代码，必须按当前实现重写路由与拓扑说明。

---

### 2.4 `docs/handbook/03-system-architecture/04-service-communication.md`

**结论：条件通过**

**实现状态声明是否成立**：基本成立。`已实现 + 部分实现 + 规划中` 与证据一致；主要问题是 C 端 WebSocket 路径缺少 `/api/c` 前缀，以及一处「HMAC」措辞不够准确。

**证据核验结果**

成立：
- §4 超时分级：`MODEL_API_TIMEOUT` 默认 60（`config.py:347`）；`QIANKE_AGENT_WALL_TIMEOUT_SECONDS` 默认 70（`api/main.py:1424`）；`QIANKE_KUAIDI100_TIMEOUT` 默认 8（`c_end/express.py:90`）；Nginx API/SSE 300s/600s（`nginx.conf:118/129/142`），成立。
- §4 幂等：`c_end/idempotency.py` 有 `claim/release/complete` 语义（测试 `test_c_end_idempotency.py` 覆盖 replay/conflict/release/ttl）；Agent `request_id` → Execution Store；物流回调按 `event_id` 幂等（`api/c_end.py:545-552`）；队列 `UNIQUE(work_item_id, kind)`（`control/schema_pg.sql:694-695`），成立。
- §4 回调安全：企微 `msg_signature + timestamp + nonce` 验签 → AES 解密 → XML 解析（`api/superagent.py:556-601`）；物流回调 HMAC-SHA256 + 300s 时间窗（`api/c_end.py:490-505`）、未配置密钥直接 503 拒绝（`:515-520`）；通用 Webhook 未配置密钥拒绝（`superagent/triggers.py:101-107`），成立。
- §4/§8 企业微信去重：`_WECOM_SEEN` 进程内集合，超过 5000 清空（`api/superagent.py:578-585`），成立。
- §5 代码位置表：`api/main.py::_attach_account`、`api/c_end.py::chat_websocket/group_chat_websocket`、`api/c_end.py::/webhooks/logistics/signed`、`api/superagent.py::wecom_callback_message`、`superagent/wecom_send.py`、`superagent/triggers.py`、`c_end/alerts.py`（generic/wecom/dingtalk，`c_end/alerts.py:25`）、`config.py::MODEL_API_BASE`，全部存在，成立。
- §4「WebSocket 优先、HTTP 回退，断线按退避重连」：前端 `CApp.vue:1356-1410` 有 2^n 退避（上限 8s、最多 5 次）与 `fallback` 状态；HTTP 回退路径存在，成立。
- §8 未核验项「企业微信回调去重只覆盖单进程」与「物流签名算法/时间窗口需对照第三方文档」标注诚实，成立。

不成立 / 需修正：
- §4 第 120 行「C 端 IM 正常走 `/ws/chat/{friend_id}` 或 `/ws/group/{group_id}`」：实际路径带路由前缀 `/api/c`（`api/c_end.py:25/1422/1478`；`web/src/views/CApp.vue:1388/1610`），按原文测试会 404。
- §4 第 118 行「通用 Webhook 用 `QIANKE_SUPERAGENT_WEBHOOK_SECRET` 做 HMAC 比较」：实现是读取请求头 `X-Superagent-Secret` 后与共享密钥做 `hmac.compare_digest`（`api/superagent.py:336-338`；`superagent/triggers.py:101-107`），是**共享密钥的常量时间比较**，不是对报文签名。表述容易被误读为「对 body 做 HMAC 验签」。

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | §4 第 120 行 | 「C 端 IM 正常走 `/ws/chat/{friend_id}` 或 `/ws/group/{group_id}`」 | 实际路径为 `/api/c/ws/chat/{friend_id}`、`/api/c/ws/group/{group_id}`（`api/c_end.py` 的 router prefix 为 `/api/c`）；按原文接入会 404 | 补全前缀，或写明「应用内路由为 `/ws/...`，对外完整路径为 `/api/c/ws/...`」 |
| P2 | §4 第 118 行 | 「通用 Webhook 用 `QIANKE_SUPERAGENT_WEBHOOK_SECRET` 做 HMAC 比较」 | 实现是共享密钥头 `X-Superagent-Secret` 与配置值的常量时间比较，不是报文 HMAC 签名 | 改为「共享密钥头 + `hmac.compare_digest` 常量时间比较；未配置密钥拒绝」，避免与物流回调的报文签名混淆 |
| P2 | §6 表「可观测 \| `trace_id` 跨边界」 | 「部分实现（有 request_id/execution_id）」 | 准确；但正文未说明 HTTP 层没有统一 request-id 中间件，读者可能以为已完成跨边界透传 | 建议在未核验项或正文补一句「HTTP 入口无统一 request-id 中间件；request_id/execution_id 目前主要在 Agent 与业务层传递」 |

**未核验项**
- 「统一 HTTP 客户端/重试治理 | 规划中 | 各调用点自建超时」：未逐文件穷举全部出站调用，属负向断言，未核验。
- 「全链路 Trace 透传 | 规划中」：未核验 WebSocket/队列路径的 trace 字段。
- 企业微信真实回调量下 `_WECOM_SEEN` 清空策略是否会造成重复处理：需按真实回调量评估，本次未核验。
- 物流回调签名算法与时间窗口是否与第三方文档一致：文章已标未核验，本次同样未核验（仓库只提供供应商无关接入点）。

**一句话总评**：通信边界、超时、幂等、验签证据扎实；只需修正 WS 路径（P1）与「HMAC 比较」的措辞即可发布。

---

### 2.5 `docs/handbook/03-system-architecture/05-message-queue-event-driven.md`

**结论：通过**

**实现状态声明是否成立**：成立。`已实现（PG Job 队列、事件接入） + 部分实现（去重、告警队列） + 规划中（事件总线、Outbox）` 与代码一致；租约、重试、死信、重放均有实现依据。

**证据核验结果**

成立：
- §2 队列字段与状态：`control/job_queue.py:53-56` 的列说明（`status/attempts/max_attempts/available_at/lease_until/worker_id/last_error/created_at/updated_at`）与 `superagent/queue_pg.py:61-75` 的建表 DDL 完全对应；状态 `PENDING/RUNNING/DONE/FAILED/DEAD` 在代码路径中可核（`finish`、`retry`、`requeue_expired`、`claim_next` 中的 `DEAD` 赋值），成立。
- §4 `FOR UPDATE SKIP LOCKED` SQL：与 `control/job_queue.py:178-195` 的实际语句一致（简化但语义未失真），并前置「过期 RUNNING 且 attempts>=max → DEAD」（`:171-176`），成立。
- §4 租约：`claim_next(lease_seconds=1800)`（`job_queue.py:163`）；心跳每 60 秒续租（`superagent/runtime.py:82-90` 的 `stop.wait(60)`）；`requeue_expired` 实现「超限 DEAD、未超限回 PENDING」（`:294-318`），成立。
- §4 重试/死信/重放：`retry(delay_seconds=5)`（`job_queue.py:262`）；`finish(FAILED/DEAD)`；`superagent/queue_pg.py:202-220` 的 `replay_job` 将 `DEAD/FAILED` 重置为 `PENDING, attempts=0`；`runtime._execute_claimed` 在异常时按 attempts 选择 retry 或 DEAD（`runtime.py:128-133`），成立。
- §4 幂等/去重：`enqueue` 使用 `ON CONFLICT (identity, kind) DO NOTHING`（`job_queue.py:145-152`）；建表 `UNIQUE(work_item_id, kind)`（`queue_pg.py:74`）；企微 MsgId 进程内去重、物流事件幂等（`api/superagent.py:578-585`、`api/c_end.py:545-552`），成立。
- §5 组件表：`control/job_queue.py`（`PostgresJobQueue`：enqueue/claim/retry/finish）、`superagent/queue_pg.py`（`sa_queue.sa_job`、`work_item_id` 身份列）、`superagent/runtime.py`（dispatcher、线程池、心跳、启动恢复、Worker 循环）、`scripts/sa_worker.py`、`api/ops.py` `/metrics`，均成立。
- §8「启动恢复 | 已实现 | `runtime.recover_jobs`、dispatcher 每 15s」：`runtime.py:193-201` `recover_jobs`；`:204-212` `_dispatch_loop` 每 15s；`start_dispatcher` 在 API 注册时启动（`api/superagent.py:604-610`），成立。
- §8「事件接入（企微/CApp/Webhook）已实现」「重试+死信+重放已实现」「独立 Worker 进程已实现」「Outbox/CDC/事件版本化规划中」「独立消息中间件规划中」：`pyproject.toml` 依赖中无 Kafka/RabbitMQ/Redis/Celery，仓库无 Outbox 实现，成立。
- §3 读图要点「业务状态与执行状态分离」「API dispatcher 与独立 Worker 可同时消费」「定时脚本直接写业务表/告警表」：`sa_work_item`/`sa_job` 分表、dispatcher 与 worker 均调 `claim_next`、`scripts/reconciliation_scheduler.py` 直接写 `c_reconciliation_run`，成立。

需修正（不构成状态错误）：
- §5 表「通用队列核心 | `control/job_queue.py` | `PostgresJobQueue`：enqueue/claim/retry/finish/**replay**」：`PostgresJobQueue` 没有 replay 方法；replay 实现在 `superagent/queue_pg.py::replay_job`（另有两处转发：`superagent/store.py:868`、`api/superagent.py:403`）。
- 正文/说明未提「默认后端是 SQLite」：`superagent/store.py:675` 默认 `QIANKE_QUEUE_BACKEND` 为 sqlite；PG 队列是显式配置后的路径。§6/§7 有「SQLite 仅开发回退」的表述，但 frontmatter 描述与前文「基于 PostgreSQL 的持久化 Job 队列已实现」容易被读成默认 PG。

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §5 组件表第 122 行 | 「通用队列核心 \| `control/job_queue.py` \| `PostgresJobQueue`：enqueue/claim/retry/finish/replay」 | `PostgresJobQueue` 无 `replay`；replay 在 `superagent/queue_pg.py::replay_job` | 把 replay 从该行拆出，或在 §5 增加一行「死信/失败重放 \| `superagent/queue_pg.py::replay_job`」 |
| P2 | §8 表 / 开头现状（第 34 行） | 「基于 PostgreSQL 的持久化 Job 队列已实现」 | 未说明默认 `QIANKE_QUEUE_BACKEND=sqlite`（`superagent/store.py:675`），PG 路径需显式配置 | 在 §6 或 §8 补一句「默认后端为 SQLite 仅开发回退；生产需显式设 `QIANKE_QUEUE_BACKEND=postgres` 才进入 SKIP LOCKED 路径」 |

**未核验项**
- 管理端队列页（`web/queue.html` 及对应 admin 接口）的「状态/kind 过滤、搜索、死信重放」UI 行为：只确认 API 层 `list_jobs` 支持 `status/kind/q` 与 `replay_job`，未打开页面验证。
- SQLite 队列与 PG 队列的行为一致性（文章已自标未核验）：本次未运行两种后端对比测试。
- 真实吞吐/积压水位：未做压测，未核验。
- 「事件量与跨服务订阅显著增长后再评估独立 MQ」为建议性判断，不构成事实声明。

**一句话总评**：队列机制与失败语义的代码依据完整、数字与默认值基本准确，仅需修正 replay 的代码归属与默认后端说明。

---

### 2.6 `docs/handbook/03-system-architecture/06-distributed-task-scheduling.md`

**结论：通过**

**实现状态声明是否成立**：成立。`已实现 + 部分实现` 与代码一致；三类任务路径、周期脚本、systemd、Watchdog、恢复逻辑均可核；缺失项与未核验项标注诚实。

**证据核验结果**

成立：
- §2/§3「无主抢占 + 租约、Worker 可水平扩容」：`claim_next` + `SKIP LOCKED` + `lease_until=1800s`（`control/job_queue.py:163-203`），成立。
- §3 路径 1（即时异步任务）：`sa_job` kind=WORKER/ACTION（`runtime.start_worker` / `start_action`，`runtime.py:33-48`）、API dispatcher 15s（`:204-212`）、独立 Worker poll 2s（`scripts/sa_worker.py:42`、`runtime.py:229`）、claim + lease 1800s、心跳 60s、finish DONE/FAILED/DEAD（`runtime.py:92-137`），成立。
- §3 路径 2（周期任务）：`b_profile_worker.py` 默认 `--interval 60`（`scripts/b_profile_worker.py:29`），docstring 写「每 60 秒检查一次 30 分钟空闲会话」；`reconciliation_scheduler.py` 默认 interval 读 `QIANKE_RECONCILE_INTERVAL_SECONDS`（默认 1800），支持 `--once`；`scan_inventory_alerts.py` 只写 `c_inventory_alert`、不调企业微信/邮件（脚本 docstring 第 1-9 行），成立。
- §3 路径 3（恢复与守护）：`runtime.recover_jobs` 先 `requeue_expired_jobs` 再重投 PENDING（`runtime.py:193-201`）；`watchdog.scan_once` 调 `store.scan_stuck_work_items` 并打 warning（`superagent/watchdog.py:31-35`）；`enabled()` 读取 `QIANKE_SUPERAGENT_WATCHDOG_ENABLED`，默认 `"0"` → 关闭（`watchdog.py:67-73`），成立。
- §4 失败处理矩阵：异常未超限 → `retry_job(delay=5s)`（`job_queue.py:262`、`runtime.py:130-131`）；超过 max_attempts → `finish(DEAD)`（`runtime.py:132-133`）；重启恢复 → `recover_jobs`；长期卡住 → Watchdog（需开启），逐项成立。
- §4 时区语义：`reconciliation_scheduler.py:55-63` 确实用 `QIANKE_RECONCILE_INTERVAL_SECONDS`（默认 1800）与 `--once`，成立。
- §5 Worker 主循环代码块与真实代码一致（`sa_worker.py` → `run_worker_loop`；`runtime.py:229-246` 的 `requeue_expired_jobs` + `claim_next_job` + `_execute_claimed`）；`_execute_claimed` 内启动 heartbeat 线程（`runtime.py:96-105`），成立。
- §5 systemd 单元：`deploy/systemd/qianke-b-profile-worker.service` 的 `ExecStart=/opt/qianke/.venv/bin/python scripts/b_profile_worker.py --interval 60`、`Restart=always`、`Environment=QIANKE_CEND_BACKEND=postgres` / `QIANKE_CONTROL_BACKEND=postgres` 与文章一致，成立。
- §8 状态表各项（持久化 Job 队列、多 Worker 竞争领取、租约与心跳、启动恢复、独立 Worker、周期任务、systemd 集成）均有对应代码/文件；「统一调度中心/任务注册表」「cron 表达式/下次执行时间」标规划中，仓库中确无调度中心实现，成立。
- §8 未核验项（Windows 任务计划程序配置、`scan_inventory_alerts.py` 调度方式）标注诚实。

**问题列表**

本次未发现 P0/P1/P2 事实错误。

（可选建议）§6 可补一句：`b_profile_worker.py` 未见跨实例互斥，多实例部署时周期任务可能重复扫描，需靠单实例部署或外部锁保证。

**未核验项**
- systemd 单元是否已在目标机实际部署并运行（仓库只有 unit 文件，无运行证据），未核验。
- `reconciliation_scheduler.py` 在 Windows 任务计划程序中的实际配置、`scan_inventory_alerts.py` 的调度方式：不在仓库内，文章已标未核验，本次同样未核验。
- 多实例部署时周期任务是否重复执行：仓库未见分布式锁；文章 §9 把它列为验收项而非已实现能力，本次未做运行验证。

**一句话总评**：三条任务路径、租约/恢复/守护与部署脚本逐项可核，状态标注与缺失项描述准确，是本批证据质量最好的一篇。

---

### 2.7 `docs/handbook/03-system-architecture/07-database-architecture.md`

**结论：条件通过**

**实现状态声明是否成立**：部分不成立。分库、只读账号、控制面双后端、Alembic 基线等主要声明成立；但「控制面 28 表」数字过时、「连接池 规划中/待核验」与代码相反，另有「两套实现」口径可收敛。因为这两处直接落在实现状态表与证据列，判条件通过。

**证据核验结果**

成立：
- §3/§8「PostgreSQL 16 + pgvector」：`docker-compose.yml:30` 镜像 `pgvector/pgvector:pg16`；`deploy/initdb/01-databases.sql` 创建 `vec_db_user`、`vec_db_test`、`rag_auth` 并启用 vector 扩展，成立。
- §4 contextvar 数据集路由/写守卫：`db/connection.py:58-60` `_current` contextvar；`:94-108` `use_dataset/reset_dataset`；`:137-205` `writes_to` + `require_write_scope` + `UnsafeWriteError`；`:260-333` `ensure_readonly_access` 创建 `sql_reader`（`NOSUPERUSER`、`CONNECT`/`USAGE`/`SELECT`）；`:336-367` `get_readonly_conn`，全部成立。
- §4「线程/线程池不会自动继承 contextvar…忘记声明必须是显式错误」：`db/connection.py:21-29、137-205` 的注释与实现一致，成立。
- §5 文件位置：`db/connection.py`、`db/schema.py`、`control/schema_pg.sql`、`alembic/versions/0001_merchant_v1.py`、`merchant/repository.py`、`auth.py`（`rag_auth`）、`scripts/backup_control_plane.py`、`restore_control_plane.py` 均存在，成立。
- §5 索引：「画像表 embedding 使用 HNSW + `vector_cosine_ops`」：`db/schema.py:108-113` 的 `user_profile_vectors_embedding_idx` / `wiki_vectors_embedding_idx` 均为 `USING hnsw (embedding vector_cosine_ops)`；「city/member_level 建 B-tree」：`ingest_data.py:108-115` 的 `INDEX_SQL` 含 `idx_upv_city`、`idx_upv_member_level`；「BM25/稀疏落 `search_index`、`sparsevec` 在库内计算」：`db/schema.py:216-232`，成立。
- §8「数据集物理分库」：`config.py:95-99` `DATASETS`；`:130-131` `enterprise_db_name` / `:157-161` `merchant_db_name` 生成独立库名；`db/provision.py:50-67` 首次构建时 `CREATE DATABASE`，成立。
- §8「写作用域守卫」「Text2SQL 只读账号」「控制面 PG schema」「Alembic 基线」「BM25/稀疏索引落库」均有上述证据；「备份/恢复脚本 部分实现」`docs/e2e/ops-readiness-backup.md` 记录脚本已实测，且「没有自动定时备份/没有自动恢复演练」，与「部分实现」一致。
- §5 连接管理取舍：`db/connection.py:49-50` 原文「每个数据集各持一条连接。不做连接池：单机单用户…」，文章引用准确。

不成立 / 需修正：
- **「控制面 28 表」过时**：§3 架构图（第 65 行）与 §5 表（第 112 行）均写「控制面 28 表」，并以 `src/rag_demo/control/schema_pg.sql` 为证据。该文件当前含 **63 个 `CREATE TABLE`**（`c_*`、`sa_*`、`b_*` 等），而 `tests/test_control_repository_contract.py:11-26` 的 `EXPECTED_TABLES` 也正好是 63 个表名。28 是 2026-11-04 P1 阶段数字（`docs/decisions/control_plane_postgres_migration_p1.md` §1/§3：「28 表 + 索引」）。这是数字与代码证据不匹配。
- **「连接池 规划中/待核验」与代码相反**：§6 第 132 行「扩展性：连接池、读写分离、分片 | 规划中」与 §8 第 164 行「连接池 | 规划中/待核验 | 当前代码明确『不做连接池』」，以及 frontmatter/description「读写分离、连接池、分片与高可用未实现（规划中）」。实际：
  - `control/postgres_repository.py:34-43` 使用 `psycopg2.pool.ThreadedConnectionPool(1, 4, ...)`；
  - `merchant/postgres_repository.py:14-15、148-163、239-247` 使用 `ThreadedConnectionPool`（默认 1..8，`QIANKE_MERCHANT_PG_POOL_MIN/MAX`）；
  - 只有 `db/connection.py`（数据集/Text2SQL 连接）明确「不做连接池」。
  因此正确状态应为「部分实现：控制面/商家仓储已有线程池；数据集连接层无池」，而不是「规划中/未实现」。文章 §8 未核验项把「AGENTS 1.9.7 连接池」与「db/connection.py 注释」的矛盾保留为「待核验」，其实两者指不同层，可核验消解。
- **「同一接口两套实现」口径**：§4 第 104 行「`control/factory.py`、`merchant/factory.py`、`c_end/store.py` 按环境变量选择 PG/SQLite；同一接口两套实现靠契约测试保证行为一致」。control/merchant 确实各有 sqlite/postgres 两套实现；但 `c_end/store.py` 是**单一实现**，通过 `control/pg_compat.py`（SQLite 风格连接兼容层，`BEGIN IMMEDIATE → BEGIN`、`? → %s`）在 PG 上运行，不是两套实现。

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | §3 图（第 65 行）、§5 表（第 112 行） | 「qianke_control schema 控制面 28 表」「控制面 PG schema（28 表）」 | 数字过时：`control/schema_pg.sql` 当前 63 个 `CREATE TABLE`，契约测试 `EXPECTED_TABLES` 也是 63；28 来自 2026-11-04 的 P1 记录 | 改为「当前 63 张表（2026-11-23 快照）」或写「表清单以 `tests/test_control_repository_contract.py::EXPECTED_TABLES` 为准（63 张）」，并注明 28 是 P1 阶段数字 |
| P1 | §6 第 132 行、§8 第 164 行、frontmatter description | 「连接池…规划中」「连接池 \| 规划中/待核验」「读写分离、连接池、分片与高可用未实现」 | 与代码相反：控制面 `ThreadedConnectionPool(1,4)`、商家仓储 `ThreadedConnectionPool(1..8)` 已实现；只有数据集连接层无池 | 改为「连接池：部分实现（控制面 1–4、商家仓储 1–8 线程池；数据集/Text2SQL 连接按单机单用户取舍不做池）」；未核验项里的「矛盾」可改为结论：两层指的不是同一模块 |
| P2 | §4 第 104 行 | 「`c_end/store.py` … 同一接口两套实现」 | control/merchant 是两套实现，c_end 是单实现 + `control/pg_compat.py` 兼容层 | 改为「控制面/商家仓储为双后端实现 + 契约测试；C 端 store 复用同一实现，经 `pg_compat` 兼容层在 PG 上运行」 |

**未核验项**
- C 端默认后端：`QIANKE_CEND_BACKEND` 默认 sqlite（`c_end/store.py:309-311`），生产是否切 PG 取决于部署环境变量；文章已标注，本次未核验部署环境。
- 备份/恢复的定时任务与恢复演练：`docs/e2e/ops-readiness-backup.md` 明确「没有自动定时备份/没有自动恢复演练」，`docs/e2e/system-audit-2026-11-10.md` 也记录未找到备份计划任务；文章「无定期演练证据」成立，但「执行待确认」未核验。
- 「控制面与业务库同实例」：代码默认 `vec_db`（`control/settings.py`、merchant 默认 dbname `vec_db`），但生产部署可能改库名；未核验实际部署。
- 回滚演练：AGENTS 2.67 记录过「PG 备份 Docker 回退与恢复清单验证」，但仓库内未见演练报告；「回滚演练有限」未核验。

**一句话总评**：分库、只读账号、迁移与索引证据基本可靠；但两个核心状态数字（28 表、连接池）与代码不符，必须修正后才能作为「按代码核验」的数据库篇发布。

---

### 2.8 `docs/handbook/03-system-architecture/08-cache-system-design.md`

**结论：通过**

**实现状态声明是否成立**：成立。`已实现（进程内缓存与失效） + 部分实现（多层小缓存） + 规划中（分布式缓存）` 与代码一致；键设计、数据版本失效、角色裁剪时机、PWA 边界均可核。

**证据核验结果**

成立：
- §1 性能数据「一次问答 9~17s，其中 92~96% 花在 LLM 生成」：`cache.py:10` 注释原文一致，属代码注释来源，非实测报告（文章表述为「来自代码注释与实测记录」，可核到注释）。
- §4 缓存键维度：`cache.py:92-130` `make_key` 显式拼接 `dataset|question|dept|keyword_mode|profile_limit|deep_thinking|history_key|data_version|persona_key|rrf_k=...` 后 sha256，与文章列表完全一致，成立。
- §4「角色不进键，裁剪在 `permissions.render`」：`cache.py:107-110` 注释；`permissions.py:620` 存在 `render(payload, role, user)`；`pipeline.py:101-103` 注释「返回完整结果，不做角色裁剪，裁剪统一在 api 层 `permissions.render()`」，成立。
- §4 数据版本失效：`cache.py:44-78` 优先级 `last_build.at` → manifest 哈希 → `unknown`；`_VERSION_TTL = 2.0`（第 39 行），成立。
- §4 容量/线程安全：`cache.py:37-38` `DEFAULT_MAXSIZE=256`、`DEFAULT_TTL=3600`；`:88` `threading.Lock`；`:157-159` `clear()` 整体清空，成立。
- §5 工程实现表：`cache.py::AnswerCache`、`dataset_data_version`；`pipeline.py` / `api/main.py` 读写缓存；`GET /cache/stats`、`POST /admin/clear-cache` 且 `_require_system_admin`（`api/main.py:2012-2031`）；`db/schema_facts.py` 的 TTL 来自 `SQL_SCHEMA_CACHE_TTL=300`（`config.py:258`）且 `ingest_data.py:703/989` 调 `invalidate`；`c_end/catalog_search.py:152` 300s、`c_end/express.py:19` 300s；`web/public/sw.js` 版本 `v24`、排除 `/api/`、`/auth/`、`/whoami`、`/admin/`，全部成立。
- §5 JSON 示例：`AnswerCache.stats()` 返回 `size/maxsize/ttl/hits/misses/hit_rate`（`cache.py:161-171`），字段一致。
- §2「没有单飞保护，热点问题过期瞬间可能并发重复计算」：`pipeline.answer_question` 在 miss 后直接计算，无 single-flight 锁，成立。
- §6「敏感数据：图片只存 key，响应时签名」：`media.py:202/222` 调 `oss_store.sign_url(key)`；`storage/oss_store.py:197` 为 presign 实现，成立。
- §8 状态表各项（问答 LRU+TTL、键维度、数据版本、统计清理、schema facts、类目/物流、PWA）均已核；分布式缓存/告警看板/防击穿标规划中，`pyproject.toml` 无 Redis 客户端依赖，成立。

需修正（不构成状态错误）：
- §6 表第 128 行「容量 | 内存上限可配置 | 已实现（LRU 256）」：`AnswerCache` 只有构造函数参数 `maxsize`，进程级单例固定 `DEFAULT_MAXSIZE=256`（`cache.py:37、175`），没有环境变量或运行期配置入口。「可配置」略超实际，应为「固定 256（改构造参数需改代码）」。

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §6 表第 128 行 | 「容量 \| 内存上限可配置 \| 已实现（LRU 256）」 | 实际上限固定 256，无运行期配置入口 | 改为「容量 \| 有内存上限 \| 已实现（固定 LRU 256；构造参数可改，但无环境变量配置）」 |

**未核验项**
- 真实缓存命中率与「命中后毫秒级」的实际延迟：未运行服务，未核验。
- PWA 缓存版本号（v24）与发布流程是否强制更新：文章已标未核验；已确认 `sw.js` 中 `CACHE`/`SHELL_CACHE` 带 v24 版本名，但构建/发布是否强制 bump 未核验。
- `schema_facts` 的 ingest 失效覆盖范围：已确认 `ingest_data.py` 两处 `schema_facts.invalidate()`，但是否覆盖全部写入路径未穷举。
- 多实例部署下的缓存一致性：文章已标「规划中/多实例前必须补齐」，未核验。

**一句话总评**：缓存键、失效、裁剪时机与 PWA 边界的代码证据完整，仅「容量可配置」一处措辞偏大，建议修正即可。

---

### 2.9 `docs/handbook/03-system-architecture/09-distributed-transactions-consistency.md`

**结论：条件通过**

**实现状态声明是否成立**：基本成立。`部分实现 + 理论知识` 与正文一致；「未使用 2PC/TCC/Saga 框架、采用本地事务 + 补偿 + 幂等 + 对账 + 审计链」可核；主要问题是 §1「不存在一个能同时覆盖它们的本地事务」的表述在双 PG 配置下过强。

**证据核验结果**

成立：
- §2/§4「DRAFT→CONFIRMED 本地事务 + 库存预占」：`c_end/store.py::prepare_order`（第 2163-2255 行）在 `BEGIN IMMEDIATE` 内校验商品/报价、调 `_reserve_merchant_stock`、插入 `c_order`（DRAFT）+ 明细并提交；异常时 `rollback` 并 `_release_merchant_reservation`，成立。
- §4 预占 TTL 900s：`_reserve_merchant_stock` 调 `reserve_inventory(..., ttl_seconds=900, ...)`（第 2146 行），成立。
- §4 预占状态机：`merchant/postgres_repository.py` `m_reservation` 状态含 `RESERVED/COMMITTED/RELEASED/EXPIRED`（`merchant/models.py` 常量、`postgres_repository.py:1509-1666`）；`SELECT ... FOR UPDATE` 锁行，成立。
- §5 幂等清单：`c_order.idempotency_key UNIQUE`（`control/schema_pg.sql:24/33`）；`c_order_item PRIMARY KEY(order_id, product_id)`（`:36-44`）；`c_after_sale` OPEN 部分唯一索引（`:664-665`）；`c_compensation.order_id UNIQUE`（`:64-74`）；`sa_job(work_item_id, kind) UNIQUE`（`:694-695`）；`c_end/idempotency.py` 客户端消息幂等；物流事件幂等（`api/c_end.py:545-552`），全部成立。
- §4 对账与审计：`reconcile_orders`（`c_end/store.py:2931-3001`）以 C 订单为主表核对商家订单存在性、状态、原始金额；`_sync_reconciliation_alerts` 去重/自动 resolved（`:3038` 起）；`c_reconciliation_alert` Webhook 推送（`c_end/alerts.py`）；策略审计哈希链 `_audit_chain_hash`（`:1512`）、`anchor_policy_audit`（`:1680`）、`verify_policy_audit_chain`（`:1779`）、`schema_pg.sql:715-732` 的 anchor append-only 触发器；`scripts/verify_policy_audit_chain.py` 存在，成立。
- §5 事务并发热点清单（`confirm_order`、`cancel_order`、`resolve_after_sale`、`receive_after_sale`、`create_compensation`、`decide_approval`、`complete_execution`、`upsert_merchant_policy`）与 `docs/decisions/control_plane_postgres_migration_v0.1.md` §5.3 的列表逐项一致（该文档第 229-243 行），成立。
- §8 表「本地事务、库存预占+行锁、TTL、订单确认幂等、客户端消息幂等、定时对账+告警、对账告警去重/恢复、策略审计哈希链 已实现」「失败补偿 部分实现」「跨存储全局事务 未实现/规划中」「反向对账 未核验/缺口」「自动修复 未实现（有意）」「Outbox/CDC 规划中」与代码一致。
- §6「对账 已实现（C→商家方向）；反向/资金对账待补」与 §8 未核验项一致，标注诚实。

不成立 / 需修正：
- §1 第 39 行：「这些写操作分布在两个存储（控制面 SQLite/PG、商家 PG）中，**不存在一个能同时覆盖它们的本地事务**。」该表述对默认配置（C 端 sqlite + 商家 PG）成立；但当 `QIANKE_CEND_BACKEND=postgres` 时，控制面 schema 默认在 `vec_db.qianke_control`、商家 schema 默认在 `vec_db.merchant_v1`（`control/settings.py` 默认 dbname `vec_db`；`merchant/postgres_repository.py:24/159` 默认 dbname `vec_db`），同一数据库内两个 schema **技术上可以由一个连接、一个事务覆盖**。代码确实没有这样做（两个仓储各自提交），但「不存在」是能力断言而非实现断言，应改为「当前实现未使用跨 schema 单事务」。

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §1 第 39 行 | 「这些写操作分布在两个存储…中，不存在一个能同时覆盖它们的本地事务」 | 默认配置成立；双 PG 配置下控制面与商家 schema 同库，技术上单事务可覆盖，只是代码未采用。「不存在」把实现事实说成能力事实，且与 §8 未核验项 ② 的谨慎表述不完全一致 | 改为「当前实现没有使用跨 schema 单事务：C 端控制面事务与商家库事务由两个仓储分别提交，因此存在不一致窗口；两者是否同库取决于 `QIANKE_CEND_BACKEND` / `QIANKE_MERCHANT_*` 配置」 |
| P2 | §6 表第 132 行 | 「核心数据强一致 \| 部分实现（单存储内强一致；跨存储最终一致）」 | 与 §1 表述同源；若按「双 PG 同库」配置，可进一步说明「同库不同 schema 但未共享事务」 | 与上一条一并修正即可，不单独作为缺陷 |

**未核验项**
- 反向对账（商家订单已创建但 C 订单写入失败）是否存在反向任务：文章 §8 未核验项 ① 已标，本次仅确认 `reconcile_orders` 以 C 订单为主表扫描（`store.py:2931-2999`），未发现反向任务。
- 售后/退款链路一致性覆盖范围：文章要求按 `tests/test_c_end_merchant_transactions.py`、`test_c_end_reconciliation_runs.py` 核验；两份测试文件存在且用例名覆盖预占/重复确认/取消回补/对账去重等，但**本次未执行测试**，只核对了用例清单。
- 「资金级对账」与「故障注入未成体系」：未核验，文章已标缺口。
- 双 PG 同库的实际部署配置：未核验生产 env。

**一句话总评**：一致性机制的代码证据与迁移方案热点清单高度吻合、未核验项诚实；只需把「不存在跨存储本地事务」改成「当前实现未使用」即可更准确。

---

### 2.10 `docs/handbook/03-system-architecture/10-system-scalability.md`

**结论：条件通过**

**实现状态声明是否成立**：基本成立。单实例、模型外置、PG 队列 Worker、PG 控制面、Cookie+DB 会话等扩展条件可核；但「连接池」状态与「仓库内未见统一压测报告」两处需修正，否则会低估已有实现/否定已有报告。

**证据核验结果**

成立：
- §5 部署限额：`docker-compose.yml` 中 db `mem_limit: 1g / cpus: 1.0`（第 59-60 行）、backend `mem_limit: 2g / cpus: 1.5`（第 140-141 行）、frontend `mem_limit: 256m / cpus: 0.5`（第 182-183 行），与文章逐项一致；文件头写明目标机「2 核 4G」，成立。
- §3 图/§4 表「模型推理外置」：`config.py:343-355` `MODEL_API_BASE`、`MODEL_API_TIMEOUT=60`；`Dockerfile:44-49` 注释「云端 API 不安装 torch / sentence-transformers … embedding 与 rerank 全部通过 MODEL_API_BASE 调用远程模型服务」，成立。
- §4 表「控制面共享存储（PG；SQLite 回退）」：`control/factory.py` 按 backend 选择；`QIANKE_CONTROL_BACKEND=postgres` 路径存在，成立。
- §4 表「会话不存进程内存（Cookie + DB）」：`auth.py` 有 `session` 表、`create_session/resolve_session/revoke_session`（`:220-228、1073-1125`），成立。
- §4/§5「PG 队列 Worker 横向扩容」：SKIP LOCKED + `scripts/sa_worker.py` 已核（同第 05/06 篇证据）。
- §4 表「静态/图片资源外置 部分实现（Nginx/PWA；OSS 可选、本地回退）」：`product_media.py` 本地 `var/uploads`（`:21-24`）+ `storage/oss_store.py` presign/上传，成立。
- §5「阻碍多实例的现状」：`answer_cache` 进程内 LRU（`cache.py`）；`db/connection.py` 每数据集一条连接、无池（`db/connection.py:49-50`）；上传默认落本地 `var/uploads`；Agent checkpoint 本地 SQLite（`agent/checkpoint.py:24` 默认 `var/agent_checkpoints.sqlite`）；日志写本地 `logs/`（`logging_setup.py:37`）；`/metrics` 为进程级（`api/ops.py:54-91`）；通用接口限流未实现（仅登录限流 `api/security.py`），逐项成立。
- §4/§8「登录限流有 PG 版，但通用接口限流未实现」：`api/security.py:56-161`，成立。
- §8 表「全链路压测基线 | 规划中/待核验」的**结论方向**（无 2C4G 容量基线）成立，但证据句不准确（见下）。
- §8 未核验项「仓库中没有找到统一的容量/压测基线（2C4G 下的并发承载、p95 延迟）」：该句本身准确。

不成立 / 需修正：
- **「连接池/数据库代理 | 未实现/待核验」「规划中/待核验」**：§4 表第 103 行、§8 表第 168 行、frontmatter description 均把连接池归为「未实现」。实际控制面与商家仓储都有 `ThreadedConnectionPool`（同第 07 篇证据：`control/postgres_repository.py:34-43`、`merchant/postgres_repository.py:148-163/239-247`）；只有数据集/Text2SQL 连接层无池。应改为「部分实现」。
- **「仓库内未见统一压测报告」**：§8 表第 171 行。仓库确有性能测试报告：`docs/e2e/b-end-performance-2026-11-14.md`、`docs/e2e/c-end-performance-2026-11-14.md`（含页面 FCP/LCP/CLS、接口 p50/p95、`/api/c/merchant/products` 5 并发 p95 870ms 等）。准确说法是「有页面/接口级性能报告，但没有 2C4G 容量基线/全链路压测」。

**问题列表**

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §4 表第 103 行、§8 表第 168 行、frontmatter description | 「连接池/代理 \| 未实现/待核验」「连接池/数据库代理 \| 规划中/待核验」「连接池…未实现」 | 控制面/商家仓储已实现 `ThreadedConnectionPool`（1–4 / 1–8），仅数据集连接层无池 | 改为「连接池：部分实现（控制面与商家仓储已用线程池；数据集/Text2SQL 连接层按单机单用户取舍不做池）」 |
| P2 | §8 表第 171 行 | 「全链路压测基线 \| 规划中/待核验 \| 仓库内未见统一压测报告」 | 仓库有 `docs/e2e/*-performance-2026-11-14.md` 两份性能报告（页面 + 接口 p95，含一次 5 并发测量），「未见压测报告」过绝对 | 改为「页面/接口级性能报告已有（`docs/e2e/b-end-performance-2026-11-14.md`、`c-end-performance-2026-11-14.md`），但无 2C4G 容量基线/全链路压测」，并把「未核验项」保留 |

**未核验项**
- 2C4G 下的实际并发承载与 p95：仓库无统一容量基线，本次未做压测，未核验（文章结论方向正确）。
- 生产实际部署规格是否为 2C4G、OSS 是否启用：`docker-compose.yml` 是目标配置注释，不是部署证据；未核验。
- 「Worker 增加实例后任务吞吐提升且无重复执行」：需要运行验证，未核验。
- 「API 多实例前完成共享缓存/上传/日志改造」为建议性清单，非事实声明。

**一句话总评**：扩展条件与阻碍项梳理准确、证据可核；连接池状态和「未见压测报告」两处与仓库事实相反，修正后即可通过。

---

## 3. 证据真实性核验汇总

### 3.1 文件引用

对 10 篇中出现的目标路径做了存在性核验（`Test-Path`），覆盖：

- 代码：`src/rag_demo/agent/*`、`api/main.py`、`api/security.py`、`api/ops.py`、`api/c_end.py`、`api/superagent.py`、`c_end/{store,idempotency,alerts,catalog_search,express}.py`、`control/{job_queue,factory,postgres_repository,pg_compat}.py`、`control/schema_pg.sql`、`merchant/{factory,postgres_repository,repository}.py`、`db/{connection,schema,schema_facts,provision}.py`、`superagent/{runtime,queue_pg,triggers,wecom_send,watchdog}.py`、`storage/oss_store.py`、`cache.py`、`pipeline.py`、`config.py`、`permissions.py`、`media.py`、`product_media.py`、`auth.py`、`agent/checkpoint.py`、`logging_setup.py`、`ai_monitor.py`
- 测试：`test_agent_execution_safety.py`、`test_agent_checkpoint.py`、`test_agent_architecture.py`、`test_control_repository_contract.py`、`test_tenant_isolation_pg.py`、`test_control_job_queue.py`、`test_superagent.py`、`test_cache_version.py`、`test_ops.py`、`test_security_headers.py`、`test_login_rate_limit_pg.py`、`test_c_logistics_webhook.py`、`test_c_end_idempotency.py`、`test_c_end_merchant_transactions.py`、`test_c_end_reconciliation_runs.py`、`test_cend_pg_runtime.py`、`test_c_end_alerts_webhook.py`
- 脚本/部署/运维：`scripts/{sa_worker,b_profile_worker,reconciliation_scheduler,scan_inventory_alerts,backup_control_plane,restore_control_plane,verify_policy_audit_chain}.py`、`deploy/systemd/qianke-b-profile-worker.service`、`deploy/initdb/01-databases.sql`、`ops/{prometheus,cloudflared}.yml`、`web/public/sw.js`
- 文档：`AGENTS.md`、`docs/agent.md`、`docs/agent-design-current-vs-target.md`、`docs/architecture-diagrams.md`、`docs/数据模型.md`、`docs/decisions/*.md`、`docs/e2e/ops-readiness-backup.md` 等
- 配置：`docker-compose.yml`、`nginx.conf`、`Dockerfile`、`alembic.ini`、`alembic/versions/0001_merchant_v1.py`、`pyproject.toml`、`.github/workflows/ci.yml`

**结论**：10 篇中引用的文件路径**全部存在**，未发现编造文件/测试/脚本；未发现编造的 commit、命令输出或测试结果（本批文章均未引用具体 commit、也未声称运行过测试/命令）。问题集中在「数字过时、状态口径不完整、路径/拓扑与当前代码不符」，属修正性问题，不构成证据造假。

### 3.2 数字与代码对照

| 数字/声明 | 出处 | 代码/文档事实 | 判定 |
|---|---|---|---|
| 控制面 28 表 | 07 §3/§5 | `control/schema_pg.sql` 63 个 `CREATE TABLE`；契约测试 `EXPECTED_TABLES` 63 个 | 不成立（过时） |
| lease 1800s / heartbeat 60s | 05/06 | `job_queue.py:163`、`runtime.py:85` | 成立 |
| dispatcher 15s / worker poll 2s | 05/06 | `runtime.py:212`、`runtime.py:229`、`sa_worker.py:42` | 成立 |
| retry delay 5s | 05/06 | `job_queue.py:262` | 成立 |
| TTL 预占 900s | 09 | `c_end/store.py:2146` | 成立 |
| LRU 256 / TTL 3600s / 版本 TTL 2s | 08 | `cache.py:37-39` | 成立 |
| schema facts TTL 300s / 类目·物流 300s | 08 | `config.py:258`、`catalog_search.py:152`、`express.py:19` | 成立 |
| model timeout 60 / agent wall timeout 70 | 03/04 | `config.py:347`、`api/main.py:1424` | 成立 |
| login 5 次/300s | 03 | `api/security.py:21` | 成立 |
| 2C4G 限额 1g/2g/256m 与 1.0/1.5/0.5 CPU | 02/10 | `docker-compose.yml:59-60/140-141/182-183` | 成立 |
| PWA v24 | 08 | `web/public/sw.js:2-3` | 成立 |

### 3.3 未核验项汇总（本报告角度）

1. 生产部署实际拓扑（cloudflared 直连还是 Nginx）、TLS 证书状态、生产 env 中的 backend 选择：未核验。
2. WebSocket 经 Nginx 的可用性：按 `nginx.conf` 推断不可用，**未实测**。
3. 所有「pytest 覆盖」类陈述：只核对测试文件与用例名，未运行测试。
4. 队列/缓存/对账的真实吞吐、命中率、容量基线：未压测，未核验。
5. systemd/任务计划程序的实际部署与运行状态：仓库只有单元/脚本文件，未核验。
6. 迁移回滚演练、备份恢复演练的实际记录：仅确认脚本与 e2e 文档的限制描述，未核验演练本身。
7. 生产 PostgreSQL 是否同实例/同库、控制面与商家 schema 的实际部署：依赖环境变量，未核验。

---

## 4. 跨篇问题与全局结论

### 4.1 跨篇一致性问题

1. **事务/存储边界（02 vs 09，P1）**：第 02 篇称「订单、库存、售后写操作放在同一存储事务内」，第 09 篇称「跨存储非原子、存在不一致窗口」，且第 09 篇与代码一致。两篇必须统一口径，否则读者无法判断 Qianke 到底有没有跨存储一致性成本。
2. **连接池状态（07、10 vs 代码，P1/P2）**：两篇都把连接池标为「规划中/未实现」，但控制面与商家仓储已有 `ThreadedConnectionPool`。需要按「数据集连接层 vs 仓储层」分层标注。
3. **WebSocket 路径（03、04 vs 代码，P1）**：两篇写 `/ws/...`，实际为 `/api/c/ws/...`；03 还没有披露 nginx 未配置 Upgrade。
4. **`/docs` 语义（03，P2）**：文章按「Swagger 文档」描述，现状是「Handbook 挂载 + Swagger 迁到 `/api/docs`」；验收清单「关闭 /docs」与当前设计冲突。
5. **表数量（07，P1）**：28 表为 P1 阶段数字，当前 63 表；同一批次内其他文章未重复该数字，无跨篇冲突，但会误导读者。

### 4.2 状态标注整体评价

- **没有把规划写成已实现**：10 篇中未发现「规划中」被标成「已实现」的系统性问题。最接近的是第 07 篇「连接池」被标成「规划中/未实现」——方向相反（低估已实现能力），属状态失准而非夸大；第 02 篇「同一存储事务」是把实现范围说大，属技术准确性（A）问题。
- **「部分实现」使用合理**：如 03 限流（仅登录限流）、05 去重（进程内）、06 告警（仅日志）、09 补偿（部分）、10 观测（部分）等，均与代码一致。
- **未核验项标注质量**：第 05、06、07、08、09 篇的「未核验项」具体、可操作，符合审计要求；第 03 篇也标注了生产链路未核验，值得保留。

### 4.3 批次结论

- 本批 10 篇的**结构、frontmatter、证据来源**整体合格，主要问题不是「编造」，而是**与快速演进的代码/部署脱节的过时细节**：WebSocket 路径、`/docs` 路由、连接池、表数量、压测报告有无、同一存储事务判断。
- 其中 3 组 P1（02 事务表述；07 表数量与连接池；03/04 WS 路径与 Nginx 代理）会直接影响工程师按文档操作或判断架构，建议在发布前修正；其余 P2 可在同一轮修订中处理。
- 修正后本批可达「通过」；当前结论：**通过 3 篇 / 条件通过 7 篇 / 不通过 0 篇**。

---

## 5. 审计方法与限制声明

- 本次审计为**只读**：未修改任何文章正文、配置或代码；仅创建本报告文件。
- 未运行 `pytest`、未启动服务、未使用浏览器/Chrome DevTools/Playwright；报告中「测试覆盖」仅来自阅读测试文件与用例名，「WebSocket 经 Nginx 不可用」「`/ready` 经 Nginx 不可达」等结论均为**按配置/代码推断**，已在对应位置标注「未实测」。
- 代码事实以 2026-11-23 本机工作区（HEAD `32ad31bc2636` + 未提交改动）为准；被审文章为未跟踪新文件，无法用提交记录核验其时间/版本，只能核对正文与代码/文档。
- 生产环境（部署拓扑、env 变量、证书、备份任务、真实数据量）不在本机可核验范围，相关项均列为「未核验」。
