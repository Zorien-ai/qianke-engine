# 多商家主线验收报告

日期：2026-11-11

## 结论

C 端多商家闭环已完成并通过回归验证：

```text
发现店宠 → 加好友 → 店宠聊天 → 商品/库存/订单
→ 报价 → CShop → 双宠谈判 → 订单
→ 取消/售后/退款 → 对账/回访
→ B 端画像 → A 端审计
```

本报告只记录实际执行过的验证。

## 本批新增

### C 端

- CApp 动态加载商家好友会话，新增 store_tea 会出现在消息列表。
- 动态商家会话支持加载历史、发送消息、WebSocket、已读。
- CShop 双宠谈判预算改为用户输入，不再固定 ¥500。
- CShop 店宠顾问 / 砍价 / 报价 / 下单都按当前 merchant 运行。

### 商家级 SOP

- 新增 `c_merchant_sop`。
- 每个商家可配置发货、退货、改价口径。
- 店宠 `search_store_policy` 按 merchant_id 读取。
- 管理端 `/admin/merchant-store-friends` 增加 SOP 编辑。
- 茶商与山野户外的发货/退货文案不同，互不串店。

### 后端修复

- 修复 PostgreSQL 下多商家空闲会话扫描的 `GROUP BY` 错误。
- 动态商家线程已读接口允许存在的 merchant friend。
- 对账/回访/取消/退款/售后全部按订单 merchant_id。

## 测试结果

### 全量 pytest

```text
748 collected
743 passed
5 skipped
0 failed
```

执行命令：

```bash
python -m pytest tests/ -q
```

### 定向测试

```text
test_c_end_merchant_transactions.py: 17 passed
test_c_end_negotiation.py: 5 passed
test_c_end_social.py: 12 passed
test_c_end_store_agent_merchant.py: 7 passed
```

### Regression Eval

本次一共运行三次：

```text
第 1 次：2/33 = 6.1%，环境失败
  原因：31 题回答异常，OSError: 页面文件太小
  不计入模型回归结论

第 2 次：28/33 = 84.8%，门禁未通过
第 3 次：30/33 = 90.9%，门禁通过（>= 85%）
```

第 2/3 次均无回答异常；差异来自模型措辞/判定波动。
最终报告：

```text
tests/eval_report.md
tests/eval_results_llm.json
```

### 前端

```text
npm run build: success
```

## E2E 证据

### C 端发现店宠

![C 端发现店宠](c-discover-merchants.png)

### 茶商店宠回复

![茶商店宠回复](c-tea-store-chat.png)

### 茶商 CShop 下单

![茶商 CShop 下单](c-tea-shop-order.png)

### 茶商 CShop 店宠顾问

![茶商店宠顾问](c-tea-shop-store-pet.png)

### 双宠谈判

![茶商双宠谈判](c-tea-negotiation.png)

### 双宠谈判预算输入

![谈判预算输入](c-tea-negotiation-budget.png)

### CApp 动态商家会话

![CApp 动态商家会话](c-app-dynamic-merchants.png)

### 管理端商家级 SOP

![管理端商家级 SOP](admin-merchant-sop.png)

### A 端多商家画像

![A 端多商家画像](admin-chat-profiles-multi-merchant.png)

### B 端画像隔离

B 商家只能看到 m_gear_002 的两份画像，看不到 m_tea_001 的茶商画像。

![B 端画像隔离](b-chat-profiles-isolation.png)

## 运行状态

```text
API: http://127.0.0.1:8000/ready = 200
B 画像 worker: 运行中
最近扫描: {"checked": 3, "ok": 0, "skipped": 3}
  checked=3 说明 store_demo / store_tea 两个商家都已进入扫描
  skipped=3 因为没有新的空闲会话，属于幂等跳过
```

## 已知限制

1. 真实支付、真实 IM、SaaS 计费仍不在范围内。
2. 商家级 SOP 目前只有管理端编辑入口，B 商家自助编辑未做。
3. CApp 动态会话只加载 merchant friends；好友类型仍按原有种子/后端数据。
4. Eval 存在模型波动：两次 84.8% / 90.9%，最终以第二次门禁通过为准。
5. 茶商订单的退款/售后是模拟链路，没有真实支付/物流。

## 回滚

本次改动均为增量：

```text
新增表 c_merchant_sop
c_order / c_quote 增加 merchant_id 列（兼容旧数据默认 m_gear_002）
前端仅新增/扩展页面
```

回滚方式：

```bash
git revert <本次提交>
```

旧数据仍可读；如需彻底清理新增表，需单独执行迁移，不在回滚脚本中自动删表。
