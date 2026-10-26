# Agent Eval v1.6.1

v1.6.1 是 v1.6 的小修，不新增题目，不改 Benchmark 语义。

## 改了什么

1. **事实引用修正**：`neg_003` 的“玩具 838 人”属于事实引用，不再被近似/结果单位护栏误杀。
2. **评测前预热检索模型**：避免首个 RAG 请求撞上未完成 fp16 转换的模型，消除 `mat1 and mat2 must have the same dtype` 错误。
3. 回归 / Benchmark 重新跑一遍，保留 v1.6 基线。

## Regression 20

| 指标 | v1.6 | v1.6.1 |
|---|---:|---:|
| Task Success（v1） | 100.0% | **100.0%** |
| Business Correctness | 100.0% | **100.0%** |
| Tool Policy Compliance | 100.0% | **100.0%** |
| Tool Execution Success | 68.9% | **100.0%** |
| Error Recovery | 100.0% | N/A（无工具错误） |
| Avg Steps | 2.75 | **2.15** |
| Avg Tool Calls | 2.25 | **1.35** |
| Avg Latency | 5.3s | **3.5s** |

`rag_001` 保持正常结束。

## Benchmark 40

| 指标 | v1.6 | v1.6.1 |
|---|---:|---:|
| Task Success（v1） | 97.5% | **97.5%** |
| Business Correctness | 100.0% | **100.0%** |
| Tool Policy Compliance | 100.0% | **97.5%** |
| Tool Selection | 100.0% | **97.5%** |
| Tool Execution Success | 96.2% | **93.1%** |
| Error Recovery | 100.0% | **100.0%** |
| Avg Steps | 2.52 | **2.58** |
| Avg Tool Calls | 2.00 | **2.17** |
| Avg Latency | 5.6s | **4.8s** |

Negative 类：**6/6 自动通过**。

## 唯一自动未通过

```text
bench_multi_004
```

- 回答正确：沉默客 2,383 人，占 29.38%
- 业务正确性：PASS
- 工具策略：FAIL（没有调用 calculator，而是在 SQL 里用 ROUND 算比例）
- 自动 Task Success：FAIL（旧复合口径要求 calculator）

这属于“工具路径 vs 业务答案”的口径问题，保留为已知项，不用改题来消除。

## 工具执行

- Regression：预热后 **100%**，无工具错误
- Benchmark：93.1%；剩余错误为少量 SQL / calculator 参数错误，均被 Agent 恢复，Error Recovery 100%

## 当前指标口径

```text
Task Success（v1）      旧复合口径
Business Correctness    只看答案
Tool Policy Compliance  只看必需工具 / 禁用工具
```

三个指标同时报告，不互相覆盖。
