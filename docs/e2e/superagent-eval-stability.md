# Eval 稳定性与多次采样

> 日期：2026-11-03 · 状态：temperature=0 + `--runs` 多次采样

## 1. Worker 温度

```bash
QIANKE_SUPERAGENT_TEMPERATURE=0
```

默认值改为 `0`，减少动作建议与最终结论的非确定性。

## 2. 多次采样

```bash
python scripts/superagent_eval_v2.py --runs 2
python scripts/superagent_eval_v2.py --runs 2 --only action_after_sale_type,action_receive_return
```

`--runs` 范围 1–5。

每个场景输出：

```text
runs[]：每次 result + score
score.total：多次平均分
score.pass_rate：多次通过率
score.passed：pass_rate >= 0.5
score.components：factual/action/safety/status 平均值
```

汇总：

```text
runs_per_case
cases
passed
pass_rate
avg_score
```

## 3. 真实稳定性复跑

目标场景：

```text
action_after_sale_type
action_receive_return
```

结果：

```text
2 cases × 2 runs
run1 score=1.0
run2 score=1.0
pass_rate=1.0
avg_score=1.0
avg_latency=33.3s
```

说明 temperature=0 下这两个此前失败的动作一致性场景可以稳定通过。

## 4. 与全量 Eval 的关系

单次全量仍是 24 场景；`--runs 2` 是 48 次真实模型调用，约 20 分钟。
建议：

```text
日常回归：--runs 1
动作一致性/安全关键：--runs 2 --only <ids>
发版前：全量 24 × runs 1
```

## 5. 已知限制

```text
temperature=0 不保证绝对确定性（服务端仍可能变化）
多次采样成本线性增长
评分器仍是关键词/结构判断，不是语义评审
没有自动重试失败场景
```
