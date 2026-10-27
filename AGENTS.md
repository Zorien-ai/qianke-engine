# Qianke Agent 项目级 AI Coding Agent 工作协议

> **Version:** 1.1.0 · **Status:** Active · **Product:** Qianke Agent  
> 本文件约束 AI Coding Agent 的工作方式；产品需求、接口和模型以对应文档为准。

## 0. 十条硬规则

1. 先理解，再方案，确认后编码。
2. 关键需求有歧义，先问，不猜。
3. 优先级：**安全 > 数据正确性 > 架构稳定 > 可测试 > 可观测 > 业务正确 > 功能 > 速度**。
4. 不绕过 SQL 安全、权限检查、数据校验和用户确认。
5. 不让 LLM 直接执行数据库写入、DDL/DML 或事务。
6. 不编造数据、结论、测试结果和 Eval 结果。
7. 改核心架构前，先说明影响面、迁移和回滚方案。
8. 新增/修改 Tool，必须同步更新 Tool Contract、测试和 Eval 场景。
9. Agent 核心逻辑变更后，必须跑 pytest + Regression Eval，必要时跑 Benchmark Eval。
10. 交付时说明：改了什么、测试结果、Eval 结果、已知限制。

---

## 1. 项目定位

Qianke Agent 是面向企业经营分析与策略决策的 AI Agent，不是通用聊天机器人，也不是单纯的 RAG Demo。

```text
数据接入 → 问题理解 → 任务规划 → 数据/知识检索
→ 多步分析 → 证据验证 → 策略生成 → 可解释结果
```

| 优先级 | 场景 | 典型问题 |
|---|---|---|
| P0 | 运营活动策略助手 | 活动效果、复盘、分群、目标人群、异常、策略、原因调查、结果验证 |
| P1 | 用户/客户分析 | 画像、价值、流失、召回、分群、行为分析 |
| P1 | 客服/销售坐席画像 | 坐席画像、服务能力、销售能力、绩效、优势短板、培训建议 |

---

## 2. 数据接入

第一版只支持 CSV，目标是完整链路，不是简单上传：

```text
CSV → Schema Inference → Data Profiling → Validation
→ Preview → Human Confirmation → Database Import → Dataset Registry
```

**LLM 可以负责：** 理解数据含义、字段语义、Schema 映射建议、数据集描述、问题解释、流程编排。

**LLM 不负责：** 直接写库、绕过校验/权限/确认、任意生成并执行 DDL/DML。

数据处理、校验、事务和写入必须由确定性代码完成。

---

## 3. Agent 设计原则

不是 `Question → Answer`，而是：

```text
Business Question → Investigation → Evidence
→ Hypothesis → Verification → Conclusion → Strategy
```

证据不足时：不猜测、不编造、不使用未经验证的数据。应告诉用户：已知什么、缺什么、为什么无法下结论、下一步需要什么数据。

---

## 4. Coding Agent 工作流

```text
Understand → Plan → Confirm → Implement → Test → Eval → Verify
```

### 4.1 Understand / Plan

先确认：真正的问题、涉及模块、是否影响架构/数据模型/安全边界/Agent 行为/Eval。

编码前说明：实现思路、涉及文件、修改范围、测试方案、风险和架构影响。

### 4.2 Confirm

涉及代码、架构、数据模型、安全边界的修改，必须等用户明确确认后再实施。

禁止：自行扩大需求、重构无关代码、改变架构、删除现有能力。

### 4.3 歧义处理

描述不清、关键参数缺失、多种合理解释、数据结构/安全边界/业务规则不明确时，先询问，禁止猜。

---

## 5. 架构保护

以下内容未经明确授权不得擅自修改：

- **Agent Loop:** `LLM → Tool Call → Tool Execution → Observation → LLM → ... → Final Answer`
- **Agent State:** 至少保留 `messages`、`step_count`、`tool_call_count`、`status`、`error`、`started_at`
- **Tool Contract:** Tool 必须有 `name`、`description`、输入 Schema、结构化 result、结构化 error

工具错误必须结构化，禁止用字符串匹配判断业务错误类型：

