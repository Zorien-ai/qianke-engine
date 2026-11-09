# C 端伙伴三模式（P0）

> 日期：2026-11-09 · 状态：已实现 · 范围：C 端对话层，不含订单链路变更

## 背景

C 端伙伴「小鱼」原本只有一个对话模式，且工具只有商品推荐、订单查询、订单草稿。
用户即使只想聊天，也很容易被拉回商品与下单，体感是“只想卖货”。

参考 AI companion 设计指南中的“存在感 / 记忆 / 场景 / 节奏”思路，但**不引入 NSFW 内容，不复制其文案**，只做电商场景下的陪伴感优化。

## 三种模式

```text
companion    陪伴：不推荐商品、不查订单、不生成订单
advisor      购物参谋：可推荐/比价，不生成订单
transaction  交易：可查订单、生成草稿、确认下单
```

路由规则：

```text
显式 mode 参数优先
否则按用户消息识别交易意图
再识别购物参谋意图
否则默认 companion
```

识别词示例：

```text
交易：下单 / 买 / 订单 / 物流 / 售后 / 退款 / 支付 / 快递
参谋：推荐 / 挑 / 对比 / 预算 / 价格 / 活动 / 优惠 / 礼物 / 尺码
陪伴：其他，例如“今天有点累，陪我聊聊”
```

## 工具隔离

| 模式 | 可用工具 |
|---|---|
| companion | 无 |
| advisor | `recommend_products` |
| transaction | `recommend_products` / `query_my_orders` / `prepare_order` |

`transaction` 继续保留原来的 interrupt 确认、库存与订单安全边界。

## UI

CApp 增加：

```text
陪我聊聊   -> mode=companion
帮我挑东西 -> mode=advisor
```

原有商品/活动/售后/砍价入口保留，但分别带对应的 mode。
输入框在伙伴会话显示：

```text
想聊什么，或者要买什么
```

## API

`POST /api/c/agent/run` 新增可选字段：

```json
{"message": "今天有点累", "mode": "companion"}
```

`mode` 只接受：

```text
companion / advisor / transaction
```

响应新增 `mode` 字段。

幂等指纹包含 `mode`，避免同文案不同模式被错误回放。

## 验证

```text
tests/test_c_end_agent.py
  companion 模式不暴露交易工具
  advisor 模式只推荐、不生成草稿

tests/test_c_end_persona.py
  companion/advisor prompt 不含 prepare_order
  detect_mode 默认陪伴、推荐进参谋、购买进交易

python -m pytest tests/
web: npm run build
```

## 已知限制

- P0 不做长期关系记忆，只依赖当前线程消息与伙伴配置。
- 模式识别是规则优先，不是 LLM 分类；后续可用评测数据校准。
- `query_my_orders` 仅在交易模式开放；用户从陪伴模式问物流时，需要切到交易模式。
- 不引入 NSFW、暧昧依赖、排他话术或消费引导。
