# 生产预检

> 日期：2026-11-05 · 一键验证 5 项交付的关键证据

## 用法

```bash
python scripts/production_preflight.py
python scripts/production_preflight.py --json
```

## 覆盖项

```text
api_ready           本地 /ready
domain_ready        固定域名 /ready
control_tables      sa_thread / sa_work_item / sa_approval /
                    c_order / c_product / c_login_attempt /
                    c_policy_audit_anchor
queue_table         sa_queue.sa_job 状态计数
c_end_data          C 端商品与订单
prometheus_ready    /-/ready
prometheus_target   qianke target up
grafana_health      /api/health
alertmanager_ready  /-/ready
security_headers    HSTS / CSP report-uri / X-Frame-Options
```

## 本机结果

```text
PASS api_ready
PASS domain_ready
PASS control_tables  sa_thread=371 sa_work_item=372 sa_approval=366
                     c_order=145 c_product=6 c_policy_audit_anchor=1
PASS queue_table     sa_queue counts={'DONE': 348}
PASS c_end_data      products=6 orders=145
PASS prometheus_ready
PASS prometheus_target  qianke_target_up=True
PASS grafana_health
PASS alertmanager_ready
PASS security_headers   hsts=True csp_report_uri=True x_frame=SAMEORIGIN
OVERALL PASS
```

## 退出码

```text
0  全部通过
1  存在失败项，逐项输出 FAIL
```

## 说明

```text
不输出任何密码/凭据
外部请求带 User-Agent，避免 Cloudflare 默认拦截
可加入 24h 观察结束后的验收步骤
```
