# System Architecture 批次 P1 修复复核报告（2026-11-23）

> **批次**：`docs/handbook/03-system-architecture/`（P1 修复后复核）
> **涉及任务**：P1-09、P1-10、P1-11、P1-12
> **复核文件**：`02-modular-monolith-vs-microservices.md`、`03-api-gateway.md`、`04-service-communication.md`、`07-database-architecture.md`、`09-distributed-transactions-consistency.md`、`10-system-scalability.md`（下文简写 `02:`/`03:`/…均指该目录下文件）
> **复核性质**：只读复核。未修改任何文章/配置/代码；本文件是本次唯一新增文件。
> **复核方式**：逐行阅读 6 篇正文 + V0.5.2 基线 + P1 任务清单/审计报告；符号级 grep；逐条对照 `src/rag_demo/` 当前工作树、`nginx.conf`、`ops/`、`tests/`、`docs-site/`；以文件 mtime 与 dist 产物时间戳做修复窗口旁证。
> **运行边界**：本次**未运行** pytest / Regression Eval / Benchmark / `npm run build`，也未启动服务或浏览器。凡涉及运行行为（WS 经 Nginx 握手、连接池实际规模、生产部署拓扑）的结论均按“代码/配置推断”，不宣称“已通过”。

## 1. 批次、范围、基线、代码快照

### 1.1 复核范围与修复时间线

| 对象 | 文件 | 本轮 mtime | 说明 |
|---|---|---|---|
| 基线（新） | `01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md` | 2026-11-23 17:50:06 | M1-01 新增 |
| 基线（冻结） | `01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md` | 2026-11-23 14:53:21 | 早于修复时段，未被本轮改动 |
| P1-09 | `02-modular-monolith-vs-microservices.md` | 2026-11-23 17:50:06 | 本轮改动 |
| P1-12 | `03-api-gateway.md` | 2026-11-23 17:51:25 | 本轮改动 |
| P1-12 | `04-service-communication.md` | 2026-11-23 17:50:29 | 本轮改动 |
| P1-10/P1-11 | `07-database-architecture.md` | 2026-11-23 17:50:29 | 本轮改动 |
| 复核文件（无任务） | `09-distributed-transactions-consistency.md` | 2026-11-23 15:27:35 | 本轮未改，仅作交叉检查 |
| P1-10 | `10-system-scalability.md` | 2026-11-23 17:50:29 | 本轮改动 |
| 同批未复核 | `01`/`05`/`06`/`08` | 2026-11-23 15:27:09–15:40:33 | 不属本批 4 个任务范围 |

时间线旁证：审计主报告 17:39:57 → P1 任务清单 17:43:25 → 文章修复 17:50:06–17:51:25 → `docs-site/.vitepress/dist` 重建 17:52:55。既有构建日志 `build-check.log`（16:37:44）、`build-npm.log`（16:39:18）**早于**本轮修复，不能作为修复后构建通过的直接证据。

### 1.2 基线与代码快照

```text
基线          = docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md
                （version: 0.5.2；V0.5.1 冻结保留，docs-site srcExclude 排除）
代码快照      = Git HEAD 32ad31bc26365e8d0cefe503e6c09cfcd2876eaa（分支 b-end-2.0-p0）
                工作区含 130 项未提交改动，其中 src/rag_demo/api/main.py 已修改（行号按当前工作树）
文档版本状态  = docs/handbook/ 整体未纳入 Git（git ls-files = 0），无法用 git diff 复核
                “只改了指定段落”；只能以当前内容 + mtime + 任务清单推定
```

基线核验要点：

1. V0.5.2 已复制 V0.5.1 并做勘误：`V0.5.2:656-657` 为 `SQL_VALIDATION_ERROR`（V0.5.1 仍保留旧示例），V0.5.1 未覆盖。
2. 与 V0.5.1 的差异共 8 insertions / 7 deletions：版本行/版本说明、错误码示例、以及 `V0.5.2:1357` 的 retry 默认值行（旧“默认 max_retries=0”→ 函数默认 1 / API 默认 0 / 上限 3）。retry 行改动本身与代码一致（`loop.py:505`、`api/main.py:623,1439`），但 V0.5.2 版本说明 `:33-35` 自称“只处理错误码示例”，与实际 diff 不一致（见 §3.3 P2-L9）。
3. 公开站入口已切 V0.5.2：`docs-site/.vitepress/config.mjs:9,154` 指向 v0.5.2；`:122` 排除 V0.5.1；`docs-site/.vitepress/dist` 17:52:55 产物含 v0.5.2 页面、无 v0.5.1 页面；`docs/handbook/README.md:5,59,73,88,107` 已更新。
4. 基线中未出现“控制面 28/63 表”“连接池”“`/api/c/ws`”等本批主题，故本批四类修复与基线之间无直接口径冲突。

