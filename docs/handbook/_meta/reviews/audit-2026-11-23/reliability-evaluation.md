# Reliability & Evaluation 批次 · 内容质量审计报告

> **批次：** `05-reliability-evaluation`（10 篇）
> **审计日期：** 2026-11-23
> **基线文章：** `docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md`（V0.5.1；代码快照 `32ad31bc2636`，分支 `b-end-2.0-p0`）
> **审计范围：**
> 1. `docs/handbook/05-reliability-evaluation/01-agent-evaluation.md`
> 2. `docs/handbook/05-reliability-evaluation/02-agent-automated-testing.md`
> 3. `docs/handbook/05-reliability-evaluation/03-agent-regression-test.md`
> 4. `docs/handbook/05-reliability-evaluation/04-agent-benchmark.md`
> 5. `docs/handbook/05-reliability-evaluation/05-agent-observability.md`
> 6. `docs/handbook/05-reliability-evaluation/06-logs-metrics-tracing.md`
> 7. `docs/handbook/05-reliability-evaluation/07-sre-slo.md`
> 8. `docs/handbook/05-reliability-evaluation/08-retry-circuit-breaker-degradation.md`
> 9. `docs/handbook/05-reliability-evaluation/09-failure-recovery-dr.md`
> 10. `docs/handbook/05-reliability-evaluation/10-cicd-canary-release.md`
> **审计标准：** A 技术准确性；B 实现状态标注一致性；C 证据真实性。辅助检查：12 个二级章节结构、frontmatter、明显自相矛盾、过时状态。
> **结论统计：** 通过 1 篇（08）· 条件通过 7 篇（01、02、05、06、07、09、10）· 不通过 2 篇（03、04）。
> **问题统计：** P0 = 0，P1 = 3（03×2、04×1），P2 = 16。

## 审计方法与边界

- 只做审计，未修改任何文章正文、配置或代码；本报告是本次审计唯一新增文件。
- 进行了静态阅读与交叉核对：`AGENTS.md` 第 10、12、13、18、19 节，`docs/agent.md`，`docs/agent-design-current-vs-target.md`，相关 `src/`、`tests/`、`docs/`、`scripts/`、`ops/`、`.github/` 文件；数据集/结果 JSON 计数；git 快照（`git rev-parse`/`git log`/`git status`）。
- 实际执行过的只读命令/脚本：文件枚举与计数、JSON 解析计数、`python scripts/check_eval_v2_gate.py`（不调用 LLM 的离线门禁，输出 `评测门禁：PASS`）。
- **未执行：** 全量 `pytest`、浏览器/E2E、PostgreSQL 连接与查询、真实模型 Eval、`scripts/production_preflight.py`、备份/恢复脚本。文章正文中的"已核验/全部 PASS"等表述若依赖这些运行，本报告按"未核验"处理。
- "未核验"表示本次无法用仓库证据或可执行命令确认，不直接等同于"错误"；已在问题列表中区分"与代码不一致"和"无法核验"。

## 批次级结论

### 结构与元数据

- 10 篇均为 **12 个二级章节**，编号 1–12 连续一致（标题命名一致：为什么/基本机制/总体架构/关键设计/工程实现/企业级要求/方案对比/Qianke Engine 实践/评估验收/常见误区/总结/延伸阅读）。
- frontmatter 10 篇字段齐全（title、description、section、section_order、order、slug、doc_status、implementation_status、version、updated、reading_minutes、prerequisites、tags、related），`updated: 2026-11-23` 一致；与 `index.md` 的 10 篇清单一致。
- 轻微元数据不一致（不构成独立问题）：01 与 04 的 `implementation_status` 声明含"部分实现"，但正文"Qianke Engine 实践"表未出现"部分实现"行；建议 frontmatter 与正文状态集合对齐（01 的"CI 评测门禁"实际更接近部分实现，见该篇 P2）。

### 跨篇一致性

1. **Eval v2 门禁的 CI 接入状态互相冲突。** 01 §8 写"CI 评测门禁：已实现"；03 §5 写"CI 门禁有两处：`scripts/check_eval_v2_gate.py` …；`.github/workflows/ci.yml` …"；10 §5 明确写"CI 未执行 v2 评测门禁脚本……当前 `ci.yml` 只跑 pytest 与 RAG 离线快照门禁"。**以 10 与 `ci.yml` 为准**（本次已核实 `ci.yml` 全文，无 `check_eval_v2_gate.py` 调用；`tests/evals/v2/README.md` 自称"CI 也跑这个"与 ci.yml 不符）。01、03 需向 10 收口。
2. **`production_preflight.py` 的检查项数被 06/07/09/10 统一写成"11 项"。** 脚本正常成功路径为 **10 项**（11 个 `checks.append` 中 1 个是 DB 异常兜底的 `postgres`）；`docs/e2e/production-preflight.md` 记录的 PASS 清单也是 10 项。四篇应统一改为 10 项（或写明"10 项 + 1 个异常兜底"）。
3. **私有 holdout 的状态与仓库事实相反（04）。** `tests/evals/agent/private_holdout/` 已有 20 题的 `dataset.v1.json`、`README.md`（"Private Holdout v2.3"）、`results/private_v1.json`（20 题、17 通过）；04 §8 却写"规划中 | 仓库内未见已填充的私有 holdout 数据"。
4. **测试文件计数口径不一致（02、04）。** 仓库 `tests/` 根目录 `test_*.py` 为 126 个，递归（含 `tests/evals/v2/` 4 个）为 **130 个**；`pyproject.toml` 的 `testpaths=["tests"]` 会递归收集，故"126"若不注明口径会与 CI 实际收集数不符。
5. **03 的冻结门禁描述与代码不一致。** `check_eval_v2_gate.py` 未实现"只对 frozen 数据集硬门禁"的分支；两套 v2 数据集均为 `frozen: false`，但门禁仍按 0.80 硬阈值判定（本次运行实测：93.3%、100% 均 PASS；`frozen` 仅出现在数据集 JSON 与脚本 docstring/入库字段中）。

