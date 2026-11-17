# C 端自由砍价 v1 设计

> 状态：P0 已实现（2026-11-17）  
> 决策：自由多轮谈价 + 商家底价 + 小额自动成交、超出额度转 B 端审批  
> 日期：2026-11-17

## 1. 定位

把当前「固定满减计算器」升级为真正的自由砍价：

```text
C 小鱼：表达目标价 / 还价 / 接受 / 不买了
B 店宠：报价 / 还价 / 解释为什么不能再降
→ 多轮自然语言协商
→ 在商家底价之上成交
→ 报价 PENDING，用户确认订单
```

但“自由”不等于让大模型随便改价：

```text
LLM 负责：理解用户意图、生成谈判话术、选择策略
确定性代码负责：底价、折扣、库存、审批、报价快照
```

## 2. 成交边界

采用已确认的方案：

```text
商家底价
  + 自动成交额度
  + 超出额度转 B 端审批
```

### 2.1 默认策略（演示环境，可由商家改）

```text
floor_ratio                  0.85   # 最终成交价不得低于原价 85%
max_merchant_discount_ratio  0.10   # 商家让利最多 10%
auto_approve_discount_ratio  0.05   # 商家让利 ≤5% 自动成交
max_rounds                   4
quote_expires_minutes        15
```

示例：明前龙井 ¥198

```text
底价              ¥168.30
商家最大让利       ¥19.80
自动成交让利上限   ¥9.90
C 目标价 ¥190：让利 ¥8.00 → 自动成交
C 目标价 ¥180：让利 ¥18.00 → 超过自动额度，转 B 端审批
C 目标价 ¥150：低于底价 → 拒绝 / 还价到底价
```

## 3. 优惠叠加规则

避免双重让利导致破价：

```text
最终应付 = 商品小计
         - 平台满减（平台承担，规则固定）
         - 商家砍价让利（商家承担，自由谈判）
```

约束：

- 底价检查针对**最终应付**。
- `auto_approve` / `max_discount` 只约束**商家砍价让利**，不把平台满减算成商家让利。
- 平台满减不参与自由谈判，LLM 不能修改。
- 成交报价必须同时记录 `platform_discount` 和 `merchant_discount` 两笔来源。

## 4. 用户流程

```text
商品详情 / 购物车 / CApp 对话
→ 打开「自由砍价」
→ 带出商品、SKU、数量、当前到手价
→ 用户说目标价或“便宜点”
→ C 小鱼与 B 店宠多轮协商
→ 出现成交价
    ├─ 自动额度内：生成 PENDING 报价
    └─ 超出自动额度：显示“等商家确认”
→ 商家 B 端审批
→ 报价生效
→ 用户准备订单草稿 → 确认订单
```

### 4.1 界面

一个共享的谈判面板，替换 CShop/CApp 两套旧逻辑：

```text
┌──────────────────────────────┐
│ 自由砍价 · 明前龙井           │
│ 原价 ¥198 · 当前到手 ¥198     │
│ 商家底价不可见                │
├──────────────────────────────┤
│ 小鱼：180 能卖吗？            │
│ 店宠：180 可以，但需要店长确认 │
│       [¥180 待确认]           │
│ 小鱼：那 190 呢？             │
│ 店宠：190 可以直接成交         │
│       [¥190 成交报价]         │
├──────────────────────────────┤
│ [输入还价]  [接受] [不买了]   │
└──────────────────────────────┘
```

用户侧展示：

```text
报价卡：原价 / 平台满减 / 商家让利 / 到手价 / 省多少 / 有效期
状态卡：协商中 / 等待商家确认 / 已成交 / 已拒绝 / 已过期
```

不显示商家底价，避免把底价当成默认成交价。

## 5. 多轮协议

### 5.1 每轮结构化状态

