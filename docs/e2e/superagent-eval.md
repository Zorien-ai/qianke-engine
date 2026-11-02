# Super-agent vs 当前 B Agent 对比 Eval

> 日期：2026-11-02 · 真实 HTTP / 真实模型 / 5 个案例

## 1. 目的

验证 Super-agent 在**商家订单/售后调查**上是否比当前通用 B Agent 更有效，同时暴露两者数据域不同带来的能力边界。

## 2. 方法

```text
Super-agent：
  POST /api/superagent/events
  → 运行 Worker
  → 轮询到 WAITING_APPROVAL
  → 取结论

当前 B Agent：
  POST /api/agent/run
  → 取 final_reply

判分：
  期望关键词命中率；无期望关键词（noise）按过滤/拒绝判断
```

执行：

```bash
python scripts/superagent_eval.py
```

输出：

```text
tests/superagent_eval_results.json
```

## 3. 结果

```text
cases                 5
Super-agent avg       0.9
B Agent avg           0.6
Super-agent wins      2
B Agent wins          0
ties                  3
```

| 案例 | Super-agent | B Agent | 胜者 |
|---|---:|---:|---|
| order_status | 1.0 | 0.5 | Super-agent |
| logistics | 1.0 | 0.0 | Super-agent |
| after_sales | 1.0 | 1.0 | tie |
| policy | 0.5 | 0.5 | tie |
| noise | 1.0 | 1.0 | tie |

真实耗时（参考）：

```text
Super-agent：约 20–28s/题（Deep Agents + DeepSeek）
B Agent：约 3.5–5s/题
```

## 4. 结论

Super-agent 在订单状态、物流这类需要商家订单工具的问题上明显更准确；当前 B Agent 只有用户画像与知识库，无法看到商家订单，因此会出现“数据没入库”的正确但无效回答。

但这不是通用能力胜负：

```text
Super-agent 目前只有订单/售后/商品/政策工具
B Agent 有 RAG/SQL/经营分析工具
两者数据域重叠很小
```

## 5. 已知问题

```text
B Agent 的 answer 是整段 JSON，关键词命中率会低估其真实表达
Super-agent 每题 20–28s，明显慢于 B Agent
policy 题 Super-agent 与 B Agent 都只拿到部分政策
noise 题两者都能识别为闲聊/无效
```

## 6. 下一步

```text
1. 给 Super-agent 接入经营分析工具后再做同域对比
2. 增加答案事实性/引用正确性评分，不只关键词
3. 记录 token、工具调用次数和人工审批率
4. 建立回归集，防止 Worker 提示词修改导致能力回退
```
