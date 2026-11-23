# Qianke Engine Architecture Handbook · 信息架构与内容规范

> 状态：规划稿，等待审核  
> 日期：2026-11-23  
> 名称：Qianke Engine Architecture Handbook（企业级 Agent 与系统架构手册）  
> 目标：既能解释 Qianke Engine 的真实架构，也能作为企业级 Agent / 系统设计的学习体系

## 1. Handbook 定位

```text
不是产品营销页
不是零散博客
不是内部代码注释的搬运
不是只讲概念的“架构鸡汤”
```

而是：

```text
可学习：从 L1 原理到 L2 设计到 L3 工程实践
可核对：每个 Qianke 结论对应代码/文档/测试
可维护：统一元数据、目录、状态、引用和审核流程
可发布：官网 Docs 模块直接消费的静态文档
```

### 1.1 读者

| 读者 | 需求 | 入口 |
|---|---|---|
| 初学者 / 学生 | 建立 Agent 与企业系统完整认知 | L1 概念与原理 |
| 后端 / Agent 工程师 | 看懂架构、取舍和实现 | L2 架构与技术方案 |
| Tech Lead / 架构师 | 评审方案、落地治理与可靠性 | L2 + L3 |
| 企业技术决策者 | 判断 Qianke 的实现边界与可借鉴性 | 各篇“Qianke Engine 实践” |
| 开源贡献者 | 找到对应模块和扩展点 | 代码路径 + ADR + 延伸阅读 |

## 2. 三层学习结构

每篇文章内部按三层组织，但**不牺牲工程细节**：

| 层级 | 对应文章章节 | 目标 |
|---|---|---|
| L1 · 概念与原理 | 核心问题 / 基础原理 | 理解“为什么需要” |
| L2 · 架构与技术方案 | 架构设计 / 工程实现 / 企业级要求 / 方案对比 | 理解“应该怎么设计” |
| L3 · 工程实践与案例 | Qianke Engine 实践 / 常见问题 / 总结 | 理解“真实项目怎么落地” |

阅读路径：

```text
L1 顺序阅读 → 建立术语和边界
L2 按主题阅读 → 掌握架构与取舍
L3 对照代码阅读 → 看真实实现、限制和演进
```

## 3. 文档站信息架构

### 3.1 顶层页面

```text
/docs
```

内容：

```text
Handbook 标题与一句话定位
学习路径（L1 / L2 / L3）
六个分类入口
状态说明（已实现 / 开发中 / 已设计 / 规划中 / 理论知识）
最新更新
全站搜索
```

### 3.2 分类页

```text
/docs/agent-architecture/
/docs/enterprise-governance/
/docs/system-architecture/
/docs/data-knowledge/
/docs/reliability-evaluation/
/docs/architecture-practice/
```

每个分类页：

```text
分类说明
文章列表（序号、标题、状态、更新时间、摘要）
推荐阅读顺序
前置知识
```

### 3.3 文章页

```text
/docs/{section}/{slug}
```

布局：

```text
顶部：Handbook 标识 / 搜索 / GitHub
左侧：分组侧边栏（当前分类展开）
中间：文章正文
右侧：本页目录 TOC
底部：上一篇 / 下一篇 / 相关文章
```

文章头：

```text
分类 · 序号
标题
摘要
文档状态 / 实现状态 / 版本 / 更新时间 / 预计阅读时间
前置知识
```

### 3.4 搜索

```text
全站搜索：标题 + 正文 + 标签
快捷键：/ 或 Ctrl/Cmd+K
结果高亮标题、分类、摘要
静态索引，不依赖后端服务
```

推荐实现：

```text
VitePress 内置 local search（MiniSearch）
或 Pagefind 静态索引
```

不在第一阶段引入 Algolia 等外部 SaaS。

### 3.5 页面状态

文档状态（写作状态）：

```text
已实现    当前代码中已有并验证
开发中    已经开始开发，未完成
已设计    方案已确定，未实现
规划中    未来可能建设
理论知识  通用架构原理，不对应 Qianke 功能
```

每篇文章只允许一个主状态；正文中出现混合状态时，在对应小节单独标注，不得把规划写成已实现。

## 4. 完整目录

共 6 个分类 × 10 篇。

### 01 · Agent Architecture

