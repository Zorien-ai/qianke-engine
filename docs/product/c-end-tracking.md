# C 端物流查询（快递100）

> 日期：2026-11-10 · 状态：适配层已实现；服务商凭据待配置

## 范围

```text
C 端订单页“查询实时物流”
交易模式小鱼 query_tracking(order_id)
未配置凭据时明确 503，不返回伪造轨迹
```

## 服务商

当前只实现快递100：

```text
POST https://poll.kuaidi100.com/poll/query.do
参数：customer / sign / param
sign = MD5(param + key + customer).upper()
```

配置：

```text
QIANKE_KUAIDI100_CUSTOMER=
QIANKE_KUAIDI100_KEY=
QIANKE_KUAIDI100_TIMEOUT=8
```

未配置时接口返回：

```json
{"detail": {"code": "EXPRESS_NOT_CONFIGURED", "message": "物流查询未配置快递100凭据"}}
```

## API

```text
GET /api/c/orders/{order_id}/tracking
```

只允许订单本人访问；只读取该订单的 `merchant_tracking_no / merchant_carrier`。

统一返回：

```json
{
  "ok": true,
  "order_id": "order_xxx",
  "carrier": "SF",
  "provider": "kuaidi100",
  "carrier_code": "shunfeng",
  "tracking_no": "SF123456789",
  "state": "5",
  "state_text": "派送中",
  "events": [
    {"time": "2026-11-10 09:00:00", "text": "快件派送中"}
  ],
  "from_cache": false
}
```

## 安全与边界

```text
订单归属在 API 层校验；不能查他人订单
运单号只允许字母/数字/短横线
承运商白名单 + 快递100编码映射；未知承运商 400
查询结果内存缓存 5 分钟，减少服务商调用
不把快递公司原始响应透传给前端
未配置/上游异常不编造节点
```

## UI

C 端「我的订单」物流区新增：

```text
查询实时物流
派送中
时间 + 轨迹节点
查询失败提示
```

## 小鱼

交易模式新增工具：

```text
query_tracking(order_id)
```

只在该模式暴露；陪伴/购物参谋模式不可用。

## 验证

```text
快递100 签名、状态归一化、缓存、未配置 503
API 本人可见 / 他人 404 / 未配置 503
交易模式 prompt 包含 query_tracking，陪伴/参谋不包含
```

## 已知限制

- 需要快递100正式凭据才能查真实轨迹；当前只有配置位。
- 只支持快递100；切换服务商需要新增 adapter。
- 快递100 查询频率/套餐限制由商户账号决定，未做配额统计。
- 缓存是进程内缓存，多 worker 不共享；后续可切 Redis。
