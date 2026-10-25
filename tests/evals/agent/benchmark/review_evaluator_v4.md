# Agent Benchmark v1.3 · Evaluator 四审报告

- 审查人：`benchmark-evaluator`（Eval 数据/技术审查，独立于 builder）
- 审查对象：`tests/evals/agent/benchmark/dataset.v1.json`（version `agent-benchmark-v1.3-demo`）+ Lead 更新的 `evaluator.py` / `runner.py` / `DATASET_QUALITY_POLICY.md`
- 审查时间：2026-10-26 01:00–01:05（Asia/Shanghai）
- 最终结论：**FAIL**（19 例回归 17/19 符合预期；另发现 1 条数据集阻塞项 `bench_multi_009`）

## 0. 审查快照（可复现）

| 文件 | SHA256（前 16 位） | mtime |
|---|---|---|
| `tests/evals/agent/benchmark/dataset.v1.json` | `38847ACE8B5EDFE4…` | 2026-10-26 01:00:25 |
| `tests/evals/agent/evaluator.py` | `D7C1CC73DF5A71A9…` | 2026-10-26 00:59:50 |
| `tests/evals/agent/runner.py` | `6643D5D9D03C986D…` | 2026-10-26 01:00:24 |
| `tests/evals/agent/DATASET_QUALITY_POLICY.md` | `96CFF4E5E12DA629…` | 2026-10-26 01:01:41 |
| `tests/evals/agent/benchmark/builder_notes.md` | `036D330785D1C9FA…` | 2026-10-26 01:01:35 |

环境说明：

- **本轮未运行完整 `run_agent`**；所有判定使用 `tests/evals/agent/evaluator.py` 的真实函数 `evaluate_task()` + 构造答案。
- **本机 PostgreSQL 不可用**（`127.0.0.1:5432` connection refused；Docker Desktop 服务未启动且本会话无管理员权限，无法拉起），因此本轮未重连 DB 做实时 SQL 复算。v1.3 仅改 6 条 negative 与版本/描述，34 条非 negative 的 expected 与 v1.1/v1.2 逐字段一致（见 §4）；其数值沿用同审查线程在 DB 可用时（2026-10-25）对同一 demo 快照（`built_at=2026-10-16 17:43:04`、8110 画像 / 36 文档）的独立复算结果，结论不受影响。`bench_multi_009` 的 48.69% 由 334/686 直接算出（48.6880%）。
- 未修改任何代码/数据；唯一写入本报告。

---

## 1. 40 条结构与 v1.3 字段校验（PASS）

```text
version = agent-benchmark-v1.3-demo；tasks = 40
category = {execute_sql: 10, rag_search: 8, multi_tool: 12, negative: 6, calculator: 4}
difficulty = {easy: 13, medium: 21, hard: 6}
task_id 唯一；expected_success 全 true；JSON 可解析
tool combos（multi）= {rag+sql+calc: 6, sql+calc: 5, rag+sql: 1}
runner --suite benchmark --validate-only → suite=benchmark tasks=40 valid
runner --suite regression --validate-only → suite=regression tasks=20 valid
```

negative 字段（6 条，与 Lead evaluator 扩展一致）：

| task | expected_tools | keywords_any | must_num | must_approx | forbidden_result_units | allowed_numbers | manual_review |
|---|---|---|---|---|---|---|---|
| neg_001 | `[]` | 6 词 | true | true | `["人"]` | 14 个统一并集 | ✓ |
| neg_002 | `[]` | 6 词 | true | true | `["%"]` | 14 个统一并集 | ✓ |
| neg_003 | `[]` | 6 词 | true | true | `["人"]` | 14 个统一并集 | ✓ |
| neg_004 | `[]` | 7 词（无“预测”） | true | true | `["人"]` | 14 个统一并集 | ✓ |
| neg_005 | `[]` | 6 词 | true | true | `[]` | 14 个统一并集 | ✓ |
| neg_006 | `["rag_search"]` | 6 词 | true | true | `["人"]` | 14 个统一并集 | ✓ |

- `allowed_numbers` 6 条完全一致：`["8110","36","2","1","10","0","364","7","2026","11","403","90","20","30"]`。
- 9 条 `manual_review`：neg_001..006 + sql_002 + sql_007 + multi_011；均为 list[str]。
- 非 negative 任务未携带 negative 专用字段（检查为 0 条）。

**v1.3 三项声明核验：**

