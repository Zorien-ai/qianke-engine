# B 端受控写 Eval：prepare_followup_task + HITL 确认（确定性）

> **版本：** agent-write-action-eval-v1
> **状态：** `deterministic` · **基线：** `not_required`（不依赖真实模型）
> **被测能力：** 经营分析 Agent 的首个写操作——只生成待确认草稿，用户确认后才生效。
> **产品/安全契约：** [docs/agent-write-action.md](agent-write-action.md)
> **实现：** `src/rag_demo/agent/actions.py`、`src/rag_demo/agent/tools/action.py`、`src/rag_demo/agent/policy.py`

## 1. 定位：这不是“真实模型 Eval”

本套 Eval 回答的是**确定性契约问题**：

```text
没有明确写意图 → 不应产生 DRAFT
明确写意图     → prepare_followup_task 产生 DRAFT（且只产生 DRAFT）
确认之前       → 业务/正式任务不存在
确认之后       → DRAFT → CONFIRMED，且可审计
越权/演示/客服 → Tool 不可见或执行层被拒
重复确认/跨账号 → 结构化错误码，不产生二次写入
整个链路       → 只写 agent_action 表，不碰业务表
```

它**不**回答“真实 LLM 在模糊问法下会不会误调写 Tool”。那需要带 `DEEPSEEK_API_KEY` 的真实模型 Eval（`tests/evals/agent/runner.py` 的 regression / benchmark 链路），本套刻意不混入。

为了保持确定性，真实模型被替换为**脚本化 AIMessage 轨迹**（`ScriptedLLM`）；但执行链路上的 `loop.run_agent`（LangGraph + ToolNode）、`ToolPolicy` 执行前复核、`action_scope`、`actions.create_followup_draft / confirm_action / cancel_action`、SQLite 动作表全部是**真实代码**，不是 mock。

## 2. 资产清单

| 文件 | 作用 |
|---|---|
| [`tests/evals/agent/write_action/dataset.v1.json`](../tests/evals/agent/write_action/dataset.v1.json) | 18 个确定性用例 + 账号矩阵 + coverage 索引 |
| [`tests/evals/agent/write_action/runner.py`](../tests/evals/agent/write_action/runner.py) | 数据集契约校验 + 场景执行器 + 判分 + JSON 摘要 CLI |
| [`tests/evals/agent/write_action/README.md`](../tests/evals/agent/write_action/README.md) | 套件速查 |
| [`tests/test_agent_write_action_eval.py`](../tests/test_agent_write_action_eval.py) | pytest 包装：数据集契约、产品契约、runner 全量执行、反证、CLI |
| [`tests/test_agent_actions.py`](../tests/test_agent_actions.py) | 原本的 3 条动作层单测（DRAFT→CONFIRMED / demo / 跨账号），继续保留 |

## 3. 与 task-34 验收点的对应

