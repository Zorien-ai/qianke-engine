# 用户画像三层模型

日期：2026-11-15

## 1. 冷启动属性

表：

```text
c_user_attribute
  owner_id
  gender
  age_range
  city
  member_level
  registered_at
  source
  updated_at
```

当前模拟数据为 80 个 C 端用户生成了确定性属性：

```text
性别 / 年龄段 / 城市 / 会员等级 / 注册时间
```

B 端接口 `profiles` 返回 `attributes`、`fields`、`has_base`。

## 2. 消费记录

复用真实订单链路，按商户聚合：

```text
订单数
累计消费
客单价
最近下单
偏好品类
```

## 3. 会话记录

优先使用 `b_chat_user_profile` 的结构化会话画像：

```text
目标与需求
偏好
顾虑与边界
预算
阶段
待确认问题
```

没有结构化画像时，保留千客用户池的最近会话摘要作为确定性证据，不再只显示「暂无结构化会话画像」。

## 页面

B 端：

```text
商家工作台 → 画像查询 → 千客用户 → 点击用户
```

详情固定显示三个分区：

```text
1 冷启动属性
2 消费记录
3 会话记录
```

### buyer_217

```text
冷启动：男 / 18-24 / 杭州 / 银卡
消费：0 笔
会话：最近两条店宠会话
```

![三层画像-冷启动和会话](docs/design/b-profile-three-layers.png)

### buyer_193

```text
冷启动：男 / 25-30 / 杭州 / 银卡
消费：2 笔 / 累计 ¥396 / 客单价 ¥198 / 偏好绿茶
会话：结构化需求 + 阶段 + 待确认问题 + 最近会话
```

![三层画像-完整](docs/design/b-profile-three-layers-193.png)

## 验证

```text
pytest：848 passed, 6 skipped
web build：PASS
浏览器：buyer_217 / buyer_193 三层详情正常
```

## 迁移说明

- SQLite/PG 控制面新增 `c_user_attribute`，`CREATE TABLE IF NOT EXISTS`，无破坏性迁移。
- 旧图像刷新千客池后自动补齐冷启动层。
- 没有冷启动数据的用户显示「暂无冷启动属性」，不伪造。
## 明确买家 ID 查询

问小千输入：

```text
buyer_217你怎么看
```

现在会先识别 `buyer_217`，直接按 `merchant_id + buyer_id` 精确取画像，不再走语义检索。

返回：

```text
buyer_217 是冷启动期的新客
冷启动：男 / 18-24 / 杭州 / 银卡
最近会话：发货时间 / 库存 / 售后政策
本次检索到千客用户池 14 人中的 1 人
```

![buyer_217 精确查询](docs/design/b-profile-buyer217-exact.png)
