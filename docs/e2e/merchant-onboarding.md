# C 端商家店宠发现 + 管理端店宠映射

日期：2026-11-11

## C 端发现店宠

入口：

```text
C 端 -> 消息 -> 好友 -> 发现店宠
```

行为：

```text
GET  /api/c/merchants/available
  → 返回已绑定商家的店宠
  → 已添加显示“已添加”

POST /api/c/friends/merchants
  → 把店宠加入当前买家好友
  → 重复添加幂等
```

截图：![C 端发现店宠](c-discover-merchants.png)

## 管理端店宠映射

入口：

```text
/v2/#/admin/merchant-store-friends
```

能力：

```text
查看所有店宠 friend_id 与 merchant_id 的绑定
新增/更新绑定
```

截图：![管理端店宠映射](admin-merchant-store-friends.png)

## 完整链路

```text
管理员绑定 store_tea -> m_tea_001
→ C 买家在“发现店宠”添加山雾茶业
→ c_friend 出现 store_tea
→ 买家与 store_tea 产生 c_message
→ B 画像扫描器遍历映射
→ 生成 m_tea_001 下该买家的画像
```

## 多商家店宠 Agent 路由

已验证：

```text
store_tea → m_tea_001
买家发送 "@店宠 推荐一款龙井"
→ 店宠读取 m_tea_001 商品
→ 返回 P-TEA-001 明前龙井
→ metadata.product_refs 带 SKU / 价格 / 库存
```

截图：

![山雾茶业店宠回复](c-tea-store-chat.png)

实现：

```text
friend_id → c_merchant_store_friend → merchant_id
→ store_agent._tools(merchant_id)
→ 商品 / 库存 / 订单全部按该商家查询
→ system prompt 使用该商家名称
```

## 已知限制

- 默认映射只有 `store_demo → m_gear_002`；其它商家需要管理员先绑定。
- 店宠 SOP 仍然是平台共享的 `store_policy`，还没有按商家配置。
- 发现页只展示已绑定映射，不展示未绑定商家。
- C 端商城入口仍默认山野户外；按当前会话切换商城商家是下一步。
