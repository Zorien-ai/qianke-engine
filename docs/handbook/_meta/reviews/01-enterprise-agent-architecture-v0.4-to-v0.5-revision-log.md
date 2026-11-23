# 第一篇 V0.4 → V0.5 修订记录与未解决问题

> 文档：企业级 Agent 架构设计：从 ReAct 到可治理的智能体系统  
> 修订版本：V0.4 → V0.5  
> 修订日期：2026-11-23  
> 本轮只改文档和做必要代码核验；不修改业务代码、官网代码、Docs 模块、路由和构建配置

## 1. 交付文件

```text
V0.1  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture.md
V0.2  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.2.md
V0.3  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.3.md
V0.4  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.4.md
V0.5  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.md
```

V0.1～V0.4 均未被覆盖。

## 2. P1 必须修正项

### 2.1 修复 ReAct 经营分析案例

V0.5 §2.1.1：

```text
1. SQL 同时查询当前周期与对照周期
2. 时间范围使用半开区间：
   start ≤ paid_at < end
3. 明确 current_paid / current_refund / baseline_paid / baseline_refund
4. Calculator 输入严格来自前序 SQL Observation
5. 净销售额由 paid - refund 计算
6. 最终结论可由 Observation 和 Calculator 结果复现
7. 明确标注 PostgreSQL 方言，SQLite 不能直接执行
8. 示意表名/字段标注“待核验”，不冒充生产 schema
```

数值链：

```text
current_paid=12800, current_refund=600 → current_net=12200
baseline_paid=14000, baseline_refund=400 → baseline_net=13600
decline=(12200-13600)/13600*100=-10.29%
```

### 2.2 修正 4.5 权限模型

V0.5 §4.5 明确拆成：

```text
Runtime Policy：任务还能不能继续
Tool Policy：当前账号能不能调用这个 Tool
Data Access Policy：这个 Tool 能看到哪些数据
```

不再使用“工具集合 ∩ 数据集合 ∩ 预算”的混合交集公式。

### 2.3 核验 wall timeout 后状态竞争

代码核验结论：

```text
1. _run_with_deadline 的 worker 只执行 invoke()
2. invoke() 只调用 runner，不在 worker 内调用 store.complete
3. store.complete 发生在 _run_with_deadline 返回后、调用线程中
4. 超时 → 调用线程抛 AgentRunTimedOut → execute_agent 调用 store.fail
5. worker 之后返回的结果被丢弃；当前代码没有超时后 store.complete 的路径
6. 同一 request_id 再次提交：claim 看到 FAILED，返回 AgentRequestFailed（API 409）
```

本次手工探针：

```text
after_worker_return_state = failed
resubmit_error = AgentRequestFailed: AgentRunTimedOut: ...
```

说明：

```text
当前代码路径下，Worker 超时后不会把 FAILED 覆盖成 COMPLETED；
但这是代码审查 + 手工探针结论，不是自动化测试结论。
```

现有测试只覆盖：

```text
test_wall_deadline_returns_timeout_and_marks_failed
  → 超时返回、耗时小于 runner、Execution Record = failed
```

未覆盖：

```text
- worker 超时后真正返回时的行为
- 超时后同 request_id 再次提交的 API 级行为
- 自定义 runner 在超时后自己写 store 的场景
```

V0.5 已明确列为待补测试，没有声称已经验证。

## 3. P2 建议完善项

### 3.1 Execution Record vs Agent Result

V0.5 §6.2 增加对照表和实际代码语义：

```text
Execution Record = COMPLETED
≠
Agent Result = COMPLETED

runner 正常返回 status=FAILED/TIMEOUT
→ store.complete
→ Execution Record = COMPLETED
→ 保存的是带失败终态的响应
```

### 3.2 统一测试命令、环境和 Git Commit

V0.5 §8.3.1 统一为一个证据入口：

```powershell
$env:QIANKE_CONTROL_BACKEND='sqlite'
$env:QIANKE_CEND_BACKEND='sqlite'
$env:LANGSMITH_TRACING='false'
$env:LANGCHAIN_TRACING_V2='false'
python -m pytest tests/test_agent_execution_safety.py tests/test_agent_checkpoint.py tests/test_agent_architecture.py -q
```

```text
34 passed
Git commit: 32ad31bc2636
测试日志: var/handbook_agent_review_tests.log
```

V0.4 中重复的测试命令已删除，只保留这一处。

### 3.3 合并第 9 章重复安全评估

V0.5：

```text
删除 9.8 重复的“安全与合规指标”
把风险维度 + 指标合并到 9.4 安全与合规（含指标）
保留 9.5 延迟、9.6 成本、9.7 可靠性
```

## 4. 代码核验命令与结果

最终执行：

```powershell
$env:QIANKE_CONTROL_BACKEND='sqlite'
$env:QIANKE_CEND_BACKEND='sqlite'
$env:LANGSMITH_TRACING='false'
$env:LANGCHAIN_TRACING_V2='false'
python -m pytest tests/test_agent_execution_safety.py tests/test_agent_checkpoint.py tests/test_agent_architecture.py -q
```

```text
34 passed, 1 warning in 7.50s
```

警告为 torch/pynvml deprecation，不是测试失败。

## 5. 未解决问题清单（V0.5）

### U-01 runner 返回 FAILED 时 Execution Record 语义缺少单测

```text
状态：待补测试
说明：代码上 store.complete 会记录 COMPLETED，但缺少直接断言。
```

### U-02 超时后 Worker 返回与状态覆盖缺少自动化测试

```text
状态：待补测试
说明：代码审查和手工探针显示当前不会覆盖，但未纳入 pytest。
```

### U-03 超时后同 request_id 的 API 级回放行为缺少测试

```text
状态：待补测试
说明：手工探针显示 AgentRequestFailed，但没有 API 级回归测试。
```

### U-04 生产 SLO / 延迟 / 成本指标未建立

```text
状态：未建立
说明：V0.5 只给指标定义，不能宣称达到任何 SLO。
```

### U-05 Prompt Injection 没有独立运行时防护层

```text
状态：未完成
说明：SQL 只读、Tool Policy、answer_guard 不等同于完整 Prompt Injection 防护。
```

### U-06 硬取消 / 进程隔离未实现

```text
状态：规划中
说明：wall timeout 不是硬杀掉执行线程。
```

### U-07 统一 HITL API 未完成

```text
状态：部分实现
说明：受控草稿确认已有；通用 interrupt resume/高风险管理未统一。
```

### U-08 统一 Data Access Policy Engine 未实现

```text
状态：待设计
说明：dataset_scope、_tenant_scope、SQL 只读/白名单分散实现。
```

### U-09 Docs 模块尚未实现

```text
状态：规划中
说明：V0.5 仍是 Markdown；/docs、Mermaid、搜索、TOC 尚未接入。
```

### U-10 文档版本快照仍需统一

```text
状态：待确认
说明：审核意见曾提 996 行版本；当前工作区 V0.1 814 行、V0.3 1215 行，
V0.5 为新修订版。发布前必须指定唯一快照。
```

### U-11 外部链接仍为人工核验

```text
状态：待接入构建期检查
说明：当前外链已人工检查，但没有自动死链门禁。
```

## 6. 审核状态

```text
V0.5：修订稿，等待人工审核
不覆盖 V0.1/V0.2/V0.3/V0.4
不继续生成后续文章
不修改代码、路由、Docs 模块、构建配置
```
