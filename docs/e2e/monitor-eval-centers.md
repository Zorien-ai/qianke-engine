# 监控中心 / 评测中心合并

日期：2026-11-15

## 入口

```text
监控中心：/v2/#/monitor-center
评测中心：/v2/#/eval-center
```

旧地址全部重定向：

```text
/monitor                  → /monitor-center?tab=request
/admin/monitor            → /monitor-center?tab=platform
/admin/agent-monitor      → /monitor-center?tab=agent
/eval                     → /eval-center?tab=rag
/admin/agent-evals        → /eval-center?tab=agent
```

## 监控中心

| tab | 内容 | 权限 |
|---|---|---|
| 业务请求 | 原有 AI 实时监控 | 管理员 |
| Agent 调用 | Agent trace 列表 / 树 / 对比 / 评分 | 系统管理员 |
| 租户与计费 | 跨租户消耗排行 + 模型销售价 | 系统管理员 |

子页面保留原有筛选、刷新、操作和接口，不修改后端。

## 评测中心

| tab | 内容 | 权限 |
|---|---|---|
| RAG 离线评测 | 原有题库评测 / LLM Judge | 管理员 / 演示只读 |
| Agent 实验 | 数据集 / 实验 / 逐条结果 | 系统管理员 |

## 导航变化

```text
删除：
  实时监控
  平台监控
  Agent 调用监控
  离线评测
  Agent 数据集与评测

新增：
  监控中心
  评测中心
```

管理端导航从 5 个重复入口收敛为 2 个。

## 验证

```text
pytest tests/ -q
  → 844 passed, 6 skipped

web build
  → PASS

浏览器：
  监控中心三个 tab 正常切换
  评测中心两个 tab 正常切换
  /admin/agent-monitor 自动跳到监控中心 Agent tab
  1440 / 390 无横向溢出
```

截图：

![监控中心](docs/design/monitor-center-request.png)

![Agent 调用](docs/design/monitor-center-agent.png)

![评测中心](docs/design/eval-center-rag.png)

![Agent 实验](docs/design/eval-center-agent.png)
