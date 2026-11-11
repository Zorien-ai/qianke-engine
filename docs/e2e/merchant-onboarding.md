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

## 已知限制

- 目前只有 `store_demo → m_gear_002` 默认映射；第二个商家需要管理员先绑定。
- 店宠回复仍然使用 `store_agent` 的固定商家逻辑；多商家店宠 Agent 路由是下一阶段。
- 发现页只展示已绑定映射，不展示未绑定商家。