| # | 验收点 | 执行的 case | 关键断言 |
|---|---|---|---|
| 1 | 无明确“创建任务/安排跟进”意图时不生成 DRAFT | `wa_no_intent_01`–`04` + 意图规则/System Prompt 契约测试 | 脚本化只读轨迹跑完 `loop.run_agent` 后，`agent_action` 中该 request 0 行；4 条负样本 query 均不命中显式写意图标记；SYSTEM_PROMPT 含“只有用户明确要求…才调用 / 不要主动创建任务” |
| 2 | 明确写意图时 `prepare_followup_task` 生成 DRAFT | `wa_explicit_01`–`03` | 真实 ToolNode 执行写 Tool（`ToolMessage` 返回 `ok=true`、`requires_confirmation=true`）；动作表恰好 1 行 `DRAFT`，字段/账号/dataset/request_id 绑定正确 |
| 3 | 用户确认后 DRAFT→CONFIRMED | `wa_hitl_confirm_01` | `confirm_action` 后 `status=CONFIRMED`、`confirmed_by=账号 id`、`confirmed_at` 非空 |
| 4 | demo/cs/guest 不能写或不可见该 Tool | `wa_perm_analytics_roles_01`、`wa_perm_cs_01`、`wa_perm_cs_rogue_01`、`wa_perm_guest_01`、`wa_perm_demo_01` | 5 类分析角色可见且 `authorize=true`；cs 可见工具集不含写 Tool，越权 tool call 被 loop 拒绝为 `TOOL_NOT_ALLOWED` 且 0 DRAFT；guest 无任何 Tool（等价 API 403，不启动 Agent）；demo 无可见 Tool 且执行层返回 `DEMO_READ_ONLY` |
| 5 | 跨账号不能确认 | `wa_hitl_cross_account_01`、`wa_hitl_cross_account_cancel_01` | `ACTION_FORBIDDEN`，动作仍为 `DRAFT`，`confirmed_by/confirmed_at` 为空 |
| 6 | 重复确认被拒绝 | `wa_hitl_duplicate_confirm_01` | 第一次成功 `CONFIRMED`，第二次 `ACTION_NOT_DRAFT`，最终仍只有一条 `CONFIRMED` 记录 |
| 7 | 只写 `agent_action`，不写业务表 | `wa_isolation_01` | 沙箱业务表（orders / customers / coupon_grants）**文件哈希 + 行快照**前后不变；动作库只有 `agent_action` 表与约定索引；动作表快照 1 行 `CONFIRMED`；源码 SQL 写目标扫描只允许 `agent_action` |

额外覆盖（不在必需清单内）：`wa_hitl_cancel_01`（本人取消 → `CANCELLED`）、`wa_perm_analytics_roles_01`（分析角色正矩阵）。

## 4. 数据集结构

顶层字段：

| 字段 | 说明 |
|---|---|
| `version` / `suite` / `title` | 套件身份 |
| `status` | 固定 `deterministic`；校验器拒绝其它值 |
| `baseline` | 固定 `not_required`；本套不写真实模型基线 |
| `dataset` | `test`（动作 DB 沙箱作用域名，不是业务数据集评测） |
| `llm` / `network` | `scripted` / `none` |
| `related_doc` / `contract_doc` | 本文档 / 写功能安全契约 |
| `tool` / `action_type` | `prepare_followup_task` / `followup_task` |
| `accounts` | 账号矩阵：analyst / ops / exec / ent_admin / admin / cs / guest / demo |
| `cases` | 用例数组（见下） |
| `coverage` | 维度 → case id 索引；校验器要求 task-34 的 7 个必需维度齐全、且每个 case 恰好归属一个维度 |

单个 case 字段：

| 字段 | 说明 |
|---|---|
| `id` | 唯一 id，`^[a-z0-9_]+$`（同时用作临时目录名） |
| `category` | 场景分类，coverage 校验依赖它 |
| `scenario` | 执行器：`agent_trajectory` / `hitl` / `permission` / `isolation` |
| `params` | 场景入参：account / query / script（脚本化 tool calls）/ steps / business_tables 等 |
| `expect` | 判分期望：status、drafts 数、draft 字段、错误码、权限矩阵等 |

四个场景执行器：

| scenario | 做什么 | 真实链路 |
|---|---|---|
| `agent_trajectory` | 按 `script` 回放 AIMessage 轨迹，跑完整 Agent loop | `loop.run_agent` + LangGraph + ToolNode + ToolPolicy + `action_scope` |
| `hitl` | 先经 `action_scope` 建真实 DRAFT，再按 steps 执行确认/取消 | `actions.create_followup_draft / confirm_action / cancel_action` |
| `permission` | 不跑 LLM，检查 `ToolPolicy` 可见性/授权矩阵；可选直调写 Tool 探针 | `ToolPolicy.for_account / allowed_tools / authorize` + 真实 Tool |
| `isolation` | 端到端：写 Tool 生成 DRAFT → 确认，比对企业务表快照与动作库 | `loop.run_agent` + `actions` + SQLite 快照 + 源码写目标扫描 |