| 声明 | 结果 | 证据 |
|---|---|---|
| neg_004 移除“预测”锚点 | ✅ | `expected_keywords=[]`；`expected_keywords_any` 7 词为 无法/没有/不存在/未提供/缺少/不支持/不能；D1「预测为 403 人」实测 FAIL（missing_any + 403） |
| 6 条 negative `forbidden_result_units` 生效 | ✅（规范内样例） | neg_001/003/004/006=`["人"]`、neg_002=`["%"]`、neg_005=`[]`；C5「触达 36 人」→ 36 非法（result_claim），E1「触达 8110 人」→ 8110 非法，C6「数量为 7 人」→ 7 非法，C1「退货率为 36%」→ 36 非法 |
| evaluator 新增 approx 窗口 | ✅（19 例内） | 11 个编造反例全部 FAIL（见 §2），包括「预计仍为 403 人」「预测 403 人」「推算为 36 人」「约 36 人/36%/7 人/30 人」 |
| runner 报告人工复核清单 | ✅ | 合成 `write_report` 实测输出「## 人工复核清单（2）」，auto-PASS 与 FAIL 的 manual_review 任务均列出；失败详情新增“缺少任一拒答词/非法数字/人工复核项” |

---

## 2. 19 个契约反例回归（task-26 核心）

**19 例范围**（按 `review_business_v3.md` §8.4“§2/§3 的 19 个契约用例：合规 8 + 编造 11”）：

- 合规 8：§2.1 FN1–FN8（期望 **PASS**）
- 编造 11：§2.2 FP1–FP5 + §3.1 D1–D4 + §3.2 C1、C2（期望 **FAIL**）

> 若 Lead 的 19 例组合与上述映射不同，下表的逐例结果可直接按组重新映射，不影响结论。

### 2.1 合规 8（期望 PASS）

| # | case | 构造答案（business v3 原文） | 实测 | 判定 |
|---|---|---|---|---|
| FN1 | neg_001 | 无法统计：只有 2 张表，没有营销活动或触达明细，需补充发送日志。 | **PASS** | ✅ |
| FN2 | neg_002 | 无法计算退货率：只有累计 order_count（1-10）与金额字段，没有订单明细和退货字段。 | **PASS** | ✅ |
| FN3 | neg_002 | 无法计算退货率：8110 条画像、累计 21000 笔订单，但没有订单级明细，分子无来源。 | **FAIL**；`disallowed=['21000']` | ❌ 未修复 |
| FN4 | neg_003 | 无法统计：top_category 只有 7 个品类，没有母婴，也没有 8110 位用户中的母婴偏好标注。 | **PASS** | ✅ |
| FN5 | neg_004 | 无法预测：demo 是 2026-10-16 单时点快照，只有 days_since_last_buy（0-364 天），没有时间序列。 | **FAIL**；`disallowed=['16']` | ❌ 未修复 |
| FN6 | neg_004 | 无法给出 2026 年 11 月的钻石会员数量；数据是单时点快照，不能外推。 | **PASS** | ✅ |
| FN7 | neg_005 | 无法统计：缺少注册时间与首单时间，只有 days_since_last_buy（0-364 天）相对天数。 | **PASS** | ✅ |
| FN8 | neg_006 | 高价值用户=近 90 天消费前 20% 且近 30 天活跃；demo 只有 8110 位用户的累计画像，缺窗口与日志，无法精确统计。 | **PASS** | ✅ |

**合规小计：6 / 8 PASS。**

- FN3 根因：`21000`（累计订单数，schema facts/合理引用）不在 `allowed_numbers` → 被 `must_not_contain_numbers` 判非法。
- FN5 根因：快照日期 `2026-10-16` 中的 `16` 不在 `allowed_numbers`（`2026`、`10` 在，`16` 缺）→ 判非法。
- 这两条正是 business v3 §8.3 S1（“allowed_numbers 为手写事实子集，合规事实可引用仍不全”）的遗留，v1.3 未处理。

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

### 2.3 汇总

| 组 | 符合预期 | 不符合 |
|---|---:|---:|
| 合规 8（期望 PASS） | 6 | 2（FN3、FN5） |
| 编造 11（期望 FAIL） | 11 | 0 |
| **19 合计** | **17** | **2** |

**19 例回归结论：17/19，不满足 task-26“合规拒答应 PASS、编造应 FAIL”的验收口径。**（若 Lead 将 FN3/FN5 的 allowed-list 误伤视为已接受的 S1 非阻塞遗留，则本组 11/11 编造拦截已达成；但该决定需要显式记录，且仍有下述数据集阻塞项。）

### 2.4 额外回归（超出 19 例的 §3.2 编造写法）

以下 8 条未被计入 19 例，但同样是 business v3 §3.2 列出的自然写法，实测 v1.3 全部被拒（✅）：

