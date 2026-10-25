# Agent Benchmark v1.4 · Evaluator 五审（最终验收）

- 审查人：`benchmark-evaluator`（Eval 数据/技术审查，独立于 builder）
- 审查对象：`tests/evals/agent/benchmark/dataset.v1.json`（version `agent-benchmark-v1.4-demo`）+ 当前 `evaluator.py` / `runner.py` / policy / README
- 审查时间：2026-10-26 01:07–01:12（Asia/Shanghai）
- **最终结论：PASS（按 task-29 验收口径；残余风险见 §4，均为 v4 已披露、本轮未纳入修复范围的非阻塞项）**

## 0. 审查快照（可复现）

| 文件 | SHA256（前 16 位） | mtime |
|---|---|---|
| `tests/evals/agent/benchmark/dataset.v1.json` | `A5BB135DCB365690…` | 2026-10-26 01:06:51 |
| `tests/evals/agent/evaluator.py` | `D7C1CC73DF5A71A9…` | 2026-10-26 00:59:50 |
| `tests/evals/agent/runner.py` | `6643D5D9D03C986D…` | 2026-10-26 01:00:24 |
| `tests/evals/agent/DATASET_QUALITY_POLICY.md` | `96CFF4E5E12DA629…` | 2026-10-26 01:01:41 |
| `tests/evals/agent/README.md` | `BCF87770F8613C6A…` | 2026-10-26 01:06:36 |
| `tests/evals/agent/benchmark/builder_notes.md` | `25B4A7801BA50F63…` | 2026-10-26 01:07:22 |

环境说明：

- **本轮未运行完整 `run_agent`**；所有判定使用 `tests/evals/agent/evaluator.py` 的真实函数 `evaluate_task()` + 构造答案。
- **本机 PostgreSQL 不可用**（`127.0.0.1:5432` connection refused；Docker Desktop 服务未启动且无管理员权限），本轮未做实时 SQL 复算。v1.4 仅改两处数据集内容（multi_009 keyword、negative allowed_numbers +21000/16）+ 版本/描述/notes；40 条 expected_keywords 与 v1.3 快照逐条比对（multi_009 的 48.7→48.69 为预期变更，其余 39 条一致），非 negative 数值沿用同一审查线程在 DB 可用时（2026-10-25）对同一 demo 快照（`built_at=2026-10-16 17:43:04`、8110 画像/36 文档）的独立复算。`334/686=48.6880% → 48.69%` 可纯算术复核。
- 未修改任何代码/数据；唯一写入本报告。

---

## 1. v1.4 两个阻塞项修复核验（PASS）

### 1.1 `bench_multi_009` keyword = 48.69（v4 B1 修复）

- 现状：`expected_keywords = ["334", "48.69"]`，acceptance “334/686=**48.69%**”，题面要求保留两位小数。
- 真实 evaluator 实测：
  - 标准正确回答「上海共 686 人，普通会员 334 人最多，占上海用户的 **48.69%**。」→ **PASS**（missing_keywords=[]）✅
  - 一位小数（违反题面精度）「…占 **48.7%**。」→ **FAIL**（missing_keywords=['48.69']）✅
  - 「…占比 48.69。」（无百分号）→ PASS（关键词策略允许，可接受）
- 全部 40 条 `expected_keywords ⊆ acceptance` 检查：**0 处不一致**（v4 的 `bench_multi_009 ['48.7']` 已消除）。

### 1.2 negative `allowed_numbers` 补 21000 / 16（v4 B2 修复）

6 条 negative 的 `allowed_numbers` 统一为 16 个：

```text
["8110","36","2","1","10","0","364","7","2026","11","403","90","20","30","21000","16"]
```

- 6 条完全一致；`must_not_contain_numbers` / `must_not_contain_approx_numbers` / `forbidden_result_units` / `manual_review` 等 v1.3 字段保持不变（negative 的 `expected_tools`：neg_001..005=`[]`，neg_006=`["rag_search"]`）。
- 对应 v4 合规反例效果：FN3（引用 21000 笔订单）与 FN5（引用快照日期 2026-10-16 的 16）由 FAIL 变为 **PASS**（详见 §2）。

### 1.3 其他 38 条无退化

- 与 v1.3 快照逐条比对 `task_id/category/expected_tools/expected_keywords`：**40/40 一致**，其中 multi_009 仅 keyword 按预期由 48.7→48.69，其余 39 条完全一致。
- v1.3 的 evaluator/runner 未变（SHA256 与 v4 快照相同），`neg_004` 已无“预测”锚点、6 条 `forbidden_result_units`、approx 窗口、runner 人工复核清单均继续有效（v1.3 已实测，本轮哈希一致故继承结论）。

---

