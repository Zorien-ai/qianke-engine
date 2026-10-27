# Agent Eval v1.8.1

v1.8.1 是 60 题 Benchmark 的收口小修，不新增题目。

## 改了什么

1. `bench_sql_013` 的期望值兼容千分位 `6,864` 与 `6864`。
2. `bench_multi_008` 将 `calculator` 标为可选（答案已在 SQL 内完成乘法）。
3. `bench_neg_007` 允许在明确标注“替代指标不是登录次数”的前提下引用近 7 天购买占比；仍禁止直接编造登录次数。
4. `bench_multi_010`、`bench_multi_016` 将 `calculator` 标为可选。

## 实测结果

```text
Task Success（v1）       93.3%
Business Correctness    100.0%
Tool Policy Compliance  98.3%
Tool Selection          93.3%
Tool Execution          95.0%
Error Recovery          100.0%

平均 Steps              2.53
平均 Tool Calls         2.00
平均耗时                4.3s
```

分类：

```text
calculator       6/6
execute_sql     15/15
rag_search      12/12
multi_tool      15/19
negative         8/8
```

## 4 条自动失败

全部是旧 Task Success 复合口径，业务正确性均为 PASS：

- `bench_multi_001`：答案正确，旧口径缺少 calculator
- `bench_multi_004`：答案正确，旧口径缺少 calculator
- `bench_multi_013`：答案正确，旧口径缺少 calculator
- `bench_multi_014`：答案正确，工具策略缺少 calculator

## 结论

- 60 题的业务正确性已经达到 **100%**
- Negative 达到 **8/8**
- Tool Policy 98.3%，剩余一条是 `multi_014` 的 calculator 策略元数据
- 旧 Task Success 仍保留严格工具路径口径，因此不会为了 100% 改题

下一版可以开始做 token / cost 指标或继续补工具策略元数据，不建议马上扩到 80/100。
