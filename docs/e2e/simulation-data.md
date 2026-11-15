# 模拟商家 / C 端用户数据

日期：2026-11-15

## 规模

```text
新增商家租户：6（总计 9）
新增商家商品：18
新增商品 SKU：18
新增 C 端商品：18
新增 C 端消费者：30（总计 33）
新增 C 端订单：40
新增 App 会话消息：60
```

订单状态：

```text
PAID：15
SHIPPED：13
COMPLETED：12
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
13810000001 ~ 13810000030
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

完整昵称 / buyer_id 列表见运行后生成的：

```text
var/simulation_accounts.json
```

每个消费者 1–2 笔订单；昵称使用真实中文姓名，订单关联到 6 个模拟商家的商品和 SKU。

## 落库方式

脚本：

```text
scripts/seed_simulation.py
```

当前本地运行时 C 端使用 PostgreSQL，执行时显式指定同一套后端：

```powershell
$env:QIANKE_CONTROL_BACKEND = "postgres"
$env:QIANKE_CEND_BACKEND = "postgres"
$env:QIANKE_MERCHANT_BACKEND = "postgres"
$env:QIANKE_QUEUE_BACKEND = "postgres"
python scripts/seed_simulation.py --apply
```

脚本只做增量插入，重复执行跳过已存在账号、租户、商品、订单和消息。

```text
dry-run（不写库）：
python scripts/seed_simulation.py
```

## 验证

```text
浏览器 B 端：
  sim_biz_tea 登录成功
  m_sim_tea 工作台：4 笔订单，1 笔完成，2 笔待发货
  商品与 SKU：3 个商品
  订单：已支付 / 已发货 / 已完成

浏览器 C 端：
  13810000001 / Sim2026! 登录成功
  我的订单：商家单号、商品、报价、状态时间线正常
  1440 / 390 无横向溢出
```

截图：

![商家工作台](docs/design/sim-b-merchant-home.png)

![商家商品](docs/design/sim-b-merchant-products.png)

![商家订单](docs/design/sim-b-merchant-orders.png)

![C 端订单](docs/design/sim-c-user-orders.png)
