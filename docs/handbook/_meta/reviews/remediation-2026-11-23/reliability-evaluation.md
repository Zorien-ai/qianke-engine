# Reliability & Evaluation 批次 P1 修复复核报告（2026-11-23）

> 复核日期：2026-11-23（Asia/Shanghai）
> 批次：`reliability-evaluation`（`docs/handbook/05-reliability-evaluation/`）
> 涉及 P1 任务：`P1-13`、`P1-14`、`P1-15`
> 复核文件：`03-agent-regression-test.md`、`04-agent-benchmark.md`、`10-cicd-canary-release.md`
> 复核性质：**只读复核**。本次只新增本报告，未修改任何文章、配置、代码或数据；未伪造任何测试/Eval 结果。

## 1. 批次、范围、基线与代码快照

### 1.1 批次与范围

| 项 | 内容 |
|---|---|
| 批次 | `05-reliability-evaluation`（10 篇） |
| 本批 P1 任务 | P1-13 修正 CI 门禁描述；P1-14 修正 frozen 数据集门禁；P1-15 修正私有 holdout 状态 |
| 指定复核文件 | `03-agent-regression-test.md`、`04-agent-benchmark.md`、`10-cicd-canary-release.md` |
| 关联参照 | `10-cicd-canary-release.md`（P1-13 要求与其对齐）；同批 `01-agent-evaluation.md`（交叉引用抽查）；其余 7 篇只做交叉引用抽查，不做全文复核 |
| 证据范围 | `.github/workflows/ci.yml`、`scripts/check_eval_v2_gate.py`、`tests/evals/v2/`、`tests/evals/agent/private_holdout/`、`tests/evals/agent/{regression,benchmark,baselines}/`、`tests/evals/agent/compare.py`、`scripts/production_preflight.py`、`docs/e2e/production-preflight.md`、`docs-site/.vitepress/config.mjs`、`docs-site` 构建产物等 |
| 复核依据 | `2026-11-23-p1-fix-tasks.md` 的 P1-13/14/15 验收标准；`2026-11-23-content-quality-audit.md` 与 `audit-2026-11-23/reliability-evaluation.md` 的原始证据与结论 |

### 1.2 基线

- 新基线：`docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md`（`version: 0.5.2`、`updated: 2026-11-23`）。
- 基线错误码勘误已生效：V0.5.2 L656 为 `SQL_VALIDATION_ERROR`；历史稿 V0.5.1 L655 仍保留 `READ_ONLY_VIOLATION`，符合“保留历史、不覆盖”的 M1-01 要求。
- 公开站入口已指向 V0.5.2：`docs-site/.vitepress/config.mjs:9,154`、`docs/handbook/index.md:11`、`docs/handbook/README.md:5,58,88,107`；`config.mjs:122` 将 V0.5.1 排除出 `source` 构建。
- 本复核未发现三篇复核文件引用 V0.5.1 或 2026-11-23 旧审计；旧版本引用问题存在于批次外文章（见 3.3 P2-09）。

### 1.3 代码快照与复核方式

**代码快照（复核时）：**

```text
Git HEAD: 32ad31bc26365e8d0cefe503e6c09cfcd2876eaa
分支:     b-end-2.0-p0
工作区:   git status 共 130 条变更/未跟踪项（复核时点）
```

关键边界：

```text
1. docs/handbook/ 整个目录未被 git 跟踪（?? docs/handbook/）；
2. P1-13 证据脚本 scripts/check_eval_v2_gate.py 未被跟踪（?? scripts/check_eval_v2_gate.py）；
3. P1-14 证据目录 tests/evals/v2/ 未被跟踪（?? tests/evals/v2/）；
4. P1-15 证据目录 tests/evals/agent/private_holdout/ 被 .gitignore:109 忽略。
```

因此：**本报告的结论基于 32ad31bc2636 工作区状态，而不是可复现的提交内容**；仅凭 HEAD 提交无法复核 P1-13/14/15 的证据。该限制单列为 P2-01。

