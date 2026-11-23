# Architecture Practice 批次 P1 修复复核报告（2026-11-23）

> **复核类型：** 只读复核审计（P1 修复后）。本轮不修改任何文章、配置或代码，只新增本报告文件。
> **批次：** architecture-practice（06 · Architecture Practice）
> **范围：** P1-18、P1-19、P1-20、P1-21、P1-22，共 5 项任务、4 篇文章
> **基线：** `docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md`（V0.5.2，2026-11-23 发布）；V0.5.1 仅保留为历史/审核记录，不进公开站
> **代码快照：** Git `32ad31bc26365e8d0cefe503e6c09cfcd2876eaa`（2026-11-22 19:15 +0800）；工作区含未提交修改，`docs/handbook/` 未纳入 git 跟踪
> **复核时点：** 2026-11-23 17:55–18:00（+08:00）
> **复核结论：** **条件通过**（P0 = 0；新增 P1 = 0；P2 = 7 项，其中 P2-1/P2-2/P2-3 与本批修复或基线切换直接相关）

---

## 0. 复核方式与证据边界

### 0.1 本轮实际执行的操作

```text
1. 逐行阅读 4 篇被修复文章与 V0.5.2 基线、P1 任务清单、内容质量审计、批次审计报告；
2. 用 read / grep 核对文章声明对应的 src/、tests/、docs/、web/ 证据；
3. 用 PowerShell 统计 store.py 行数（总量与非空行两种口径）、读取文件 mtime、git 状态；
4. 抽查 docs-site/.vitepress/dist 构建产物是否包含修复后文本、是否仅发布 V0.5.2；
5. 核对 P1 任务要求的“修复前原文—真实证据—修改方向—验收”四项是否逐条兑现。
```

**未运行：** `pytest`、docs-site 构建、HTTP/浏览器、真实 LLM Eval、性能重测。凡涉及“运行结果”的结论，本报告一律标为“未核验”，不以审计报告或历史日志代替本次运行。

### 0.2 无法取得精确 diff 的说明

`docs/handbook/` 当前是未跟踪目录（`git status --porcelain -- docs/handbook` 输出 `?? docs/handbook/`），4 篇文章 mtime 均为 `2026-11-23 17:50:29`。因此无法用 `git diff` 精确还原“修复前/修复后”差异；本报告的“修复前原文”取自：

```text
docs/handbook/_meta/reviews/2026-11-23-content-quality-audit.md
docs/handbook/_meta/reviews/2026-11-23-p1-fix-tasks.md
docs/handbook/_meta/reviews/audit-2026-11-23/architecture-practice.md
```

### 0.3 并发修改提示

复核期间工作区存在其他批次的并发修改（如 `03-system-architecture/07-database-architecture.md` 同样在 17:50:29 被修改）。本报告以 **17:55–18:00 快照**为准；若此后文件再变，相关结论需重新核对。

---

## 1. 批次、范围、基线、代码快照

| 项 | 值 | 证据 |
|---|---|---|
| 批次 | architecture-practice（06 · Architecture Practice） | `2026-11-23-p1-fix-tasks.md` §4 |
| 本批 P1 | P1-18 / P1-19 / P1-20 / P1-21 / P1-22 | 同上 |
| 复核文件 1 | `docs/handbook/06-architecture-practice/02-architecture-design-method.md` | mtime 17:50:29 |
| 复核文件 2 | `docs/handbook/06-architecture-practice/03-module-decomposition.md` | mtime 17:50:29 |
| 复核文件 3 | `docs/handbook/06-architecture-practice/06-architecture-decision-records.md` | mtime 17:50:29 |
| 复核文件 4 | `docs/handbook/06-architecture-practice/09-technical-debt.md` | mtime 17:50:29 |
| 新基线 | V0.5.2（`doc_status: 草稿`，`version: 0.5.2`，`updated: 2026-11-23`） | V0.5.2 frontmatter L10；头注 L33–L38 |
| 旧基线处置 | V0.5.1 冻结保留、不进入公开站；`srcExclude` 显式排除 | V0.5.2 头注 L36；`docs-site/.vitepress/config.mjs:122` |
| 公开站入口 | 第 1 篇已指向 V0.5.2 | `docs-site/.vitepress/config.mjs:9,154`；`docs/handbook/README.md:5,59,73` |
| 代码快照 | `32ad31bc26365e8d0cefe503e6c09cfcd2876eaa`（分支 `b-end-2.0-p0`，2026-11-22 19:15 +0800） | `git rev-parse HEAD`；与批次审计报告快照一致 |
| 行数证据文件 | `src/rag_demo/c_end/store.py`、`src/rag_demo/superagent/store.py` | 两文件 `git status` 均为空（工作区 = HEAD） |

