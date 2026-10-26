

>Qianke Agent 项目级 AI Coding Agent 工作协议
>Version: 1.0
>Status: Active

⸻

## 1. 项目定位

Qianke Agent 是一个面向企业经营分析与策略决策的 AI Agent。

项目不是通用聊天机器人，也不是单纯的 RAG Demo。

核心目标：

数据接入
    ↓
问题理解
    ↓
任务规划
    ↓
数据 / 知识检索
    ↓
多步分析
    ↓
证据验证
    ↓
策略生成
    ↓
可解释结果

1.1 核心业务场景

P0：运营活动策略助手

主要场景：

* 活动效果分析
* 活动复盘
* 用户分群
* 活动目标人群分析
* 活动异常分析
* 活动策略建议
* 活动原因调查
* 活动结果验证

P1：用户 / 客户分析

包括：

* 用户画像
* 用户价值分析
* 用户流失分析
* 用户召回分析
* 用户分群
* 用户行为分析

P1：客服 / 销售坐席画像助手

包括：

* 坐席画像
* 服务能力分析
* 销售能力分析
* 绩效分析
* 优势 / 短板分析
* 培训与改进建议

⸻

## 2. AI 数据接入

Qianke Agent 第一版必须具备基础的数据接入能力。

第一阶段只支持 CSV。

目标不是简单的“CSV 上传”，而是：

CSV
 ↓
Schema Inference
 ↓
Data Profiling
 ↓
Validation
 ↓
Preview
 ↓
Human Confirmation
 ↓
Database Import
 ↓
Dataset Registry

2.1 LLM 与确定性代码职责边界

LLM 可以负责：

* 理解数据含义
* 字段语义识别
* Schema 映射建议
* 数据集描述生成
* 数据问题解释
* 数据接入流程编排

LLM 不负责：

* 直接执行数据库写入
* 绕过数据校验
* 绕过权限检查
* 绕过用户确认
* 任意生成并执行 DDL / DML

真正的数据处理、校验、事务、写入必须由确定性代码完成。

⸻

## 3. Agent 的核心设计原则

Qianke Agent 的核心不是：

Question → Answer

而是：

Business Question
        ↓
Investigation
        ↓
Evidence
        ↓
Hypothesis
        ↓
Verification
        ↓
Conclusion
        ↓
Strategy

Agent 必须优先寻找证据，而不是直接生成结论。

当证据不足时：

不得猜测
不得编造
不得使用未经验证的数据

应该明确告诉用户：

* 当前已知信息
* 缺少什么信息
* 为什么无法得出结论
* 下一步需要什么数据

⸻

## 4. Agent 工作原则

所有 AI Coding Agent 在修改项目之前必须遵循：

Understand
    ↓
Plan
    ↓
Confirm
    ↓
Implement
    ↓
Test
    ↓
Eval
    ↓
Verify

### 4.1 理解需求

首先确认：

* 用户真正想解决的问题
* 涉及哪些模块
* 是否涉及架构变化
* 是否涉及数据模型变化
* 是否涉及安全边界
* 是否涉及 Agent 行为变化
* 是否影响已有 Eval

### 4.2 制定方案

开始修改代码前，应说明：

* 实现思路
* 涉及文件
* 修改范围
* 测试方案
* 风险
* 是否影响现有架构

### 4.3 等待确认

涉及代码、架构、数据模型、安全边界的修改：

必须等待用户明确确认后再实施。

禁止：

* 自行扩大需求
* 自行重构无关代码
* 自行改变架构
* 自行删除现有能力

⸻

## 5. 需求存在歧义时

如果存在：

* 描述不清
* 关键参数缺失
* 多种合理解释
* 数据结构不明确
* 安全边界不明确
* 业务规则不明确

必须先询问。

禁止通过猜测解决关键需求。

⸻

## 6. 架构保护原则

以下内容属于核心架构，不允许 AI Coding Agent 在没有明确授权的情况下擅自修改：

Agent Loop

LLM
 ↓
Tool Call
 ↓
Tool Execution
 ↓
Observation
 ↓
LLM
 ↓
...
 ↓
Final Answer

Agent State

至少保持：

* messages
* step_count
* tool_call_count
* status
* error
* started_at

Tool Contract

Tool 必须具备明确的：

* name
* description
* input schema
* structured result
* structured error

ToolResult

工具错误必须结构化。

禁止依赖：

if "xxx" in error_message

判断业务错误类型。

优先使用：

error.code

⸻

## 7. 当前核心 Tools

当前 Agent 的基础工具体系包括：

Tools
├── RAG Tool
├── SQL Tool
└── Calculator

未来增加：

├── Data Ingestion
├── Dataset Inspection
├── Dataset Profiling
└── ...

新增 Tool 必须：

1. 定义明确输入 Schema
2. 定义结构化输出
3. 定义结构化错误
4. 明确权限边界
5. 添加单元测试
6. 添加 Agent Eval 场景
7. 不破坏现有 Tool Contract

⸻

## 8. SQL 安全边界

