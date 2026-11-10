# 千客系统验收报告

> 日期：2026-11-10 · 范围：后端、运维、C 端与 B/A 端主要前端页面 · 结论：**可内部试点，不建议直接公开生产**

## 一、结论

核心链路和主要页面可用，生产预检全部通过；本次验收发现并修复 2 个真实问题：

```text
平台监控/Token 账单/计费页 500：ai_monitor / chat_history 使用了导入时缓存的旧 PG 配置（5432）
首页 Lighthouse：页脚对比度不足、缺少 meta description
```

修复后：

```text
710 passed, 5 skipped
production_preflight.py -> OVERALL PASS
Lighthouse 首页：Accessibility 100 / Best Practices 100 / SEO 100
19 个主要前端路由：0 console error、0 个 /api 或 /v2 4xx/5xx
C App 390px 移动端：无横向溢出
```

## 二、已修复

### 1. 监控/账单页 500

根因：

```text
ai_monitor._connect() / chat_history._connect()
-> auth.PG_CONFIG（模块导入时缓存）
-> port 5432
实际 pgvector 映射 15432
```

修复：

```text
auth.current_pg_config() 动态读取 .env
ai_monitor / chat_history 改用动态配置
新增 tests/test_auth_pg_config.py
```

复测：

```text
/api/monitor/overview             200
/api/admin/billing/prices         200
/api/admin/monitor/tenants        200
/api/billing/wallet               200
/api/billing/invoices             200
```

### 2. 首页可访问性/SEO

```text
页脚文字对比度 3.36 -> 5.23
补充 meta description
Lighthouse: 96/91 -> 100/100
```

截图：

![C App 移动端](system-audit-c-app-mobile.png)

## 三、页面验收

| 页面 | 结果 |
|---|---|
| 官网 /home | 正常；Lighthouse 100/100/100 |
| 工作台 / | 正常 |
| 对话 /chat | 正常 |
| Agent /agent | 正常 |
| 任务看板 /agent/actions | 正常 |
| 我的 AI /my-agent | 正常 |
| C 商城 /c | 正常（mock 商品库） |
| 社交消息 /c/social | 正常（mock IM） |
| 我的订单 /c/orders | 正常（空状态） |
| C App /c/app | 正常；移动端无横向溢出 |
| C 端审计 /admin/c-end | 正常 |
| 知识库 /kb、/kb/docs | 正常 |
| 员工管理 /staff | 正常 |
| 权限配置 /settings | 正常 |
| 离线评测 /eval | 正常 |
| 实时监控 /monitor | 修复后正常 |
| Token 账单 /billing | 修复后正常 |
| 平台监控 /admin/monitor | 修复后正常 |

## 四、仍然缺什么

### P0：上线前必须处理

1. **告警没有真正通知人**
   - Prometheus 正在 firing `QiankeStuckWorkItems`。
   - Alertmanager 只有默认 receiver，没有邮件/Webhook/企业微信配置。
   - 当前效果：告警面板能看到，但没人会收到通知。

2. **备份过期**
   - `backups/` 最新目录是 2026-11-05，之后没有新备份。
   - 没有找到千客专用备份计划任务。
   - 需要确认备份 cron/计划任务，并做一次恢复演练。

3. **Docker Desktop 单点**
   - 11-09、11-10 两次整站不可用，都是 Docker Desktop 停止。
   - 容器 restart policy 是 `unless-stopped`，但 Docker Desktop 本身没有随系统启动/守护。
   - 需要开机自启 + 外部健康检查 + 自动拉起。

4. **审批积压**
   - `WAITING_APPROVAL` 347 条，`PENDING` 审批 347 条。
   - `STUCK` 1 条：`saw_6a7a025aaf3c4fd5`，2026-11-02 起未处理。
   - `EXECUTION_FAILED` 5 条。
   - 需要人工清理/重放，否则监控会长期告警。

5. **凭据文件仍在磁盘**
   - `var/credential-rotation-final.txt` 仍存在，包含 PG / 只读账号密码。
   - 文件里的 admin 密码已失效（说明密码已改），但 PG 凭据仍需按敏感文件处理。
   - 建议删除文件或迁入密钥管理，并确认 `.gitignore` 未跟踪。

### P1：影响可信度/运营

6. **PG 观察没有连续运行**
   - `logs/control_pg_observation_20261109_recovery.jsonl` 最后写入 2026-11-09 21:52。
   - 没有新的 24h 观察证据。

7. **快递查询只有兜底**
   - 快递100 API 未配置凭据，服务端查询返回 503。
   - 订单页“去快递100查询”可用，但小鱼无法自动分析真实物流节点。
   - 签收回调接口已就绪，但没有真实物流商转发。

8. **C 端部分页面仍是演示数据**
   - C App 月度支出 `¥1,286`、部分会话/概览是静态参考；页面自己也标注“订单为实时数据 · 其余为界面参考”。
   - C 商城商品库、社交 IM 仍是 mock。
   - Dashboard 数字来自接口，但 demo 数据集不是生产数据。

9. **交易/物流仍是模拟**
   - 支付、真实订单、真实物流、真实 IM 都未接入。
   - 当前只能定位为内部试点/演示，不应对外承诺真实交易。

10. **日志噪音**
    - API 日志仍保留修复前的 5432 连接错误堆栈，缺少按启动切分/轮转。
    - 建议日志按日期/进程切分，避免历史错误干扰排障。

### P2：体验/工程

11. 前端无自动化视觉回归；本次靠 Playwright 人工巡检。
12. C App、C 商城、社交页仍有静态演示态，未完全接真实数据。
13. 没有真实 Push/IM 主动通知；关系节奏仍是打开 App 时检查。
14. 备份保留/恢复演练没有自动化验证。
15. 没有前端错误上报（Sentry 类）与用户行为分析。

## 五、建议下一步

按顺序：

```text
1. 配 Alertmanager 邮件/企业微信 receiver，确认告警能到人
2. 恢复备份计划任务，做一次恢复演练
3. 清理 347 条待审批 + 1 条 STUCK + 5 条 EXECUTION_FAILED
4. Docker Desktop 开机自启 + 外部健康检查
5. 删除/迁移 credential-rotation-final.txt
6. 重新启动 24h PG 观察并出报告
```

完成 1–5 后，才适合从“内部试点”提升到“小范围生产”。
