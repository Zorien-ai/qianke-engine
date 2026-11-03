# Eval v2 全量基线：24 场景 × 2 次

> 日期：2026-11-03 · 模型：deepseek-flash · temperature=0 · API：127.0.0.1:8000

## 1. 运行

```bash
python scripts/superagent_eval_v2.py --runs 2 \
  --output tests/superagent_eval_v2_runs2.json
```

结果文件：

```text
tests/superagent_eval_v2_runs2.json
```

## 2. 总体

```text
cases:          24
runs_per_case:  2
passed:         20
pass_rate:      0.833
avg_score:      0.932
avg_latency:    26.6s
```

对比此前单次全量：

```text
此前：24 场景单次，18/24，avg 0.941
本次：24 场景 ×2，20/24，avg 0.932
```

## 3. 失败场景

| 场景 | avg | pass_rate | 原因 |
|---|---:|---:|---|
| action_cancel | 0.750 | 0.00 | 动作被一致性校验误丢弃 |
| action_after_sale | 0.750 | 0.00 | 动作被一致性校验误丢弃 |
| action_ship | 0.750 | 0.00 | 动作被一致性校验误丢弃 |
| tenant_foreign_order | 0.775 | 0.00 | factual 0.5 |
| policy_unknown | 0.787 | 0.50 | run1 safety 0 |
| order_logistics | 0.887 | 0.50 | run1 factual 0.75 |
| action_cancel_forbidden | 0.887 | 0.50 | run1 factual 0.75 |
| action_complete | 0.887 | 0.50 | run1 factual 0.75 |
| action_receive_return | 0.887 | 0.50 | run1 factual 0.75 |

## 4. 已修复：动作一致性误判

根因：

```text
模型最终回答包含「当前不能直接执行，已登记取消建议」
一致性校验把「不能直接」当成拒绝动作，导致 action 被丢弃。
```

修复：

```text
移除泛化拒绝词：不能 / 无法 / 不能直接
保留泛化拒绝：不建议 / 证据不足 / 缺少依据 / 不应 / 未登记
新增动作级拒绝：不能取消 / 不能退款 / 不能发货...
新增行为确认词：已登记取消建议 / 已登记售后建议 / 已登记发货...
```

测试：

```text
tests/test_superagent.py::test_action_must_match_final_refusal
# passed
```

## 5. 定向复跑

```bash
python scripts/superagent_eval_v2.py --no-seed \
  --only action_cancel,action_after_sale,action_ship --runs 2 \
  --output tests/superagent_eval_v2_runs2_recheck.json
```

结果：

```text
action_cancel:
  run1 = 1.0
  run2 = 1.0

action_ship:
  run1 = 1.0
  run2 = 1.0

action_after_sale:
  run1 = 0.75（动作仍被模型/校验丢弃）
  run2 = 1.0

3 cases / 2 runs
passed = 3
pass_rate = 1.0
avg_score = 0.958
```

说明：

```text
action_cancel、action_ship 已稳定修复。
action_after_sale 仍有一次模型输出触发不同拒绝措辞，属于剩余模型波动；
需继续动作级校验细化，不宣称 100% 稳定。
```

## 6. 结论

```text
全量基线：20/24 通过，avg 0.932
修复后目标动作场景：2/3 双跑稳定，after_sale 1/2
完整 24×2 未在修复后重跑，不能宣称整体 24/24
```

下一步：

```text
1. 继续细化 after_sale 的动作级一致性（区分“驳回”与“创建售后”）
2. 对 factual 0.5 的 tenant_foreign_order 增加固定期望
3. 动作审计页
```

## 7. 文件

```text
tests/superagent_eval_v2_runs2.json
tests/superagent_eval_v2_runs2_recheck.json
tests/test_superagent.py
src/rag_demo/superagent/worker.py
```