SQL Tool 属于高风险 Tool。

必须保持：

* SELECT / WITH 为主要允许操作
* 禁止危险 SQL
* 表白名单
* LIMIT 限制
* Read-only 数据库连接
* Statement Timeout
* Fetch Limit

Agent 不得通过自然语言绕过 SQL 安全限制。

禁止：

DROP
DELETE
UPDATE
INSERT
ALTER
TRUNCATE

以及任何其他未经明确授权的数据库写操作。

⸻

## 9. 数据接入安全边界

CSV 导入必须经过：

Parse
 ↓
Schema Validation
 ↓
Data Profiling
 ↓
Validation
 ↓
Preview
 ↓
Human Confirmation
 ↓
Transaction
 ↓
Import

任何情况下：

未经用户确认不得直接执行最终入库。

导入失败必须：

* 保证事务一致性
* 不产生部分成功的脏数据
* 返回结构化错误
* 保留必要日志

⸻

## 10. Dataset Registry

数据接入体系应该通过 Dataset Registry 管理数据集。

数据集至少应具有：

* dataset_id
* name
* description
* schema
* source
* row_count
* created_at
* owner
* status
* schema_version
* content_hash

Agent 不应该假设数据库中存在某张表。

应该优先通过 Dataset Registry 了解当前可用数据。

⸻

## 11. RAG 原则

RAG 是 Agent 的知识工具，而不是 Agent 本身。

RAG 主要负责：

* 企业知识
* 活动规则
* KPI 定义
* 业务口径
* 运营规范
* 坐席评价标准
* 业务知识

Agent 应根据任务决定是否调用 RAG。

禁止为了“看起来用了 RAG”而强制调用 RAG。

⸻

## 12. Agent Evaluation

Agent 的行为必须通过 Evaluation 验证。

当前 Eval 分为：

Regression Set
    20 questions
Benchmark Set
    40 questions

12.1 Regression Set

每次 Agent 核心逻辑发生变化后优先运行。

目的：

防止已有能力发生回归。

12.2 Benchmark Set

用于衡量 Agent 当前整体能力。

目的：

衡量 Agent 的真实任务完成能力，而不是单元测试通过率。

⸻

## 13. Eval 审核机制

Agent Eval 使用多角色审核：

Builder
   ↓
Evaluator
   ↓
Business Expert
   ↓
Lead

Builder

负责构造测试问题。

Evaluator

负责检查：

* 数据结构
* 标准答案
* 判定逻辑
* 测试有效性

Business Expert

负责检查：

* 电商业务合理性
* 问题真实性
* 业务语义
* 业务答案合理性

Lead

负责最终审核和接受。

⸻

## 14. Eval 的重要原则

不能只检查：

答案字符串是否匹配

应该关注：

事实是否正确
工具是否正确
推理是否合理
是否产生幻觉
是否遵守安全边界

对于“数据不存在”的问题：

正确答案可以包含真实存在的数据事实。

例如：

当前数据库只有 2 张相关表，
但不存在营销触达字段，
因此无法统计触达人数。

这不应该因为出现数字 2 而被判定为幻觉。

评测应该判断：

数字在答案中的语义角色。

禁止将不存在的业务结果编造成：

预计 36 人
大约 403 人
估算 7 人

⸻

## 15. 测试要求

项目使用 pytest。

测试目录：

tests/

测试文件遵循：

test_*.py

新功能必须同步添加测试。

至少覆盖：

* 正常路径
* 关键边界
* 异常路径
* 安全边界

⸻

## 16. 修改后的验证流程

普通代码修改：

python -m pytest tests/ -v

Agent 核心逻辑修改：

pytest
 ↓
Regression Eval
 ↓
必要时 Benchmark Eval

如果涉及：

* Tool Contract
* Agent Loop
* State
* Planner
* SQL
* RAG
* Verification
* Data Ingestion

必须评估是否需要更新 Agent Eval。

⸻

## 17. 日志与 Observability

项目必须具备足够的日志和可观测性。

至少关注：

Agent Run
Tool Call
Tool Result
Step
Error
Latency
Token / Cost

日志应该：

* 输出到控制台
* 输出到文件
* 包含关键上下文
* 支持定位失败原因

禁止通过删除日志来“解决”程序问题。

日志应优先用于定位：

Agent 为什么失败？
调用了什么 Tool？
Tool 返回什么？
Agent 为什么继续 / 停止？
最终答案依据什么？

⸻

## 18. 不允许伪造验证结果

AI Coding Agent 不得声称：

* “测试已经通过”
* “Eval 已通过”
* “功能已验证”
* “浏览器测试正常”

除非确实执行了对应验证。

如果环境限制导致无法运行：

必须明确说明：

未执行
原因
建议如何验证

⸻

## 19. Git 工作原则

修改前先检查：

git status

修改后检查：

git diff
git status

禁止：

* 擅自删除用户已有修改
* 覆盖未提交代码
* 强制 reset
* 强制 checkout 丢弃修改
* 未经授权修改其他分支