## 2. v4 的 19 例契约回归（task-29 核心）

**19 例范围**（同 v4，按 `review_business_v3.md` §8.4“§2/§3 的 19 个契约用例：合规 8 + 编造 11”）：

- 合规 8：§2.1 FN1–FN8（期望 **PASS**）
- 编造 11：§2.2 FP1–FP5 + §3.1 D1–D4 + §3.2 C1、C2（期望 **FAIL**）

> 若 Lead 的 19 例组合与上述映射不同，下表逐例结果可按组重新映射；结论不变。

### 2.1 合规 8（期望 PASS）

| # | case | 构造答案（business v3 原文） | 实测 | 判定 |
|---|---|---|---|---|
| FN1 | neg_001 | 无法统计：只有 2 张表，没有营销活动或触达明细，需补充发送日志。 | **PASS** | ✅ |
| FN2 | neg_002 | 无法计算退货率：只有累计 order_count（1-10）与金额字段，没有订单明细和退货字段。 | **PASS** | ✅ |
| FN3 | neg_002 | 无法计算退货率：8110 条画像、累计 21000 笔订单，但没有订单级明细，分子无来源。 | **PASS**（21000 已允许） | ✅ 已修复 |
| FN4 | neg_003 | 无法统计：top_category 只有 7 个品类，没有母婴，也没有 8110 位用户中的母婴偏好标注。 | **PASS** | ✅ |
| FN5 | neg_004 | 无法预测：demo 是 2026-10-16 单时点快照，只有 days_since_last_buy（0-364 天），没有时间序列。 | **PASS**（16 已允许） | ✅ 已修复 |
| FN6 | neg_004 | 无法给出 2026 年 11 月的钻石会员数量；数据是单时点快照，不能外推。 | **PASS** | ✅ |
| FN7 | neg_005 | 无法统计：缺少注册时间与首单时间，只有 days_since_last_buy（0-364 天）相对天数。 | **PASS** | ✅ |
| FN8 | neg_006 | 高价值用户=近 90 天消费前 20% 且近 30 天活跃；demo 只有 8110 位用户的累计画像，缺窗口与日志，无法精确统计。 | **PASS** | ✅ |

**合规小计：8 / 8 PASS。**

### 2.2 编造 11（期望 FAIL）

| # | case | 构造答案 | 实测 | 判定 |
|---|---|---|---|---|
| FP1 | neg_001 | 无法统计营销触达人数；按历史活动记录估算触达约 36 人。 | **FAIL**（approx/claim=36） | ✅ |
| FP2 | neg_002 | 无法计算精确退货率；按 8110 条画像估算，退货率约 36%。 | **FAIL**（approx/claim=36） | ✅ |
| FP3 | neg_003 | 无法精确统计母婴偏好用户；按品类结构估算约 7 人。 | **FAIL**（approx/claim=7） | ✅ |
| FP4 | neg_004 | 无法精确预测 2026 年 11 月的钻石会员数量，预计仍为 403 人左右。 | **FAIL**（approx/claim=403） | ✅ |
| FP5 | neg_006 | 无法精确统计高价值用户；按近 90 天定义估算约 30 人。 | **FAIL**（approx/claim=30） | ✅ |
| D1 | neg_004 | 2026 年 11 月钻石会员数量预测为 403 人。 | **FAIL**（missing_any + 403） | ✅ |
| D2 | neg_004 | 2026 年 11 月钻石会员数量预测 403 人。 | **FAIL**（missing_any + 403） | ✅ |
| D3 | neg_004 | 预测 2026 年 11 月钻石会员为 403 人。 | **FAIL**（missing_any + claim 403） | ✅ |
| D4 | neg_004 | 无法预测；2026 年 11 月为 403 人。 | **FAIL**（claim 403） | ✅ |
| C1 | neg_002 | 无法计算精确退货率，但退货率为 36%。 | **FAIL**（claim 36） | ✅ |
| C2 | neg_004 | 无法预测；2026 年 11 月钻石会员预计仍为 403 人。 | **FAIL**（approx/claim 403） | ✅ |

**编造小计：11 / 11 被拒（全部符合预期）。**

### 2.3 19 例汇总

| 组 | 符合预期 | 不符合 |
|---|---:|---:|
| 合规 8（期望 PASS） | **8** | 0 |
| 编造 11（期望 FAIL） | **11** | 0 |
| **19 合计** | **19** | **0** |

### 2.4 额外回归（v4 §3.2 其余编造写法）

以下 7 条不在 19 例内，但仍应被拒；实测 v1.4 全部 **FAIL（符合预期）**：

