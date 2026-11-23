---
layout: home

hero:
  name: Qianke Engine Architecture Handbook
  text: 企业级 Agent 与系统架构手册
  tagline: 从 ReAct 到可治理的智能体系统。理解原理、架构、工程边界与 Qianke Engine 的真实实践。
  actions:
    - theme: brand
      text: 开始阅读
      link: /agent-architecture/01-enterprise-agent-architecture-v0.5.2
    - theme: alt
      text: 查看完整目录
      link: /agent-architecture/
    - theme: alt
      text: 返回官网
      link: https://qianke.qiankeagent.com/

features:
  - title: Agent Architecture
    details: Runtime、Orchestrator、State、Memory、Tool、任务生命周期。
    link: /agent-architecture/
  - title: Enterprise Governance
    details: IAM、RBAC/ABAC、多租户、Tool 安全、HITL、Prompt Injection、审计。
    link: /enterprise-governance/
  - title: System Architecture
    details: 单体/微服务、Gateway、队列、调度、数据库、缓存与一致性。
    link: /system-architecture/
  - title: Data & Knowledge
    details: RAG、向量库、混合检索、知识图谱、数据治理与语义层。
    link: /data-knowledge/
  - title: Reliability & Evaluation
    details: Eval、回归、Benchmark、Observability、SLO 与故障恢复。
    link: /reliability-evaluation/
  - title: Architecture Practice
    details: 需求分析、架构方法、模块拆分、选型、ADR 与评审。
    link: /architecture-practice/
---

## 关于这本手册

Qianke Engine Architecture Handbook 是企业级 Agent 与系统架构的长期维护知识库。

每篇文章遵循同一套阅读结构：

```text
L1 概念与原理
→ L2 架构与技术方案
→ L3 Qianke Engine 工程实践
```

所有 Qianke Engine 结论都区分：

```text
已实现
部分实现
已设计
规划中
理论知识
```

不把规划能力写成已上线功能，不用空泛名词替代工程事实。
