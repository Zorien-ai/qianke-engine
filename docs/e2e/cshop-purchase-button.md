# C 端市集购买按钮

日期：2026-11-14

## 问题

```text
C 端市集商品卡只有“问问小鱼 / 详情”
没有“购买 / 加入购物车”按钮
即使打开详情，通用市集也不显示加入购物车
```

## 原因

```text
通用市集走 /api/c/products，商品只有 product_id/price/stock，没有真实 SKU
购物车 add 要求 sku + 商家 friend_id
通用市集商品没有绑定商家会话，加入购物车会失败
```

## 修复

```text
商品卡增加“加入购物车”按钮（有库存时）
通用市集优先读取 store_demo 的真实商家商品（含 SKU/库存）
加入购物车时自动确保商品所属商家的 friend_id
商品详情页也对通用市集显示加入购物车
```

## 验证

```text
390 视口：10 个商品卡 / 9 个购买按钮
点击“加入购物车”：toast 已加入购物车，购物车 1 件 ¥299.00
localStorage 写入 SKU-GEAR-P001-STD
无横向溢出
```

截图：docs/design/c-shop-purchase-button.png
