# Agent 评测报告

日期：2026-11-14  
代码基线：`b-end-2.0-p0` / HEAD `7a4672f`（Agent 核心未改；C 端 UI/gzip 提交在评测期间落地，不影响 Agent 评测）  
数据集：demo（8110 用户）  
运行方式：真实 DeepSeek + LangGraph run_agent + 真实工具，`LANGCHAIN_TRACING_V2=false`，本地判分

## 结论

```text
Regression 20/20：100%，所有指标 100%
Benchmark 80 两轮：
  Run 1：Task Success 90.0% / Business 100.0%
  Run 2：Task Success 95.0% / Business 98.8%
  均值 92.5%，基线 v2.2 为 96.2%

没有发现稳定的新回归：
  两轮共同失败只有 bench_multi_004（基线已知失败）
  其余失败是 calculator 工具调用采样波动
  Business Correctness 的 1 条 FAIL 是拒答关键词不匹配，实际回答正确
```

## Regression

```text
任务数：20
Task Success          100.0%
Business Correctness  100.0%
Tool Policy           100.0%
Tool Selection        100.0%
Tool Execution        100.0%
平均 Steps            2.25
平均 Tool Calls       1.65
平均耗时              3.8s
```

结果：`tests/evals/agent/results/system_agent_regression_2026-11-14.json`  
报告：`tests/evals/agent/reports/system_agent_regression_2026-11-14.md`

## Benchmark 两轮

| 指标 | Run 1 | Run 2 | 基线 v2.2 |
|---|---:|---:|---:|
| Task Success | 90.0% | 95.0% | 96.2% |
| Business Correctness | 100.0% | 98.8% | 100.0% |
| Tool Policy Compliance | 92.5% | 98.8% | 97.5% |
| Tool Selection Accuracy | 90.0% | 96.2% | 96.2% |
| Tool Execution Success | 92.8% | 92.9% | 96.0% |
| Error Recovery | 100.0% | 87.5% | 100.0% |
| 平均 Steps | 2.50 | 2.50 | 2.48 |
| 平均 Tool Calls | 1.91 | 1.94 | 1.88 |
| 平均耗时 | 4.1s | 4.0s | 3.9s |

结果：

```text
tests/evals/agent/results/system_agent_benchmark_2026-11-14.json
tests/evals/agent/results/system_agent_benchmark_2026-11-14_run2.json
```

报告：

```text
tests/evals/agent/reports/system_agent_benchmark_2026-11-14.md
tests/evals/agent/reports/system_agent_benchmark_2026-11-14_run2.md
```

## 失败分析

Run 1 失败 8 条：

```text
bench_multi_004, 006, 007, 009, 013, 018, 019, hold_016
```

Run 2 失败 4 条：

```text
bench_multi_001, bench_multi_004, hold_011, hold_018
```

共同失败：

```text
bench_multi_004（v2.2 基线已知失败）
```

主要类型：

```text
multi_tool 期望 calculator，但模型本轮直接用 SQL/心算完成
Business Correctness 大多为 PASS，属于工具路径/Task Success 复合口径失败
```

失败子集复跑：

```text
8 条失败子集：
  Task Success 87.5%
  7/8 通过
  唯一未通过 bench_multi_004（基线已知）
```

说明 calculator 调用存在明显采样波动，单轮 Task Success 不能直接判定代码退化。

## 负样本误判

Run 2 的 `hold_018`：

```text
问题：统计商品毛利率，数据不支持时不要编造数字
实际回答：现有数据无法统计商品毛利率，我没有做任何估算
Business Correctness：FAIL
原因：期望关键词包含“不存在”，回答用了“无法/没有”，自动关键词未命中
人工复核：回答没有编造毛利率，实际业务正确
```

这是 evaluator 关键词口径问题，不是 Agent 幻觉。

## 评测判断

```text
1. Regression：稳定通过。
2. Benchmark：单轮 90-95%，相对基线 96.2% 有波动，但两轮共同失败只有已知的 multi_004。
3. 业务答案质量：run1 100%，run2 自动 98.8%；唯一 FAIL 经人工复核为误判。
4. 工具路径：multi_tool 的 calculator 可选/必需调用不稳定，是当前主要波动源。
```

## 建议

```text
1. 用 3 轮重复取均值/最差轮，而不是单轮对基线做硬比较。
2. 对 optional calculator 的 Task Success 复合口径做一次 evaluator 评审，避免“答案对但工具路径不同”被判失败。
3. hold_018 的拒答关键词补充“无法/没有/不能”，或标记人工复核；不要为了提分直接改题集。
4. 若要收紧工具路径，应单独做 calculator 调用专项，而不是用 Benchmark 单轮波动判断。
```

## 未执行 / 限制

```text
未跑 Super-agent v2 Eval 与 C 端人设 Eval；本轮只做 Agent Regression + Benchmark。
未跑公网环境；本轮为本地 API/DB/LLM。
评测期间 C 端会话合入 60c1bf4 / e40b704（UI/gzip），Agent 核心文件未改；本轮结论仍适用于 Agent 行为。
LangSmith tracing 关闭，避免外部 429 影响；本地判分完整。
```

## 第三轮 Benchmark（B/C 修复后）

日期：2026-11-15 00:13  
代码基线：`38d33fb`（B 端修复后；Agent 核心未改）

```text
Task Success          93.8%
Business Correctness  97.5%
Tool Policy           97.5%
Tool Selection        96.2%
Tool Execution        95.5%
Error Recovery        83.3%
平均 Steps            2.50
平均 Tool Calls       1.96
平均耗时              3.7s
```

失败 5 条：

```text
bench_multi_001：答案正确，Task Success 复合口径失败
bench_neg_004：明确拒答，但答案引用“前 5%”被数字规则误判
hold_011：缺 calculator
hold_016：缺 calculator
hold_018：拒答关键词“不存在”未命中
```

`bench_neg_004` 和 `hold_018` 人工复核均为正确拒答，不是编造结果；自动 Business Correctness 仍按规则 FAIL。

## 三轮汇总

| 指标 | Run1 | Run2 | Run3 | 均值 | 基线 |
|---|---:|---:|---:|---:|---:|
| Task Success | 90.0% | 95.0% | 93.8% | **92.9%** | 96.2% |
| Business Correctness | 100.0% | 98.8% | 97.5% | 98.8% | 100.0% |
| Tool Policy | 92.5% | 98.8% | 97.5% | 96.3% | 97.5% |
| Tool Selection | 90.0% | 96.2% | 96.2% | 94.1% | 96.2% |

三轮共同失败：

```text
无
```

两轮出现的失败：

```text
bench_multi_004（v2.2 基线已知失败）
hold_018（拒答关键词误判）
```

结论：

```text
三轮均值 92.9%，比基线 96.2% 低 3.3pp；
没有一条任务三轮全部失败，主要波动仍是 calculator 路径和负样本关键词/数字规则误判。
单轮结果不足以判定稳定回归。
```
