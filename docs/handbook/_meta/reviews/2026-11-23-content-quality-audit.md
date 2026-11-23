# Architecture Handbook 内容质量审计（2026-11-23）

> 审计对象：V0.5.1 第 1 篇之外的 59 篇公开文章  
> 质量基线：`docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md`  
> 审计方式：逐篇只读审计 + 代码/测试/文档交叉核对；不回写文章  
> 代码快照：Git `32ad31bc2636`（工作区含未提交修改）  
> P1 状态：上一轮 P1 导航修复与 IAM `/docs` 表述修复**已冻结**，本轮未修改文章正文

## 1. 总体结论

**当前不建议把 59 篇全部作为可发布内容。** 建议保留第 1 篇为质量基准，先修复 P1，再按批次复核。

| 结论 | 篇数 |
|---|---:|
| 通过 | 25 |
| 条件通过 | 32 |
| 不通过 | 2 |
| 合计 | 59 |

问题分级：

```text
P0 = 0
P1 = 22
P2 = 约 115（批次报告口径略有差异）
```

没有发现 P0 级“系统性伪造证据”或“把完整规划体系写成已实现”的问题；
但存在会误导实现/测试的具体错误、过时状态和跨篇矛盾，集中在 P1 的 22 处。

## 2. 基线自身也有一个需要同步修正的问题

V0.5.1 第 1 篇是质量基准，但它自身仍保留了旧错误码示例：

```text
READ_ONLY_VIOLATION
```

当前 SQL Tool 的真实错误码是：

```text
SQL_VALIDATION_ERROR
```

第 09 篇《Agent 工具调用机制》沿用了这个旧示例，并进一步写出了不存在的
`LIMIT_REQUIRED`、把函数名 `_tenant_scope` 当成错误码 `TENANT_SCOPE`。

因此：

```text
09 篇需要修；
V0.5.1 基线也需要单独做一次错误码勘误；
否则 09 修完后仍会与基线冲突。
```

这不否定第一篇文章的整体质量，但说明“质量基准”不等于“每一行都已核验”。

## 3. 分批次结论

| 批次 | 通过 | 条件通过 | 不通过 | P1 | P2 | 报告 |
|---|---:|---:|---:|---:|---:|---|
| Agent Architecture（第 2–10 篇） | 6 | 3 | 0 | 5 | 20 | [agent-architecture.md](audit-2026-11-23/agent-architecture.md) |
| Enterprise Governance | 7 | 3 | 0 | 3 | 31 | [enterprise-governance.md](audit-2026-11-23/enterprise-governance.md) |
| System Architecture | 3 | 7 | 0 | 4 | 17 | [system-architecture.md](audit-2026-11-23/system-architecture.md) |
| Data & Knowledge | 5 | 5 | 0 | 2 | 18 | [data-knowledge.md](audit-2026-11-23/data-knowledge.md) |
| Reliability & Evaluation | 1 | 7 | 2 | 3 | 16 | [reliability-evaluation.md](audit-2026-11-23/reliability-evaluation.md) |
| Architecture Practice | 3 | 7 | 0 | 5 | 13 | [architecture-practice.md](audit-2026-11-23/architecture-practice.md) |

## 4. 22 个 P1 问题

### 4.1 Agent Architecture

1. **09 篇 Tool 错误码与代码不符**
   - `READ_ONLY_VIOLATION` 不存在；实际为 `SQL_VALIDATION_ERROR`。
   - `LIMIT_REQUIRED` 不存在；`TENANT_SCOPE` 实际是 `_tenant_scope` 函数名，不是错误码。
2. **09 篇低估受控草稿幂等缺口**
   - `create_followup_draft` 没有幂等键/唯一约束，重复调用会产生多条 DRAFT；
   - 原文写成“只缺 retry 专项测试”，把实现缺口误写成测试缺口。
3. **03 篇把 `RUNNING` 列入“终态”**
   - `RUNNING` 是初始/中间态；`_TERMINAL_STATUSES` 不包含它。
4. **10 篇 retry 默认值错误**
   - `run_agent_with_retry` 函数默认 `max_retries=1`；
   - API 请求默认 0、上限 3；
   - 原文把 API 默认值错挂到函数默认值。
5. **09 篇错误码分类整体混用**
   - 把行业通用分类、函数名、复合后缀混在一起，放在“Qianke 当前”语境下会被当成真实契约。

### 4.2 Enterprise Governance

6. **01 篇登录限流环境变量名错误**
   - 文章写 `RAG_LOGIN_RATE_BACKEND`；代码读取 `QIANKE_LOGIN_RATE_BACKEND`。
7. **03 篇多租户隔离强度标注过强**
   - 汇总处写“已实现”，与本文自身列出的缺口冲突：`sa_job` 无 `merchant_id`、队列观测全局、Webhook `merchant_id` 由调用方声明、单应用单商家。
8. **09 篇 Trace 事件名错误**
   - 代码为 `llm_started` / `llm_finished` / `llm_failed`、`tool_started` / `tool_finished` / `tool_failed`；
   - 文章写 `llm_start` / `llm_end` / `llm_error` 等，按文过滤 Trace 会全部落空。

### 4.3 System Architecture

9. **02 篇把跨存储写入描述为同一事务**
   - 代码实际是商家库事务与控制面事务分别提交，存在不一致窗口；
   - 与 09 篇“跨存储非原子”自相矛盾。
10. **03/04 篇 WebSocket 路径与 Nginx 拓扑描述不准确**
    - 实际路径为 `/api/c/ws/chat|group`，文章写 `/ws/...`；
    - Nginx `/api/` location 未配置 Upgrade，按配置推断该拓扑下 WS 不可用，未实测。
