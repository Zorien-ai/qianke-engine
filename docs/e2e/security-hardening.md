# 生产安全加固与租户试点

> 日期：2026-11-05 · 状态：已落地安全头、租户试点烟测；SSO/PII/限流仍未做

## 1. 已落地

| 项 | 状态 | 证据 |
|---|---|---|
| 登录态 / 密码哈希 | ✅ 已有 | `rag_demo/auth.py`，Argon2 |
| 角色权限 owner/admin/staff | ✅ 已有 | 租户 API、B 工作台 |
| 租户数据隔离 | ✅ 已有 | `merchant_id` 作用域 + 跨租户守卫 |
| 高风险动作人工审批 | ✅ 已有 | Super-agent HITL |
| 动作策略/金额上限 | ✅ 已有 | `c_merchant_policy` |
| 执行审计 | ✅ 已有 | `sa_approval` + 审计页 |
| SQL 只读防御 | ✅ 已有 | SELECT-only / 白名单 / LIMIT |
| 安全响应头 | ✅ 本次新增 | `api/security.py` + 2 tests |
| 生产监控告警 | ✅ 本次部署 | Prometheus/Grafana/Alertmanager |

安全响应头：

```text
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Strict-Transport-Security（仅 HTTPS）
```

## 2. 租户试点

试点租户：

```text
merchant_id: m_pilot_001
owner: aaa / myc6666
补偿上限: 40
退款上限: 300
```

冒烟：

```bash
python scripts/tenant_pilot_smoke.py
```

检查：

```text
tenant_exists
owner_bound
policy_initialized
work_items_scoped
```

## 3. 未完成（生产阻断项）

```text
SSO / MFA
PII 字段识别、脱敏、加密
登录限流 / WAF / IP 白名单
审计不可篡改 / WORM / 异地备份
Secrets Manager（当前 .env）
CSP（需先梳理 Vue/inline script）
依赖漏洞扫描与 SBOM
渗透测试
数据保留与删除策略
租户级配额/计费
```

## 4. 上线前最低清单

```text
[ ] Grafana 密码改为随机并纳入密钥管理
[ ] Alertmanager 接真实通知渠道
[ ] 审计日志只追加 + 备份
[ ] 租户数据导出/删除流程
[ ] 登录失败限流
[ ] HTTPS/HSTS 在入口生效
[ ] 依赖漏洞扫描通过
```