文件 mtime 旁证（仅辅助，不作为 diff 依据）：`03`/`04` 为 2026-11-23 17:50:29，`10` 为 15:40:25；与 P1 任务清单只要求修改 `03`/`04` 相符，`10` 本次未被改动（其已知 P2 因此保留，见 3.3）。

**本次实际执行的只读核验：**

| 操作 | 结果 |
|---|---|
| `git rev-parse HEAD` / `git branch --show-current` | `32ad31bc2636…` / `b-end-2.0-p0` |
| `git status --porcelain` | 130 条；其中 `?? docs/handbook/`、`?? scripts/check_eval_v2_gate.py`、`?? tests/evals/v2/` |
| `git ls-files` / `git check-ignore` | `scripts/check_eval_v2_gate.py` 未跟踪；`tests/evals/agent/private_holdout/` 被忽略 |
| `python scripts/check_eval_v2_gate.py`（不调用 LLM） | `评测门禁：PASS`，exit 0；b_analyst 93.3%、c_guide 100.0%，各 15 条，2 条 manual-pending 仅 WARN |
| JSON 计数 | regression 20 / benchmark 80 / v2 B 15 / v2 C 15 / private_holdout 20（results：total 20、passed 17） |
| v2 数据集 `frozen` 字段 | `b_analyst`、`c_guide` 均为 `false`；gate 仍按 0.80 判定 |
| `baselines/` | 12 份 JSON：v1.5、v1.6、v1.6.1、v1.7、v1.8、v1.8.1、v1.8.2、v1.8.3、v1.9、v1.9.1、v1.9.2、v2.2 |
| 测试文件计数 | `tests/` 根目录 `test_*.py` 126 个；递归 130 个；`pyproject.toml:72 testpaths=["tests"]` 为递归收集 |
| `scripts/production_preflight.py` | 11 个 `checks.append`，成功路径 10 项（`postgres` 为异常兜底，L93-94） |
| `docs/e2e/production-preflight.md` | 记录 10 项 PASS（L32-43） |
| `docs-site/.vitepress/dist` 产物 | 60 篇文章页 + 6 个分类导读页 + 首页/404，共 68 个 HTML；V0.5.2 页面存在、V0.5.1 页面不存在（**仅查看既有产物，未重跑构建**） |
| 固定产物内容抽查 | 17:52:55 构建的 `03`/`04` 页面已包含修复后文字；`01` 页面仍包含旧 `CI 门禁` 表述 |

未执行：全量 `pytest`、真实模型 Eval/Regression/Benchmark、private holdout 重跑、GitHub Actions 触发、`docs-site` 重新构建、生产预检、PG 查询、浏览器/E2E。详见第 5 节。

## 2. P1 任务逐项结论

| 任务 | 结论 | 关键证据 |
|---|---|---|
| P1-13 修正 CI 门禁描述 | **通过**（按任务范围） | `03:121` 已改为“v2 门禁脚本已实现，可手动/按需执行，尚未接入 `.github/workflows/ci.yml`；当前 CI 门禁只有 pytest + 离线评测快照门禁（RAG 快照通过率 ≥ 0.85、题数 ≥ 5）”。`ci.yml` 全文无 `check_eval_v2_gate.py` 调用；仅 `ci.yml` 一个 workflow；本地执行门禁脚本 PASS。与 `10:131,165` 一致。 |
| P1-14 修正 frozen 数据集门禁 | **通过**（按任务范围） | `03:97` 已改为“当前脚本没有实现 frozen 分支，所有全量存档运行都按统一硬阈值判定；‘只对 frozen 硬门禁’仍是设计意图，未在代码中实现”；`03:155` 状态表改为“部分实现 / 冻结集分支未实现”；`03:194` 同步。源码无 frozen 分支，两套数据集 `frozen:false`，仍按 0.80 硬判定（实测 93.3%、100% PASS）。 |
| P1-15 修正私有 holdout 状态 | **通过**（按任务范围） | `04:153` 已改为“已实现 \| `tests/evals/agent/private_holdout/`，20 题；已有归档运行 17/20，本次未重跑”；`04:191` 同步。数据集 20 题、README `Private Holdout v2.3`、`results/private_v1.json` total 20 / passed 17；文章明确“本次未重跑”，未把归档结果写成当前通过。 |

