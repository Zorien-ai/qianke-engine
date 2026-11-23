---
title: 如何进行技术选型
description: 从需求约束、总拥有成本、可逆性与退出成本出发说明技术选型方法，并结合 Qianke Engine 的 PostgreSQL、Ant Design Vue、LangGraph 与文档站选型案例复盘。
section: "06 · Architecture Practice"
section_order: 6
order: 5
slug: technology-selection
doc_status: 草稿
implementation_status: 理论知识 + 已实现
version: 0.1.0
updated: 2026-11-23
reading_minutes: 15
prerequisites:
  - 架构设计与质量属性基础
  - 常见后端/数据库/前端技术栈认知
  - 成本与运维基础概念
tags:
  - Technology Selection
  - Trade-off
  - TCO
  - Lock-in
related:
  - architecture-decision-records
  - module-dependencies
  - performance-analysis
---

# 如何进行技术选型

> 技术选型不是选“最强的技术”，而是在给定约束下选**最合适、最可维护、最容易退出**的技术。

## 1. 为什么需要技术选型

一个技术选择会长期影响系统：开发效率、运维复杂度、招聘与培训、性能上限、安全合规、供应商锁定与迁移成本。常见的选型失败模式：

```text
为了追新引入不成熟框架，半年后无人能维护
为了“统一”强行使用不匹配的技术，开发效率下降
只看功能对比，不算迁移、运维与退出成本
用个人偏好替代团队能力与组织约束
没有 PoC，凭宣传材料做决定
```

技术选型不是一次性动作，而是一项持续治理活动：引入、验证、推广、废弃都需要记录与评审。

## 2. 基本机制

选型可以从六个维度评估：

| 维度 | 要回答的问题 |
|---|---|
| 需求匹配 | 是否解决真实约束？性能、安全、合规能否满足？ |
| 成熟度 | 社区、发布节奏、已知问题、生产案例如何？ |
| 团队能力 | 团队能否维护？招聘、培训、排障成本多少？ |
| 总拥有成本 | 许可证、基础设施、人力、监控、升级成本？ |
| 可逆性 / 锁定 | 替换成本多高？数据、接口、模型是否可迁移？ |
| 风险 | 供应链、许可证、停维护、安全漏洞、供应商依赖？ |

一个实用的决策流程：

```text
明确约束与验收标准 → 列候选 → 设定权重 → 小范围 PoC → 记录决策(ADR) → 小流量试点 → 复盘与退出计划
```

权重必须显式。安全与合规通常是门槛项（不满足直接淘汰），性能、成本、团队能力再做加权比较。只有门槛项都通过后，才讨论“哪个更好”。

## 3. 总体架构

```mermaid
flowchart LR
    N["需求与约束<br/>性能 / 安全 / 合规 / 预算"]
    C["候选技术<br/>至少 2 个方案"]
    W["评估矩阵<br/>门槛项 + 权重"]
    P["PoC / Benchmark<br/>真实数据与场景"]
    D["决策与 ADR<br/>理由、风险、退出方案"]
    T["小范围试点"]
    R["复盘与推广 / 废弃"]
    N --> C --> W --> P --> D --> T --> R
    R -->|不满足| C
```

选型产出不只是一个技术名字，还包括：版本与许可、部署与运维方式、验证证据、禁用场景、退出与迁移路径、责任人。

## 4. 关键设计

**先定门槛，再比优劣。** 例如企业系统要求数据不出内网、审计可追溯、许可证合规。如果候选方案不满足，就无需再比较性能。

**区分可逆与不可逆选择。** 日志库、UI 组件通常可替换；数据库、消息中间件、云厂商、模型供应商、对外 API 契约往往替换成本很高。不可逆选择需要更严格的 PoC、退出方案和正式评审。

**总拥有成本（TCO）优先于初始成本。** 开源不等于免费：运维、监控、升级、故障排查、安全补丁都需要人力。SaaS 也不等于省事：数据合规、网络依赖、费用增长与锁定风险都要算。

**用真实场景验证。** PoC 必须基于真实数据量、真实查询模式、真实并发与真实失败场景。只跑一个 Hello World 或官方 benchmark，无法证明在业务约束下可用。

**团队能力是硬约束。** 一个团队无法维护的技术，即使先进也会变成负债。选型时要问：出故障时谁能定位？升级时谁能处理？新人多久能上手？

