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
## 业务 Trace → Agent 输入/输出

`业务请求` 里的 Agent Trace 抽屉新增：

```text
查看 Agent 输入/输出
```

点击后跳到：

```text
/monitor-center?tab=agent&trace=<trace_id>
```

自动打开同一 Trace 的 Agent 节点树，可查看 Input / Output / Metadata。

截图：

![业务 Trace 跳 Agent 输入输出](docs/design/agent-trace-io-from-monitor.png)
## 评测实验 → Trace 输入输出

Agent 实验的逐条结果表新增「查看 Trace」：

```text
点击后关闭实验弹层 → 跳到 Agent 调用 tab → 自动打开同一 Trace
```

修复点：早期直接在弹层里用 RouterLink 跳转，页面过渡会卡在离场状态；现在先关闭弹层再 router.push。

截图：

![评测结果跳 Trace](docs/design/eval-trace-link.png)