```json
{
  "bargain_id": "bargain_...",
  "status": "NEGOTIATING",
  "list_total": 198.0,
  "platform_discount": 0.0,
  "current_offer": {
    "offer_id": "offer_3",
    "merchant_discount": 8.0,
    "payable": 190.0,
    "expires_at": "2026-11-17T12:15:00+08:00",
    "approval": "AUTO"
  },
  "round": 2,
  "max_rounds": 4,
  "transcript": []
}
```

### 5.2 状态机

```text
NEGOTIATING
  → ACCEPTED            自动额度内成交
  → WAITING_APPROVAL    超出自动额度，等待 B 端
  → REJECTED            低于底价 / 轮次用尽 / 用户放弃
  → EXPIRED

WAITING_APPROVAL
  → ACCEPTED            商家同意
  → REJECTED            商家拒绝
  → EXPIRED

ACCEPTED
  → QUOTE_CREATED
  → CONSUMED            用户确认订单
```

### 5.3 B 店宠允许的动作

B 店宠只能通过工具拿到“被允许的报价”：

```text
propose_offer(bargain_id, merchant_discount, reason)
  → 服务端校验：
      最终应付 >= floor
      商家让利 <= max_discount
      库存充足
      轮次 / 有效期未过
  → 返回允许的 offer 或结构化错误
```

LLM 不能直接写价格；它只能选择工具返回的合法 offer。

### 5.4 C 小鱼允许的动作

```text
counter(target_or_message)
accept(offer_id)
reject()
```

服务端解析用户消息中的金额和意图，但最终状态由代码判定：

- 用户说“180 可以” → 只有存在 ≤180 的合法 offer 才能 ACCEPTED。
- 用户说“再便宜点” → 进入下一轮，B 降一档或拒绝。
- 用户说“不买了” → REJECTED。

## 6. 数据模型

新增三张表（SQLite / PostgreSQL 双写 schema 同步）：

### c_bargain_policy

```text
merchant_id PK
enabled
floor_ratio
max_merchant_discount_ratio
auto_approve_discount_ratio
max_rounds
expires_minutes
updated_by
updated_at
```

### c_bargain_session

```text
bargain_id PK
buyer_id
friend_id
merchant_id
status
list_total
platform_discount
target_price
current_offer_json
merchant_discount
transcript_json
quote_id
approval_id
created_at
updated_at
expires_at
```

### c_bargain_approval

```text
approval_id PK
bargain_id
merchant_id
buyer_id
status PENDING / APPROVED / REJECTED
proposed_payable
merchant_discount
note
decided_by
decided_at
created_at
```

最终仍复用 `c_quote` 和订单确认链路，不新增订单状态。

## 7. API

### C 端

```text
POST /api/c/bargains
  { items | sku, target_price?, message? }
  → 创建 session，返回首轮 B 报价

GET  /api/c/bargains/{bargain_id}
POST /api/c/bargains/{bargain_id}/messages
  { message }
  → 解析意图，生成下一轮
POST /api/c/bargains/{bargain_id}/accept
  { offer_id }
  → AUTO：创建 PENDING quote
  → APPROVAL：创建 approval，status=WAITING_APPROVAL
POST /api/c/bargains/{bargain_id}/cancel
```

### B 端

```text
GET  /api/b/workbench/bargains?status=PENDING_APPROVAL
POST /api/b/workbench/bargains/{approval_id}/approve
POST /api/b/workbench/bargains/{approval_id}/reject
```

B 端审批后：

```text
APPROVED → 创建 PENDING quote
REJECTED → session 回 NEGOTIATING 或 REJECTED
```

## 8. 前端改造

### 8.1 共享组件

新增 `web/src/components/BargainChat.vue`：

- 输入：商品 / 购物车 / friend_id / merchant_id / target_price
- 输出：quote、session 状态、审批状态
- CShop 商品详情、CShop 购物车、CApp 弹层共用

### 8.2 CShop