11. **07 篇控制面表数量过时**
    - 文章写 28 表；`control/schema_pg.sql` 与契约测试当前为 63 表。
12. **07/10 篇连接池状态与代码相反**
    - 控制面与商家仓储已使用 `ThreadedConnectionPool`；
    - 只有数据集/Text2SQL 连接层没有池；
    - 文章整体写成“连接池未实现/规划中”。

### 4.4 Data & Knowledge

13. **05 篇上下文脱敏结论过强**
    - 主问答链路没有统一的上下文脱敏；
    - 实际只有日志脱敏、画像卡牌展示脱敏，以及 `b_end/insights.py` 的一条旁路脱敏；
    - `profile_text` 仍可能作为检索候选文本进入生成上下文。
14. **06 篇代码围栏未正确闭合**
    - 关闭围栏写在文字行末，Markdown 渲染可能把后续章节并入代码块，破坏 12 节结构。

### 4.5 Reliability & Evaluation

15. **03 篇把未接入 CI 的门禁写成 CI 门禁**
    - `ci.yml` 没有调用 `check_eval_v2_gate.py`；
    - 同批 10 篇明确写了这个缺口。
16. **03 篇“只对 frozen 数据集硬门禁”未实现**
    - 门禁代码没有 frozen 分支；
    - 当前两套数据集 `frozen:false` 仍按 0.80 硬阈值判定。
17. **04 篇私有 holdout 状态与仓库事实相反**
    - `private_holdout` 已有 20 题数据集与一次 17/20 归档运行；
    - 文章写“规划中 / 仓库内未见数据”。

### 4.6 Architecture Practice

18. **02 篇把人工性能报告写成测试/CI 性能门禁**
    - 仓库有性能报告，但没有性能测试或 CI 性能门禁。
19. **02 篇 M0 状态过时**
    - 文章写“M0 验收进行中”；
    - `merchant-dashboard-v1.1-m0-closure.md` 已记录 M0 ACCEPTED（2026-11-22），M1 未批准。
20. **03 篇代码行数“已核验”与当前文件不符**
    - 文章写 `c_end/store.py` 约 2,744 行、`superagent/store.py` 约 1,044 行；
    - 当前约 6,578 / 1,198 行，数字来自旧迁移方案快照。
21. **06 篇 M0 状态同样过时**
    - 与第 02 篇同一问题：M0 已 ACCEPTED，应补 closure 证据。
22. **09 篇代码行数引用旧快照**
    - 技术债务论证使用的行数偏小，低估了当前单文件膨胀程度。

## 5. 高优先 P2（P1 修复后应同批处理）

- **System 03 API Gateway**：仍写“生产 `/docs` 与 `/openapi.json` 关闭”。当前 `/docs` 是公开 Handbook，Swagger 已迁 `/api/docs`。
- **Practice 05 技术选型**：仍写“VitePress 已选型，构建与上线待核验”。当前已构建并挂载 `/docs`，状态过时。
- **System 03/04 WS 路径**与 **System 07 表数量**已列 P1；修复时同时清理 `/docs` 旧叙述。
- **Enterprise 08 日志脱敏示例**：身份证实际输出为 `110101********4`，不是 `110101********1234`。
- **Data 06 缓存键**：文章写“缓存键不含数据版本”，代码和 01 篇都表明包含 `data_version`。
- **Reliability 06/07/09/10 预检项数**：统一写 11 项，成功路径实际 10 项。
- **Tests 计数口径**：`tests/` 顶层 126 个 `test_*.py`，递归 130 个；文章未注明口径。
- **Practice 10 时间线**：1.0 引证与 AGENTS 变更记录语义不一致；2.1–2.29 区间漏 2.30 审计。

## 6. 证据真实性核验

已实际执行：

```text
python -m pytest tests/test_agent_execution_safety.py tests/test_agent_checkpoint.py tests/test_agent_architecture.py -q
环境：SQLite 控制面/数据面
结果：34 passed, 1 warning in 20.66s
Git HEAD：32ad31bc2636
```

核验结论：

```text
1. 基线文章的 34 passed、commit、代码路径均可复核；
2. 59 篇引用的测试文件路径全部存在；
3. 代码路径引用总体存在；带 ::symbol 的引用需按“文件存在 + 符号存在”分别核；
4. 未发现 P0 级伪造文件或伪造测试结果；
5. 问题主要是错误码、过时状态、错误实现结论和跨篇矛盾，不是凭空编造整套证据。
```

未核验：

```text
- 外部链接可达性
- 全量 pytest / Regression / Benchmark
- 真实 LLM Eval、生产并发、SLO、成本看板
- 浏览器端全部 60 页交互（本轮审计只审内容，不重复做 UI 验收）
- 生产 PostgreSQL、企业微信真实投递、备份恢复实测
```

## 7. 建议的后续顺序

1. **冻结第 1 篇 V0.5.1 作为质量基准**，但单独勘误 `READ_ONLY_VIOLATION` 示例。
2. **先修 22 个 P1**，不要继续批量生成或全站重写。
3. 修完后按批次复核 32 篇条件通过文章；2 篇不通过必须重新审计。
4. P1 通过后，再处理高优先 P2（`/docs` 旧叙述、VitePress 状态、缓存键、预检项数、测试计数口径）。
5. 最后统一检查 frontmatter、12 章结构、归档目录和链接。
6. 本轮 P1 导航/IAM 修复保持冻结，不回滚、不扩散。

## 8. 审计边界

- 本报告只新增审计文件，没有修改任何文章正文、配置或代码。
- 批次报告由 6 个只读审计任务生成；其中 Code Agent 报告明确区分了“已运行”和“未核验”。
- 本报告汇总了 P1/P2 计数，但逐条证据以批次报告中的“位置—原文—代码/文档证据—修正方向”表格为准。