### 统计

| 结论 | 篇目 | 数量 |
|---|---|---:|
| 通过 | 08 | 1 |
| 条件通过 | 01、02、05、06、07、09、10 | 7 |
| 不通过 | 03、04 | 2 |

| 严重级别 | 数量 | 分布 |
|---|---:|---|
| P0 | 0 | — |
| P1 | 3 | 03×2、04×1 |
| P2 | 16 | 01×4、02×1、03×1、04×1、05×1、06×2、07×2、09×2、10×2 |

---

## 1. `01-agent-evaluation.md`

### 结论

**条件通过。**

### 实现状态声明是否成立

基本成立。frontmatter 的"已实现 + 部分实现 + 已设计 + 规划中"与 §8 状态表大体吻合：v1/v2 评测代码、`ae2_*` 指标入库、客观/人工分离、副作用回收、CI 快照门禁均有仓库证据；"Agent 级 LLM Judge / groundedness 已设计"、"线上抽样裁判与 bad case 回流 规划中"、"实时成本预算 规划中"也与 README、蓝图文档一致。需修正 2 处状态表述："CI 评测门禁"和"成本看板"。

### 证据核验结果（已核验）

- 数据集条数：`tests/evals/agent/regression/dataset.v1.json` = 20 条，`benchmark/dataset.v1.json` = 80 条（JSON `tasks` 计数）。
- 代码结构：`tests/evals/agent/{runner,evaluator,compare}.py`；`tests/evals/v2/core/{contracts,evaluators,runner,storage,report,adapter}.py`；`agents/b/adapter.py`、`agents/c/adapter.py`；`datasets/b_analyst.regression.v1.json` 与 `c_guide.regression.v1.json` 各 15 条。
- 门禁脚本：`scripts/check_eval_v2_gate.py` 默认 `--min-pass 0.80`，跳过 `total < dataset_case_count` 的子集运行，`cleanup.ok is False` 判失败；本次只读执行输出 `评测门禁：PASS`（b_analyst 93.3%、c_guide 100%，各 15 条，2 条 manual-pending 仅告警）。
- `ae2_*` 表：`src/rag_demo/agent_eval_v2_store.py` 定义 `ae2_agent / ae2_dataset / ae2_case / ae2_run / ae2_case_result / ae2_metric`；`src/rag_demo/api/agent_eval_v2.py::_persist` 在一次 API 运行结束后写入，`ae2_run.run_id` 与 `runs/<run_id>/` 关联。
- RAG 离线评测快照 `tests/eval_results_llm.json`：`total=33`、`passed=30`、`pass_rate=0.909090…`（开始时间 2026-11-11，judge_model `deepseek-chat`）。
- `scripts/run_eval.py`：LLM-as-a-Judge，`parse_judge_json` 严格解析，失败记 `judge_error` 而非伪造分数。
- Agent 级 LLM Judge 状态：`tests/evals/agent/README.md` 原文"这版是确定性评测，不引入 LLM Judge；后续再增加 groundedness / judge。"
- 无合成总分：`tests/evals/v2/test_core_runner.py` 第 205、295 行断言 summary 与 Markdown 中均无 `total_score`。
- 副作用回收：`tests/evals/v2/agents/c/adapter.py::teardown` 返回 `ok = not pending`；CLI 与门禁对 `cleanup.ok is False` 判失败。
- `docs/评测落地方案.md` 存在（线上抽样 + 数据回流蓝图），与"规划中"一致。

### 问题列表

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §8 状态表"CI 评测门禁"行 | "CI 评测门禁 \| 已实现 \| `scripts/check_eval_v2_gate.py`、`.github/workflows/ci.yml` 离线快照门禁" | v2 门禁脚本未接入 `ci.yml`；`ci.yml` 实际只有 pytest 与内联 RAG 离线快照门禁。该行易被读成"v2 门禁已在 CI 执行"，且与同批 10 的明确表述冲突 | 改为"门禁脚本已实现；尚未接入 ci.yml；当前 CI 门禁为 RAG 离线快照"，与 10 对齐 |
| P2 | §5 | "v2 把运行结果写 PostgreSQL `ae2_*` 表……并与落盘 JSON 通过 `run_id` 关联" | 只有 API 任务路径（`api/agent_eval_v2.py::_persist`）写 `ae2_*`；`tests/evals/v2/cli.py run` 只落盘 JSON，不入库 | 写明"API 触发运行入库；CLI 运行仅落盘" |
| P2 | §8 末行 | "实时成本预算与全量看板 \| 规划中 \| 仅有 token 记录与单价配置" | 状态偏旧/偏低：`ai_monitor.py` 已有成本聚合与用量/钱包/发票查询，`/api/billing/*`、`web/src/views/Billing.vue`、监控中心"租户与计费"tab 均已存在；缺的主要是"实时成本预算/配额强制执行" | 拆为"成本看板：已实现；实时成本预算：规划中" |
| P2 | §9 | "'评测代码与门禁可运行'已核验" | 未附命令/输出索引；完整 runner 需真实模型 Key，本次无法复核全量运行，该"已核验"范围大于可核验证据 | 补证据索引（命令 + 结果），或限定为"门禁/契约脚本可运行"，runner 标注"需按当次运行核验" |

### 未核验项

