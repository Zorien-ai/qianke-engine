# 退货物流验收入库 E2E

> 日期：2026-10-31 · 状态：通过（真实 C 端 + 运营台 + 商家库存）

## 1. 状态机

```text
OPEN
  ├─ REFUND_ONLY 通过 → APPROVED + 退款
  └─ RETURN_REFUND 同意退货 → RETURN_PENDING
                                  ↓ 用户填退回运单
                              RETURN_SHIPPED
                                  ↓ 商家验收
                          ┌───────┴────────┐
                     通过 → APPROVED      拒收 → REJECTED
                     + 恢复库存 + 退款
```

## 2. 真实 API 链路

订单 `order_ccbf04ec71cf4f35`（P001 跑鞋）：

```text
创建退货退款工单 as_665a4b6ee1474430
→ 管理员同意退货：RETURN_PENDING
→ 用户提交退回运单：RETURN_SHIPPED / SF-RETURN-001
→ 运营台验收通过：APPROVED / 退款 ¥299.00 / 入库时间写回
→ C 订单 REFUNDED / 商家订单 REFUNDED
→ 商家 P001 库存 18 → 18（原扣减 1，退回 1）
```

## 3. 真实浏览器链路

C 端订单 `order_d87a80506fd24f48`（P002 通勤双肩包）：

```text
售后 · 请寄回
as_bbc95ee3f47e40ee
退货退款 / 颜色不喜欢，申请退货
请将商品寄回，并填写退回运单；商家验收入库后退款。
```

填写：

```text
退回运单号：SF-RETURN-UI-001
承运商：顺丰速运
→ 提交退回运单
→ 售后 · 退货运输中
→ 退回运单：顺丰速运 · SF-RETURN-UI-001
```

运营台：

```text
售后工单 / 退货运输中
→ 点击「验收通过」
→ 已通过
→ 退款金额 ¥199.00
→ 入库 2026-10-31 13:31:39
```

## 4. 接口

```text
POST /api/c/orders/{order_id}/after-sales/{ticket_id}/return-shipment
{"tracking_no":"SF-RETURN-UI-001","carrier":"顺丰速运"}

POST /api/c/admin/after-sales/{ticket_id}/receive
{"accepted":true}

PATCH /api/c/admin/after-sales/{ticket_id}
{"approved":true}     # REFUND_ONLY 直接退款；RETURN_REFUND 进入 RETURN_PENDING
```

## 5. 商家入库契约

```text
receive_return(merchant_id, order_id, request_id=None)
```

规则：

```text
只允许 SHIPPED / COMPLETED
按该订单 COMMITTED 预占的 SKU/仓库/数量恢复库存
预占标记 REVERSED，reserved 不变
无预占（如种子订单）→ MERCHANT_CONFLICT，不猜仓库
整单一次入库；重复调用幂等
订单状态不变，只写 returned_at / restock_request_id
推荐顺序：receive_return → refund_order
```

## 6. 测试与构建

```bash
pytest tests/ -q
# 558 passed, 5 skipped, 1 warning

npm run build
# ✓ built in 4.16s
```

商家专项：

```text
tests/test_merchant_store.py
tests/test_merchant_write.py
tests/test_merchant_postgres.py
# 154 passed（含真实 PostgreSQL 16）
```

C 端交易专项：

```text
tests/test_c_end_merchant_transactions.py
# 13 passed
```

覆盖：

```text
退货同意 → RETURN_PENDING
提交退回运单 → RETURN_SHIPPED
验收通过 → APPROVED + 退款 + 恢复商家/C 库存
拒收 → REJECTED，订单保持 CONFIRMED
退回运单校验
```

## 7. 已知限制

```text
整单一次退货入库，不支持部分退货/多批次
没有质检结果、不良品、二次销售标记
没有真实逆向物流 API，退回运单由用户手填
退款仍是本地模拟，无支付网关
C 端和商家仍是两个 SQLite 事务，没有分布式事务
```