### 2.1 P1-13 详细核验

**修复后原文（`03-agent-regression-test.md:121`）：**

> v2 门禁脚本 `scripts/check_eval_v2_gate.py` 已实现，可手动/按需执行，尚未接入 `.github/workflows/ci.yml`；当前 CI 门禁只有 pytest + 离线评测快照门禁（RAG 快照通过率 ≥ 0.85、题数 ≥ 5）。

**证据核验：**

1. `.github/workflows/ci.yml` 仅包含：`python -m pytest tests/ -q`（L76-77）与内联“Offline eval snapshot gate”（L79-112，读取 `tests/eval_results_llm.json`，`total ≥ 5`、`pass_rate ≥ 0.85`）；全文无 `check_eval_v2_gate.py`。
2. `.github/workflows/` 下只有 `ci.yml` 一个 workflow（目录枚举）。
3. 本次只读执行 `python scripts/check_eval_v2_gate.py`：exit 0，`评测门禁：PASS`；说明“可手动/按需执行”成立（未调用模型）。
4. `10-cicd-canary-release.md:131` 写“CI 未执行 v2 评测门禁脚本……ci.yml 只跑 pytest 与 RAG 离线快照门禁”；`:165` 写“Eval v2 门禁脚本 \| 已实现（未接入 ci.yml）”。与 `03` 一致。
5. `tests/evals/v2/README.md:41,53` 与该结论存在“源文档”层面冲突（README 仍写“CI 也跑这个”“CI 门禁”），但这属于源文档旧结论，不是 `03` 的表述错误（见 P2-08）。

**结论：** P1-13 在 `03` 的指定位置已按代码事实修复，不是只改措辞；它承认“脚本实现但未接入 CI”这一真实状态。**但同批 `01-agent-evaluation.md:118,156,198` 仍保留相反的 CI 门禁旧结论，P1-13 的批内交叉引用未收口**（见 NEW-P1-01）。

### 2.2 P1-14 详细核验

**修复后原文：**

- `03:97`：当前脚本没有实现 frozen 分支，所有全量存档运行都按统一硬阈值判定；“只对 frozen 硬门禁”仍是设计意图，未在代码中实现。
- `03:155`：`v2 门禁（全量运行 + 阈值；冻结集分支未实现） | 部分实现 | scripts/check_eval_v2_gate.py；未接入 ci.yml`
- `03:194`：`v2 门禁尚未接入 CI、frozen 分支未实现……`

**证据核验：**

1. `scripts/check_eval_v2_gate.py`：`DEFAULT_MIN_PASS = 0.8`（L40）；`check_snapshots()`（L65-123）逐条读取存档运行，按 `latest[agent:suite]` 取最新全量运行后直接 `rate < min_pass` 判定失败（L111-113），代码中**没有**读取/判断 `frozen` 的分支；`frozen` 仅出现在函数 docstring（L68）。
2. 两套 v2 数据集 `b_analyst.regression.v1.json`、`c_guide.regression.v1.json` 均为 15 条、`frozen: false`；对应存档运行 93.3%、100%，在 0.80 阈值下 PASS——证明“未 frozen 也硬判定”的行为。
3. 状态表不再把“冻结集 + 全量运行 + 副作用回收”整体写成“已实现”，符合 P1-14 验收“状态表不再写已实现；文中不再宣称 frozen 分支存在”。
4. 源脚本 docstring 仍写“只有 `frozen` 的数据集才做硬门禁”（L67-70），与代码行为不符；这是本次修复的“根因残留”，见 P2-08（不改变 P1-14 文章结论，但会持续误导代码读者）。

**表述精度问题：** `03:97` 的“所有全量存档运行都按统一硬阈值判定”略宽于代码行为——门禁实际只对**每个 `agent:suite` 的最新一次全量运行**做硬判定，历史全量运行被排除（L79-95）。当前仓库每个 key 只有一次全量运行，故无实际误差；建议改为“最新全量存档运行”以免被未来多轮运行放大（见 P2-02）。