### 1.3 复核方法

- 以“审计报告原文引用 → 当前正文 → 真实代码/配置”三点对照，判断修复是事实修正还是只改措辞。
- 数字类（63 表、池大小 1..4/1..8、retry 等）逐项回源码计数或读取构造参数。
- 路径/拓扑类（`/api/c/ws/*`、Nginx Upgrade）同时检查后端路由定义、前端请求与 `nginx.conf` location。
- 跨篇检查 02↔09、07↔10、03↔04，以及 02↔V0.5.2 基线的状态口径。

## 2. P1 任务逐项结论表

| 任务 | 结论 | 核心证据（当前工作树 / 当前文档） |
|---|---|---|
| P1-09 修正跨存储事务描述 | **已修复**（事实口径正确） | `02:104` 已改为“订单、库存、售后写操作分别放在商家库事务与控制面事务中：两个仓储、两个提交点，跨存储并不原子，存在不一致窗口；靠补偿、幂等与对账兜底”。代码核对：`c_end/store.py::prepare_order` 控制面 `BEGIN IMMEDIATE`（`:2174`）→ 商家 `reserve_inventory`（`:2219`）→ 控制面 `commit`（`:2244`）；`confirm_order` 控制面 `BEGIN`（`:2288`）→ `create_order`/`commit_reservation`（`:2336-2353`）→ 控制面 `commit`（`:2400`）；`cancel_confirmed_order` 商家 `cancel_order`（`:2433`）先于控制面事务（`:2443`）；`resolve_after_sale`（`:2627`）与 `receive_after_sale`（`:2739,2744`）同类。全批 `同一存储事务` 命中 0；与 `09:39,76,166,199`“跨存储非原子/最终一致”一致。残留：`02:104`“对账兜底”未限定方向（见 P2-3）。 |
| P1-10 修正连接池状态 | **已修复**（状态分层正确；引入 1 处新数字错误） | `07:34,118,132,164`、`10:34,103,126,168` 均改为“连接池部分实现：控制面/商家仓储已用线程池，数据集连接层按单机单用户不做池”，两篇口径一致。代码核对：`control/postgres_repository.py:34-36` `ThreadedConnectionPool(1,4)`；`auth.py:301` `ThreadedConnectionPool(1,8)`；`merchant/postgres_repository.py:148-149` 默认 `POOL_MIN=1/POOL_MAX=8`，`:245-247` 创建；`db/connection.py:49-50` 注释明确“不做连接池”。新问题：`07:118` 把 `auth.py` 也写成“1..4”（见 P2-1）。 |
| P1-11 修正控制面表数量 | **已修复** | `07:65` 架构图为“控制面 63 表”；`07:112` 为“控制面 PG schema（63 表，2026-11-23 快照）”。代码/测试核对：`src/rag_demo/control/schema_pg.sql` 当前 63 个 `CREATE TABLE`（全部 `__SCHEMA__.` 限定）；`tests/test_control_repository_contract.py:11-26` 的 `EXPECTED_TABLES` 恰为 63 个。批内 `\b28\b` 命中 0，旧数字已清除。备注：未保留“28 为 2026-11-04 P1 阶段数字”的历史说明（因 28 已不出现，不构成错误）。 |
| P1-12 修正 WebSocket 路径与 Nginx 拓扑 | **部分修复**（04 完整；03 未完全满足验收） | `04:75,120,122`：路径补全为 `/api/c/ws/chat/{friend_id}`、`/api/c/ws/group/{group_id}`，并明确“当前 `nginx.conf` 的 `/api/` 未配置 Upgrade/Connection，按配置推断经 Nginx 时 WS 不可用”。代码核对：`api/c_end.py:25` 前缀 `/api/c`、`:1422`/`:1478` 路由；`web/src/views/CApp.vue:1388,1610` 前端路径；`nginx.conf:110-118` `/api/` 有 `proxy_http_version 1.1` 但 `proxy_set_header Connection ""`、无 `Upgrade`。`03:74,99` 已改为 `/api/c/ws/chat|group`，但**未写“当前 nginx.conf 未配置（按配置推断，未实测）”与 WS read timeout**，03:166/168 仍称边缘代理“已实现”、03:183 仍只列验收项；另 03 图路径未带 `{friend_id}/{group_id}`（见 P1-1）。 |

