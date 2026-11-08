# PG 观察报告

> 日期：2026-11-09 · 状态：最终观察窗口进行中

## 命令

```bash
python scripts/observation_report.py
python scripts/observation_report.py --json
python scripts/observation_report.py --file logs/control_pg_observation_post_recovery.jsonl
```

## 判定

```text
PASS         观察时长 ≥ 24h 且全部 ready
IN_PROGRESS  已采样但不足 24h
FAIL         出现 ready 失败
NO_DATA      没有样本
```

## 输出字段

```text
samples / first_at / last_at / duration_seconds
ready_ok / ready_fail / ready_rate / metrics_ok
gaps_over_180s
queue_done_last / queue_done_delta
queue_pending_max / queue_dead_max
waiting_approval_max / stuck_max
```

## 最终观察窗口

```text
logs/control_pg_observation_final.jsonl
```

此前恢复窗口：

```text
logs/control_pg_observation_post_recovery.jsonl
```

恢复窗口包含 API 重启导致的 3 次 ready 失败，因此报告为 FAIL；最终窗口从稳定运行后重新计时。

## 说明

观察脚本本身 24h 后退出；需要持续观察时由外部进程重新拉起。
