# 对账任务 E2E

> 日期：2026-10-31 · 状态：通过（手动对账 + 定时 worker + 运营台）

## 1. 数据留痕

新增 `c_reconciliation_run`：

```text
run_id / trigger / started_at / finished_at
ok / checked / legacy / issue_count / issues_json
```

对账只检测、不自动修改订单。

## 2. 接口

```text
GET  /api/c/admin/reconciliation?limit=200
POST /api/c/admin/reconciliation/run?limit=200
GET  /api/c/admin/reconciliation/runs?limit=20
```

实测：

```text
run rec_e1baeccb4e414f93 / MANUAL
ok=True / checked=9 / legacy=6 / issue_count=0
POST 后 runs 从 1 条变为 2 条
```

## 3. 运营台

入口：

```text
http://127.0.0.1:8000/v2/#/admin/c-end
→ 对账
```

页面展示：

```text
已核对 9
旧平台订单 6
问题数 0
状态 正常
当前问题：未发现问题
对账历史：MANUAL / SCHEDULED
```

点击「立即对账」：

```text
最近一次运行：2026-10-31 14:17:02 · MANUAL
对账完成：检查 9 单，未发现问题
历史新增一条 MANUAL
```

## 4. 定时 worker

```bash
python scripts/reconciliation_scheduler.py --interval 1800
# 或 Windows 任务计划程序调用：
python scripts/reconciliation_scheduler.py --once
```

实测 15 秒间隔运行约 50 秒：

```text
rec_8d7e15251c484e18 SCHEDULED 14:17:58 ok=True
rec_02cf987829834a44 SCHEDULED 14:17:43 ok=True
rec_d602518545bd4ca0 SCHEDULED 14:17:28 ok=True
rec_aba175304153478a SCHEDULED 14:17:13 ok=True
共 7 条 run（4 条 SCHEDULED + 手动）
```

日志：

```text
logs/reconciliation_scheduler.log
```

## 5. 问题检测

```text
MERCHANT_ORDER_MISSING  商家订单缺失
STATUS_DIVERGENCE       C 端/商家状态不一致
AMOUNT_DIVERGENCE       C 端/商家金额不一致
legacy                  无 merchant_order_id 的旧平台订单，单独计数
```

单测构造「只取消商家侧」后，对账返回 `ok=False`，`STATUS_DIVERGENCE` 正确落库。

## 6. 测试与构建

```bash
pytest tests/ -q
# 561 passed, 5 skipped, 1 warning

npm run build
# ✓ built in 4.51s
```

新增：

```text
tests/test_c_end_reconciliation_runs.py
3 passed
```

## 7. 已知限制

```text
只检测，不自动修复；修复仍需人工/后续自动化策略
一次最多 200 单，无全量分页扫描
旧平台订单只计 legacy，无法核对
单商家 m_gear_002；多商家需扩展
worker 是独立脚本，不在 API 进程内常驻
没有告警/通知；问题仅写 run 记录和日志
```