### 2.1 逐项核验细节

**P1-09**

- `prepare_order`/`confirm_order` 的商家调用发生在控制面事务内（同一应用线程），但 `get_merchant_write_repository()` 是独立连接、独立提交，因此“两个仓储、两个提交点”成立；`confirm_order` 在控制面提交前失败时不会回滚已提交的商家订单（正是 `09:171` 未核验项①描述的差异窗口）。
- 旧文“同一存储事务”已消除；02 与 09 不再互斥。
- 新增表述中的“靠……对账兜底”覆盖范围偏大：`09:171` 明确反向对账（商家订单已创建但 C 订单写入失败）是未核验/缺口，02 未限定“C→商家方向”（P2-3）。

**P1-10**

- 分层口径与代码一致：控制面仓储/认证池（1..4 / 1..8）、商家仓储（1..8）、数据集连接层无池；两篇文章不再出现“连接池未实现/规划中”的整体判断。
- `10:126` 的“阻碍多实例”描述保留了“数据集层无连接池、控制面/商家已有线程池但不解决数据集层问题”，准确。
- `07:118` 的括号把 `auth.py` 与 `control/postgres_repository.py` 合并标注“1..4”，与 `auth.py:301` 的 1..8 不符（P2-1）。

**P1-11**

- 63 为当前快照真实数字；`schema_pg.sql` 是 `__SCHEMA__.` 参数化 schema，63 张表均落在控制面 schema，图/表标注成立。
- 主审计要求的“28 仅作为历史数字出现”未被采用（文章完全不提 28）；这消除了错误数字，但也没有向读者解释旧口径来源，属可接受的简化。

**P1-12**

- 04 的修复完整：路径、缺口披露、“按配置推断”标记都在；对 WS 经 Nginx 不可用的判断与 `nginx.conf` 一致（未实测，标注诚实）。
- 03 的修复只完成一半：路径已改，但原 P1 问题中的“披露当前 Nginx 配置缺口”未落地；读者按 03 部署到 docker-compose 的 Nginx 拓扑时，仍可能不知道 WS 当前无法升级成功（04 有披露，但两篇独立阅读）。
- 04 新增“生产实际入口为 cloudflared→8000”为强断言，未标未核验，且与 03:86“两种拓扑都真实存在，排障前必须确认实际部署”、03:176“需以当前部署与 tunnel 配置为准”的谨慎口径不一致（P2-2）。

## 3. 新发现问题

### 3.1 P0 / P1

- **P0：无。** 未发现伪造证据、把规划写成已实现、或系统性数据造假。
- **P1-1（未修复/修复不完整，P1 级）：P1-12 中 03 的 Nginx 缺口披露与 WS read timeout 未落地。**
  - 位置：`03:86,99,166,168,183`。
  - 证据：03 只写“`/api/c/ws/*` 需要代理支持 Upgrade”（`:86,99`），未写“当前 `nginx.conf` 的 `/api/` location 未配置 Upgrade/Connection、按配置推断 WS 不可用（未实测）”；`nginx.conf:110-118` 确实 `Connection ""`、无 Upgrade；相对地 `04:122` 已完整披露。
  - 影响：P1-12 验收项“Nginx 缺口明确标‘按配置推断，未实测’”在 03 未满足；工程师按 03 部署 Nginx 拓扑仍有踩坑风险。修复成本低（补一段即可）。

### 3.2 本轮修复新引入的 P2