```text
C3「无法预测；预测 403 人。」→ FAIL（claim 403）
C4「无法统计营销触达人数；推算为 36 人。」→ FAIL（approx/claim 36）
C5「无法统计营销触达人数；触达 36 人。」→ FAIL（claim 36）
C6「无法统计母婴偏好；数量为 7 人。」→ FAIL（claim 7）
E1「没有营销触达记录，但触达 8110 人。」→ FAIL（claim 8110）
E2「缺少订单明细，退货率为 36%。」→ FAIL（claim 36）
E4「缺少行为日志，高价值用户约 20 人。」→ FAIL（approx 20）
FP4b（v2 原例）「预计仍为 403 人左右」→ FAIL（approx/claim 403）
```

### 2.5 标准合规拒答基线（6 条，期望 PASS）

“只有 8110 条画像与 36 个知识块，没有营销触达记录 / 没有订单明细 / 品类只有 7 类没有母婴 / 单时点快照无时间序列 / 缺注册与首单时间 / 缺 90 天窗口与行为日志”——**6/6 PASS**（neg_006 按 expected_tools 调用 rag_search，符合契约）。说明 v2 的核心误伤已消除。

---

## 3. 仍存在的契约缺口（19 例之外，真实 evaluator 复现）

> 以下不是“猜测”，均用 `evaluator.evaluate_task()` 实测；建议 Lead 在冻结前决定是否收口（人工复核兜底或继续收紧）。

### 3.1 false positive：无“线索词/结果标记”时，明确结果仍可 PASS（中风险）

| case | 答案 | 实测 | 说明 |
|---|---|---|---|
| R1 | neg_003：「无法统计母婴偏好，母婴偏好 7 人。」 | **PASS** | 数字后带“人”，但前面没有 触达/数量/为/约 等标记，`_RESULT_CLAIM_RE` 不命中 |
| R2 | neg_004：「无法预测；2026 年 11 月钻石会员 403 人。」 | **PASS** | 把 403（当前事实）直接写成预测结果，无标记词 |
| R3 | neg_005：「无法统计注册转化天数；缺少注册时间，平均 8110 天。」 | **PASS** | `forbidden_result_units=[]`（business v3 记为低风险），且“平均”不在标记表 |

- 影响：负样本自动 PASS 仍可能包含编造结果；这正是 business v3 H2 的残余形态。`manual_review` 能兜底，但报告虽已展示复核清单，自动分仍会偏乐观。
- 建议（Lead 决定）：把“数字 + 指标单位”改为不依赖前置标记的单位级拦截（或按题限定单位），同时避免误伤合规事实；或明确 negative 自动结果只作初筛、task_success 由人工定案。

### 3.2 false negative：合规事实引用被新规则误伤（中风险，措辞敏感）

| case | 答案 | 实测 | 说明 |
|---|---|---|---|
| F1 | neg_004：「无法预测未来；当前钻石会员**为 403 人**（事实）。」 | **FAIL** | `_RESULT_CLAIM_RE` 的“为”+“人”命中；但 manual_review 明说“可提当前 403 人作为事实” |
| F2 | neg_004：「无法预测未来；当前钻石会员 403 人。」 | **PASS** | 去掉“为”就通过——判定高度依赖措辞 |
| F3 | neg_001：「无法统计；全库用户总数**为 8110 人**，但没有营销触达记录。」 | **FAIL** | “为 8110 人”被当作结果；而「共有 8110 位用户」「8110 条画像、36 个知识块」PASS |
| F4 | neg_006：「高价值用户定义**约 90 天**消费前 20%、近 30 天活跃；…」 | **FAIL** | approx 窗口把“约 90 天”当近似结果（90 为定义数字） |

- 影响：同一事实、不同自然措辞，PASS/FAIL 不一致；与“允许引用事实数字”的契约存在冲突。
- 建议：对 `allowed_numbers` 中的事实数字，若其后单位与“被问指标”不一致（如“人”用于总用户数）应允许；或把 fact citation 降级为 manual_review，不直接判失败。该取舍属于 Lead/evaluator 设计决定。

### 3.3 allowed_numbers 仍是手写子集（中风险）

- FN3（21000）、FN5（16）已证明；business v3 S1 还列出 platforms 计数（937/7277）等 schema 事实也不在白名单。任何新的“认真解释数据缺口”写法都可能再次误伤。
- 建议：改为“题干 + schema facts 可见数字”动态允许集（S1），或事实引用只告警、最终由 manual_review 定案。

---

## 4. 40 条其余 34 条回归（未退化）与 v1.1 阻塞项状态

### 4.1 非 negative 34 条

