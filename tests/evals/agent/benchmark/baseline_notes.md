# Benchmark v1.5 Baseline 说明

本次使用真实 DeepSeek + LangGraph `run_agent` + 真实工具，对 40 条 benchmark 跑了一次基线。

## 自动指标

```text
Task Success Rate        92.5%  (37/40)
Tool Selection Accuracy  95.0%
Tool Execution Success   92.3%
Error Recovery           100.0%
平均 Steps               2.83
平均 Tool Calls          2.60
平均耗时                 5.6s
```

分类：

```text
calculator       4/4
execute_sql     10/10
rag_search       8/8
multi_tool      10/12
negative         5/6
```

## 3 条自动失败的人工复核结论

### bench_multi_004

- 自动失败原因：缺少 `calculator`
- 实际回答：沉默客 2,383 人，占比 29.38%，正确
- 模型在 SQL 内用 `ROUND(...)` 直接算比例，没有调用 calculator
- 人工结论：答案正确；失败属于“工具合规性”未满足，不是业务结果错误

### bench_multi_011

- 自动失败原因：缺少 `calculator`
- 实际回答：黑卡平均客单价约为钻石会员的 1.76 倍，正确，并提示黑卡仅 3 人
- 人工结论：答案正确；失败属于“工具合规性”未满足

### bench_neg_004

- 自动失败原因：回答引用“当前钻石会员 403 人”，触发 `forbidden_result_units=["人"]`
- 实际回答明确说明“无法预测 2026 年 11 月数量，数据只有单时点快照”
- 人工结论：这是允许的事实引用，不是编造预测；应在人工复核中改判合规

## 口径结论

- 自动 Task Success Rate：**92.5%**
- 业务实质正确率（人工复核修正 3 条后）：**40/40**
- 工具合规性与答案正确性应分开看：multi_004 / multi_011 是工具路径失败，不是答案错误
- negative 的最终结论以 runner“人工复核清单”为准，自动分仅作初筛

## Regression 20

```text
Task Success Rate        95.0%  (19/20)
Tool Selection Accuracy 100.0%
Tool Execution Success   92.2%
Error Recovery           50.0%
平均 Steps               2.70
平均 Tool Calls          2.55
```

唯一失败：`rag_001` 达到 `MAX_STEPS_EXCEEDED`（6 步），未完成回答；属于真实回归信号，未做人工改判。