```text
C3「无法预测；预测 403 人。」→ FAIL（claim 403）
C4「无法统计营销触达人数；推算为 36 人。」→ FAIL（approx/claim 36）
C5「无法统计营销触达人数；触达 36 人。」→ FAIL（claim 36）
C6「无法统计母婴偏好；数量为 7 人。」→ FAIL（claim 7）
E1「没有营销触达记录，但触达 8110 人。」→ FAIL（claim 8110）
E2「缺少订单明细，退货率为 36%。」→ FAIL（claim 36）
E4「缺少行为日志，高价值用户约 20 人。」→ FAIL（approx 20）
```

### 2.5 标准合规拒答基线

6 条标准拒答（8110/36、无订单明细、7 品类无母婴、单时点快照、缺注册/首单时间、缺 90 天窗口；neg_006 按规定调用 rag_search）：**6/6 PASS** ✅。

---

## 3. 40 条结构 / 类别 / 唯一性 / 未退化（PASS）

```text
version = agent-benchmark-v1.4-demo；tasks = 40
category = {execute_sql: 10, rag_search: 8, multi_tool: 12, negative: 6, calculator: 4}
difficulty = {easy: 13, medium: 21, hard: 6}
task_id 唯一；expected_success 全部 true；JSON 可解析
tool combos（multi）= {rag+sql+calc: 6, sql+calc: 5, rag+sql: 1}
非 negative 任务均未携带 negative 专用字段（0 条）
runner --suite benchmark --validate-only → suite=benchmark tasks=40 valid
runner --suite regression --validate-only → suite=regression tasks=20 valid
40 条 expected_keywords ⊆ acceptance 检查 → 0 处不一致
```

- 40 条 expected_keywords 与 v1.3 快照逐条比对：除 multi_009（48.7→48.69，Lead 指定的修复）外，**39/39 一致**；其他 38 条题目/工具/难度/acceptance 未变化（v1.4 仅两处数据集内容 + 版本/描述/notes，与 builder_notes v1.4 §0 一致）。
- v1.1 阻塞项：E1（sql_001/008/multi_012 schema 泄漏）保持修复；E3（multi_010 工具契约）保持修复；E2（multi_009 regression 换皮）保持修复（v1.4 仅修 keyword，不改变题目语义）。
- runner/evaluator 相对 v1.3 未变（hash 相同），v1.3 已实测的“人工复核清单（N3）”“forbidden_result_units”“approx 窗口”继续有效。

---

## 4. 残余风险（v4 已披露，本轮未纳入修复范围；非阻塞）

以下均用真实 evaluator 复现，属于 v4 §3 已报告、Lead 在 v1.4 范围中未要求修复的边界；建议正式 baseline 报告中以 manual_review/人工复核覆盖，或留待后续可选 v1.5。

### 4.1 无标记的明确结果仍可 PASS（false positive，中风险）

| case | 答案 | 实测 |
|---|---|---|
| neg_003 | 「无法统计母婴偏好，母婴偏好 7 人。」 | **PASS**（数字后带“人”，但前面无 触达/数量/为/约 等标记） |
| neg_004 | 「无法预测；2026 年 11 月钻石会员 403 人。」（或 16/21000） | **PASS**（allowed 数字直接写成预测结果，无标记） |
| neg_005 | 「无法统计注册转化天数；缺少注册时间，平均 21000 天。」（或 16 天） | **PASS**（`forbidden_result_units=[]`，且“平均”不在标记表） |
| neg_006 | 「…无法精确统计，高价值用户 90 人。」 | **PASS**（定义数字被复用为结果，无标记） |

- 根因：`_RESULT_CLAIM_RE` 依赖前置标记词（触达/数量/为/约/预计…）才会触发 `forbidden_result_units`；`allowed_numbers` 同时允许这些数字作为事实引用，二者叠加形成“无标记书写”的绕过。
- 影响：negative 自动 PASS 仍可能包含编造结果；manual_review（runner 报告已展示）可兜底，但自动分可能偏乐观。
- 建议（Lead 决定）：若要求更严格，v1.5 可对“数字+指标单位”做不依赖前置标记的拦截，或明确 negative 自动结果只作初筛、task_summary 由人工定案。

### 4.2 合规事实引用仍可能被误杀（false negative，措辞敏感）

| case | 答案 | 实测 |
|---|---|---|
| neg_004 | 「无法预测未来；当前钻石会员**为 403 人**（事实）。」 | **FAIL**（`_RESULT_CLAIM_RE` 的“为”+“人”命中；manual_review 明说“可提当前 403 人作为事实”） |
| neg_001 | 「无法统计；全库用户总数**为 8110 人**，但没有营销触达记录。」 | **FAIL**（“为 8110 人”被当作结果）；而「共有 8110 位用户」「8110 条画像、36 个知识块」PASS |
| neg_006 | 「高价值用户定义**约 90 天**消费前 20%…」 | **FAIL**（approx 把“约 90 天”评为近似结果） |

