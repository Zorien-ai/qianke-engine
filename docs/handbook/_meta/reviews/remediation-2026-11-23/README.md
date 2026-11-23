# M3 批次复核汇总（2026-11-23）

> 范围：M2 修复后的 6 个分类复核  
> 基线：`docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.2.md`  
> 审计性质：只读复核；6 份报告完成后，残余 P1/P2 由 M4 收口

## 1. 六份复核报告

| 批次 | 结论（复核时） | 报告 |
|---|---|---|
| Agent Architecture | 条件通过 | [agent-architecture.md](remediation-2026-11-23/agent-architecture.md) |
| Enterprise Governance | 通过 | [enterprise-governance.md](remediation-2026-11-23/enterprise-governance.md) |
| System Architecture | 条件通过 | [system-architecture.md](remediation-2026-11-23/system-architecture.md) |
| Data & Knowledge | 条件通过 | [data-knowledge.md](remediation-2026-11-23/data-knowledge.md) |
| Reliability & Evaluation | 条件通过 | [reliability-evaluation.md](remediation-2026-11-23/reliability-evaluation.md) |
| Architecture Practice | 条件通过 | [architecture-practice.md](remediation-2026-11-23/architecture-practice.md) |

## 2. P1 复核结果

复核确认以下 P1 已真正修复：

```text
P1-01 ~ P1-11
P1-13 ~ P1-22
```

复核时仍在收口的两项：

```text
P1-12：03 API Gateway 缺少 Nginx Upgrade 缺口说明
P1-21/P1-22：行数改用“非空行”口径，与总行数口径不一致
```

M4 已补修：

```text
03-api-gateway.md 增加 Nginx Upgrade/Connection 缺口与非实测声明
03-module-decomposition.md / 09-technical-debt.md 改为总行数口径 6,578 / 1,202
```

复核还发现 P1-13 的跨篇矛盾：

```text
01-agent-evaluation.md 仍把 check_eval_v2_gate.py 写成 CI 门禁
```

M4 已改为“v2 门禁可手动执行，未接入 ci.yml”。

## 3. 复核后仍需 M4/M5 处理的 P2

```text
- V0.5.1 旧引用（已在 M4 统一为 V0.5.2）
- README 旧状态与旧路径（已修正）
- M0 证据链（已补 closure 文档）
- 03 API Gateway 的 /docs 路由旧叙述（已修正）
- Practice 05 VitePress 状态过旧（已修正）
- Data 06 缓存键错误（已修正）
- 生产预检 11 项与 10 项口径（已修正）
- tests 126/130 口径（已修正）
- Enterprise 08 脱敏示例与递归描述（已修正）
- Practice 10 链路数量与时间线（已修正）
```

剩余未逐项修复的 P2 仍包括 HITL 口径、Prompt Injection 状态、部分跨篇状态差异和历史文档漂移；这些不影响 P1 验收，但不能宣称全站内容零问题。

## 4. 复核边界

- 6 份报告均为只读审计，未修改文章、配置或代码。
- 复核时未重跑全量 pytest/Eval；以代码、文档和静态检查为主。
- 6 份报告是复核时点快照；M4 修改后需以 M5 最终验收为准。