### 2.3 P1-15 详细核验

**修复后原文：**

- `04:153`：`独立私有 holdout 集 | 已实现 | tests/evals/agent/private_holdout/，20 题；已有归档运行 17/20，本次未重跑`
- `04:191`：`私有 holdout 已有 20 题与 17/20 归档结果，尚未建立外部独立第三方 holdout。`

**证据核验：**

1. `tests/evals/agent/private_holdout/dataset.v1.json`：`tasks` 数组 20 条；`version: private-holdout-v2.3`；分类含 calculator / execute_sql / multi_tool / negative / rag_search。
2. `tests/evals/agent/private_holdout/README.md`：`# Private Holdout v2.3`，20 题。
3. `tests/evals/agent/private_holdout/results/private_v1.json`：`summary.total=20`、`passed=17`、`task_success_rate=0.85`、`business_correctness_rate=0.85`。
4. `tests/evals/agent/KNOWN_ISSUES.md:24-71`：说明 private holdout 20 题、构建期未运行 Agent；首跑题目构造有 bug 已废弃，修复后重跑得到有效基线（85%/85%/100%/100%/93.5%/50%），与 `private_v1.json` 一致。
5. 旧 `tests/evals/agent/holdout/baseline_v2.0.md` 所记 20 题 holdout 已在 v2.2 退役并入公共 Benchmark；当前 `private_holdout` 是重建后的新集合。文章 `04:191` 用“尚未建立外部独立第三方 holdout”区分“已有内部私有 holdout”与“外部第三方 holdout”，口径清楚。
6. 本次**未重跑**私有 holdout（需真实模型 Key），因此只核验归档 JSON 与 README；文章中“本次未重跑”与复核边界一致，未伪造“当前通过”。

**遗留限制：**

- `private_holdout/` 被 `.gitignore:109` 忽略，`KNOWN_ISSUES.md:36` 也明确“已加入 .gitignore，不进入公共仓库”。因此“已实现”只能在本地工作区复核，公开仓库读者无法访问该证据；文章未注明“私有、不入库”（见 P2-01）。
- `04` 的 frontmatter `implementation_status` 仍为“已实现 + 部分实现 + 规划中”，而 P1-15 修正后正文状态表已无“部分实现/规划中”行（见 P2-03）。

## 3. 新发现问题

### 3.1 P0

无。

### 3.2 P1

#### NEW-P1-01 同批 `01-agent-evaluation.md` 仍把 v2 门禁写成 CI 门禁，与修复后的 `03`/`10` 直接矛盾