### 1.1 基线 V0.5.2 抽查（作为本批的对照基准）

| 检查 | 结果 | 证据 |
|---|---|---|
| 错误码勘误已落地 | **通过** | V0.5.2 L656 为 `"code": "SQL_VALIDATION_ERROR"`；区分大小写搜索无 `READ_ONLY_VIOLATION`；V0.5.1 L655 仍保留旧码（冻结稿，符合保留策略） |
| V0.5.1 未进公开站 | **通过** | `config.mjs:122` 的 `srcExclude` 含 `01-enterprise-agent-architecture-v0.5.1.md`；`dist/agent-architecture/` 下只有 `01-enterprise-agent-architecture-v0.5.2.html` |
| 版本说明与 diff 一致 | **观察（P3，不计入本批）** | V0.5.2 头注（L33–L38）声明“只处理基线错误码示例”，但与 V0.5.1 的 diff 还含 L1357 retry 表述修正（`函数默认 1；API 请求默认 0、上限 3`）。内容本身正确（同 P1-03 证据），但版本说明少记一项，建议在修订记录补一句。**不影响本批 5 项任务的判定。** |

---

## 2. P1 任务逐项结论

### 2.1 结论总表

| 任务编号 | 复核对象（位置） | 结论 | 关键证据 |
|---|---|---|---|
| **P1-18** | 02 篇 §5 L123、§9 L184 | **已修复** | 两处均改为“人工性能报告，不是自动化测试/CI 门禁”；`tests/` 无性能门禁命中；`ci.yml` 只有单测 + 离线 Eval 快照门禁；与 08 篇口径一致 |
| **P1-19** | 02 篇 §8 L161 | **已修复** | 状态改为“M0 ACCEPTED 2026-11-22；M1 未批准”；证据列已补 `docs/product/merchant-dashboard-v1.1-m0-closure.md` |
| **P1-20** | 06 篇 §8 L163 | **基本修复（附 P2 证据缺口）** | 状态文字与 P1-19 同口径；但证据列只引 ADR-0002，未按“同 P1-19”补 closure 文档；所引 ADR 头状态行仍为“M0 验收进行中” |
| **P1-21** | 03 篇 §5 L131 | **部分修复（P2：计数口径未注明）** | 旧数字已更新、删除“已核验的”；但新数字 6,028/1,084 是**非空行**口径，文中未注明，且与 P1 清单/审计报告的 6,578/1,198（总行数）不一致 |
| **P1-22** | 09 篇 §5 L107 | **部分修复（P2：同 P1-21）** | 与 03 篇同一组数字、同一口径问题；两篇互相一致 |

**判定口径：** 已修复 = 原文错误结论、状态或数字已按真实证据改正且验收项全部满足；基本修复 = 原始缺陷已改正但验收项未全部满足（仅剩证据链/表述级问题）；部分修复 = 原始缺陷方向已改，但关键验收项（计数口径）未满足，可能被下一轮复核再次判为旧数字。

### 2.2 P1-18 修正性能门禁表述 — 已修复

**修改后原文：**

```text
02 L123：测试中已有租户隔离、Tool Policy、schema 双端契约；性能门禁目前是 B/C 端人工性能报告，不是自动化测试/CI 门禁。
02 L184：…B/C 端性能门禁目前以人工报告形式存在，尚未进入测试/CI。统一的架构评审门禁与依赖边界 CI 仍属规划/待补。
```

**核验结果：**

