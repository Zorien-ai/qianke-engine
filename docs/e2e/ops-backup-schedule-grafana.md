# 定时备份与 Grafana 看板

> 日期：2026-11-04 · 状态：备份保留/校验已验证；Prometheus/Grafana 配置已生成，未启动服务实测

## 1. 备份保留

```bash
python scripts/backup_control_plane.py --keep 7
```

行为：

```text
SQLite backup API 一致性复制
manifest sha256 + size
备份后校验 sha256
只保留最近 N 个带 manifest 的时间戳目录
```

实测：

```text
backup=backups/20261104-093748 keep=2
backup=backups/20261104-093756 keep=1
pruned=20261104-093748
最终目录：20261104-093756
```

## 2. 定时调度

### Windows

```powershell
pwsh -File scripts/backup_control_plane.ps1
```

任务计划程序：

```text
触发器：每天 02:00
操作：powershell.exe -NoProfile -File F:\workspace\python\rag-demo\scripts\backup_control_plane.ps1
```

日志：

```text
logs/backup.log
```

### Linux

```bash
crontab -e
0 2 * * * /path/to/rag-demo/scripts/backup_control_plane.sh
```

## 3. Prometheus

配置：

```text
ops/prometheus.yml
```

抓取：

```text
job_name: qianke
metrics_path: /metrics
targets: 127.0.0.1:8000
```

如果设置 `QIANKE_METRICS_TOKEN`：

```yaml
headers:
  X-Metrics-Token:
    values: ["<token>"]
```

校验：

```text
yaml.safe_load 通过，job_name=qianke
```

## 4. Grafana 看板

文件：

```text
ops/grafana-qianke-dashboard.json
```

UID：

```text
qianke-ops
```

面板：

```text
Qianke Up
Tenants
API Uptime
Queue Jobs by Status
Work Items by Status
Approvals / Executions
Dead Jobs
```

数据源变量：

```text
${DS_PROMETHEUS}
```

导入方式：

```text
Grafana → Dashboards → Import → 上传 JSON → 选择 Prometheus 数据源
```

校验：

```text
JSON 解析通过
panels=7
uid=qianke-ops
```

## 5. 未实测项

```text
当前机器未安装/启动 Prometheus
当前机器未安装/启动 Grafana
没有配置告警规则（Alertmanager）
没有做面板截图
```

因此只声明配置与 JSON/YAML 校验通过，不声明 Grafana 页面已实际运行。

## 6. 后续

```text
1. 安装 Prometheus + Grafana
2. 导入 dashboard，截图验收
3. 配置 Dead Jobs / ready 失败告警
4. 备份异机/对象存储
5. pg_dump 安装后加入 PostgreSQL 备份
```
