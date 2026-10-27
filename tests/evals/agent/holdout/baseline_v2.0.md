# Holdout v2.0

20 条 private holdout，首次运行：

```text
Task Success        90.0%
Business Correctness 95.0%
Tool Policy         95.0%
Tool Selection      95.0%
Tool Execution      97.1%
```

失败 2 条：

- `hold_004`：金额千分位格式关键词未命中
- `hold_016`：工具路径差异

该 holdout 完成首次基线后，在 v2.2 退役并纳入公共 Benchmark；后续版本需要重建新的 private holdout。