**保留退出路径。** 数据可导出、协议标准化、抽象层隔离、许可证允许迁移。Qianke 的 Merchant/Control Repository 抽象与双后端实现，就是为数据库替换保留退出路径。

## 5. 工程实现

一个可落地的评估矩阵模板（伪模板，不是仓库现有文件）：

| 候选 | 门槛项 | 性能 | 成本 | 团队能力 | 可逆性 | 风险 | 结论 |
|---|---|---|---|---|---|---|---|
| A | 通过 | 4 | 3 | 5 | 3 | 中 | 试点 |
| B | 通过 | 3 | 5 | 4 | 5 | 低 | 采用 |

PoC 至少应覆盖：

```text
真实数据规模下的性能与资源占用
故障与恢复：超时、断连、节点重启、数据损坏
运维操作：部署、升级、备份、恢复、监控
安全：认证、授权、网络边界、依赖漏洞
迁移：数据导入导出、版本升级、回滚
成本：机器、存储、网络、许可证、人力
```

选型记录应进入 ADR：背景、候选、评估结果、最终决定、理由、被否决原因、风险与退出方案。没有记录的选型会重复争论，也无法在新约束出现时复盘。

## 6. 企业级要求

| 维度 | 选型时必须有答案 |
|---|---|
| 安全 | 依赖漏洞如何扫描？密钥与权限如何管理？ |
| 合规 | 数据存储位置、保留期限、删除能力是否满足？ |
| 可用性 | 单点故障、升级窗口、故障转移怎么做？ |
| 运维 | 监控指标、日志、告警、备份恢复是否成熟？ |
| 供应链 | 许可证、维护者、版本策略、停维护风险？ |
| 成本 | 规模增长后成本曲线如何？是否有预算上限？ |
| 退出 | 替换需要多久？数据与接口能否迁移？ |

企业选型的一个常见错误是只让技术团队评估。安全、合规、财务、运维都应参与门槛项评审，否则决定很可能在上线前被推翻。

## 7. 方案对比

| 场景 | 方案 | 优点 | 代价 | Qianke 的选择 |
|---|---|---|---|---|
| 数据库 | 继续用现有 PostgreSQL | 复用运维经验、事务/行锁成熟、pgvector 可承载向量 | 需要 schema 与连接池治理 | 采用（控制面 SQLite 迁移到 PG） |
| 数据库 | 保留 SQLite 作为主库 | 简单、零运维 | 并发写弱、多实例困难、备份恢复受限 | 仅本地开发回退，不作为主库 |
| 前端组件库 | Ant Design Vue | 组件完整、与 Vue 3 一致、设计 Token 可定制 | 体积较大，需要路由懒加载与按需引入 | 采用（B 端），固定版本 4.2.6 |
| 前端组件库 | 自研组件 | 体积可控、完全贴合品牌 | 表格/弹窗/表单等基础能力重复造轮子 | 已在旧页面使用，逐步被替代 |
| 服务形态 | 自研 vs SaaS | 自研可控；SaaS 省人力 | 自研成本高；SaaS 有合规/锁定风险 | 核心链路自研，外围能力按需引入 |
| 文档站 | 自建 SPA 页面 vs VitePress | VitePress 搜索/目录/静态 SEO 开箱可用 | 新增构建依赖与 /docs 挂载冲突 | VitePress（已实现：构建 + FastAPI `/docs` 挂载；公网访问已核验） |

对比表的价值不在“谁赢”，而在于把代价写出来。任何选型都有代价，没有代价的选型通常意味着隐藏成本尚未暴露。

## 8. Qianke Engine 实践

当前技术栈（可从 `pyproject.toml`、`web/package.json`、`docs/部署指南.md` 核验）：

| 层次 | 选择 | 证据 | 状态 |
|---|---|---|---|
| 语言与包管理 | Python 3.12 + uv | `requires-python = ">=3.12,<3.13"`、`uv sync --frozen` | 已实现 |
| Web 框架 | FastAPI + uvicorn | `pyproject.toml`、`docs/部署指南.md` | 已实现 |
| Agent 编排 | LangGraph + LangChain Core | `langgraph`、`langchain-core`、`agent/loop.py` | 已实现 |
| 模型接入 | DeepSeek（OpenAI 兼容接口） | `langchain-openai`、`docs/项目背景.md` | 已实现 |
| 数据库 | PostgreSQL 16 + pgvector | `docs/部署指南.md`、`docker-compose.yml` | 已实现 |
| 本地回退 | SQLite（控制面/商家数据） | `control/`、`merchant/` 双后端 | 已实现 |
| 检索模型 | BGE-M3 + bge-reranker-v2-m3 + jieba | `docs/项目背景.md` 附录 | 已实现 |
| 前端 | Vue 3 + Vite + Ant Design Vue 4.2.6 | `web/package.json`、`docs/product/b-ant-design-adoption.md` | 已实现 |
| 文档站 | VitePress（方案 B） | `docs/handbook/_meta/docs-module-implementation-plan.md` | 已实现（VitePress 构建 + FastAPI `/docs` 挂载；公网可访问） |

