# C 端 Mock 商品与模拟订单 v0.1

> 当前没有真实商品/订单数据，先用独立 SQLite mock 存储验证 C 端订单闭环。
> 不写入 demo 评测库，不影响 Regression/Benchmark。

## 1. 存储

默认文件：

```text
var/c_end_mock.sqlite
```

可配置：

```bash
QIANKE_C_END_DB=var/c_end_mock.sqlite
```

表：

```text
c_product
  product_id / merchant_id / title / category / price / stock / status

c_order
  order_id / buyer_id / status / total_amount
  confirmation_hash / snapshot_json / idempotency_key / source_order_id
  created_at / confirmed_at

c_order_item
  order_id / product_id / quantity / unit_price

c_companion
  owner_id / name / species / persona / appearance
  level / exp / satiety / updated_at
```

伙伴字段是抽象表现层，不把“锦鲤”写死：

```text
species: digital_companion / cat / fish / robot / brand_mascot / custom
```

默认伙伴为“小伴 / digital_companion”；可通过 PATCH 改名、换 species/persona/appearance。
买家的伙伴只在确认订单后获得成长值/饱食度奖励。

```text
GET   /api/c/companion
PATCH /api/c/companion
{"name":"阿团","species":"cat","persona":"calm","appearance":"cat-v1"}
```

内置 6 个 mock 商品：

```text
P001 轻量跑鞋     299
P002 通勤双肩包   199
P003 保温杯        89
P004 蓝牙耳机     399
P005 运动 T 恤    129
P006 防晒衣       159
```

## 2. 订单状态

```text
DRAFT      已准备，未扣库存
CONFIRMED  已确认，已扣库存
```

流程：

```text
POST /api/c/orders/prepare
  → 校验商品/库存/价格
  → 创建 DRAFT
  → 返回 order_id + confirmation_token + 订单摘要

用户确认订单内容

POST /api/c/orders/{draft_id}/confirm
  → 校验 token
  → 校验商品价格/库存未变化
  → 扣库存 + 创建 CONFIRMED 订单
```

## 3. 强制约束

- prepare 不扣库存
- confirm 必须带 confirmation_token
- token 绑定草稿快照
- 商品价格变化后旧确认失效
- 库存不足拒绝
- request_id 幂等，重复确认返回同一订单，不重复扣库存
- 不能确认/查看其他 buyer 的订单
- 第一版只模拟，不接真实支付

## 4. API

```text
GET  /api/c/products
POST /api/c/orders/prepare
POST /api/c/orders/{draft_id}/confirm
GET  /api/c/orders/{order_id}
```

请求示例：

```json
{
  "items": [
    {"product_id": "P001", "quantity": 2}
  ]
}
```

确认示例：

```json
{
  "confirmation_token": "prepare 返回的 token",
  "request_id": "req_c_order_001"
}
```

## 5. C 端 Agent 与 HITL

C 端 Agent Graph：

```text
用户消息
  → recommend_products（真实商品库）
  → prepare_order（只生成 DRAFT）
  → interrupt（返回草稿，等待用户确认）
  → approved=true  → confirm_order（扣库存，生成正式模拟订单）
  → approved=false → CANCELLED
```

API：

```text
POST /api/c/agent/run
  → 首次一般返回 200 + status=AWAITING_CONFIRMATION + draft
  → 也可能直接返回推荐结果

POST /api/c/agent/resume
  → thread_id + approved
  → approved=true 创建模拟订单
  → approved=false 取消
```

关键点：

- `prepare_order` 不扣库存
- 用户在 interrupt 后确认
- 确认绑定 prepare 返回的 draft/token
- Agent 不能自行跳过确认创建订单

## 6. C 端页面

Vue 页面：

```text
/v2/#/c
```

功能：

- 商品目录
- 输入购物需求
- 导购 Agent 回复
- 订单草稿确认/取消
- 确认后展示模拟订单

页面源码：

```text
web/src/views/CShop.vue
```

截图：

![C 端商城](screenshots/c-end-shop.png)

## 7. 当前买家身份

当前复用登录账号：

```text
buyer_id = buyer_<app_user.id>
```

这不是最终 C 端消费者模型。真正接入前需要独立消费者身份、收货信息和会员体系。