- 真实模型全量 Eval 复跑（需要 `DEEPSEEK_API_KEY`，本次未执行）。
- `ae2_*` 实际 PostgreSQL 入库（本次未连接 PG，仅核验代码与测试存在）。
- A 端人工标注页面闭环（未做浏览器验证）。
- "评测代码可运行"中完整 runner 部分（仅核验门禁脚本可执行）。

### 一句话总评

评测主线证据最扎实的一篇，但"CI 门禁"与"成本看板"两处状态落后于代码，修正后可判通过。

---

## 2. `02-agent-automated-testing.md`

### 结论

**条件通过。**

### 实现状态声明是否成立

成立。pytest 体系、Tool Contract/权限/状态机测试、幂等/超时/隔离测试、运维探针、日志 PII、安全响应头、PG 租户隔离、CI 自动执行均有代码与文件证据；浏览器 E2E 未接入 CI、Live Eval 默认 skip 的"部分实现"、故障注入/覆盖率门禁"规划中"也如实标注。唯一需修正的是测试文件计数口径。

### 证据核验结果（已核验）

- 夹具示例：§4.1 引用的 `tests/test_ops.py::c_store` 与真实代码逐行一致（`QIANKE_C_END_DB`、`monkeypatch.setattr(store, "_DB_PATH", None)`、`store.init()`、`sa_store.init()`）。
- 测试文件：`tests/` 根目录 `test_*.py` = **126** 个；递归（含 `tests/evals/v2/test_*.py` 4 个）= **130** 个；`pyproject.toml` `testpaths=["tests"]` 递归收集。
- §5 列出的测试文件全部存在：`test_agent_architecture.py`、`test_agent_execution_safety.py`、`test_agent_checkpoint.py`、`test_ops.py`、`test_logging_pii.py`、`test_security_headers.py`、`test_tenant_isolation_pg.py`、`tests/evals/v2/test_core_*.py`。
- `test_ops.py` 断言 `/ready` 四项（`control_store`、`superagent_store`、`queue`、`merchant_store`）与 `/metrics` 含队列/工作项/审批/租户指标。
- CI：`.github/workflows/ci.yml` 为 push/PR 到 main + `workflow_dispatch`；`permissions: contents: read`；`concurrency` 同 ref 取消；`ubuntu-latest`、`timeout-minutes: 20`；`uv 0.12.5` + Python 3.12；显式安装测试依赖并注释"不要用 uv sync（torch 指向 Windows wheel）"；`python -m pytest tests/ -q`；假 Key `sk-ci-placeholder`。
- Live Eval 默认 skip：`tests/test_agent_write_action_live.py` 仅在 `RUN_WRITE_ACTION_LIVE_EVAL=1` 且有 Key 时执行。
- 无覆盖率/变异测试门禁：`pyproject.toml` 无 coverage 配置、`ci.yml` 无覆盖率步骤；tests 中未检出混沌/故障注入实现。

### 问题列表

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §8 状态表 | "pytest 测试体系 \| 已实现 \| `tests/` 下 126 个 `test_*.py` 文件" | 递归计数为 130（`tests/evals/v2/test_*.py` 4 个也属 pytest 用例，CI 会收集）；"tests/ 下"的 126 与 CI 实际收集数不一致，且本篇 §5 自己列出了这 4 个文件 | 改为"tests/ 根目录 126 个；含 tests/evals/v2 共 130 个"，或按 pytest 收集数写明口径 |

### 未核验项

- 全量 `pytest` 是否通过（本次未运行 `tests/`）。
- `docs/e2e/` 中浏览器验收记录未逐份复跑复核。
- "故障注入/混沌测试未见实现"为检索结论（未做运行时验证）。

### 一句话总评

与代码高度一致的一篇，仅测试文件计数需注明口径。

---

## 3. `03-agent-regression-test.md`

### 结论

**不通过。**

### 实现状态声明是否成立

部分不成立。Regression 20、共用 runner/报告、12 份基线 JSON、compare 工具、v2 B/C 各 15 条回归集、子集跳过、0.80 阈值、默认产物路径均有证据；但**"CI 门禁有两处（含 v2 门禁脚本）"与"只对 frozen 数据集做硬门禁"两处实现状态不成立**，均会误导读者对门禁实际行为的判断。

### 证据核验结果

已核验：

- `regression/dataset.v1.json` = 20 条；`compare.py` 读取 `baselines/<version>.json`，`baselines/` 下 v1.5–v2.2 共 12 份 JSON；`compare.py` 支持 `--json`，指标列表 12 项。
- `tests/evals/v2/datasets/` 的 B/C regression 各 15 条。
- `check_eval_v2_gate.py`：默认 `DEFAULT_MIN_PASS = 0.8`；`metadata.dataset_case_count` 与 `total` 比较跳过子集运行；本次运行输出 93.3%/100% PASS。
- 默认产物：`runner.py` 中 regression/benchmark/holdout 的 results/reports 路径与文章一致；支持 `--only/--limit/--validate-only`。
- `ci.yml` 仅包含 `pytest tests/ -q` 与内联 RAG 离线快照门禁（读取 `tests/eval_results_llm.json`，`total ≥ 5` 且 `pass_rate ≥ 0.85`）；无任何 `check_eval_v2_gate.py` 调用。
- `check_eval_v2_gate.py` 源码中没有 frozen 分支；`frozen` 仅出现在数据集 JSON（两套均为 `false`）与 `api/agent_eval_v2.py` 的入库字段中；门禁对全部最新全量存档运行统一执行 `rate < min_pass` 硬判定。

未核验：

- v1.5–v2.2 历史基线的具体分数（本次未逐份复跑模型）。
- `docs/e2e/` 中回归记录的真实运行细节。