| 声明 | 结果 | 证据 |
|---|---|---|
| `tests/` 中无性能门禁测试 | 成立 | 对 `tests/*.py` 检索 `LCP`、`CLS`、`p95`、`performance_gate`、`性能门禁`，**0 命中**（本轮实际执行） |
| CI 无性能门禁 | 成立 | `.github/workflows/ci.yml:76-77` 仅 `pytest tests/ -q`；`:79-111` 为离线 Eval 快照门禁 |
| 性能门禁只存在于人工报告 | 成立 | `docs/e2e/b-end-performance-2026-11-14.md`、`docs/e2e/c-end-performance-2026-11-14.md` 存在（人工报告口径） |
| 与 08 篇口径一致 | 成立 | 08 篇 L128：生产 SLO、p95 告警、容量基线与 CI 性能门禁“尚未完整建立”；L174：持续性能门禁/容量基线“规划中” |

**结论：** 非表面措辞修改——把“测试证据”降级为“人工报告”，与真实证据一致，验收项“不把人工报告写成自动化测试；与 08 篇一致”满足。

### 2.3 P1-19 修正 Dashboard M0 状态 — 已修复

**修改后原文（02 L161）：**

```text
| Dashboard V1.1 架构基线 | docs/decisions/merchant_dashboard_v1_1_m0_adr.md；docs/product/merchant-dashboard-v1.1-m0-closure.md | 已实现（M0 ACCEPTED 2026-11-22；M1 未批准） |
```

**核验结果：**

| 声明 | 结果 | 证据 |
|---|---|---|
| M0 = ACCEPTED，日期 2026-11-22 | 成立 | `docs/product/merchant-dashboard-v1.1-m0-closure.md:3-6`：“状态：M0 ACCEPTED / 日期：2026-11-22 / M1：未批准，未启动” |
| A-01～A-08 全 PASS | 成立 | closure L12-16；`merchant-dashboard-v1.1-m0-acceptance-report.md:3-7` 同（含 M0 ACCEPTED、M1 未批准/未启动） |
| M1 未批准 | 成立 | closure L6；acceptance report L7 |
| 证据列已补 closure | 成立 | 02 L161 的“证据”列同时列出 ADR 与 closure 文档 |

**结论：** 状态与 closure/acceptance 文档一致，验收项满足。

### 2.4 P1-20 修正 ADR 篇 M0 状态 — 基本修复（附 P2 证据缺口）

**修改后原文（06 L163）：**

```text
| docs/decisions/merchant_dashboard_v1_1_m0_adr.md | ADR-0002：Dashboard V1.1 M0 架构基线与 M1 边界 | 已实现（M0 ACCEPTED 2026-11-22；M1 未批准） |
```

**已满足的部分：**

- 状态文字与 02 篇完全同口径（`M0 ACCEPTED 2026-11-22；M1 未批准`），批次内不再出现两种 M0 状态；
- 断言本身为真（closure 文档佐证）。

**未满足的部分（P2-3）：**

```text
1. P1-20 的“修改/证据：同 P1-19”要求补 closure 证据，但 06 篇该行证据列仍只有 ADR-0002；
   在 06 篇全文检索 m0-closure/closure 无命中；
2. 被引用的 ADR 头部状态行仍是旧状态：
   docs/decisions/merchant_dashboard_v1_1_m0_adr.md:6
   > 状态：架构决策冻结；M0 验收进行中
   读者顺证据链打开 ADR 会看到与文章结论相反的旧状态。
```

**结论：** P1 级缺陷（M0 状态过时）已改正；但“补证据 + 与 P1-19 完全同口径”未做全，属 P2 证据链问题，不影响本批“P1 已修”的定性。

### 2.5 P1-21 / P1-22 修正模块拆分篇、技术债务篇旧行数 — 部分修复

**修改后原文：**

```text
03 L131：…c_end/store.py 约 6,028 行、superagent/store.py 约 1,084 行（2026-11-23 当前文件统计）…（已删“这是已核验的盘点结论”）
09 L107：| 超大存储文件 | c_end/store.py 约 6,028 行、superagent/store.py 约 1,084 行（2026-11-23 当前文件统计） | … |
```

**本轮实测（两个口径都给出）：**