- 位置：
  - `docs/handbook/05-reliability-evaluation/01-agent-evaluation.md:118`：

    `python scripts/check_eval_v2_gate.py --min-pass 0.80                    # CI 门禁`

  - 同篇 `:156`：`| CI 评测门禁 | 已实现 | scripts/check_eval_v2_gate.py、.github/workflows/ci.yml` 离线快照门禁 |`（原文两处脚本名均带反引号）
  - 同篇 `:198`：`Qianke 已具备 v1/v2 评测与 CI 门禁；……`
- 事实：`.github/workflows/ci.yml` 全文没有 `check_eval_v2_gate.py` 调用；修复后的 `03:121` 明确写“尚未接入 ci.yml”；`10:131,165` 也写“CI 未执行 v2 评测门禁脚本”“未接入 ci.yml”。
- 影响：同批两篇（`03`/`10`）与 `01` 对 CI 实际行为给出相反结论；`01` 的行文与 P1-13 修复前 `03` 的错误类型相同（把“已实现/设计意图”写成“CI 已接入”）。
- 历史定级：批审计已将 `01` 的“CI 评测门禁”行列为 **P2**（`audit-2026-11-23/reliability-evaluation.md:39,88`），P1-13 任务清单只指定修改 `03`；但修复规则第 3 条要求“修复后必须检查关联文章，避免一篇修好、另一篇保留旧结论”，本批未将 `01` 一并收口。
- 复核定级：**P1**（修复后批内直接矛盾；同类错误在 `01` 仍会误导读者；“已进入 17:52 构建产物”，会随公开站发布）。
- 建议：把 `01:118` 注释改为“本地/手动门禁脚本”，`:156` 行改为“门禁脚本已实现；未接入 ci.yml；当前 CI 门禁为 RAG 离线快照门禁”，`:198` 同步与 `03`/`10` 对齐。

### 3.3 P2

| 编号 | 位置 | 问题 | 证据 | 是否本次修复引入/加剧 |
|---|---|---|---|---|
| P2-01 | 三篇 P1 任务的证据源 | “已实现/可手动执行”的证据不在提交快照中，公开仓库无法复现 | `git status`：`docs/handbook/`、`scripts/check_eval_v2_gate.py`、`tests/evals/v2/` 均未跟踪；`tests/evals/agent/private_holdout/` 被 `.gitignore:109` 忽略，`KNOWN_ISSUES.md:36` 明确“不进入公共仓库” | 既有结构性问题；P1-13/14/15 都在其影响下，建议发布前处理 |
| P2-02 | `03:97` | “所有全量存档运行都按统一硬阈值判定”范围略大 | 门禁 `check_snapshots()` 仅对 `latest[agent:suite]` 最新一次全量运行硬判定（L79-95）；历史全量运行不判定 | **P1-14 修复措辞引入**（程度轻） |
| P2-03 | `04:9` 与正文 `04:143-154` | frontmatter `implementation_status: 已实现 + 部分实现 + 规划中` 与正文状态集合不一致；P1-15 将唯一“规划中”行改为“已实现”后更明显 | 正文状态表只剩“已实现/不适用”，无“部分实现/规划中”行；批审计 L35 已提示元数据与正文对齐 | **P1-15 修复加剧**（正文已变、frontmatter 未同步） |
| P2-04 | `03:119` | compare 指标名称列 11 项，代码 `METRICS` 为 12 项 | `tests/evals/agent/compare.py:12-24` 含 `total_tokens`、`avg_tokens_per_task` 两项 token 指标；文章未写“12 项” | 既有已知 P2，未修（不在 P1 范围） |
| P2-05 | `04:40` | “126 个 `test_*.py`”未注明计数口径 | `tests/` 根目录 126，递归 130；`pyproject.toml:72 testpaths=["tests"]` 使 CI 递归收集 130 | 既有已知 P2，未修 |
| P2-06 | `10:129` | “`scripts/production_preflight.py` 11 项关键证据一键检查” | 脚本 11 个 `checks.append` 中 `postgres` 为异常兜底（L93-94），成功路径 10 项；`docs/e2e/production-preflight.md:32-43` 记录 10 项 PASS | 既有已知 P2，未修 |
| P2-07 | `10:126` | “`ops/cloudflared.yml` 固定域名入口（模板不入库）”表述反了 | 真实配置 `ops/cloudflared.yml` 被 `.gitignore:115` 忽略；仓库内保留并跟踪的是 `ops/cloudflared.example.yml` 模板 | 既有已知 P2，未修 |
| P2-08 | `scripts/check_eval_v2_gate.py:1-19,65-70`、`tests/evals/v2/README.md:41,53` | 代码侧源文档仍保留“CI 快照门禁/CI 做两件事”“只有 frozen 数据集才做硬门禁”“CI 也跑这个/CI 门禁”等旧结论，与代码实际行为、与修复后的文章都冲突 | 脚本 docstring 写“CI 快照门禁”“CI 做两件事”；`check_snapshots` 实际无 frozen 分支；v2 README 仍称 CI 会跑 | 既有根因；P1-13/P1-14 只修了文章，未收口源文档；后续重新生成文档可能回流 |
| P2-09 | 批次外多篇 | 仍用 V0.5.1 表述/链接指向 V0.5.2（或引用不可公开访问的 V0.5.1 路径），与“V0.5.2 为新基线、V0.5.1 不进入公开站”不一致 | `02-agent-vs-enterprise-agent.md:518,616,689`（689 链接文字写 V0.5.1、目标为 v0.5.2）；`03-agent-runtime.md:419,475`；`04-agent-orchestrator.md:325`；直接引用 v0.5.1 路径：`02-enterprise-governance/07-prompt-injection-defense.md:48`、`06-architecture-practice/02-architecture-design-method.md:157`、`09-technical-debt.md:112,159,211`、`10-enterprise-architecture-case.md:210` | 批次外既有问题；`agent-architecture.md` 批次报告 P2-1 已同步记录 02/03/04 的旧版本标签，建议合并处理；本批三篇复核文件未发现 V0.5.1 引用 |

补充说明：

- P2-04～P2-07 是 2026-11-23 批审计已记录的 P2。本次复核确认它们在本次 P1 修复后仍然存在；P1 清单明确不纳入这些事项，因此不计为 P1 任务失败，但应在批次“条件通过”中列明。
- P2-08 是 P1-13/P1-14 的“源文档”根因：文章已按代码事实修正，但脚本自身 docstring 与 v2 README 仍写旧结论。若后续有人依据脚本文档再改文章，会重新引入 P1-13/P1-14 类错误。
- P2-09 不属于本批三篇文件，列出以满足“旧版本被错误引用”的检查要求；建议在 agent-architecture / architecture-practice 批次或 V0.5.2 基线收口时统一处理。

## 4. 跨篇一致性检查

| # | 检查项 | 检查结果 | 证据 |
|---|---|---|---|
| 1 | v2 门禁脚本是否在 CI 执行 | **不一致（P1）**：`03`/`10` 为“未接入”；`01` 为“CI 门禁/已实现” | `03:121,155,194`；`10:131,165`；`ci.yml` 无调用；`01:118,156,198` |
| 2 | 当前 CI 实际门禁内容 | 一致：pytest + RAG 离线快照门禁（≥0.85、≥5） | `ci.yml:76-112`；`03:121`；`02:127`；`10:131` |
| 3 | “只对 frozen 硬门禁”实现状态 | `03` 与代码一致：未实现，所有全量运行仍硬判定；未发现其他文章宣称已实现 | `03:97,155,194`；gate 源码无 frozen 分支；数据集 `frozen:false` |
| 4 | 私有 holdout 状态 | `04` 与工作区文件/`KNOWN_ISSUES.md` 一致：内部 20 题 + 17/20 归档；未发现相反文章 | `04:153,191`；`private_v1.json`；`KNOWN_ISSUES.md:24-71`；`docs/agent-design-current-vs-target.md:31` |
| 5 | Regression 20 / Benchmark 80 | 三篇与数据集一致 | `03:85,151`；`04:42,145`；数据集计数 20/80 |
| 6 | 生产预检项数 | `10` 仍写 11 项；`docs/e2e` 记录 10 项；批内 06/07/09 同错 | `10:129`；`production_preflight.py:62-120`；`docs/e2e/production-preflight.md:32-43` |
| 7 | 与 V0.5.2 基线的版本/错误码口径 | 三篇复核文件无旧错误码、无 V0.5.1 引用；基线 `SQL_VALIDATION_ERROR` 已生效 | V0.5.2 L656；V0.5.1 L655 仅历史保留 |
| 8 | 公开站入口/构建产物 | 入口已指向 V0.5.2；既有 dist 产物含 V0.5.2、不含 V0.5.1；17:52:55 构建产物已包含 `03`/`04` 修复文本；`01` 的旧 CI 门禁表述也已进入产物 | `config.mjs:9,122,154`；dist 目录与页面内容抽查（未重跑构建） |
| 9 | 与 `10` 的 P1-13 对齐 | 一致：`03` 的“脚本已实现、未接入 ci.yml、CI 仅 pytest+快照”与 `10` 相同 | `03:121`；`10:131,165` |

## 5. 未核验项

以下项目本次**未运行/未核验**，不能视为通过：

```text
1. 全量 pytest（未执行 `python -m pytest tests/ -q`；130 个收集用例是否全绿未核验）；
2. 真实模型 Regression / Benchmark / Agent Eval（未调用 LLM，未产生新分数）；
3. private holdout 17/20 的当前版本重跑（文章已写“本次未重跑”，本次仅核验归档 JSON）；
4. `scripts/check_eval_v2_gate.py` 的 CI 接入效果（未触发 GitHub Actions；仅本地只读执行 PASS）；
5. GitHub Actions 行为（无远端运行环境；`ci.yml` 结论来自全文静态阅读）；
6. `docs-site` 重新构建（未执行 `npm run build`；只检查既有 dist 与 build-check.log，不能声称本次构建通过）；
7. 60 篇公开路由的浏览器可访问性/交互（仅枚举 dist HTML 文件，未做浏览器验证）；
8. `scripts/production_preflight.py` 实际运行、`/ready`、`/metrics`、Prometheus/Grafana/Alertmanager；
9. PostgreSQL 查询与 `ae2_*` 实际入库（未连接 PG）；
10. 真实 LLM 成本/token/延迟数据、SLO、并发与故障注入；
11. 批内其余 7 篇（02、05–09）的 P2 修复情况（仅交叉引用抽查 01/02 相关句）；
12. 外部链接可达性。
```

## 6. 批次结论

**结论：条件通过。**

判定说明：

| 维度 | 结论 |
|---|---|
| P1-13 | 通过（`03` 已按代码事实修正；`ci.yml` 无调用、本地门禁脚本可执行、与 `10` 一致） |
| P1-14 | 通过（`03` 已明确 frozen 分支未实现；代码/数据集/实测阈值行为一致；状态表不再写“已实现”） |
| P1-15 | 通过（`04` 已改为“已实现 + 20 题 + 17/20 归档 + 本次未重跑”；目录、README、结果 JSON、KNOWN_ISSUES 一致） |
| 修复后新增/暴露问题 | 1 个 P1：`01-agent-evaluation.md` 仍把 v2 门禁写成 CI 门禁，与 `03`/`10`/`ci.yml` 矛盾（NEW-P1-01） |
| 其余问题 | 9 个 P2：证据可复现性、`03` frozen 表述范围、`04` frontmatter、既有 P2 数字/表述、源文档旧结论、批次外 V0.5.1 引用 |
| 未核验 | 见第 5 节（未运行全量测试/真实 Eval/构建/CI/PG 等） |

**通过/发布条件（按优先级）：**

```text
1. 收口 NEW-P1-01：修改 01-agent-evaluation.md:118/156/198，使其与 03/10/ci.yml 一致；
2. 修正同批已知 P2：03 compare 指标 11→12；04 测试计数注明 126/130 口径；
   10 生产预检 11→10；10 cloudflared 真实配置/模板表述；04 frontmatter 状态集合与正文对齐；