### 问题列表

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | §5 | "CI 门禁有两处：`scripts/check_eval_v2_gate.py` 做数据集契约 + 归档运行阈值（默认 0.80）；`.github/workflows/ci.yml` 做 pytest + 离线评测快照门禁" | v2 门禁脚本未接入 CI：`ci.yml` 全文无 `check_eval_v2_gate.py` 调用，只有 pytest 与 RAG 快照门禁。同批 10 明确写了"CI 未执行 v2 评测门禁脚本"，两篇直接冲突 | 改为"v2 门禁脚本已实现，可手动/按需执行，尚未接入 ci.yml；当前 CI 门禁只有 RAG 离线快照"，与 10 对齐 |
| P1 | §4.3、§8 状态表 | "并只对 `frozen` 数据集做硬门禁，正在迭代的集合只告警不卡死"；"v2 门禁（冻结集 + 全量运行 + 副作用回收） \| 已实现" | 门禁代码无 frozen 分支；当前两套数据集 `frozen: false` 仍被 0.80 硬阈值判定（本次运行 93.3%/100% PASS）。"只对 frozen 硬门禁"仅存在于脚本 docstring 与数据集字段，未在代码中实现 | 修正为"冻结门禁仍是设计意图（代码未实现）；当前对所有全量存档运行统一硬门禁"，或补实现后再标"已实现" |
| P2 | §5 | "对比字段包括任务成功率、业务正确性、工具策略合规、工具选择、工具执行、错误恢复、平均步数、平均工具调用、平均耗时、token 与估算成本" | `compare.py` 的 `METRICS` 为 12 项，其中 token 分为 `total_tokens` 与 `avg_tokens_per_task` 两项；正文列了 11 个名称 | 改为"12 项指标（含 total_tokens / avg_tokens_per_task 两项 token 指标）" |

### 未核验项

- 历史基线分数、当前 Regression 20 的真实运行结果（未跑模型）。
- 线上流量回放式回归（文章已标"规划中"，未见实现）。
- 失败自动分诊（文章已标"规划中"）。

### 一句话总评

回归方法论与大部分证据成立，但把"脚本存在/设计意图"写成"CI 已接入/已实现"，需修正后才能通过。

---

## 4. `04-agent-benchmark.md`

### 结论

**不通过。**

### 实现状态声明是否成立

大部分成立，但**"独立私有 holdout 集：规划中"与实际相反**：仓库中已存在私有 holdout 数据集、README 与已归档运行结果，且旧 20 题 holdout 在 v2.2 已退场并明确"下一版需重建新的 private holdout"——新 private holdout 已建成并被运行。该行属于明确的实现状态误标与证据失实。

### 证据核验结果

已核验：

- `benchmark/dataset.v1.json` = 80 条，分类 5 类：`calculator / execute_sql / multi_tool / negative / rag_search`（与 §4.2 一致）。
- 出题与评审记录：`benchmark/builder_notes.md`、`review_evaluator*.md`、`review_business*.md`、`baseline_v1.6.md … baseline_v2.2.md`、`baselines/*.json` 均存在；`compare.py` 12 项指标。
- 人工复核：`benchmark/baseline_notes.md` 含 3 条自动失败题的人工复核结论（`bench_multi_004`、`bench_multi_011`、`bench_neg_004`），与 §4.4 一致。
- RAG 离线快照：`tests/eval_results_llm.json` total 33 / passed 30 / 90.9%。
- Super-agent Eval v2：`scripts/superagent_eval_v2.py` 的 `score_case` 为四维加权（factual 0.45 / action 0.25 / safety 0.20 / status 0.10），`passed = total >= 0.8`；`docs/e2e/superagent-eval-v2.md` 记录 24 个场景、四维评分、通过线 `total >= 0.8`，与 §8 一致。
- **私有 holdout 已存在**：`tests/evals/agent/private_holdout/dataset.v1.json` 20 条；`README.md` 标注"Private Holdout v2.3 / 20 条"；`results/private_v1.json` 有完整 summary（total 20、passed 17）；`tests/evals/agent/holdout/baseline_v2.0.md` 说明 20 条 private holdout 首次运行后于 v2.2 退场并入公共 Benchmark，后续需重建新 private holdout。

未核验：

- Benchmark 80 题的当前分数（本次未复跑模型）。
- private holdout 的 17/20 结果是否为当前版本（未重跑，仅核实归档文件存在）。

### 问题列表

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P1 | §8 状态表、§11 总结 | "独立私有 holdout 集 \| 规划中 \| 仓库内未见已填充的私有 holdout 数据"；"私有 holdout 仍属规划" | 与仓库事实相反：`private_holdout/dataset.v1.json` 已填充 20 题，`README.md` 标注 v2.3，`results/private_v1.json` 已有一次运行结果（17/20）；旧 holdout 已在 v2.2 退场并重建 | 改为"已实现：`tests/evals/agent/private_holdout`，20 题，已有一次归档运行（17/20）"，并注明结果未重跑；若想表达"尚未建立外部独立第三方 holdout"，需明确区分 |
| P2 | §1 表格 | "单元/契约测试 \| 126 个 `test_*.py`" | 递归含 `tests/evals/v2` 共 130 个；与 02 同一口径问题 | 写明计数口径（tests 根目录 126 / 递归 130） |

### 未核验项

- 80 题 Benchmark 当前版本的分数与分类通过率（未复跑）。
- private holdout 归档结果是否对应当前代码状态（未重跑）。
- "公开 Benchmark 仅作技术调研参考"属流程约定，无运行证据。

### 一句话总评

Benchmark 主体与证据一致，但私有 holdout 的实现状态写反了，属于需要优先修正的实现状态错误。

---

## 5. `05-agent-observability.md`

### 结论

**条件通过。**

### 实现状态声明是否成立