```python
# 禁止
if "xxx" in error_message: ...

# 优先
error.code
```

---

## 6. Tools

当前工具：

```text
Tools
├── RAG Tool
├── SQL Tool
└── Calculator
```

未来：Data Ingestion、Dataset Inspection、Dataset Profiling 等。

新增 Tool 必须：

1. 定义输入 Schema、结构化输出和错误；
2. 明确权限边界；
3. 添加单元测试和 Agent Eval 场景；
4. 不破坏现有 Tool Contract。

---

## 7. 安全边界

### 7.1 SQL

SQL Tool 属于高风险 Tool，必须保持：

- `SELECT / WITH` 为主要允许操作
- 危险 SQL 禁止、表白名单、LIMIT、只读连接、Statement Timeout、Fetch Limit

禁止 `DROP`、`DELETE`、`UPDATE`、`INSERT`、`ALTER`、`TRUNCATE` 及任何未经授权的写操作。Agent 不得通过自然语言绕过 SQL 安全限制。

### 7.2 CSV 导入

```text
Parse → Schema Validation → Data Profiling → Validation
→ Preview → Human Confirmation → Transaction → Import
```

未经用户确认，不得最终入库。导入失败必须保证事务一致性、不产生部分成功脏数据、返回结构化错误、保留必要日志。

---

## 8. Dataset Registry 与 RAG

### 8.1 Dataset Registry

数据集至少包括：`dataset_id`、`name`、`description`、`schema`、`source`、`row_count`、`created_at`、`owner`、`status`、`schema_version`、`content_hash`。

Agent 不应假设某张表一定存在，应优先通过 Dataset Registry 了解可用数据。

### 8.2 RAG

RAG 是 Agent 的知识工具，不是 Agent 本身。负责企业知识、活动规则、KPI 定义、业务口径、运营规范、坐席评价标准。

Agent 根据任务决定是否调用 RAG；禁止为了“看起来用了 RAG”而强制调用。

---

## 9. Agent Evaluation

| 集合 | 题量 | 用途 |
|---|---:|---|
| Regression Set | 20 | 防止已有能力回归；Agent 核心逻辑变化后优先跑 |
| Benchmark Set | 60 | 衡量真实任务完成能力；不能替代单元测试 |

审核链路：

```text
Builder（出题）→ Evaluator（结构/答案/判分/有效性）
→ Business Expert（业务合理性/语义/答案）→ Lead（最终审核）
```

Eval 不能只看字符串匹配，还要看事实、工具、推理、幻觉和安全边界。

“数据不存在”类问题允许引用真实事实，例如：

> 当前库只有 2 张相关表，但没有营销触达字段，因此无法统计触达人数。

不能因为出现数字 `2` 就判幻觉。应判断数字的语义角色：

- 事实引用：允许
- 有依据的计算结果：允许
- 编造的预测/结果：拒绝

禁止把不存在的业务结果编造成“预计 36 人”“大约 403 人”“估算 7 人”。

---

## 10. 测试、验证与日志

### 10.1 测试

- 使用 `pytest`，目录 `tests/`，文件 `test_*.py`
- 新功能同步添加测试，覆盖正常、边界、异常、安全路径

### 10.2 验证

普通修改：

```bash
python -m pytest tests/ -v
```

Agent 核心逻辑修改：

```text
pytest → Regression Eval → 必要时 Benchmark Eval
```

涉及 Tool Contract、Agent Loop、State、Planner、SQL、RAG、Verification、Data Ingestion 时，必须评估是否更新 Eval。

### 10.3 日志与 Observability

至少关注 Agent Run、Tool Call、Tool Result、Step、Error、Latency、Token/Cost。

日志输出控制台和文件，包含关键上下文，能定位失败原因。禁止通过删除日志“解决”问题。

### 10.4 不伪造验证结果

未实际执行验证，不得声称测试、Eval、功能或浏览器测试已通过。环境限制无法执行时，说明：未执行、原因、建议如何验证。

---

## 11. Git 工作原则

修改前 `git status`；修改后 `git diff` + `git status`。

禁止：擅自删除用户已有修改、覆盖未提交代码、强制 `reset`、强制 `checkout` 丢弃修改、未经授权修改其他分支。