三个真实的选型案例：

1. **控制面数据库迁移。** `docs/decisions/control_plane_postgres_migration_v0.1.md` 明确“继续使用 PostgreSQL，不换数据库”，目标是多实例共享、事务与行锁、统一备份监控；SQLite 保留为本地开发回退。方案还写了方言改造清单、回填、维护窗口、回滚与双后端契约测试，这是“选型 + 迁移 + 退出”的完整案例。
2. **B 端组件库。** `docs/product/b-ant-design-adoption.md` 先确认官方 `antd` 是 React、当前 B 端是 Vue 3，因此选 `ant-design-vue` 并固定版本；同时记录体积代价（订单页 chunk 约 686 KB / gzip 205 KB），要求路由懒加载，下一步按需引入。这比“Ant Design 好看所以用”更接近工程选型。
3. **文档站方案。** 实施方案对比了“在 Vue SPA 内加 Docs 页面”“独立 VitePress”“Docusaurus”三种方案，基于 SEO、Markdown 能力、与 Vue 生态一致性和包体影响选择 VitePress；同时提前识别 FastAPI `/docs` 冲突。当前 `src/rag_demo/api/main.py` 已把 Swagger 迁到 `/api/docs`，并将 VitePress 构建产物挂载到 `/docs`；公网 `/docs` 已实际访问核验。

未核验项：DeepSeek、BGE-M3、LangGraph 的候选方案对比文档在仓库中未见（目前可核验的是选型结果与运行配置）；这些选择的完整权衡理由标为“待核验”。统一技术雷达、选型退出演练与周期性复审仍属规划中。

## 9. 评估 / 验收

```text
[ ] 需求门槛（性能、安全、合规）有明确结论
[ ] 至少有两个候选方案与对比结果
[ ] PoC 使用真实数据/并发/失败场景
[ ] 总拥有成本（含运维与人力）已评估
[ ] 版本、许可证、维护状态已核验
[ ] 退出与迁移路径已写明
[ ] 决策进入 ADR 并注明被否决方案
[ ] 试点范围、成功标准与回滚条件明确
```

选型不是“评审通过就结束”，试点结束后要复盘：实际性能、故障率、团队上手时间、成本偏差。如果偏差超过预设门槛，应有勇气更换方案，而不是继续沉没成本。

## 10. 常见误区

1. 只比较功能列表，不比较运维、迁移与退出成本。
2. 用个人偏好或技术热度替代需求与团队能力。
3. 没有 PoC，直接在生产上试错。
4. 把“开源”等同于“免费、无风险”。
5. 不记录决策理由，人员变动后无法复盘。

## 11. 总结

```text
技术选型 = 门槛约束 + 多方案对比 + 真实验证 + 退出方案
```

1. 选型服务于约束，不服务于技术偏好。
2. 先过门槛项，再比较性能与成本。
3. 真实 PoC 与总拥有成本比宣传材料可靠。
4. 记录决策并保留退出路径，才能长期可维护。

## 12. 延伸阅读

项目内部资料：

- `docs/decisions/control_plane_postgres_migration_v0.1.md`：数据库迁移与回滚
- `docs/product/b-ant-design-adoption.md`：B 端组件库选型与代价
- `docs/handbook/_meta/docs-module-implementation-plan.md`：文档站方案对比
- `pyproject.toml`、`web/package.json`、`docs/部署指南.md`：当前技术栈事实

外部资料：

- ThoughtWorks Technology Radar：https://www.thoughtworks.com/radar
- PostgreSQL 官方文档：https://www.postgresql.org/docs/
- FastAPI 官方文档：https://fastapi.tiangolo.com/
- VitePress 官方文档：https://vitepress.dev/
