# 第一篇 V0.3 → V0.4 修订记录与未解决问题

> 文档：企业级 Agent 架构设计：从 ReAct 到可治理的智能体系统  
> 修订版本：V0.3 → V0.4  
> 修订日期：2026-11-23  
> 本轮只改文档；不修改代码、路由、Docs 模块、构建配置

## 1. 交付文件

```text
V0.1  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture.md
V0.2  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.2.md
V0.3  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.3.md
V0.4  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.4.md
```

V0.1、V0.2、V0.3 均未被覆盖。

## 2. 必须修复项

| 要求 | V0.4 位置 | 修订 |
|---|---|---|
| 1. PowerShell 测试命令 | §8.3.1 | 改为单行 `python -m pytest ... -q`，不再使用 `\` 续行 |
| 2. Execution Record vs Agent Result | §6.2 | 新增状态对照表、实际代码语义、回放/失败分支、待补测试 |
| 3. wall timeout 解释 | §6.4 | 区分 Agent 内部 timeout、请求级 wall timeout、协作取消、Hard Kill |
| 4. 六层架构图 | §3.1 | Governance 与 Observability & Evaluation 拆为两个独立节点 |
| 5. max_total_tokens=0 | §2.2 | 以 `loop.py` 代码为依据：0 = 关闭预算检查，不是零预算 |

## 3. 建议完善项

| 要求 | V0.4 位置 | 修订 |
|---|---|---|
| 6. Runtime/Tool/Data Access Policy 边界 | §4.5 | 三类策略分别定义检查对象、位置和当前状态 |
| 7. Tool/账号/租户权限交集 | §4.5 | 给出 effective_tools / effective_data 交集公式 |
| 8. 可复核证据 | §8.3.1 | 增加 Git commit、代码路径、关键函数、测试文件与命令 |
| 9. 延迟/成本/可靠性/安全指标 | §9.5–§9.8 | 增加指标定义、当前可观测性与待建能力 |
| 10. ReAct 经营分析案例 | §2.1.1 | 增加 State → Action → Observation → Final 的完整教学案例 |

## 4. 事实核验摘要

```text
代码快照：32ad31bc2636
验证测试：34 passed
命令：
python -m pytest tests/test_agent_execution_safety.py tests/test_agent_checkpoint.py tests/test_agent_architecture.py -q
```

核验到的关键事实：

```text
1. 执行记录状态与 Agent Result 是两个状态机
2. runner 正常返回 status=FAILED 时，execute_agent 仍调用 store.complete
3. wall timeout 由 _run_with_deadline 实现，底层 daemon 线程可能继续运行
4. AgentConfig.timeout_seconds 与 QIANKE_AGENT_WALL_TIMEOUT_SECONDS 不同
5. max_total_tokens=0 时预算检查被跳过
6. 实际注册 7 个 Tool；不是 3 个
7. prepare_followup_task 创建 DRAFT，确认由独立 API 完成
8. Super-agent queue 与主 /api/agent/run 是两条独立链路
9. LangGraph SqliteSaver、JSON attempt snapshot、retry 三者不是同一个机制
10. 通用 HITL resume API 当前未接入
```

## 5. 未解决问题清单

以下问题不能在 V0.4 中写成“已实现”，标记为待核验/待补：

### U-01 Execution Record 失败终态缺少单测

```text
问题：runner 正常返回 status=FAILED 时，execution_record 实际是 COMPLETED；
     当前测试没有直接覆盖该语义。
状态：待补测试
影响：文档已按代码解释，但缺少回归保护。
```

### U-02 生产 SLO / 延迟 / 成本数据未建立

```text
问题：V0.4 只给出指标定义与现有可观测性；
     没有生产 p50/p95、成本看板或告警数据。
状态：待核验 / 规划中
影响：不能宣称已达到任何 SLO。
```

### U-03 Prompt Injection 没有独立运行时防护层

```text
问题：当前有 SQL 只读、Tool Policy、answer_guard 等约束，
     但没有独立的 Prompt Injection 检测/隔离层。
状态：未完成
影响：安全指标只能定义，不能宣称已覆盖对抗性场景。
```

### U-04 硬取消 / 进程隔离未实现

```text
问题：wall timeout 不保证线程停止；Agent Tool 当前只读。
状态：规划中
影响：未来写 Tool 上线前必须改造。
```

### U-05 统一 HITL API 未完成

```text
问题：受控草稿确认 API 已实现；
     通用 interrupt resume / 高风险动作统一审批未接入。
状态：部分实现 / 已设计
影响：HITL 能力必须按动作类型分级描述。
```

### U-06 统一 Policy Engine 未实现

```text
问题：Runtime Policy、Tool Policy、Data Access Policy 分散在 loop/policy/
     context/SQL Tool 中，不是单一策略引擎。
状态：待设计/重构
影响：交集关系可解释，但不能宣称有统一策略中心。
```

### U-07 文档版本快照不一致

```text
问题：审核意见提到约 996 行；当前工作区 V0.1 曾为 814 行，
     V0.3 为 1215 行，V0.4 为新增修订版。
状态：待确认
影响：发布前必须确认唯一内容快照，避免同一版本多份正文。
```

### U-08 Docs 渲染尚未实现

```text
问题：V0.4 是 Markdown 草稿；官网 /docs 尚未建设，
     Mermaid、代码高亮、TOC、搜索、链接检查尚未接入。
状态：规划中
影响：本文还不能作为“官网已可阅读”验收。
```

### U-09 外部链接只做人工验证

```text
问题：链接在审核时人工检查；
     还没有构建期自动死链检查。
状态：待接入
影响：发布后链接可能漂移。
```

## 6. 审核状态

```text
V0.4：修订稿，等待人工审核
不覆盖 V0.1/V0.2/V0.3
不进入后续文章生成
不修改 Docs 模块或官网代码
```