- 与 v1.1/v1.2 快照逐字段核对：34 条非 negative 的 `task_id/category/expected_tools/expected_keywords` **完全一致**（本轮脚本逐条比对，0 处不一致）；v1.3 只改 6 条 negative + 版本/描述（与 builder_notes v1.3 §0/§12 一致）。
- 结构、类别分布、唯一性未变（§1）。
- evidence 数值沿用本审查线程 v1.1 复审时对 demo 的独立 SQL 复算（当时 DB 可用），如：sql_001 成都 11984.84、sql_006 西安 10222.56、sql_008 338、multi_005 40.57、multi_006 45.19%、multi_007 52.33%、multi_008 12.17、multi_009 334/48.69%、multi_010 1175.89、multi_012 57.54% 等；v1.3 未改动这些任务。
- v1.1 五个阻塞项复核：
  - E1（schema facts 泄漏：sql_001/008/multi_012）：**保持修复**（题目/expected 未变；v1.1 时已渲染 `get_sql_schema()` 确认新 expected 不在注入文本中，且不可由枚举计数/范围直接推出；本轮 DB 不可用未重渲染，但任务内容逐字段一致）。
  - E2（multi_009 regression 换皮）：**换皮已修复**（上海结构题 vs regression multi_004 单档钻石问法，expected 334/48.69% 不同）；但该题自身存在**新的 keyword 缺陷**（见 §5 B1）。
  - E3（multi_010 工具矛盾）：**保持修复**（题干无 2495；rag 必需；expected_tools 三项合理）。

### 4.2 阻塞项 B1：`bench_multi_009` 的 expected_keyword 与标准答案不一致（v1.1 引入，v1.3 仍未修）

- 数据：上海 普通 334 / 白银 206 / 黄金 114 / 钻石 32，共 686；334/686 = 48.6880466% → **保留两位小数 = 48.69%**。
- 现状：`expected_keywords = ["334", "48.7"]`，acceptance 写的是 48.69%。
- 用真实 evaluator 实测：
  - 标准正确回答「上海共 686 人，普通会员 334 人最多，占上海用户的 **48.69%**。」→ **FAIL**（`missing_keywords=['48.7']`）；
  - 只写一位小数（违反题目“保留两位小数”）「…占 **48.7%**。」→ **PASS**。
- 结论：该题把**错误精度/错误表述**判为通过、把**正确标准答案**判为失败，是确定性的数据集缺陷；v1.2/v1.3 的 negative 修订未覆盖它。
- 建议修复：keyword 改为 `"48.6"`（“48.69”的前缀，与其它比率题如 82.7/45.1/52.3/57.5 的兼容策略一致）或 `"48.69"`；同步 builder_notes；按 policy §9 版本 +1（建议 v1.4），修复后用 evaluator 复核“48.69% → PASS”。

**全 40 条 keyword/acceptance 一致性检查：仅 `bench_multi_009` 出现 keyword 不在 acceptance 中的情况（48.7 vs 48.69）。**

---

## 5. 结论与修订要求

### 5.1 最终结论：**FAIL**

判定依据：

1. **19 例契约回归仅 17/19**：合规 FN3、FN5 仍被 `allowed_numbers` 误杀（21000、16），与 task-26“合规拒答应 PASS”的验收口径不符；编造 11/11 已全部被拒，方向正确。
2. **数据集阻塞项 `bench_multi_009`**：标准正确回答（48.69%）被 keyword `48.7` 判 FAIL，而错误的一位小数（48.7%）PASS；v1.3 未修复。该问题与 negative 无关，但直接影响 benchmark 可交付性。
3. negative 契约仍有残余 false positive/false negative（§3：无标记明确结果可 PASS；“为 403 人/为 8110 人”等事实引用被误杀；neg_005 空单位白名单可被“平均 8110 天”绕过），建议在冻结前由 Lead 决定收口方式或明确“自动初筛 + 人工定案”边界。

### 5.2 通过项（应记录）

- 11/11 个 v3 编造反例被拒（含 FP1–FP5、D1–D4、C1、C2），且 §3.2 额外 8 条（C3–C6/E1/E2/E4/FP4b）也全部被拒 → N2 的主体目标在 19 例范围内达成。
- neg_004 已移除“预测”锚点，D1–D3 均因 missing_any/数字被拒 → N1 达成。
- runner 报告新增“人工复核清单”（auto-PASS 与 FAIL 的 manual_review 任务均列出）与失败详情三项 → N3 达成。
- 6 条标准合规拒答 6/6 PASS；40 条结构/类别/唯一性不变；其余 34 条未退化。

### 5.3 阻塞修复清单（builder/Lead）

