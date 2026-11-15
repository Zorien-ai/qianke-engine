# 模拟商家 / C 端用户数据

日期：2026-11-15

## 规模

```text
新增商家租户：6（总计 9）
新增商家商品：18
新增商品 SKU：18
新增 C 端商品：18
模拟 C 端消费者：80（总计 83）
模拟 C 端订单：100
模拟店宠会话消息：100
```

订单状态（模拟商家订单）：

```text
PAID / SHIPPED / COMPLETED 混合
```

## 商家账号

统一密码：

```text
Sim2026!
```

| 商家 | merchant_id | 登录账号 |
|---|---|---|
| 山岚茶事 | m_sim_tea | sim_biz_tea |
| 岩行户外 | m_sim_outdoor | sim_biz_outdoor |
| 晚灯家居 | m_sim_home | sim_biz_home |
| 北纬咖啡 | m_sim_coffee | sim_biz_coffee |
| 纸间文具 | m_sim_stationery | sim_biz_stationery |
| 禾木生鲜 | m_sim_fresh | sim_biz_fresh |

入口：

```text
/v2/login
登录后进入 /v2/b.html
```

## C 端消费者

手机号：

```text
13810000001 ~ 13810000080
```

密码：

```text
Sim2026!
```

入口：

```text
/c/login
→ 使用密码登录
```

完整昵称 / buyer_id 列表：

```text
var/simulation_accounts.json
```

## 落库方式

脚本：

```text
scripts/seed_simulation.py
scripts/seed_simulation_activity.py
```

`seed_simulation.py` 建商家、商品、基础用户和订单；  
`seed_simulation_activity.py` 把用户补到 80、订单补到 100、店宠会话消息补到 100。

当前本地运行时 C 端使用 PostgreSQL，执行时显式指定同一套后端：

```powershell
$env:QIANKE_CONTROL_BACKEND = "postgres"
$env:QIANKE_CEND_BACKEND = "postgres"
$env:QIANKE_MERCHANT_BACKEND = "postgres"
$env:QIANKE_QUEUE_BACKEND = "postgres"
python scripts/seed_simulation.py --apply
python scripts/seed_simulation_activity.py --apply
```

两个脚本都只做增量插入；重复执行会跳过已存在账号、租户、商品、订单和消息。

## 真实购买验证

```text
C 端账号：13810000001 / Sim2026!
入口：山岚茶事店铺
商品：明前龙井 × 1
报价：¥198.00
订单：order_1d5507b7318a4d61
状态：已创建（模拟支付）
```

![C 端真实下单](docs/design/c-real-purchase-created.png)

## 画像功能验证

B 端账号：`sim_biz_tea`  
入口：商家工作台 → 画像查询 → 千客用户

刷新千客池后：

```text
千客用户：14 人
有订单：6 人
有会话：9 人
```

问小千：

```text
哪些客户买过绿茶？请列出买家 ID 和订单数
```

答案正确列出 4 位买家，并明确说明：

```text
千客池共 14 人，本次检索到 5 人
不能用少数检索结果推算全量
导入用户数据空间尚未构建
```

对 buyer_193 执行真实会话画像抽取后，详情显示：

```text
目标与需求：了解发货时间 / 了解库存 / 了解售后政策
阶段：信息咨询
待确认问题：库存情况未明确回复 / 售后政策具体以商品页为准
置信度：60%
订单：2 笔
客单价：¥198.00
```

![千客画像池](docs/design/b-profile-refreshed.png)

![问小千画像](docs/design/b-profile-ask.png)

![结构化会话画像](docs/design/b-profile-structured.png)

## 测试

```text
pytest：846 passed, 6 skipped
```

## 已知边界

- 订单和会话都是本地模拟数据，不接真实支付。
- 导入用户数据空间未构建，画像页只验证千客用户池。
- 店宠会话画像需要 30 分钟空闲后由扫描器抽取；本次验证用未来时间触发同一抽取函数。