基本成立。结构化 `event_trace`、span 转换、`ai_monitor` 存储/聚合、监控中心 UI、trace 标签与评分、业务 trace ↔ 评测 trace 联动、Prometheus 指标与就绪探针、LangSmith 可选旁路都有代码或文档证据；采样/分级保留/自动清理、OpenTelemetry、SLO 告警标"规划中"与仓库现状一致。

### 证据核验结果（已核验）

- `TraceCallbackHandler`：`src/rag_demo/agent/loop.py` 中旁路采集，LLM/工具输入输出截断 12000 字符（`prompt_text`、`output_text`、`input_text`、`output_text`），事件名由 `f"{kind}_started/_finished/_failed"` 生成；`run_started` / `run_finished` / `run_failed` 在 loop.py 中存在。
- `_build_agent_spans` / `_record_agent_monitor`：`src/rag_demo/agent/service.py`，span 含 `parent_span_id`、`latency_ms`、`prompt_tokens`/`completion_tokens`/`total_tokens`、输入输出字段。
- `ai_monitor.py`：`overview / timeseries / traces / trace_detail / agent_traces / set_agent_trace_tags / set_agent_trace_feedback` 均存在。
- API：`src/rag_demo/api/monitor.py` 中 `/api/monitor/overview`、`/timeseries`、`/traces`、`/traces/{trace_id}`、`/api/admin/agent-traces`（status/q/tag/feedback/min_latency_ms/max_latency_ms 过滤）、`PATCH .../tags`、`POST .../feedback` 均存在；`/ready`、`/metrics` 在 `api/ops.py`。
- UI：`web/src/router.js` 有 `/monitor-center`；`MonitorCenter.vue` 注释与代码为"业务请求 / Agent 调用 / 租户与计费"三个 tab；`AdminAgentMonitor.vue` 有"对比 Trace"与标签/评分。
- 联动：`docs/e2e/monitor-eval-centers.md` 记录"业务 Trace → Agent 输入/输出"与"评测实验 → Trace 输入输出"双向跳转。
- LangSmith：`src/rag_demo/config.py` 在 `LANGSMITH_API_KEY` 非空时 `setdefault LANGSMITH_TRACING=true`；`docs/langsmith.md` 要求 key 只从环境变量读取、不提交 `.env`、不作为 CLI 参数。

### 问题列表

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §5 | "`overview` 的聚合字段包含成功率、p95 延迟与 token" | `ai_monitor.overview()` 实际返回 `error_rate`（以及 `requests/errors`、`p95_latency_ms`、`tokens`），没有直接的成功率字段；成功率需由 `1 - error_rate` 推导 | 改为"错误率、p95 延迟与 token；成功率可由错误率推导" |

### 未核验项

- 监控中心三个 tab、Trace 对比/评分等浏览器交互（本次未跑浏览器）。
- PG 中 `ai_traces/ai_spans` 的实际数据与查询结果（未连接 PG）。
- LangSmith 实际上报（未配置 Key）。

### 一句话总评

可观测性实现与文档基本吻合，仅 overview 指标字段表述需精确。

---

## 6. `06-logs-metrics-tracing.md`

### 结论

**条件通过。**

### 实现状态声明是否成立

基本成立。日志双通道/轮转/PII、`/ready`、`/metrics`、Prometheus/Grafana/Alertmanager、自建 trace/span 均可核验；日志聚合、Histogram、外部通知、OpenTelemetry 标"规划中"与实际一致。需修正两处：预检项数（11→10）与"日志与 trace 强制关联"的状态证据。

### 证据核验结果（已核验）

- `src/rag_demo/logging_setup.py`：控制台短格式、文件格式 `%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s`、`TimedRotatingFileHandler(when="midnight", backupCount=BACKUP_DAYS)`（`BACKUP_DAYS = 7`）、手机号/邮箱/身份证 PII 打码、显式处理 `uvicorn` / `uvicorn.access` logger。
- `src/rag_demo/api/ops.py`：`/ready` 四项（`control_store`、`superagent_store`、`queue`、`merchant_store`），失败返回 503；`/metrics` 支持 `QIANKE_METRICS_TOKEN`，token 错误返回 401，未配置时开放。
- 指标：`qianke_up`、`qianke_process_start_time_seconds`、`qianke_queue_jobs{status}`、`qianke_work_items{status}`、`qianke_approvals{status}`、`qianke_tenants`。
- 告警：`ops/alert-rules.yml` 四条与文章一致（`QiankeApiDown up==0 for 2m`、`QiankeDeadJobs dead>0 for 5m`、`QiankeQueueBacklog pending>50 for 10m`、`QiankeStuckWorkItems stuck>0 for 5m`）。
- 部署：`ops/prometheus.yml` scrape 30s、target `host.docker.internal:8000`；`ops/alertmanager.yml` group_wait 10s / group_interval 30s / repeat_interval 2h，receiver 未接外部通知；`ops/grafana/dashboards/qianke-ops.json` 7 个面板；`docs/e2e/observability-deployment.md` 记录已运行验证；`docs/e2e/production-preflight.md` 记录 **10 项 PASS**。
- `scripts/production_preflight.py`：正常成功路径 10 个检查（11 个 `checks.append` 中 `postgres` 仅异常兜底）。

### 问题列表

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §5 末、§8 状态表 | "……等 11 项生产预检，全部 PASS"；"生产预检脚本 \| 已实现 \| `scripts/production_preflight.py`、`docs/e2e/production-preflight.md`" | 实际成功路径为 10 项；`docs/e2e/production-preflight.md` 记录的 PASS 清单也是 10 项。"11 项"把 DB 异常兜底检查也算作正常项 | 统一改为 10 项（或"10 项检查 + 1 个异常兜底"）；同批 07/09/10 同步修正 |
| P2 | §8 状态表 | "日志与 trace 强制关联 \| 部分实现 \| 有 request_id/execution_id，但日志文本未强制写 trace_id" | 日志格式与日志调用中未检出 `request_id/execution_id/trace_id` 字段，§5 也自述"没有强制关联字段"；"部分实现"缺少证据 | 下调为"未实现（日志未携带关联 ID）"，或补充日志中出现 request_id/execution_id 的具体证据 |