| 编号 | 范围 | 必须做到 |
|---|---|---|
| B1 | `bench_multi_009`（dataset） | `expected_keywords` 的 `"48.7"` 改为 `"48.6"`（或 `"48.69"`），保证“占 48.69%”标准答案 PASS；版本 +1（v1.4）；同步 notes；重新跑 evaluator 契约测试。 |
| B2 | negative allowed_numbers（dataset 或 evaluator） | 让 FN3/FN5 的合规拒答 PASS：至少让 21000、快照日期 16 可按事实引用（加入 allowed_numbers、或按题干/schema facts 动态允许、或允许但标记 manual_review）。注意直接加入 `16` 会同时放宽 neg_005（当前 `forbidden_result_units=[]`，“平均 16 天”会 PASS），需评估/单题化处理。 |
| B3（Lead 决策） | negative 自动判定边界 | 对 §3 三类残余（无标记明确结果、事实引用误杀、neg_005 空单位）决定：继续强化（单位级结果拦截/事实数字豁免/单位限制）或明确“自动初筛 + manual_review 人工定案”并写入 policy/报告。 |

### 5.4 建议（非阻塞）

1. README 尚未同步 `forbidden_result_units` 与“人工复核清单”（policy 已更新）；建议补文档，避免实现/文档不一致。
2. `allowed_numbers` 的维护成本已显现（FN3/FN5、platforms 计数、日期），优先考虑 S1 动态允许集，而不是继续手写补数。
3. v1.3 尚未修复的 v1.1 低风险遗留（sql_005 差异/口径说明、sql_004/calc 低价值题等）不影响本轮 FAIL，但可在 v1.4 一并处理。
4. 正式 baseline 前（DB 恢复后）按 policy 做一次全量 SQL 复算；本轮因本机 PostgreSQL 不可用未做。

### 5.5 复审通过条件

- B1 修复：`bench_multi_009` 用“48.69%”标准答案实测 PASS，且“48.7%”不再被当作正确精度；
- 19 例回归全部符合预期（合规 8/8 PASS、编造 11/11 FAIL）——或 Lead 明确把 FN3/FN5 的 allowed-list 误伤列为已接受的非阻塞例外并记录；
- 6 条 standard 合规拒答 6/6 PASS；40 条结构/类别/唯一性不变；其余 34 条不动；
- 版本号 +1 并更新 builder_notes；由 evaluator 重新审查。

---

## 附录 A：本轮 evaluator 契约测试命令（可复现）

```text
解释器：.venv\Scripts\python.exe （Python 3.12）
导入：sys.path.insert(0, "tests/evals/agent"); import evaluator
判定：evaluator.evaluate_task(task, {"status":"COMPLETED","final_answer":answer,
        "tool_calls":[{"name":t} for t in task["expected_tools"]],
        "messages":[{"type":"tool","name":t,"content":"{\"ok\": true}"} ...]})
```

说明：因为本轮**不跑 run_agent**，构造的 `tool_calls` 仅用于工具契约（negative 的 `[]` 均为零工具；neg_006 按 `["rag_search"]`），不涉及模型输出。

## 附录 B：19 例实测关键字段

```text
FN3: task_success=False, disallowed_numbers=['21000'], approx=[], result_claims=[]
FN5: task_success=False, disallowed_numbers=['16'], approx=[], result_claims=[]
FP1: False, disallowed=['36'], approx=['36'], result_claims=['36']
FP2: False, disallowed=['36'], approx=['36'], result_claims=['36']
FP3: False, disallowed=['7'],  approx=['7'],  result_claims=['7']
FP4: False, disallowed=['403'], approx=['403'], result_claims=['403']
FP5: False, disallowed=['30'], approx=['30'], result_claims=['30']
D1/D2: False, missing_any=[无法..不能], disallowed=['403']
D3: False, missing_any=[...], disallowed=['403'], result_claims=['403']
D4: False, disallowed=['403'], result_claims=['403']
C1: False, disallowed=['36'], result_claims=['36']
C2: False, disallowed=['403'], approx=['403'], result_claims=['403']
```

## 附录 C：边界声明

- 未运行完整 Agent；未修改 `dataset.v1.json`、`builder_notes.md`、`regression/`、`policy`、`runner.py`、`evaluator.py`、`src/`；未提交 Git。
- 唯一新增：`tests/evals/agent/benchmark/review_evaluator_v4.md`。
- 本机 PostgreSQL/Docker 不可用（§0），本轮未做实时 SQL 复算；非 negative 数值沿用同一审查线程在 DB 可用时对同一 demo 快照的独立复算，negative 判定不依赖 DB。

---

*审查人：benchmark-evaluator · task-26 · 2026-10-26*
