# 可试点运维底座：就绪、指标、备份恢复

> 日期：2026-11-04 · 状态：/ready、/metrics、控制面备份/Restore dry-run 已验证

## 1. 就绪探针

```text
GET /ready
```

检查：

```text
control_db        C 端/控制面 SQLite
superagent_store  WorkItem/Approval 查询
queue             Job 队列统计
merchant_store    商家数据层（当前 PostgreSQL）
```

正常：

```json
{"status":"ok","checks":[...]}
```

任一依赖失败返回 `503`，错误只暴露异常类型，不泄露连接串。

实测：

```text
ready=200
control_db 3.2ms
superagent_store 7.6ms
queue 7.1ms
merchant_store 93.3ms
```

## 2. Prometheus 指标

```text
GET /metrics
```

指标：

```text
qianke_up
qianke_process_start_time_seconds
qianke_queue_jobs{status=...}
qianke_work_items{status=...}
qianke_approvals{status=...}
qianke_tenants
```

可选鉴权：

```bash
QIANKE_METRICS_TOKEN=...
# Header: X-Metrics-Token: ...
# 或 ?token=...
```

未配置 token 时开放；生产建议配置。

实测：

```text
metrics=200
qianke_queue_jobs{status="done"} 348
qianke_work_items{status="done"} 14
qianke_tenants ...
```

## 3. 备份

```bash
python scripts/backup_control_plane.py
python scripts/backup_control_plane.py --output backups/manual
python scripts/backup_control_plane.py --include-pg
```

流程：

```text
SQLite 一致性 backup API
→ 复制控制面 DB（c_end_mock.sqlite）
→ 可选 SQLite 商家库
→ 可选 pg_dump 商家 schema
→ manifest.json（sha256 + size + source）
```

实测：

```text
backup=backups/test-backup
c_end_mock.sqlite 2,760,704 bytes
sha256=b2f3acf479163f5d…
```

注意：

```text
当前环境没有 pg_dump，--include-pg 返回 ok=false / pg_dump not found
PostgreSQL 备份需安装 postgresql-client
```

## 4. 恢复

```bash
python scripts/restore_control_plane.py backups/test-backup
python scripts/restore_control_plane.py backups/test-backup --yes
```

行为：

```text
校验 manifest 与 sha256
默认 dry-run
--yes 前把当前 DB 保存为 *.before-restore-<ts>
覆盖后需重启 API/Worker
```

实测：

```text
ok c_end_mock.sqlite 2760704 bytes
dry-run：加 --yes 才会覆盖当前数据库
```

PG 恢复：

```bash
python scripts/restore_control_plane.py backups/... --yes --include-pg
# 需要 pg_restore；--clean --if-exists 覆盖 schema
```

## 5. 测试

```text
tests/test_ops.py
# 2 passed

完整套件
# 649 passed, 5 skipped, 1 warning
```

覆盖：

```text
readiness 四个检查全通过
metrics 包含 queue/work item/approval/tenant
```

## 6. 已知限制

```text
没有自动定时备份
没有对象存储/加密
没有备份保留策略
恢复需要停 API/Worker
pg_dump/pg_restore 当前未安装，PG 备份未真实验证
没有自动恢复演练
指标没有业务成功率/延迟直方图
```

## 7. 下一步 M1

```text
1. 安装 postgresql-client，验证 pg_dump/pg_restore
2. 定时备份 + 保留 7 天
3. Prometheus/Grafana 接入
4. 租户开通流程
5. 全量 PostgreSQL 控制面迁移
```