| 编号 | 问题 | 证据 | 影响/建议 |
|---|---|---|---|
| P2-1 | `07:118` 把 `auth.py` 的连接池写成 1..4，实际为 1..8 | 正文“控制面仓储（`auth.py`、`control/postgres_repository.py`，1..4）”；代码 `auth.py:301` 为 `ThreadedConnectionPool(1, 8, ...)`，`control/postgres_repository.py:34-36` 才是 `(1, 4)` | 数字错误由 P1-10 修复引入；建议改为“控制面仓储（`control/postgres_repository.py` 1..4；`auth.py` 1..8）” |
| P2-2 | `04:122`“生产实际入口为 cloudflared→8000”为未核验的强断言 | 仓库仅有被 gitignore 的本机配置 `ops/cloudflared.yml`（`.gitignore:115`，`credentials-file` 为 Windows 本机路径），ingress 指向 `127.0.0.1:8000`；`docs/e2e/observability-deployment.md:144` 称“**本地** cloudflared ingress 指向 8000”；原审计 §2.3 将生产拓扑列为未核验；03:86/176 仍要求“确认实际部署” | 与 03 口径不一致，且“生产实际”超出仓库可证范围。建议改为“仓库内 cloudflared 配置指向 8000；生产实际入口（cloudflared 直连或 Nginx 443）未核验，部署前确认” |
| P2-3 | `02:104`“靠补偿、幂等与对账兜底”未限定对账方向，覆盖范围偏大 | `09:167` 反向对账标“未核验/缺口”，`09:171` 未核验项①明确“商家订单已创建但 C 订单写入失败可能不被当前扫描发现”；当前 `reconcile_orders` 以 C 订单为主表扫描 | P1-09 事实修正成立；建议限定“对账目前覆盖 C→商家方向，反向对账仍是缺口” |

### 3.3 复核确认仍在的旧 P2（原审计已列，不属本批 4 个 P1 任务范围）

> 本批 P1 清单 §6 明确“不批量重写剩余 P2”，以下不作为 P1 修复失败的判据，但主审计主报告 §5 点名“修复时同时清理 `/docs` 旧叙述”的项目未做，列出供下批收口。

| 编号 | 问题 | 证据 | 级别 |
|---|---|---|---|
| P2-L1 | 03 仍把 `/docs`、`/openapi.json` 当 API 文档 | `03:95` 路由表“/health /metrics /openapi.json /docs → 运维与文档”；`03:186`“生产 /docs 与 /openapi.json 关闭”。当前 `api/main.py:520-523` `docs_url="/api/docs"`、`openapi_url="/api/openapi.json"`；`:757-758` `/docs` 挂载公开 Handbook | P2（主审计 §5 点名） |
| P2-L2 | 03 路由表缺 `/ready`（图中有），且经 Nginx 不可达 | `03:75` 图 R3 含 `/ready`；`03:92-96` 路由表无；`nginx.conf:194` 正则 `^/(stats\|health\|metrics\|openapi\.json\|docs)` 不匹配 `/ready` | P2 |
| P2-L3 | `02:175`“三端独立 Graph/数据隔离 \| 已设计”与基线冲突 | V0.5.2 `:1360`“C 端 Agent Graph \| 已实现（独立链路）”、`:1362`“C/B/A 三端统一 Runtime \| 已设计”；02 把 C 端已实现项合并标为已设计 | P2 |
| P2-L4 | `04:118`“通用 Webhook 用 `QIANKE_SUPERAGENT_WEBHOOK_SECRET` 做 HMAC 比较”不准确 | 实现是请求头 `X-Superagent-Secret` 与共享密钥的 `hmac.compare_digest` 常量时间比较（`api/superagent.py:336-338`、`superagent/triggers.py:101-107`），不是报文签名 | P2 |
| P2-L5 | `07:104`“`c_end/store.py` … 同一接口两套实现”不准确 | control/merchant 为双后端实现；`c_end/store.py` 是单一实现，经 `control/pg_compat.py`（`store.py:330` 引用）在 PG 上运行 | P2 |
| P2-L6 | `09:39`“不存在一个能同时覆盖它们的本地事务”能力断言过强 | 双 PG 配置下控制面/商家 schema 可同库，技术上单事务可覆盖（代码未采用）；同文 `09:171` 未核验项②已给出更谨慎表述 | P2 |
| P2-L7 | `10:171`“仓库内未见统一压测报告”与仓库事实相反 | 仓库有 `docs/e2e/b-end-performance-2026-11-14.md`、`c-end-performance-2026-11-14.md`（含 FCP/LCP、接口 p50/p95、5 并发测量）；准确说法是“有页面/接口级性能报告，无 2C4G 容量基线/全链路压测” | P2 |
| P2-L8 | `03:168`“公网隧道入口 \| 已实现 \| `ops/cloudflared.yml`”证据强度不足 | 该文件被 `.gitignore:115` 忽略、含 Windows 本机凭据路径；只能证明本机配置存在，不能证明生产隧道已运行 | P2 |
| P2-L9 | V0.5.2 版本说明与自身 diff 不一致 | `V0.5.2:33-35` 称“只处理……错误码示例”，但 `:1357` retry 行也被改（改动内容正确，与 P1-03 一致） | P2（基线侧，非本批文章） |