3. 收口源文档 P2-08：更新 check_eval_v2_gate.py docstring 与 tests/evals/v2/README.md，
   删除“CI 已接入/只有 frozen 硬门禁”的旧结论；否则后续文档再生成会回流；
4. 发布前处理 P2-01：将 P1-13/14 证据脚本/数据集纳入提交，或在文章中注明
   “私有 holdout 不入库、脚本/评测数据为工作区证据”，保证“已实现”可复核；
5. 发布前按门禁重跑：全量 pytest + docs-site build；本次均未运行，不得以既有日志替代。
```

**最终判断：**

- 若验收口径**只针对 P1-13、P1-14、P1-15 三个指定文件**：三项均按代码事实修复，可以判**通过**；
- 若验收口径包含**同批次跨篇一致性与证据可复现性**（本报告采用的口径）：批次为**条件通过**，其中 NEW-P1-01 是唯一的 P1 级阻塞项，其余为 P2/未核验项；
- 未发现 P0，未发现三个复核文件中的 P1 修复被写成“未实现的新能力”或伪造测试结果。

---

> 复核边界说明：本报告为只读审计产物；除本文件外未修改任何文章、配置、代码或数据。所有“已核验”仅指本报告第 1.3 节列出的只读操作与静态证据；所有“未核验”均已在第 5 节列明，不构成“已通过”结论。
