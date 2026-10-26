# Agent Eval v1.6

v1.6 只做三件事：

1. 保留 v1.5 baseline，不覆盖旧口径
2. 新增 Business Correctness / Tool Policy Compliance 两个指标
3. 修正 rag_001 的停止规则，再跑 Regression + Benchmark

## 指标版本

```text
v1 复合口径（保留）:
  status + expected_tools + expected_keywords

v2 新增:
  Business Correctness    只看状态 + 业务答案
  Tool Policy Compliance  只看必需工具 / 禁用工具
```

## v1.5 → v1.6 对比

### Regression 20

| 指标 | v1.5 | v1.6 |
|---|---:|---:|
| Task Success（v1） | 95.0% | **100.0%** |
| Business Correctness | - | **100.0%** |
| Tool Policy Compliance | - | **100.0%** |
| Tool Execution Success | 92.2% | 68.9% |
| Avg Steps | 2.70 | 2.75 |

Regression 中 `rag_001` 不再 MAX_STEPS_EXCEEDED。

### Benchmark 40

| 指标 | v1.5 | v1.6 |
|---|---:|---:|
| Task Success（v1） | 92.5% | **97.5%** |
| Business Correctness | 人工复核 ≈40/40 | **100.0%** |
| Tool Policy Compliance | - | **100.0%** |
| Tool Selection Accuracy | 95.0% | **100.0%** |
| Tool Execution Success | 92.3% | **96.2%** |
| Error Recovery | 100.0% | 100.0% |
| Avg Steps | 2.83 | **2.52** |
| Avg Tool Calls | 2.60 | **2.00** |
| Avg Latency | 5.6s | 5.6s |

## v1.6 唯一自动未通过

```text
bench_neg_003
```

- 业务正确性：PASS（明确说明没有母婴品类，不编造）
- 工具策略：PASS
- 自动 v1 失败原因：回答引用品类事实 `玩具 838 人`，被 `forbidden_result_units=["人"]` 判为结果型数字
- 处理：人工复核明确为事实引用；不修改题目

## rag_001 根因

v1.5 中 `rag_001` 会：

```text
RAG → SQL → calculator → RAG → SQL ...
```

v1.6 增加了停止规则：

```text
定义 / 口径 / 权益 / SOP 类问题：
rag_search 已返回明确原文时，直接回答；
用户没有明确要求统计人数 / 占比 / 金额时，
不要为了给近似数字继续 SQL / calculator 验证。
已能完整回答时立即结束，不要重复检索。
```

效果：

```text
rag_001 v1.5：MAX_STEPS_EXCEEDED
rag_001 v1.6：COMPLETED，Regression 全通过
```

这不是简单把 MAX_STEPS 从 6 调到 10，而是明确“定义题什么时候该停”。

## 口径说明

- v1.5 auto 92.5% 保留，不重算
- v1.6 auto 97.5% 是新版指标下的结果
- Business Correctness 100% 与 Tool Policy 100% 分开报告
- `bench_neg_003` 的自动误判属于已知事实引用边界，保留在人工复核清单