```powershell
# 总行数（Get-Content 行数，包含空行）
(Get-Content -LiteralPath 'src/rag_demo/c_end/store.py').Count        # 6578
(Get-Content -LiteralPath 'src/rag_demo/superagent/store.py').Count   # 1198

# 非空行数（Trim() 后仍非空）
... | Where-Object { $_.Trim() -ne '' }  # c_end: 6028；superagent: 1084
```

**结论：**

| 项 | 判定 | 说明 |
|---|---|---|
| 旧快照数字（2,744 / 1,044）“已核验”表述 | **已修复** | 两篇均已替换，且删除“已核验的” |
| 数字更新为当前值 | **部分成立** | 6,028 / 1,084 恰为**非空行**数（空行 550 / 114）；若按总行数复核为 6,578 / 1,198 |
| 验收项“计数口径注明” | **未满足** | 两篇均只写“2026-11-23 当前文件统计”，未说明按非空行统计；而 P1 清单 L252 的真实证据、批次审计 L152/L362 的复核值均为 6,578 / 1,198 |
| 两篇一致性 | **通过** | 03 与 09 使用同一组数字，无互相矛盾 |

**风险：** 下一轮复核若按“总行数”重数，会把 6,028/1,084 再次判为与当前文件不一致，P1 会被重新打开；且读者无法复现“当前文件统计”的方法。

---

## 3. 新发现问题

本批**未发现 P0**，**未发现新增 P1**。以下 P2 中，P2-1、P2-2、P2-3 与本批修复动作直接相关（修复后新出现或新暴露的不一致）；P2-4～P2-7 为原审计已列、且不在本批 P1 清单范围内的残留项，复核时仍在文中。

### P2-1 行数“当前文件统计”未注明口径，与审计/任务给出的复核值不一致

- **位置：** `03-module-decomposition.md:131`；`09-technical-debt.md:107`
- **现象：** 文章写“约 6,028 行 / 约 1,084 行（2026-11-23 当前文件统计）”；实测总行数 6,578 / 1,198，非空行 6,028 / 1,084。
- **证据：** `2026-11-23-p1-fix-tasks.md:251-253` 要求“行数与当前文件一致；计数口径注明”，并给出“当前约 6,578 / 1,198 行”；`audit-2026-11-23/architecture-practice.md:152,158,362,368` 采用 `Get-Content().Count` 口径。
- **建议：** 写成“约 6,028 行（非空行；总行数 6,578，2026-11-23）”，或直接改为总行数 6,578 / 1,198；两篇同步。

### P2-2 仍在引用已冻结的 V0.5.1（新基线为 V0.5.2）

- **位置：** `02-architecture-design-method.md:157`；`09-technical-debt.md:112,159,211`
- **现象：**
  - 02 L157 以 `docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md` 作为“企业级 Agent 六层架构”的证据；
  - 09 L112 写“未覆盖（v0.5.1）”，L159 以该 V0.5.1 路径作为“已知缺口记录”证据，L211 的延伸阅读也指向它；
  - 4 篇复核文件中检索 `v0.5.2` **0 命中**。
- **证据：** 新基线为 V0.5.2（README `:5,59,73`；`config.mjs:9,154`）；V0.5.1 已冻结、`srcExclude` 排除（`config.mjs:122`），`dist/agent-architecture/` 只有 v0.5.2 页面；V0.5.2 头注 L36 明确“V0.5.1 冻结稿保留…不进入公开站”。
- **影响：** 内容层面 V0.5.2 与 V0.5.1 在“测试缺口/已知限制”文字上相同，引用不会造成事实错误；但会把读者导向冻结版本，与“V0.5.2 为唯一基线”的站内约定矛盾。
- **全站同类残留（供后续批次参考，不属本批 5 项 P1）：** 公开文章中共 7 篇仍出现 `v0.5.1`——`01-agent-architecture/02-agent-vs-enterprise-agent.md:518,616,689`、`03-agent-runtime.md:419,475`、`04-agent-orchestrator.md:325`、`02-enterprise-governance/07-prompt-injection-defense.md:48`、`10-enterprise-architecture-case.md:210`。其中 3 处链接文字仍写“V0.5.1”、目标已指向 V0.5.2（如 02-agent-vs-enterprise-agent L689），属全站基线迁移未扫尾。
- **建议：** 本批先把 02/09 的 4 处指向改为 V0.5.2（或改称“基线文章（V0.5.2）”）；其余 7 篇统一另开迁移清扫任务。