- 商品详情：「让小鱼去砍价」→ 打开谈判面板
- 购物车：「合并砍价」→ 打开谈判面板
- 取消“预算 500”默认值；改为目标价可选
- 报价卡显示“平台满减”和“商家让利”两行，避免用户误以为是平台优惠

### 8.3 CApp

- 对话中砍价意图 → 打开同一谈判面板
- 面板关闭后保留未完成 session，可从消息卡恢复
- 商家审批中显示“等商家确认”，不允许直接生成订单

### 8.4 B 工作台

新增「砍价审批」入口：

```text
待审批列表：买家 / 商品 / 原价 / 申请价 / 让利 / 轮次 / 有效期
操作：同意 / 拒绝 / 备注
审批记录：谁、何时、改了什么
```

只有 owner/admin 可审批；staff 只读。

## 9. 安全与风控

强制边界：

```text
价格不能低于商家底价
商家让利不能超过 max_merchant_discount
超出自动额度必须 B 端审批
库存不足 / 商品下架 / SKU 不可用不能成交
报价有有效期，过期作废
同一 session 最多 4 轮，防无限纠缠
每买家 / 每商品限频，防刷报价
LLM 不能直接写库、不能改价、不能确认订单
```

审计：

- 每轮 C/B 消息、报价、审批、quote 创建都落库。
- B 端审批记录谁在何时同意了多少让利。
- A 端可查 bargain session / approval 审计。

## 10. 测试计划

### 单元

```text
目标价高于原价：不允许反向加价
目标价在自动额度内：ACCEPTED
目标价超过自动额度但高于底价：WAITING_APPROVAL
目标价低于底价：REJECTED / 还价
超过 max_rounds：REJECTED
库存不足 / 商品下架
平台满减 + 商家让利同时存在
报价过期
重复 accept 幂等
```

### API

```text
创建 session 不生成 quote
accept 自动成交只生成 PENDING quote
approval 通过后才生成 quote
approval 跨商家/跨用户 403
```

### 浏览器 E2E

```text
CShop 商品详情：180 申请 → 190 自动成交
CShop 购物车：多商品合并砍价
CApp：自由输入“再便宜点”/“190 可以”
B 端：审批 180 → C 端拿到报价 → 确认订单
移动端 390px
```

## 11. 分期与工作量

```text
P0：后端 session + policy + C API + B 审批 API + 测试
   预计 2 天

P1：CShop/CApp 共享谈判面板 + B 工作台审批页
   预计 1.5 天

P2：通知、限频、A 端审计、转化埋点
   预计 1 天
```

不新增真实支付；最终订单仍然是模拟交易 + 用户确认。

## 12. 需要确认

1. 默认策略采用 `85% 底价 / 10% 最大让利 / 5% 自动审批`？
2. 自由砍价只谈**商家让利**，平台满减规则固定、不参与谈判？
3. B 端审批入口放在「经营协作 → 砍价审批」？

确认后按 P0 开始实现。


## 13. P0 实现记录

```text
后端
  src/rag_demo/c_end/free_bargain.py
  store.py：c_bargain_policy / c_bargain_session / c_bargain_approval
  c_end.py：POST/GET /api/c/bargains*
  b_workbench.py：GET /api/b/workbench/bargains、POST .../decide

前端
  web/src/components/BargainChat.vue
  CShop 商品详情 / 购物车 / CApp 对话
  B 工作台「经营协作 → 砍价审批」
```

已验证：

```text
180 元：需要 B 端审批，审批后报价 180，草稿金额 180、优惠 18
190 元：自动额度内直接报价，草稿金额 190、优惠 8
订单确认：CONFIRMED / total 190
pytest：860 passed, 6 skipped
```

说明：

- `85%` 是绝对硬底价；`10%` 是最大商家让利。两者同时生效时取更严格者，所以当前有效最低价是原价的 90%。
- P0 店宠回复是确定性模板；自由输入、还价、接受由服务端解析并校验。
- 审批结果需要 C 端点「刷新状态」；后续 P1 可加通知/轮询。