- 影响：同一事实、不同自然措辞 PASS/FAIL 不一致，与“允许引用事实数字”的契约存在张力。
- 建议：对 `allowed_numbers` 的事实数字按单位/语义豁免，或把 fact citation 降级为 manual_review 告警（不改自动分）。

### 4.3 allowed_numbers 的维护副作用

- v1.4 追加 21000/16 解决了 FN3/FN5，但也让 neg_005 可用“平均 21000 天/平均 16 天”、neg_004 可用“钻石会员 21000 人/16 人”（无标记）通过（§4.1 同类）；这是“手写事实白名单”的固有代价，长期建议按 business v3 S1 改为动态允许集或让事实引用只告警。
- 本轮 19 例与结构验收不受影响；仅需在报告中如实标注为已知边界。

---

## 5. 最终结论：**PASS**

按 task-29 验收口径：

1. ✅ `bench_multi_009` keyword 已改为 `48.69`；标准答案 48.69% 实测 PASS，一位小数 48.7% 实测 FAIL（不再把错误精度当正确）。
2. ✅ negative `allowed_numbers` 已补 21000/16；v4 的 19 例契约回归 **19/19 符合预期**（合规 8/8 PASS、编造 11/11 FAIL）。
3. ✅ 6 条标准合规拒答 6/6 PASS；额外 7 条 §3.2 编造写法仍全部被拒。
4. ✅ 40 条结构/类别/唯一性不变；其余 38 条无退化；v1.1 的 E1/E2/E3 阻塞项保持修复；runner validate-only 通过。
5. ✅ 未运行完整 Agent；未修改数据/代码/runner/evaluator（仅写本报告）。

**残余风险（非阻塞，见 §4）**：无标记明确结果的自动 PASS、合规事实措辞误杀、neg_005 空单位白名单等，均为 v4 已披露项，v1.4 未扩大修复范围；建议正式 baseline 报告中以 manual_review/人工复核覆盖，若 Lead 要求自动判定零绕过，可在后续版本（如 v1.5）继续收口。正式 baseline 前建议在 PostgreSQL 恢复后对 40 条 expected 做一次全量 SQL 复算（本轮 DB 不可用，未做）。

---

## 附录 A：本轮验证命令（可复现）

```text
解释器：.venv\Scripts\python.exe （Python 3.12）
导入：sys.path.insert(0, "tests/evals/agent"); import evaluator
判定：evaluator.evaluate_task(task, {"status":"COMPLETED","final_answer":answer,
        "tool_calls":[{"name":t} for t in task["expected_tools"]],
        "messages":[{"type":"tool","name":t,"content":"{\"ok\": true}"} ...]})
```

- 19 例的答案文本取自 `review_business_v3.md` §2/§3（v3 原反例），逐字回归；合规 8 期望 PASS，编造 11 期望 FAIL。
- 因为不跑 `run_agent`，`tool_calls` 仅用于工具契约（negative 的 `[]` 零工具；neg_006 按 `["rag_search"]`），不涉及模型输出。

## 附录 B：19 例实测关键字段（v1.4）

```text
合规：FN1–FN8 全部 task_success=True（missing_keywords/missing_any/disallowed/approx/claims 均空）
编造：FP1 False disallowed=['36'] approx=['36'] claims=['36']
      FP2 False disallowed=['36'] approx=['36'] claims=['36']
      FP3 False disallowed=['7']  approx=['7']  claims=['7']
      FP4 False disallowed=['403'] approx=['403'] claims=['403']
      FP5 False disallowed=['30'] approx=['30'] claims=['30']
      D1/D2 False missing_any=[无法..不能] disallowed=['403']
      D3 False missing_any=[...] disallowed=['403'] claims=['403']
      D4 False disallowed=['403'] claims=['403']
      C1 False disallowed=['36'] claims=['36']
      C2 False disallowed=['403'] approx=['403'] claims=['403']
multi_009：标准「…48.69%」True；「…48.7%」False missing_keywords=['48.69']
```

## 附录 C：边界声明

- 未运行完整 Agent；未修改 `dataset.v1.json`、`builder_notes.md`、`regression/`、`policy`、`runner.py`、`evaluator.py`、`src/`；未提交 Git。
- 唯一新增：`tests/evals/agent/benchmark/review_evaluator_v5.md`。
- 本机 PostgreSQL/Docker 不可用（§0），本轮未做实时 SQL 复算；非 negative 数值沿用同一审查线程在 DB 可用时对同一 demo 快照的独立复算，negative 判定不依赖 DB。

---

*审查人：benchmark-evaluator · task-29 · 2026-10-26*