| # | 标题 | slug | 文档状态 |
|---:|---|---|---|
| 1 | 企业级 Agent 架构概述 | `enterprise-agent-architecture` | 草稿（本次首篇） |
| 2 | 普通 Agent 与企业级 Agent 的区别 | `agent-vs-enterprise-agent` | 规划中 |
| 3 | Agent Runtime 设计 | `agent-runtime` | 规划中 |
| 4 | Agent Orchestrator 设计 | `agent-orchestrator` | 规划中 |
| 5 | Multi-Agent 协作架构 | `multi-agent-collaboration` | 规划中 |
| 6 | Agent State 状态管理 | `agent-state-management` | 规划中 |
| 7 | Agent Memory 记忆系统 | `agent-memory` | 规划中 |
| 8 | Task Manager 任务生命周期管理 | `task-lifecycle-management` | 规划中 |
| 9 | Agent 工具调用机制 | `agent-tool-calling` | 规划中 |
| 10 | Agent 执行流程与异常处理 | `agent-execution-reliability` | 规划中 |

### 02 · Enterprise Governance

| # | 标题 | slug | 文档状态 |
|---:|---|---|---|
| 1 | 企业级身份认证与权限管理 | `identity-and-access-management` | 规划中 |
| 2 | RBAC 与 ABAC 权限模型 | `rbac-abac` | 规划中 |
| 3 | 多租户隔离架构 | `multi-tenancy-isolation` | 规划中 |
| 4 | Agent 权限治理 | `agent-permission-governance` | 规划中 |
| 5 | Tool Gateway 安全设计 | `tool-gateway-security` | 规划中 |
| 6 | Human-in-the-loop 人工审批 | `human-in-the-loop` | 规划中 |
| 7 | Prompt Injection 防护 | `prompt-injection-defense` | 规划中 |
| 8 | 数据隐私与脱敏 | `data-privacy-redaction` | 规划中 |
| 9 | 操作审计与追踪 | `operation-audit-tracing` | 规划中 |
| 10 | 企业级安全体系设计 | `enterprise-security-architecture` | 规划中 |

### 03 · System Architecture

| # | 标题 | slug | 文档状态 |
|---:|---|---|---|
| 1 | 企业级系统架构设计方法 | `enterprise-system-design` | 规划中 |
| 2 | 模块化单体与微服务架构 | `modular-monolith-vs-microservices` | 规划中 |
| 3 | API Gateway 设计 | `api-gateway` | 规划中 |
| 4 | 服务间通信 | `service-communication` | 规划中 |
| 5 | 消息队列与事件驱动架构 | `message-queue-event-driven` | 规划中 |
| 6 | 分布式任务调度 | `distributed-task-scheduling` | 规划中 |
| 7 | 数据库架构设计 | `database-architecture` | 规划中 |
| 8 | 缓存系统设计 | `cache-system-design` | 规划中 |
| 9 | 分布式事务与数据一致性 | `distributed-transactions-consistency` | 规划中 |
| 10 | 系统扩展性设计 | `system-scalability` | 规划中 |

### 04 · Data & Knowledge

| # | 标题 | slug | 文档状态 |
|---:|---|---|---|
| 1 | RAG 系统架构 | `rag-architecture` | 规划中 |
| 2 | 向量数据库原理 | `vector-database` | 规划中 |
| 3 | 混合检索与重排序 | `hybrid-retrieval-reranking` | 规划中 |
| 4 | Knowledge Graph 知识图谱 | `knowledge-graph` | 规划中 |
| 5 | 企业数据治理 | `enterprise-data-governance` | 规划中 |
| 6 | 数据接入与 ETL | `data-ingestion-etl` | 规划中 |
| 7 | OLTP 与 OLAP | `oltp-olap` | 规划中 |
| 8 | 指标语义层设计 | `metric-semantic-layer` | 规划中 |
| 9 | 数据血缘与质量管理 | `data-lineage-quality` | 规划中 |
| 10 | 企业级知识库架构 | `enterprise-knowledge-base` | 规划中 |

### 05 · Reliability & Evaluation

| # | 标题 | slug | 文档状态 |
|---:|---|---|---|
| 1 | Agent Evaluation 评测体系 | `agent-evaluation` | 规划中 |
| 2 | Agent 自动化测试 | `agent-automated-testing` | 规划中 |
| 3 | Regression Test 回归测试 | `agent-regression-test` | 规划中 |
| 4 | Benchmark 基准评测 | `agent-benchmark` | 规划中 |
| 5 | Agent Observability 可观测性 | `agent-observability` | 规划中 |
| 6 | 日志、指标与链路追踪 | `logs-metrics-tracing` | 规划中 |
| 7 | SRE 与 SLO | `sre-slo` | 规划中 |
| 8 | 重试、熔断与降级 | `retry-circuit-breaker-degradation` | 规划中 |
| 9 | 故障恢复与灾难恢复 | `failure-recovery-dr` | 规划中 |
| 10 | CI/CD 与灰度发布 | `cicd-canary-release` | 规划中 |