## 4. 跨篇一致性检查

| # | 检查项 | 结论 | 证据/说明 |
|---|---|---|---|
| 1 | 02↔09 事务/存储边界（P1-09 目标） | **一致（已修复）** | `02:104`“两个仓储、两个提交点、跨存储并不原子”；`09:39,76,166,199`“跨存储非原子/最终一致”；代码见 §2.1 |
| 2 | 07↔10 连接池状态（P1-10 目标） | **一致（已修复）** | `07:34,118,132,164` 与 `10:34,103,126,168` 均为“部分实现：控制面/商家仓储线程池 + 数据集层无池” |
| 3 | 03↔04 WebSocket 路径（P1-12 目标） | **一致（前缀已统一）** | 两篇均为 `/api/c/ws/chat`、`/api/c/ws/group`；04:120 给出带参完整路径；与 `api/c_end.py:25,1422,1478` 一致 |
| 4 | 03↔04 生产入口确定性 | **不一致（P2-2）** | 03:86,176 为“需确认/以当前部署为准”；04:122 断言“生产实际入口为 cloudflared→8000” |
| 5 | 02↔V0.5.2 三端 Graph 状态 | **不一致（P2-L3）** | 02:175“三端独立 Graph/数据隔离 \| 已设计” vs V0.5.2:1360“C 端 Agent Graph 已实现” |
| 6 | 07 的 63 表 ↔ 契约测试 | **一致** | `control/schema_pg.sql` 63 个 `CREATE TABLE`；`test_control_repository_contract.py:11-26` 63 个期望表名 |
| 7 | 03↔代码 `/docs` 语义 | **不一致（P2-L1）** | 03:95,186 按 API 文档描述；代码 `/docs` 为 Handbook，Swagger 在 `/api/docs` |
| 8 | 10↔仓库压测报告 | **不一致（P2-L7）** | 10:171“未见统一压测报告” vs 两份 `docs/e2e/*-performance-2026-11-14.md` |
| 9 | 04 Webhook 验签实现 | **不一致（P2-L4）** | 04:118“HMAC 比较” vs 共享密钥头常量时间比较 |
| 10 | 07 C 端存储实现口径 | **不一致（P2-L5）** | 07:104“同一接口两套实现” vs `c_end/store.py` 单实现 + `pg_compat` |
| 11 | 02 对账兜底范围 ↔ 09 反向对账缺口 | **有张力（P2-3）** | 02:104“对账兜底” vs 09:167,171 反向对账未核验/缺口 |
| 12 | 批内旧错误码/旧版本引用 | **未发现** | 6 篇均无 `READ_ONLY_VIOLATION`、`LIMIT_REQUIRED`、`TENANT_SCOPE`；无对 V0.5.1/旧审计报告的引用；正文也未引用旧审计结论 |
| 13 | 63 表数字的批内重复 | **一致** | 只有 07 使用该数字，且图/表一致；其余文章未重复旧“28 表” |
| 14 | 跨批次旧版本引用（本批文件外） | 需其他批次处理 | 其他章节仍有多处引用 `01-…-v0.5.1.md`（如 06-architecture-practice、02-enterprise-governance 等），本批 6 篇不涉及 |

## 5. 未核验项

以下项目本次**未执行**，报告中未给出“通过/已验证”结论：

