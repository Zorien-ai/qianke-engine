# 第一篇 V0.5 → V0.5.1 微调记录

> 文档：企业级 Agent 架构设计：从 ReAct 到可治理的智能体系统  
> 修订版本：V0.5 → V0.5.1  
> 日期：2026-11-23  
> 范围：只处理三个 P2，不新增章节、不改变 12 章结构、不修改代码/路由/Docs/构建配置

## 1. 交付文件

```text
V0.5    docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.md
V0.5.1  docs/handbook/01-agent-architecture/01-enterprise-agent-architecture-v0.5.1.md
```

V0.1～V0.5 均未覆盖。

## 2. P2-01 聚合 SQL 的 LIMIT 与成本控制

修改位置：§2.1.1

```text
- 删除 SQL 示例中的 LIMIT 100
- 说明聚合查询最终通常只返回一行，LIMIT 不控制扫描量
- 成本控制改为：
  · 明确半开时间范围
  · merchant_id + paid_at 索引（待 schema 核验）
  · statement timeout
  · 连接/资源配额与 fetch limit
- 明确 merchant_id 由服务端可信上下文注入，不允许 LLM 生成/覆盖
- 补充 SQL Tool 的 LIMIT 契约说明：
  若工具要求 LIMIT，那是工具安全门禁，不是成本控制
```

## 3. P2-02 测试覆盖描述精确化

修改位置：§8.3.1 测试覆盖表

```text
已覆盖：
  - dataset 隔离
  - 已完成请求幂等回放
  - request_id 冲突
  - runner 抛异常后的失败记录
  - wall timeout 后的失败记录
  - ToolPolicy
  - 并发 claim

未覆盖：
  - runner 正常返回 Agent Result=FAILED 时
    Execution Record 的状态语义
  - 超时后 Worker 返回的状态竞争
  - 超时后同 request_id 再次提交的 API 行为
```

该表述与 §6.2 的待补测试清单一致，不再使用笼统的“失败终态已覆盖”。

## 4. P2-03 完整自然月口径

修改位置：§2.1.1

```text
原：“最近一个月净销售额为什么下降？”
改为：“最近一个完整自然月的净销售额为什么下降？”
明确当前周期：2026 年 10 月完整自然月
明确对照周期：2026 年 9 月完整自然月
```

避免读者把案例误解为“最近 30 天滚动窗口”。

## 5. 未修改内容

```text
12 章结构不变
原有 7 Tool、角色矩阵、受控草稿、Checkpoint/Retry、HITL 边界不变
已有实现/部分实现/已设计/规划中状态不变
代码、测试、路由、官网 Docs、构建配置不变
```

## 6. 证据状态

V0.5.1 只改文档，没有重新运行测试。沿用 V0.5 的证据：

```text
Git commit: 32ad31bc2636
环境: SQLite 控制面/数据面
命令:
python -m pytest tests/test_agent_execution_safety.py tests/test_agent_checkpoint.py tests/test_agent_architecture.py -q
结果: 34 passed
日志: var/handbook_agent_review_tests.log
```

仍不把该结果外推为生产 SLO、安全或完整路径验证。

## 7. 未解决问题（沿用）

```text
U-01 runner 返回 Agent Result=FAILED 时 Execution Record 缺少单测
U-02 超时后 Worker 返回的状态竞争缺少自动化测试
U-03 超时后同 request_id 的 API 级回放缺少测试
U-04 生产 SLO / 延迟 / 成本指标未建立
U-05 Prompt Injection 独立运行时防护未完成
U-06 硬取消 / 进程隔离未实现
U-07 统一 HITL API 未完成
U-08 统一 Data Access Policy Engine 未实现
U-09 官网 Docs 模块尚未实现
U-10 文档版本快照仍需统一
U-11 外部链接尚未接入构建期自动检查
```

## 8. 状态

```text
V0.5.1：冻结候选，等待人工最终确认
不覆盖 V0.5
不继续生成后续文章
```