### 未核验项

- 未启动 Prometheus/Grafana/Alertmanager，未验证线上告警触发与看板数据。
- 未执行 `scripts/production_preflight.py`（未验证实际 PASS/时间点）。
- 日志轮转与 PII 打码的运行时行为（仅静态核验代码）。

### 一句话总评

三支柱与运维底座描述基本准确，需修正预检项数与日志-trace 关联状态。

---

## 7. `07-sre-slo.md`

### 结论

**条件通过。**

### 实现状态声明是否成立

成立。`/ready`、`/metrics`、4 条告警、告警路由、生产预检、24h 观察脚本、compose 健康检查均属实；正式 SLI/SLO、错误预算、值班、复盘模板标"规划中"，RTO/RPO 标"已设计"与架构决策文档一致（"第一版不承诺硬性 RTO"、RPO 目标需演练验证）。

### 证据核验结果（已核验）

- `src/rag_demo/api/ops.py`：`/ready` 四项、`/metrics` 文本与可选鉴权。
- `ops/alert-rules.yml` 四条规则（带 `for` 持续时间）与文章一致。
- `ops/alertmanager.yml` 有分组与重复间隔，receiver 默认只落 UI。
- `scripts/production_preflight.py`：成功路径 10 项（见 06 P2）。
- `scripts/observation_report.py`：计算 `ready_status`/`metrics_status` 是否为 200、`> 180s` 采样缺口、`queue_done`/`queue_pending`/`queue_dead`、`work_items_waiting_approval`、`stuck_max`，输出 `PASS/IN_PROGRESS/FAIL/NO_DATA` verdict；与 §5 描述基本一致。
- `docker-compose.yml`：db、backend、frontend 三个服务均有 healthcheck。
- SLO 现状：`docs/agent.md` 与基线文章均写"无正式 SLO"；`docs/decisions/three_agent_platform_architecture_decisions_v0.1.md` 给出 RPO 目标与"第一版不承诺硬性 RTO"，并要求演练验证。

### 问题列表

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §5、§8 状态表 | "`scripts/production_preflight.py` 一键检查 11 项关键证据"；"生产预检脚本 \| 已实现 \| ……，11 项检查" | 实际成功路径为 10 项检查；同批 06/09/10 同一错误 | 统一改为 10 项 |
| P2 | §5 | "`waiting_approval` 等工作项状态" | 实际字段为 `work_items_waiting_approval`（另有 `work_items_stuck`/`stuck_max`）；字段名写作简称，易与接口字段对不上 | 写实际字段名，或注明简称 |

### 未核验项

- 告警是否真的触发与升级（未部署 Prometheus/Alertmanager）。
- 24h 观察报告的实际 verdict（未运行 `observation_report.py`）。
- 值班制度、事故复盘模板（文章已标"规划中"；仓库内未见，未做运行时验证）。

### 一句话总评

对"有指标、有告警、无正式 SLO"的判断符合仓库事实，小问题集中在预检计数与观察字段名。

---

## 8. `08-retry-circuit-breaker-degradation.md`

### 结论

**通过。**

### 实现状态声明是否成立

成立。重试（LLM 客户端 + Runtime attempt）、幂等（request_id + scope + fingerprint）、队列重试/租约/死信、C 端 `client_message_id` 幂等与 WS 退避重连、多处降级均有代码证据；熔断器明确标"规划中"，代码中未检出 CircuitBreaker，未把规划写成已实现。

### 证据核验结果（已核验）

- `src/rag_demo/agent/loop.py`：`ChatOpenAI(..., timeout=60, max_retries=2)`；`run_agent_with_retry(..., max_retries: int = 1)`；`_RETRYABLE_STATUSES = {FAILED, TIMEOUT, MAX_STEPS_EXCEEDED, MAX_TOOL_CALLS_EXCEEDED}`；每次 attempt 新 `execution_id`、`parent_execution_id` 指向上一次。
- API：`src/rag_demo/api/main.py` 请求模型 `max_retries: int = 0`，执行前 `max(0, min(req.max_retries, 3))`，与"API 默认 0，限制 0–3"一致。
- 幂等：`agent/service.py` 的 `request_fingerprint`、`agent_scope`、`store.claim` 处理 `completed/conflict/in_progress/failed`，与"已完成回放、执行中 409、冲突 409、失败不自动重跑"一致。
- 队列：`superagent/queue_pg.py` `sa_job.attempts`、`max_attempts DEFAULT 2`、`claim_next_job(lease_seconds=1800)`、DEAD/FAILED 重放 `attempts=0`；Super-agent Worker 异常时 `deterministic_fallback`（`superagent/worker.py`）。
- C 端：`client_message_id` 字段与 `c_end/idempotency.py`（同 ID 不同内容 `IdempotencyConflict`）；`web/src/views/CApp.vue` 重连指数退避 `Math.min(1000 * 2 ** (attempts-1), 8000)`、最多 5 次。
- 降级：`agent/tools/rag.py` 混合检索失败→`keyword_search`；`c_end/recommend/service.py` `strategy="rules_fallback"`；`c_end/bargain_dialogue.py` 失败回退模板；`c_end/social.py`"诚实降级，不伪造商品/价格/优惠"；`storage/oss_store.py` 签名失败降级无图；`agent/policy.py` 未识别角色得到空授权集合（等价 guest 拒绝）。
- 熔断：`src/` 内未检出 `CircuitBreaker`/`circuit_breaker`/熔断实现，与"规划中"一致。