```text
1. pytest / Regression Eval / Benchmark：未运行；本批文章未声称运行过测试，本报告也不宣称任何测试通过。
2. npm run build：本轮未执行。旁证仅为 docs-site dist 17:52:55 已含修复后内容
   （dist-02 含“两个提交点”、dist-03 含“/api/c/ws/chat”、dist-04 含 cloudflared 句），
   且 v0.5.2 页面存在、v0.5.1 页面被排除；该次构建无日志/退出码
   （build-check.log 16:37:44、build-npm.log 16:39:18 均早于修复），故“构建通过”未核验。
3. WebSocket 经 Nginx 的实际握手：未用浏览器/websocat 实测，结论仅按 nginx.conf 配置推断。
4. 生产部署拓扑（cloudflared 直连 8000 或 Nginx 443）、TLS 证书、域名解析：未核验。
5. 生产 env 的 backend 选择（QIANKE_CEND_BACKEND / QIANKE_MERCHANT_* / 控制面 PG 实例与库）：未核验。
6. “控制面 63 表”仅核对 schema_pg.sql 与契约测试期望，未连接真实 PG 核对实际库表数量。
7. 连接池运行期实际连接数/池行为：仅做静态参数核对，未压测。
8. 订单/售后/对账链路：未做故障注入，未验证“跨存储失败后补偿/对账”在运行时的实际行为。
9. 修复前后的精确 diff 无法取得（docs/handbook 未入 Git），因此“只改指定位置、不扩大范围”只能按当前内容与任务清单推定，未做版本库级核验。
10. V0.5.1“保留不变”为 mtime + 内容签名间接核验（14:53，早于修复窗口），非 git diff。
11. 外部链接可达性、60 篇公开路由与浏览器端渲染/交互：未核验（本报告只审内容）。
```

## 6. 批次结论

**条件通过。**

判定依据：

```text
1. 4 个 P1 任务中，3 个已真正修复且与代码证据一致：
   - P1-09：02 的跨存储事务口径与 c_end/store.py 的“商家先提交、控制面后提交”一致，且与 09 篇统一；
   - P1-10：07/10 两篇连接池状态已按“控制面/商家仓储有池、数据集层无池”分层，与代码一致；
   - P1-11：63 表为当前 schema_pg.sql 与契约测试的真实数字，旧 28 已清除。
2. P1-12 为部分修复：04 完整（路径 + Nginx 缺口披露）；03 只改了路径，
   未披露当前 nginx.conf 的 Upgrade/Connection 缺口，也未提 WS read timeout，P1 验收未完全满足（P1-1）。
3. 未发现修复引入的 P0/P1 事实错误，无伪造测试/构建结果。
4. 不满足“无条件通过”的原因：
   - P1-1：03 的 Nginx 缺口披露缺失（P1 级未完成项）；
   - P2-1：07:118 auth.py 连接池大小写错（1..4 vs 实际 1..8）；
   - P2-2：04:122 生产入口强断言与 03/仓库证据不一致；
   - P2-3：02:104“对账兜底”未限定方向，与 09 反向对账缺口有张力；
   - 既有 P2 残留：03 的 /docs、/ready/tunnel（P2-L1/L2/L8）、02 的三端 Graph（P2-L3）、
     04 的 Webhook 措辞（P2-L4）、07 的 c_end 双实现（P2-L5）、09 的“不存在”表述（P2-L6）、
     10 的“未见压测报告”（P2-L7）、V0.5.2 版本说明与 diff 不一致（P2-L9）。
```

建议的通过条件（本批发布前完成）：

```text
A. 03 补一段 Nginx 缺口披露：/api/c/ws/ 需 proxy_http_version 1.1 + Upgrade/Connection
   升级头与更长 read timeout；当前 nginx.conf 未配置，按配置推断 WS 不可用（未实测）。
B. 04:122 改为“仓库内 cloudflared 配置指向 8000；生产实际入口未核验，部署前按拓扑确认”。
C. 07:118 改为“control/postgres_repository.py 1..4；auth.py 1..8”。
D. 02:104 把“对账兜底”限定为“C→商家方向；反向对账仍是缺口”。
E. 旧 P2 随下批收口：03 的 /docs、/ready、tunnel 证据；02:175 三端 Graph 拆分；
   04:118 Webhook 措辞；07:104 c_end 双实现；09:39“不存在”；10:171 压测报告；
   V0.5.2 版本说明补记 retry 行勘误。
F. 为最近一次 docs-site 构建留存日志/退出码（当前仅有 dist 17:52:55 产物，无日志）。
```