Commit 保持单一职责。

---

## 12. 当前架构与 Runtime v0.2

当前阶段：

```text
RAG → Evaluation-driven RAG → Agent v0.1
→ Agent Eval v1.8.3 → Agent Runtime v0.2
```

Agent v0.1 已具备：State、Loop、Tool Contract、SQL Tool、Calculator Tool、RAG、Tool Calling、Step/Tool Call Limit、Timeout、Agent Eval。

Runtime v0.2 方向：

```text
Agent Runtime
├── State
├── Request ID
├── Execution ID
├── Timeout
├── Budget
├── Event Trace
├── Retry
├── Checkpoint
└── Observability
```

重点关注 `request_id` 幂等性、`execution_id` 执行身份、retry 新 `execution_id`、`parent_execution_id`、timeout/budget/cancellation、checkpoint/event trace。

优先复用项目已有的 Runtime / Stillroom 设计思想；不得为了快速实现破坏长期架构原则。

---

## 13. 安全定位与工程原则

第一阶段是 **Decision Support Agent**，不是 **Autonomous Business Agent**。

**可以：** 分析数据、查询数据、检索知识、发现异常、提出/验证假设、生成策略、给建议。

**暂时不能：** 自动执行营销活动、自动发送营销消息、自动修改/删除数据、无确认执行高风险操作。

所有涉及真实业务状态变化的操作，必须有明确权限与人工确认。

**不要过度工程化：** 第一版优先正确、可靠、可测试、可解释、可验证，而不是功能数量、复杂框架、多 Agent、复杂 Memory/Planner。简单方案能解决，就优先简单方案；不要为了用框架而用框架。

**LangChain / LangGraph：** 用于减少重复代码、管理 Agent Graph、Tool Calling、State Management；核心业务逻辑必须可理解。Tool Contract、State、Safety、Evaluation、Business Rules 不能完全隐藏在框架调用里。

---

## 14. 修改核心架构前必须回答

1. 为什么现在的设计不够？
2. 当前设计具体有什么问题？
3. 新设计解决什么问题？
4. 是否影响 Tool Contract / State / Agent Loop / Safety Boundary / Eval？
5. 是否需要迁移？如何回滚？

回答不了，不要直接重构。

---

## 15. 验收标准

```text
代码完成 → pytest → Agent Regression → 必要时 Benchmark
→ 检查 Git Diff → 检查日志 → 确认安全边界 → 最终交付
```

只有验证通过才能通知验收。交付时说明：修改内容、测试结果、Eval 结果、已知限制。存在失败项先修复，不得直接宣布完成。

---

## 16. 最高优先级

发生冲突时：

```text
安全 → 数据正确性 → 架构稳定性 → 可测试性
→ 可观测性 → 业务正确性 → 功能完整度 → 开发速度
```

不得为了“快速实现”牺牲数据安全、SQL 安全、Tool Contract、Eval、Agent 可观测性、架构一致性。

---

## 17. 最终目标

不是让 AI 看起来聪明，而是让它在真实企业数据环境中：

```text
Business Question → Agent Investigation
→ Data Ingestion / SQL / RAG
→ Reasoning → Verification → Evidence
→ Strategy → Human Decision
```

Agent 负责调查与决策辅助；系统负责安全、数据正确性、执行约束与验证。

---

## 18. 版本状态

| 项 | 当前值 |
|---|---|
| AGENTS.md | v1.1.0 |
| Product | Qianke Agent |
| Positioning | Enterprise Business Analysis & Strategy Decision Agent |
| Primary | 运营活动策略助手 |
| Secondary | 用户/客户分析、客服/销售坐席画像 |
| Data Ingestion | CSV v1 |
| Agent | v0.1 |
| Evaluation | Regression 20 / Benchmark 60 / Eval v1.8.3 |
| Next | Agent Runtime v0.2 |

## 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| 1.0 | - | 初版，29 节 |
| 1.1.0 | 2026-10-26 | 合并重复章节；统一标题/列表/代码块；压缩流程图；拆分“工作协议”与“产品设计”；更新 Eval 版本状态 |