## 5. 运行方式

在仓库根目录（Windows 使用仓库 venv）：

```powershell
# 1) pytest 套件（task-34 指定命令）
.\.venv\Scripts\python.exe -m pytest tests/test_agent_actions.py tests/test_agent_write_action_eval.py -q

# 2) runner 全量：stdout 输出 JSON 摘要，退出码 0/1/2
.\.venv\Scripts\python.exe tests/evals/agent/write_action/runner.py

# 3) 只校验数据集
.\.venv\Scripts\python.exe tests/evals/agent/write_action/runner.py --validate-only

# 4) 可选：摘要落盘（注意不要提交真实业务数据；本套只有测试用例数据）
.\.venv\Scripts\python.exe tests/evals/agent/write_action/runner.py --output var/write_action_eval.json
```

隔离约定（与 task-34 要求一致）：

```text
pytest: tmp_path + monkeypatch.setenv("QIANKE_AGENT_ACTION_DB", ...) + monkeypatch.setattr(actions, "_DB_PATH", None)
runner: 每个 case 独立目录，设置 QIANKE_AGENT_ACTION_DB 并重置 actions._DB_PATH，结束后恢复进程原值
```

因此本套**不会**写 `var/agent_actions.sqlite`，也不会污染其它 Agent 测试。

## 6. 实际运行结果（2026-10-29，本机仓库 venv）

### 6.1 pytest（task-34 指定命令）

```text
$ .\.venv\Scripts\python.exe -m pytest tests/test_agent_actions.py tests/test_agent_write_action_eval.py -q
...................                                                      [100%]
19 passed in 4.86s
```

其中 `tests/test_agent_actions.py` 3 条、`tests/test_agent_write_action_eval.py` 16 条。耗时为当次运行值，会随机器负载小幅波动，断言与结果不依赖耗时。

### 6.2 runner 全量

```text
$ .\.venv\Scripts\python.exe tests/evals/agent/write_action/runner.py
total=18  passed=18  failed=0  pass_rate=1.0
check_total=186  check_passed=186
EXIT=0
```

分类别通过率（全部 1.0）：

| category | 通过/总数 |
|---|---:|
| no_write_intent | 4/4 |
| explicit_write_intent | 3/3 |
| hitl_confirm | 1/1 |
| hitl_duplicate_confirm | 1/1 |
| hitl_cross_account | 2/2 |
| hitl_cancel | 1/1 |
| permission_allowed_roles | 1/1 |
| permission_cs | 2/2 |
| permission_guest | 1/1 |
| permission_demo | 1/1 |
| write_isolation | 1/1 |

说明：

- 上述结果是**确定性 Eval**结果，不代表真实模型在开放对话中的行为正确率；
- 反证测试（篡改 `wa_explicit_01` 的期望标题）实测：`total=18 passed=17 failed=1 pass_rate=0.9444 failed_cases=["wa_explicit_01"]`，证明判分链路不会“永远通过”。

### 6.3 JSON 摘要示例（节选，实际输出）

```json
{
  "suite": "write_action",
  "version": "agent-write-action-eval-v1",
  "deterministic": true,
  "llm": "scripted",
  "network": "none",
  "storage": "per-case-tmp-sqlite",
  "total": 18,
  "passed": 18,
  "failed": 0,
  "pass_rate": 1.0,
  "check_total": 186,
  "check_passed": 186,
  "failed_cases": [],
  "cases": [
    {
      "id": "wa_isolation_01",
      "category": "write_isolation",
      "scenario": "isolation",
      "status": "PASS",
      "detail": {
        "business_tables": ["orders", "customers", "coupon_grants"],
        "action_db_tables": ["agent_action"],
        "action_rows": 1,
        "final_status": "CONFIRMED",
        "write_targets": ["agent_action"]
      }
    }
  ]
}
```

（`cases[].checks` 会列出每个断言的名字与失败详情，便于定位；摘要中不含时间戳与绝对路径，输出可直接 diff。）