### P2-3 06 篇 M0 状态缺 closure 证据，且被引 ADR 状态行仍为“M0 验收进行中”

- **位置：** `06-architecture-decision-records.md:163`；`docs/decisions/merchant_dashboard_v1_1_m0_adr.md:6`
- **现象：** 文章状态已改“M0 ACCEPTED 2026-11-22”，但证据列只引 ADR-0002；ADR 头状态行仍写“架构决策冻结；M0 验收进行中”。
- **证据：** `merchant-dashboard-v1.1-m0-closure.md:3-6`（ACCEPTED / 2026-11-22 / M1 未批准，未启动）；06 篇全文无 closure 引用（grep `closure|m0-closure` 0 命中）。
- **性质：** 这是“修复文章状态但未同步证据源”产生的**跨文档新矛盾**：修复前文章与 ADR 都写“进行中”，互相一致；修复后文章写 ACCEPTED，而它引用的唯一证据文档仍写“进行中”。
- **建议：** 06 L163 证据列补 `docs/product/merchant-dashboard-v1.1-m0-closure.md`；同时建议在 ADR 状态行加注“M0 已于 2026-11-22 ACCEPTED（见 closure 文档）”或由 ADR 治理任务统一更新状态字段（改状态字段 vs 不改原文需按团队 ADR 规范决定，本报告不代判）。

### P2-4 01 篇性能门禁仍标“已实现”，与修复后的 02 篇和 08 篇口径冲突

- **位置：** `01-requirements-analysis.md:155`
- **现象：** `| 需求到验收的可执行口径 | docs/e2e/b-end-performance-2026-11-14.md 性能门禁 | 已实现 |`
- **证据：** 02 篇修复后 L123/L184 明确“人工报告，不是自动化测试/CI 门禁”；08 篇 L128/L174 明确“CI 性能门禁尚未完整建立/规划中”；`tests/` 与 `ci.yml` 无性能门禁（本轮 grep 实测）。
- **性质：** 原审计已列的 P2（architecture-practice 审计 L91），不在 P1-18～P1-22 修复范围（P1 清单 §6 明确“不批量重写剩余 P2”）；但 02 篇修好后，批次内 01↔02 的口径差异更醒目，属“修复后跨篇不一致”。
- **建议：** 01 L155 改为“已实现（人工门禁报告，未自动化）”，或与 02/08 口径对齐。

### P2-5 06 篇“保留 16 项待确认决策清单”数字错误（实际 12 项）

- **位置：** `06-architecture-decision-records.md:170`
- **现象：** 写“保留 16 项待确认决策清单”。
- **证据：** `docs/decisions/three_agent_platform_architecture_decisions_v0.1.md:643-658` §16 清单逐条共 **12 项**（L647–L658）。
- **性质：** 原审计 P2（L262），仍存在；“16”疑与章节号 §16 混淆。
- **建议：** 改为“保留 12 项待确认决策清单（原文 §16）”或“保留 §16 的待确认决策清单”。

### P2-6 03 篇控制面存储抽象路径 `control/repository` 不存在

- **位置：** `03-module-decomposition.md:164`
- **现象：** `| 控制面存储抽象 | control/repository、factory.py、双后端 | 已实现 |`
- **证据：** `src/rag_demo/control/` 下无 `repository` 文件/目录；实际为 `factory.py`、`sqlite_repository.py`、`postgres_repository.py`、`superagent_repository.py`、`job_queue.py`、`settings.py`、`pg_compat.py`。
- **性质：** 原审计 P2（L159），仍存在。
- **建议：** 改为 `control/factory.py`、`control/sqlite_repository.py`、`control/postgres_repository.py`。

### P2-7 02 篇“企业级 Agent 六层架构”仍标“已实现”

- **位置：** `02-architecture-design-method.md:157`
- **现象：** 状态列“已实现（文档 + 部分代码对应）”。
- **证据：** 六层（接入/Runtime/Tool/Data/Governance/Observability）是 V0.5.2 §3.1 的逻辑分层模型（V0.5.2 L500–L557 明示“逻辑分层，不等于必须拆成微服务”）；当前代码没有对应的六层落地结构。
- **性质：** 原审计 P2（L127），仍存在；与 P2-2 同位置，可在一次修改中处理。
- **建议：** 改为“已设计（逻辑分层）+ 部分实现（代码映射）”，或“理论知识（分层模型）+ 部分实现”。

