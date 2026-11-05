# 控制面 PostgreSQL 迁移 P3-A：C 端表回填

> 日期：2026-11-05 · 状态：c_* 数据已幂等回填；运行时仍读 SQLite

## 1. 回填范围

```text
c_product / c_order / c_order_item / c_after_sale
c_compensation / c_quote / c_message / c_app_message
c_friend / c_group / c_group_member / c_group_message
c_mention / c_thread_read / c_companion / c_client_request
c_reconciliation_run / c_reconciliation_alert
c_merchant_tenant / c_merchant_member / c_merchant_policy
c_merchant_policy_audit / c_tenant_provision
```

脚本：

```bash
python scripts/migrate_cend_to_pg.py          # dry-run
python scripts/migrate_cend_to_pg.py --yes    # 写入
```

## 2. 实际结果

```text
c_product                    6
c_order                    145
c_order_item               145
c_after_sale                29
c_compensation               1
c_quote                     15
c_message                   71
c_app_message               15
c_friend                     2
c_group                      1
c_group_member               3
c_group_message             12
c_mention                   10
c_thread_read                4
c_companion                  1
c_client_request            18
c_reconciliation_run        12
c_reconciliation_alert       1
c_merchant_tenant            3
c_merchant_member            2
c_merchant_policy            2
c_merchant_policy_audit      1
c_tenant_provision           1
```

target 与 source 全部一致；重复执行幂等。

## 3. 测试

```bash
pytest tests/test_cend_pg_backfill.py -q
# 1 passed
```

## 4. 当前边界

```text
只做了数据回填
C 端 API 仍读写 SQLite
没有 c_* 运行时 backend 开关
没有双写
切换前需要再次最终同步
```

## 5. P3-B 计划

```text
1. c_end/store.py 增加 PG 兼容层/仓储实现
2. 读写切 PG
3. 交易写入并发与库存锁验证
4. C 端/PG 契约测试
5. 维护窗口切换
```