Commit 应保持单一职责。

⸻

## 20. 当前架构阶段

当前项目处于：

RAG
  ↓
Evaluation-driven RAG
  ↓
Agent v0.1
  ↓
Agent Eval v0.1
  ↓
Agent Runtime v0.2

当前 Agent v0.1 已经具备：

* Agent State
* Agent Loop
* Tool Contract
* SQL Tool
* Calculator Tool
* RAG 能力
* Tool Calling
* Step Limit
* Tool Call Limit
* Timeout 基础机制
* Agent Eval

⸻

## 21. Runtime v0.2 方向

后续 Agent Runtime 应逐步加入：

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

设计应优先复用项目已有的 Runtime / Stillroom 设计思想。

尤其关注：

* request_id 幂等性
* execution_id 执行身份
* retry 的新 execution_id
* parent_execution_id
* timeout
* budget
* cancellation
* checkpoint
* event trace

不得为了快速实现而破坏这些长期架构原则。

⸻

## 22. Agent 的安全原则

Qianke Agent 第一阶段定位为：

Decision Support Agent

而不是：

Autonomous Business Agent

因此：

Agent 可以：

* 分析数据
* 查询数据
* 检索知识
* 发现异常
* 提出假设
* 验证假设
* 生成策略
* 给出建议

Agent 暂时不能：

* 自动执行营销活动
* 自动发送营销消息
* 自动修改业务数据
* 自动删除数据
* 无确认执行高风险操作

所有涉及真实业务状态变化的操作必须具有明确的权限与人工确认机制。

⸻

## 23. 不要过度工程化

第一版优先：

正确
可靠
可测试
可解释
可验证

而不是：

功能数量
复杂框架
多 Agent
复杂 Memory
复杂 Planner

如果简单方案能够解决问题：

优先选择简单方案。

不要为了使用某个框架而使用框架。

⸻

## 24. LangChain / LangGraph 使用原则

框架用于：

* 减少重复代码
* 管理 Agent Graph
* Tool Calling
* State Management

但核心业务逻辑必须保持可理解。

不得让核心业务规则完全隐藏在框架调用中。

尤其：

Tool Contract
State
Safety
Evaluation
Business Rules

必须保持清晰、可测试。

⸻

## 25. 修改现有架构前必须回答

如果准备修改 Agent 核心架构，必须先回答：

1. 为什么现在的设计不够？
2. 当前设计有什么具体问题？
3. 新设计解决什么问题？
4. 是否影响 Tool Contract？
5. 是否影响 State？
6. 是否影响 Agent Loop？
7. 是否影响 Safety Boundary？
8. 是否影响 Eval？
9. 是否需要迁移？
10. 如何回滚？

如果无法回答，不应该直接进行架构重构。

⸻

## 26. 验收标准

功能完成后必须：

代码完成
    ↓
pytest
    ↓
Agent Regression
    ↓
必要时 Benchmark
    ↓
检查 Git Diff
    ↓
检查日志
    ↓
确认安全边界
    ↓
最终交付

只有验证通过后才能通知用户验收。

交付时简要说明：

修改内容
测试结果
Eval 结果
已知限制

如果存在失败项：

先修复，不得直接宣布完成。

⸻

## 27. 当前项目的最高优先级原则

当不同需求发生冲突时，优先级如下：

安全
 ↓
数据正确性
 ↓
架构稳定性
 ↓
可测试性
 ↓
可观测性
 ↓
业务正确性
 ↓
功能完整度
 ↓
开发速度

不得为了：

“快速实现”

牺牲：

* 数据安全
* SQL 安全
* Tool Contract
* Eval
* Agent 可观测性
* 架构一致性

⸻

## 28. 最终设计原则

Qianke Agent 的核心目标不是：

让 AI 看起来很聪明。

而是：

让 AI 在真实企业数据环境中，能够自主调查问题、调用工具、获取证据、验证假设，并给出可靠、可解释、可复现的经营分析与策略建议。

最终目标：

                    Qianke Agent
                         │
                 Business Question
                         ↓
                  Agent Investigation
                         ↓
          ┌──────────────┼──────────────┐
          ↓              ↓              ↓
      Data Ingestion    SQL            RAG
          │              │              │
          └──────────────┼──────────────┘
                         ↓
                     Reasoning
                         ↓
                    Verification
                         ↓
                    Evidence
                         ↓
                    Strategy
                         ↓
                  Human Decision

Agent 负责调查与决策辅助。

系统负责安全、数据正确性、执行约束与验证。

⸻

## 29. 当前版本状态

AGENTS.md
Version: 1.0
Status: Active
Product:
Qianke Agent
Positioning:
Enterprise Business Analysis & Strategy Decision Agent
Primary:
运营活动策略助手
Secondary:
用户 / 客户分析
客服 / 销售坐席画像
Data Ingestion:
CSV v1
Agent:
v0.1
Evaluation:
Regression Set 20
Benchmark Set 40
Next:
Agent Runtime v0.2