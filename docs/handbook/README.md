# Qianke Engine Architecture Handbook

> 企业级 Agent 与系统架构手册  
> 状态：60 篇正文已生成（6 分类 × 10）；官网 Docs 模块已实现，/docs 可访问  
> 第 1 篇为 V0.5.2 基线勘误稿；M5 条件通过，剩余 P2 继续迭代

## 这是什么

Architecture Handbook 是 Qianke Engine 的公开技术知识库：

```text
既解释 Qianke Engine 的真实架构与实现边界，
也系统讲解企业级 Agent、治理、系统设计、数据、可靠性与架构实践。
```

每篇文章都区分：

```text
已实现
开发中
已设计
规划中
理论知识
```

不把规划能力写成已上线功能，不用空泛名词替代工程事实。

## 学习路径

```text
L1 · 概念与原理
  为什么企业需要 Agent，而不是聊天机器人？
  ↓
L2 · 架构与技术方案
  Runtime、Tool、HITL、租户、队列、数据与评测如何组合？
  ↓
L3 · 工程实践
  Qianke Engine 的代码、限制、演进与真实取舍
```

## 分类

| 分类 | 内容 |
|---|---|
| [01 · Agent Architecture](01-agent-architecture/) | Agent Runtime、Orchestrator、State、Memory、Tool、任务生命周期 |
| [02 · Enterprise Governance](02-enterprise-governance/) | IAM、RBAC/ABAC、多租户、Tool 安全、HITL、Prompt Injection、审计 |
| [03 · System Architecture](03-system-architecture/) | 单体/微服务、Gateway、队列、调度、数据库、缓存、一致性 |
| [04 · Data & Knowledge](04-data-knowledge/) | RAG、向量库、混合检索、知识图谱、数据治理、语义层 |
| [05 · Reliability & Evaluation](05-reliability-evaluation/) | Eval、回归、Benchmark、Observability、SLO、故障恢复、CI/CD |
| [06 · Architecture Practice](06-architecture-practice/) | 需求分析、架构方法、模块拆分、选型、ADR、评审、技术债 |

## 当前进度

```text
信息架构：完成
完整目录：完成
内容规范：完成
Docs 实施方案：完成
第一篇：V0.5.2 基线勘误
60 篇正文：6 个分类 × 10 篇，已生成
官网 Docs 模块：已实现，/docs 可访问
后续内容维护：M5 条件通过，按剩余 P2 继续迭代
```

## 交付文档

```text
_meta/docs-current-state-audit.md           Docs 模块现状检查
_meta/information-architecture.md           信息架构、完整目录、内容规范、第一阶段规划
_meta/docs-module-implementation-plan.md    Docs 技术实施方案与验收标准
01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md
                                            第一篇基线勘误
01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md
                                            第一篇冻结候选
01-agent-architecture/02-agent-vs-enterprise-agent.md
                                            第一阶段第 2 篇
01-agent-architecture/03-agent-runtime.md
                                            第一阶段第 3 篇
```

## 第一篇

- [企业级 Agent 架构概述 V0.1（历史审核基线）](_meta/versions/01-enterprise-agent-architecture.md)
- [企业级 Agent 架构概述 V0.2（修订稿，不覆盖 V0.1）](_meta/versions/01-enterprise-agent-architecture-v0.2.md)
- [企业级 Agent 架构设计 V0.3（按 11111.md 学习型结构重写）](_meta/versions/01-enterprise-agent-architecture-v0.3.md)
- [企业级 Agent 架构设计 V0.4（按 V0.3 审核意见修订）](_meta/versions/01-enterprise-agent-architecture-v0.4.md)
- [企业级 Agent 架构设计 V0.5（按 V0.4 审核意见修订）](_meta/versions/01-enterprise-agent-architecture-v0.5.md)
- [企业级 Agent 架构设计 V0.5.2（基线错误码勘误）](01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md)
- [V0.5 → V0.5.1 微调记录](_meta/reviews/01-enterprise-agent-architecture-v0.5-to-v0.5.1-revision-log.md)
- [V0.4 → V0.5 修订记录与未解决问题](_meta/reviews/01-enterprise-agent-architecture-v0.4-to-v0.5-revision-log.md)
- [V0.3 → V0.4 修订记录与未解决问题](_meta/reviews/01-enterprise-agent-architecture-v0.3-to-v0.4-revision-log.md)
- [V0.1 技术审核报告](_meta/reviews/01-enterprise-agent-architecture-v0.1-technical-review.md)

内容覆盖：

```text
普通 Agent 与企业级 Agent 的差距
Agent Runtime 的预算/超时/重试/幂等
Tool Contract 与 Tool 授权
证据优先与 Human-in-the-loop
单 Agent vs Multi-Agent
方案对比、Qianke 真实实现、当前限制、常见误区
```

## 第一阶段正文

- [第 1 篇 · 企业级 Agent 架构设计 V0.5.2（基线错误码勘误）](01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md)
- [第 2 篇 · 普通 Agent 与企业级 Agent 的区别](01-agent-architecture/02-agent-vs-enterprise-agent.md)
- [第 3 篇 · Agent Runtime 设计](01-agent-architecture/03-agent-runtime.md)
- [第 4 篇 · Agent Orchestrator 设计](01-agent-architecture/04-agent-orchestrator.md)
- [第 5 篇 · Multi-Agent 协作架构](01-agent-architecture/05-multi-agent-collaboration.md)
- [第 6 篇 · Agent State 状态管理](01-agent-architecture/06-agent-state-management.md)
- [第 7 篇 · Agent Memory 记忆系统](01-agent-architecture/07-agent-memory.md)
- [第 8 篇 · Task Manager 任务生命周期管理](01-agent-architecture/08-task-lifecycle-management.md)
- [第 9 篇 · Agent 工具调用机制](01-agent-architecture/09-agent-tool-calling.md)
- [第 10 篇 · Agent 执行流程与异常处理](01-agent-architecture/10-agent-execution-reliability.md)

## 官网 Docs 模块（已实现）

```text
URL：/docs
布局：左侧分类导航 + 中间正文 + 右侧 TOC
能力：静态 HTML、搜索、代码高亮/复制、Mermaid、上/下一篇
来源：docs/handbook/*.md
构建：docs-site（VitePress 静态站）
发布：FastAPI 挂载 /docs
```

本地构建：

```powershell
cd docs-site
npm run build
```

FastAPI 在 `docs-site/.vitepress/dist` 存在时自动挂载 `/docs`；
Swagger 文档已迁到 `/api/docs`，避免和公开 Handbook 冲突。

具体见：

- [Docs 现状检查](_meta/docs-current-state-audit.md)
- [信息架构与内容规范](_meta/information-architecture.md)
- [Docs 实施方案](_meta/docs-module-implementation-plan.md)

## 审核状态

```text
本目录内容尚未发布到官网
本次未修改官网代码、路由或构建配置
等待人工审核后再进入 Docs 模块实施和后续文章生成
```





- [M5 最终质量验收报告](_meta/reviews/2026-11-23-final-quality-acceptance.md)