### 3.1 未形成 P1/P2 的观察（不计入本批判定）

- **V0.5.2 版本说明少记 retry 修正：** 头注 L33–L38 声明“只处理基线错误码示例”，但实际 diff 还改了 L1357 的 retry 默认值表述（`函数默认 1；API 请求默认 0、上限 3`）。内容本身正确（与 P1-03 证据一致），建议在修订记录补登，避免“基线快照=单一变更”的误解。
- **02 L167“SQLite 28 张表”**：该数字出现在“控制面数据库迁移”案例中，语境是“方案先盘点…方言依赖”，与 `control_plane_postgres_migration_v0.1.md:46`（2026-11-05 盘点值）一致；不算旧数字错误（与 System 07 的“当前 63 表”是不同对象/时点）。若追求严谨可加“迁移方案盘点时”限定。

---

## 4. 跨篇一致性检查

| 检查项 | 结果 | 证据 / 级别 |
|---|---|---|
| M0 状态：02 vs 06 vs closure | **一致** | 02 L161、06 L163 均为“M0 ACCEPTED 2026-11-22；M1 未批准”；closure L3-6 同 |
| M0 状态：文章 vs 被引 ADR | **不一致（P2-3）** | 文章 ACCEPTED，ADR L6“M0 验收进行中” |
| 性能门禁：02 vs 08 | **一致** | 02 L123/L184 与 08 L128/L174 均为“人工报告/未进入 CI” |
| 性能门禁：01 vs 02/08 | **不一致（P2-4）** | 01 L155“已实现” |
| 行数：03 vs 09 | **一致** | 均为 6,028 / 1,084 |
| 行数：文章 vs 审计报告/P1 清单 | **不一致（P2-1）** | 审计/P1 清单为 6,578 / 1,198（总行数口径） |
| 基线版本：4 篇 vs README/站内配置 | **不一致（P2-2）** | 4 篇引用 V0.5.1；README/config/dist 均已切换 V0.5.2 |
| 控制面表数量：02 L167（28） vs System 07（63） | **通过（语境不同）** | 02 为迁移方案 2026-11-05 盘点值；System 07 为当前 PG schema 63 表（`07-database-architecture.md:65,112`）；不构成矛盾 |
| ADR 待确认清单：06 L170（16） vs 源文档（12） | **不一致（P2-5）** | `three_agent_platform_architecture_decisions_v0.1.md:647-658` 共 12 项 |
| 控制面存储抽象：03 L164 vs `control/` 实际文件 | **不一致（P2-6）** | 无 `control/repository` |
| 六层架构状态：02 L157 vs V0.5.2 定性 | **不一致（P2-7）** | V0.5.2 称逻辑分层；文章称“已实现” |
| 基线错误码：V0.5.2 vs 旧码 | **通过** | V0.5.2 L656 `SQL_VALIDATION_ERROR`；大小写敏感检索无 `READ_ONLY_VIOLATION` |
| 公开站基线入口：README / config / dist | **通过** | README L5/L59/L73；config L9/L154；dist 仅 v0.5.2 页面 |
| 本批 4 篇是否互相矛盾 | **未发现** | 02/03/06/09 之间无新增互相矛盾；03 与 09 行数一致 |

---

## 5. 未核验项