### 06 · Architecture Practice

| # | 标题 | slug | 文档状态 |
|---:|---|---|---|
| 1 | 如何进行系统需求分析 | `requirements-analysis` | 规划中 |
| 2 | 如何进行架构设计 | `architecture-design-method` | 规划中 |
| 3 | 如何拆分系统模块 | `module-decomposition` | 规划中 |
| 4 | 如何设计模块依赖关系 | `module-dependencies` | 规划中 |
| 5 | 如何进行技术选型 | `technology-selection` | 规划中 |
| 6 | ADR 架构决策记录 | `architecture-decision-records` | 规划中 |
| 7 | 架构评审方法 | `architecture-review` | 规划中 |
| 8 | 系统性能分析 | `performance-analysis` | 规划中 |
| 9 | 技术债务治理 | `technical-debt` | 规划中 |
| 10 | 企业级项目架构案例 | `enterprise-architecture-case` | 规划中 |

## 5. 内容元数据规范

每篇 Markdown 必须带 frontmatter：

```yaml
---
title: 企业级 Agent 架构概述
description: 一句话说明本文解决什么问题
section: Agent Architecture
section_order: 1
order: 1
slug: enterprise-agent-architecture
doc_status: 草稿
implementation_status: 已实现 + 已设计
version: 0.1.0
updated: 2026-11-23
reading_minutes: 18
prerequisites:
  - LLM 基础
  - Tool Calling
  - HTTP 与异步任务
tags:
  - agent
  - runtime
  - enterprise
related:
  - agent-vs-enterprise-agent
  - agent-runtime
---
```

字段约束：

```text
title          必填，和 H1 一致
description    必填，80–160 字
section        必填，六个分类之一
section_order  必填，1–6
order          必填，1–10
slug           必填，小写 kebab-case，全局唯一
doc_status     必填，草稿/已实现/开发中/已设计/规划中/理论知识
implementation_status  可选；文章涉及 Qianke 功能时必填
version        必填，SemVer（文档版本，不是产品版本）
updated        必填，YYYY-MM-DD
reading_minutes 可选
prerequisites  可选
tags           可选
related        必填至少 1 个
```

## 6. 单篇内容模板

每篇文章严格按以下 11 节：

```text
1. 文档基本信息
2. 核心问题
3. 基础原理
4. 架构设计
5. 工程实现
6. 企业级设计要求
7. 方案对比
8. Qianke Engine 实践
9. 常见问题与设计误区
10. 本篇总结
11. 延伸阅读
```

### 6.1 各节最低要求

| 节 | 最低要求 |
|---|---|
| 1 基本信息 | 分类/版本/状态/更新时间/前置知识 |
| 2 核心问题 | 问题、业务背景、为什么企业级需要 |
| 3 基础原理 | 术语、机制、公式/伪代码/流程，解释为什么 |
| 4 架构设计 | 模块、职责、依赖、数据流、控制流，至少 1 张图 |
| 5 工程实现 | 技术选型、目录、接口、数据模型、代码示例、异常、测试 |
| 6 企业级要求 | 安全/扩展/维护/可用/性能/可观测/一致性/恢复，逐项说明 |
| 7 方案对比 | 至少 2 个方案，优缺点和适用场景 |
| 8 Qianke 实践 | 对应模块、实现程度、为什么、未来演进；无实现则明确理论/规划 |
| 9 常见问题 | 真实工程误区 + 解决方法 |
| 10 总结 | 3–5 条核心结论 |
| 11 延伸阅读 | 真实可访问的权威资料 + 内部文档 |

### 6.2 事实与状态规则

```text
1. “已实现”必须能指向代码路径、测试或运行证据
2. “开发中”必须说明当前进度和剩余工作
3. “已设计”必须说明设计文档/ADR，不得暗示已上线
4. “规划中”不得写成未来确定能力
5. “理论知识”不得包装成 Qianke 已采用
6. 外部链接必须真实可访问；不能编造论文/链接
7. 架构图必须与正文一致；图号和图注必须有
8. 代码示例必须与当前代码风格一致；不确定的示例标注伪代码
```

### 6.3 写作风格

```text
先问题，后原理，再方案
先结论，后论证
重要决策回答：为什么/不采用会怎样/替代方案/为什么选这个
避免堆砌名词
避免“赋能、魔法、全链路、一键起飞”等空话
中文为主，保留关键英文术语
每篇可独立阅读，但必须有交叉链接
```

## 7. 第一阶段：Agent Architecture 详细规划