### 问题列表

无 P0/P1/P2 问题。（提示级：§5 "权限解析非法角色 → 降级为 guest（拒绝方向）"更精确的表述是"返回空授权集合，效果等价 guest 拒绝"；不影响结论，未计入问题。）

### 未核验项

- 熔断缺失为代码检索结论，未做运行时验证（不存在该功能，运行时难以"验证不存在"）。
- 队列重试/租约/死信在真实 PostgreSQL 上的行为（本次未连接 PG，未跑队列）。
- LLM 客户端重试在真实模型限流下的表现（未调用真实模型）。

### 一句话总评

本批实现状态与代码最一致的一篇，可以判定通过。

---

## 9. `09-failure-recovery-dr.md`

### 结论

**条件通过。**

### 实现状态声明是否成立

成立。备份/恢复脚本、manifest 校验、保留策略、定时备份、恢复 dry-run、生产预检、24h 观察、PG 切换预演/观察/冒烟均有代码与文档证据；备份加密/异地/自动演练/stale RUNNING 回收/跨区域灾备/RPO 演练验证标"规划中/已设计"与事实一致。需修正预检项数与产物清单小偏差。

### 证据核验结果（已核验）

- `scripts/backup_control_plane.py`：SQLite `source_conn.backup(target_conn)` 一致性复制；PG `pg_dump`（宿主机优先，缺失时 `docker exec` 回退，校验 `PGDMP` 头）；manifest 含 `created_at/files(source/file/sha256/size)/postgres/verified`；`--keep 7` 只清理带 `manifest.json` 的时间戳目录；`--include-pg`。
- `scripts/backup_control_plane.ps1` / `.sh`：写 `logs/backup.log`，`--keep 7`，ps1 用 `.venv\Scripts\python.exe`；`docs/e2e/ops-backup-schedule-grafana.md` 记录 Windows 任务计划程序每天 02:00、Linux `crontab 0 2 * * *`。
- `scripts/restore_control_plane.py`：默认 dry-run，`--yes` 才覆盖，覆盖前保存 `*.before-restore-<ts>`；先校验 manifest 与 sha256；`pg_restore -n <schema> --clean --if-exists`。
- 测试：`tests/test_backup_pg_fallback.py` 验证宿主 `pg_dump` 缺失时 Docker 回退（`mode="docker"`、`-Fc`、`PGDMP` 头）。
- 切换/观察/冒烟：`scripts/rehearse_control_pg_switch.py`、`scripts/observe_control_pg.py`、`scripts/smoke_control_pg.py` 存在；`tests/test_observe_control_pg.py`、`tests/test_observation_report.py` 存在。
- 回滚说明：`docs/decisions/control_plane_postgres_migration_p2b.md` 第 166 行"回滚：恢复环境变量为 sqlite，重启，恢复 SQLite 备份"。
- 删除标记与 RPO/RTO：`docs/decisions/three_agent_platform_architecture_decisions_v0.1.md` 要求恢复时重放删除标记、给出 RPO 目标表（核心数据 5 分钟）、"第一版暂不承诺硬性 RTO"，与文章一致。
- 已记录 PASS：`docs/e2e/production-preflight.md` 为 10 项 PASS（见问题）。

### 问题列表

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §5、§8 状态表 | "`scripts/production_preflight.py` 一键检查 11 项关键证据"；"生产预检 \| 已实现 \| ……；11 项 PASS 记录" | 实际成功路径为 10 项检查，文档记录的 PASS 也是 10 项 | 统一改为 10 项 |
| P2 | §5 产物结构 | "backups/<时间戳>/ ├── c_end_mock.sqlite ├── vec_db.dump └── manifest.json" | 漏了条件性产物：当 `var/merchant_v1.sqlite` 存在且商家后端为 sqlite 时还会备份 `merchant_v1.sqlite`；`vec_db.dump` 仅在 `--include-pg` 且成功时存在；manifest 里 `postgres` 字段记录结果 | 补一句"merchant_v1.sqlite（条件）"并说明 `vec_db.dump` 依赖 `--include-pg` |

### 未核验项

- 实际执行备份/恢复（本次未运行，避免产生 `backups/` 等写入产物）。
- RPO 5 分钟目标未演练验证（文章自身已标"已设计、需测试或演练验证"）。
- 季度演练记录（仓库内未检索到统一演练报告）。

### 一句话总评

恢复设计证据链完整，除预检项数与产物清单小偏差外符合实现。

---

## 10. `10-cicd-canary-release.md`

### 结论

**条件通过。**

### 实现状态声明是否成立

成立，且是本批次唯一正确指出"Eval v2 门禁脚本未接入 `ci.yml`"的文章。CI 行为、镜像化部署、健康检查、生产预检、24h 观察、环境开关、租户试点烟测均有证据；自动化 CD、灰度/金丝雀、发布单/自动回滚标"规划中"与仓库一致（仅 `ci.yml` 一个 workflow，无部署自动化）。需修正预检项数与一处表述。

### 证据核验结果（已核验）