## 7. 运行时防护（为什么这套 Eval 可信）

1. **不接模型**：`ScriptedLLM` 只按 dataset 回放固定 AIMessage；轨迹耗尽会抛错而不是静默通过。
2. **不连业务库**：`loop.build_system_prompt` 被替换为固定串，避免触发 schema 查询；SQL/RAG Tool 未被调用。
3. **真实执行**：写 Tool 由 LangGraph ToolNode 真实执行，`action_scope` 提供 actor 上下文；权限由真实 `ToolPolicy` 判定。
4. **判分可反证**：`test_runner_and_validator_detect_broken_expectation` 与 `test_validator_rejects_no_intent_case_that_expects_draft` 保证 grader / validator 不是空转。
5. **状态自恢复**：`loop.get_llm`、`loop.build_system_prompt`、`actions._DB_PATH`、`QIANKE_AGENT_ACTION_DB` 在 case 结束后恢复，pytest 里还有显式断言。

## 8. 未覆盖项与已知限制

| 未覆盖 | 原因 / 影响 | 后续 |
|---|---|---|
| 真实 LLM 是否正确区分“显式写意图 / 隐式提一句” | 本套用确定性规则 + 脚本化轨迹代替，不产生真实模型行为证据 | 在真实模型 Regression / Benchmark 中加入写 Tool 用例（需要 `DEEPSEEK_API_KEY`） |
| HTTP API 层（`/api/agent/run`、`/actions/{id}/confirm|cancel`）的 403/409 状态码与 `pending_actions` 序列化 | 直接测 service/tool 同层函数；`src/rag_demo/api/main.py` 当前正被其它任务修改，本套不建立对该文件的环境依赖 | 由 API 集成测试或前端 E2E 覆盖 |
| 真实 PostgreSQL 业务表（orders / coupons / user_profile） | 不连业务库；用沙箱 SQLite 业务表快照 + 源码写目标扫描代替 | 需要真实库的回归环境时再补 |
| 并发确认 / 跨进程竞态 | SQLite 顺序执行，未构造并发访问；重复确认只覆盖顺序场景 | 若引入任务状态机/审批链再补并发用例 |
| `request_id` 级别写幂等 | `create_followup_draft` 本身不去重；幂等主要在 Runtime `execution_store`。本套未覆盖“同 request_id 重复跑 Agent” | 如产品要求，补执行层幂等用例并明确冲突语义 |
| 审批链、多级审批、任务执行器、负责人账号真实性校验 | 产品尚未实现，无法评测 | 功能落地时同步新增 Eval |
| 前端「待确认写入」面板交互 | 前端 E2E 不在本套范围 | 由前端/E2E 测试覆盖 |
| 新增角色的权限矩阵 | 当前只覆盖 policy 现有 4 类角色 + demo / cs / guest | 改 `ToolPolicy` 时同步扩 `accounts` 与 `wa_perm_*` |

另：本套不记录真实模型基线，**不得**把本套 `pass_rate` 当作人设、业务正确性或真实模型能力的 Eval 结果引用。

## 9. 维护规则

- 改 `prepare_followup_task` 的 Tool Contract（名称/参数/返回结构/错误码）→ 必须同步更新本套 `expect` 与 `tests/test_agent_write_action_eval.py` 的契约断言；
- 改 `ToolPolicy` 角色矩阵 → 同步更新 dataset `accounts` 与权限 case；
- 改确认/取消语义（状态机、错误码）→ 同步更新 `hitl` case 的 `steps` / `expect`；
- 改 `actions.py` 的表或写目标 → `wa_isolation_01` 的列/写目标断言会失败，属于预期保护；
- 新增 case 必须同步 `coverage`（task-34 的 7 个必需维度保持齐全），并保证 pytest 中的条数/场景断言同步；
- 本套通过后仍需按项目协议运行 `pytest` + Regression Eval（涉及 Agent 核心链路时）。