```text
1. 未运行 pytest / 全量测试 / Regression / Benchmark。本报告不引用任何“测试通过”结论；
   涉及的测试相关事实（无性能门禁测试、ci.yml 步骤）来自本轮的静态 grep/文件读取。
2. 未重跑 docs-site 构建。
   现有证据：4 篇文章 mtime 17:50:29；docs-site/.vitepress/dist mtime 17:52:55；
   dist 共 68 个 HTML（60 文章 + 6 分类索引 + 首页 + 404），其中 02/03/06/09 页面已含
   修复后文本（人工性能报告、M0 ACCEPTED、6,028、仅 v0.5.2 页面）。
   但 docs-site/build-check.log（16:37:44）与 build-npm.log（16:39:18）均早于修复时间，
   没有 17:52 那次构建的日志与退出码 → 只能按产物推断“构建已执行且产物完整”，
   不能声称“本次已复核构建通过”。P1 清单的“docs-site 构建通过”验收项按此标注为未核验。
3. 未做浏览器/HTTP 验证：/docs 线上可访问性、60 篇公开路由实际可达性均未验证（仅数了 dist 文件）。
4. 外部链接（ISO、arc42、C4、Martin Fowler 等）未抓取，未核验可达性。
5. 性能数字（p95 862ms / 870ms、N+1 726→56.5ms、CLS/首屏等）均引用报告，本轮未重测。
6. 无法获得精确修复 diff：docs/handbook/ 未被 git 跟踪；修复前文本取自审计报告/P1 清单。
7. “仓库中未见 ADR 模板/索引”“决策散落在 docs/product、docs/design”等缺失型声明：
   仅按目录与关键词检索，未做全仓库穷举（沿用原审计口径）。
8. 工作区为多 agent 并发修改状态，本报告结论以 2026-11-23 17:55–18:00 快照为准。
```

---

## 6. 批次结论

### 6.1 结论：**条件通过**

**理由：**

1. **5 项 P1 中 2 项判定为已修复（P1-18、P1-19）**，1 项基本修复（P1-20：核心状态缺陷已改正，但未补 closure 证据），2 项为部分修复（P1-21、P1-22 的数字已更新，但计数口径未注明，可能被下一轮复核重新判为“旧数字”）；
2. **未发现 P0，未发现新增 P1**；本批修复没有产生“把规划写成已实现”或伪造测试结果的退化；
3. 但复核发现 **7 项 P2**，其中 P2-1（行数口径）、P2-2（旧基线 V0.5.1 引用）、P2-3（06 篇 M0 证据链/ADR 旧状态）与本批修复动作直接相关，且 P2-3 是修复后新出现的跨文档矛盾；
4. 原批次审计已列、但明确不在本批 P1 范围的 P2（01 性能门禁口径、06 的 16→12、03 的 `control/repository`、02 六层架构状态）仍存在，不能判为“通过”。

**判定为“条件通过”而非“通过”的关键条件：**

```text
C1（对应 P1-21/P1-22）：03 L131、09 L107 注明“按非空行统计”，或直接改为总行数 6,578 / 1,198；
C2（对应 P2-2）：02 L157、09 L112/L159/L211 的 V0.5.1 引用改为 V0.5.2 / “基线文章”；
C3（对应 P2-3）：06 L163 证据列补 closure 文档；ADR-0002 L6 状态行按 ADR 治理规范同步或加注；
C4（对应 P2-4～P2-7）：01 L155、06 L170、03 L164、02 L157 状态措辞按原审计建议修正（可排后续 P2 批次）。
```

以上 C1–C3 修完后，本批 P1 可整体结转；C4 为原审计 P2 的常规清扫项。**不建议**在没有补 C1/C2 的情况下直接宣布本批 P1 全部完成。

### 6.2 回答委托复核的四个问题

| 问题 | 回答 |
|---|---|
| 原文修改是否与代码证据一致？ | P1-18、P1-19 完全一致；P1-20 结论正确但证据链不闭合（P2-3）；P1-21/P1-22 数字可用但口径与审计/任务证据不一致（P2-1） |
| 是否只改表面措辞？ | P1-18/P1-19 为实质修改；P1-20 只改了状态文字、未补证据（P2-3）；P1-21/22 数字确实更新、删除了“已核验”表述，但口径未注明，仍有再次被质疑的风险 |
| 是否与相关文章保持一致？ | 02↔08、02↔06 的 M0 状态一致；但 02/09 与新基线 V0.5.2 不一致（P2-2）、06 与被引 ADR 不一致（P2-3）、02 与 01 的性能门禁口径不一致（P2-4） |
| 是否还有旧版本（V0.5.1/旧审计）被错误引用？ | 有。02 与 09 共 4 处引用 V0.5.1（P2-2）；未发现对本轮审计报告的错误引用 |