- `.github/workflows/ci.yml`：push/PR 到 main + `workflow_dispatch`；`permissions: contents: read`；同 ref `concurrency` 取消；`ubuntu-latest`、`timeout-minutes: 20`；`uv 0.12.5`、Python 3.12；显式安装依赖并注释"不要用 uv sync（Windows 专用 torch wheel）"；`python -m pytest tests/ -q`；内联门禁读取 `tests/eval_results_llm.json`，`total >= 5`、`pass_rate >= 0.85`；假 Key `sk-ci-placeholder`；未调用 `scripts/check_eval_v2_gate.py`。
- 部署文件：`docker-compose.yml`（db PostgreSQL+pgvector、backend、frontend Nginx，三个 healthcheck）、`Dockerfile`、`web/Dockerfile`、`deploy/initdb/01-databases.sql`、`deploy/systemd/qianke-b-profile-worker.service`、`ops/cloudflared.example.yml` + `ops/cloudflared.yml`（后者被 `.gitignore:115` 忽略）。
- 验证/观察：`scripts/production_preflight.py`、`/health`（`api/main.py`）、`scripts/observation_report.py`、`docs/e2e/` 验收记录。
- 环境开关：`QIANKE_CONTROL_BACKEND`、`RAG_AUTH_ENABLED`、`RAG_ENABLE_API_DOCS` 均在代码中使用。
- 租户试点烟测：`scripts/tenant_pilot_smoke.py` 检查租户、owner 绑定、策略初始化、工作项按商家隔离。
- 缺口属实：仅 `ci.yml` 一个 workflow，无 CD/灰度/蓝绿/金丝雀/发布审批自动化；v2 门禁脚本未接入 CI（与文章 §5 一致）。

### 问题列表

| 级别 | 位置 | 原文摘要 | 问题 | 建议修正方向 |
|---|---|---|---|---|
| P2 | §5 | "`scripts/production_preflight.py` 11 项关键证据一键检查" | 实际成功路径为 10 项检查（同批 06/07/09 同一错误） | 统一改为 10 项 |
| P2 | §5 部署路径 | "`ops/cloudflared.yml` 固定域名入口（模板不入库）" | 表述写反：被忽略、不入库的是真实配置 `ops/cloudflared.yml`（`.gitignore:115`）；仓库内保留并入库的是模板 `ops/cloudflared.example.yml` | 改为"真实配置不入库（已被 gitignore），仓库内保留 `cloudflared.example.yml` 模板" |

### 未核验项

- 未实际触发 GitHub Actions CI（无远端运行环境），CI 行为依据 `ci.yml` 静态核验。
- 未执行 `docker compose up` 部署、未验证回滚流程（避免起服务/改环境）。
- "没有发布单/变更审批/版本 tag 自动生成"为仓库检索结论（仅 `ci.yml`，未见其他 workflow）。

### 一句话总评

对 CI/CD 现状与缺口的判断与代码一致，仅两处小表述需修正；同时它是本批纠正 01/03 CI 门禁表述的参照。

---

## 附：问题总表（按严重级别）

| 级别 | 篇目 | 位置 | 问题摘要 |
|---|---|---|---|
| P1 | 03 | §5 | 把 v2 门禁脚本写成 CI 门禁之一；`ci.yml` 未调用 |
| P1 | 03 | §4.3、§8 | "只对 frozen 数据集硬门禁"未实现；门禁对所有全量存档统一硬阈值 |
| P1 | 04 | §8、§11 | 私有 holdout 已实现（20 题 + 归档结果），文章写"规划中/未见数据" |
| P2 | 01 | §8 | "CI 评测门禁：已实现"与 ci.yml 真实行为不符，与 10 冲突 |
| P2 | 01 | §5 | `ae2_*` 仅 API 任务路径入库，CLI 不入库 |
| P2 | 01 | §8 | 成本看板已存在，文章写"仅有 token 记录与单价配置" |
| P2 | 01 | §9 | "已核验"缺命令/输出，范围大于可核验证据 |
| P2 | 02 | §8 | 126 与递归 130 / pytest 收集口径不一致 |
| P2 | 03 | §5 | compare 指标列 11 项 vs 代码 12 项 |
| P2 | 04 | §1 | 126 与递归 130 口径不一致 |
| P2 | 05 | §5 | overview 返回 error_rate，非直接成功率 |
| P2 | 06 | §5、§8 | 预检 11 项 vs 成功路径 10 项 |
| P2 | 06 | §8 | "日志与 trace 强制关联：部分实现"缺证据 |
| P2 | 07 | §5、§8 | 预检 11 项 vs 10 项 |
| P2 | 07 | §5 | `waiting_approval` 实际字段名 `work_items_waiting_approval` |
| P2 | 09 | §5、§8 | 预检 11 项 vs 10 项 |
| P2 | 09 | §5 | 备份产物清单遗漏条件性 `merchant_v1.sqlite` 与 `--include-pg` 条件 |
| P2 | 10 | §5 | 预检 11 项 vs 10 项 |
| P2 | 10 | §5 | cloudflared "模板不入库"表述写反 |

## 附：本报告依据的可执行核验（只读）

| 操作 | 结果 |
|---|---|
| `git rev-parse HEAD` / `git branch --show-current` | `32ad31bc2636…` / `b-end-2.0-p0`，与基线文章快照一致 |
| JSON 计数：regression/benchmark/v2 B/v2 C/private_holdout | 20 / 80 / 15 / 15 / 20 条 |
| `python scripts/check_eval_v2_gate.py` | `评测门禁：PASS`；b_analyst 93.3%（15 题）、c_guide 100.0%（15 题）；2 条 manual-pending 仅 WARN |
| `tests/eval_results_llm.json` summary | total 33 / passed 30 / pass_rate 0.9091 |
| `ops/grafana/dashboards/qianke-ops.json` panels | 7 |
| `scripts/production_preflight.py` 检查语句计数 | 11 个 `checks.append`，成功路径 10 项（含异常兜底 `postgres`） |
| `tests/` 下 `test_*.py` 计数 | 根目录 126；递归 130 |

> 说明：以上为本次审计实际执行的只读核验。未执行的项（全量 pytest、浏览器、PG 查询、真实模型 Eval、部署/备份脚本）均已在各篇"未核验项"中注明，不以推断冒充实测。