第一阶段 10 篇，建议按以下顺序生成。

| 顺序 | 文章 | 核心问题 | 主要 Qianke 依据 | 关键图 |
|---:|---|---|---|---|
| 1 | 企业级 Agent 架构概述 | 企业级 Agent 与普通聊天机器人的边界是什么？ | `docs/agent.md`、`AGENTS.md`、`docs/agent-design-current-vs-target.md` | 总体分层图、请求时序图 |
| 2 | 普通 Agent 与企业级 Agent 的区别 | 为什么 demo Agent 不能直接进企业？ | 当前限制、Eval、安全边界 | 能力对比矩阵 |
| 3 | Agent Runtime 设计 | 状态、预算、超时、重试、幂等如何成为运行时约束？ | `agent/state.py`、`service.py`、`docs/agent.md` §3 | Runtime 组件图、状态机 |
| 4 | Agent Orchestrator 设计 | 单 Agent Loop、Graph、Worker 如何编排？ | `agent/loop.py`、`superagent/` | 编排流程图 |
| 5 | Multi-Agent 协作架构 | 什么时候需要多 Agent？如何避免为了多而多？ | 三端目标设计、当前单 Agent 限制 | 单/多 Agent 对比图 |
| 6 | Agent State 状态管理 | 哪些状态必须持久化？如何避免上下文污染？ | `AgentState`、LangGraph checkpointer | State 生命周期图 |
| 7 | Agent Memory 记忆系统 | 短期/长期/业务记忆如何分层与治理？ | `docs/product/agent-memory-context.md` | 记忆分层图 |
| 8 | Task Manager 任务生命周期管理 | 任务如何创建、领取、执行、重试、审批、审计？ | Super-agent work item、job queue | 任务状态机 |
| 9 | Agent 工具调用机制 | Tool Contract、授权、错误、注入防护如何设计？ | `agent/tool.py`、`registry.py`、SQL/RAG Tool | Tool 调用时序图 |
| 10 | Agent 执行流程与异常处理 | 超时、取消、重试、部分失败如何收口？ | Runtime v0.2.2、wall timeout、known limits | 异常决策树 |

### 7.1 第一阶段完成标准

```text
[ ] 10 篇目录和摘要完成
[ ] 每篇有 frontmatter、状态、前置知识
[ ] 第 1 篇完整正文通过技术审核
[ ] 其余 9 篇至少完成详细大纲
[ ] 每篇至少 1 张 Mermaid 图
[ ] Qianke 实践事实全部可追溯到代码/文档
[ ] 交叉链接无死链
[ ] 术语表初版
```

### 7.2 本次交付范围

```text
1. 本文档：完整目录 + 内容规范 + 第一阶段规划
2. 第一篇完整文章：企业级 Agent 架构概述
3. Docs 技术实施方案和验收标准
```

其余 9 篇只做规划，不在本次批量生成。

## 8. 文档之间的关联

最低要求：

```text
每篇 related 至少 1 篇
第一阶段文章之间形成阅读链
治理/可靠性文章引用 Agent Runtime
数据文章引用 RAG/SQL Tool
实践文章引用 ADR 与案例
```

禁止：

```text
同一概念在不同文章给出互相矛盾的定义
重复大段内容
一篇文档同时承担产品介绍、API 文档、教程三种角色
```

## 9. 内容审核流程

```text
Draft
→ 技术事实核对（代码/文档/测试）
→ 架构评审（是否自洽、是否有替代方案）
→ 编辑审校（术语/结构/链接）
→ 状态标注确认
→ 发布
```

审核人：

```text
技术负责人：事实与架构
文档负责人：结构、链接、术语
产品负责人：产品边界与对外表述
```

## 10. URL 与 slug 规则

```text
/docs/{section}/{slug}
```

示例：

```text
/docs/agent-architecture/enterprise-agent-architecture
/docs/enterprise-governance/multi-tenancy-isolation
/docs/data-knowledge/rag-architecture
```

规则：

```text
section 使用固定英文 kebab-case
slug 全局唯一、稳定、不随标题改
文章内锚点使用标题 slug
旧 slug 变更必须保留重定向
```

## 11. 验收标准（文档内容）

```text
[ ] 结构完整（11 节）
[ ] 技术原理准确
[ ] 架构图与正文一致
[ ] 关键模块职责清晰
[ ] 工程实现可操作
[ ] 企业级要求有实际解释
[ ] Qianke 现状描述准确
[ ] 状态标注符合事实
[ ] 外部引用可访问
[ ] 与其他文档无冲突
[ ] Markdown 格式正确
[ ] 官网 Docs 可正常渲染
```
