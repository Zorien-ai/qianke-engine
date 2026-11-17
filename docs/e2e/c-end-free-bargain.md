# C 端自由砍价 E2E

日期：2026-11-17  
范围：CShop 商品详情 / CApp 对话 / B 端砍价审批 / 报价转订单

## 1. CShop 商品详情

```text
山岚茶事 → 明前龙井 → 详情 → 让小鱼去砍价
→ 输入「180 能卖吗」
→ 店宠：¥180 可以做，但需要店长确认
→ 提交商家确认
→ WAITING_APPROVAL
```

![砍价面板](docs/design/bargain-chat-open.png)

![等待商家确认](docs/design/bargain-waiting-approval.png)

## 2. 自动额度内成交

```text
明前龙井 ¥198 → 输入「190 可以吗」
→ 店宠直接给 ¥190 报价
→ 接受这个报价
→ CShop 报价卡：商品小计 ¥198 / 优惠 ¥8 / 报价 ¥190
```

![自动成交](docs/design/bargain-auto-accepted.png)

## 3. B 端审批

```text
B 工作台 → 经营协作 → 砍价审批
→ buyer_193 / 明前龙井 / ¥180 / 商家让利 ¥18
→ 同意 ¥180
→ C 端报价生成
```

![B 端待审批](docs/design/b-bargain-approvals.png)

![B 端已同意](docs/design/b-bargain-approved.png)

## 4. CApp 对话入口

在 CApp 说「帮我砍个价」，有最近商品上下文时打开同一个自由砍价面板。

![CApp 砍价](docs/design/capp-free-bargain.png)

## 5. 报价转订单

API 实测：

```text
190 元自动成交
→ quote_bargain_... 
→ prepare 200：DRAFT / total 190 / discount 8
→ confirm 200：CONFIRMED / total 190
```

180 元审批链路：

```text
create target 180 → approval_required true
accept → WAITING_APPROVAL
B approve → ACCEPTED / quote
prepare → DRAFT total 180 / discount 18
```

## 6. 自动化

```text
pytest：860 passed, 6 skipped
web build：PASS
```

新增覆盖：

```text
tests/test_free_bargain.py
  - 自动额度报价
  - 商家审批后才生成报价
  - 商家拒绝
  - 低于底价还价
  - 商家让利进入订单折扣
  - 跨买家访问拒绝
```

## 7. 已知边界

- P0 的 B 店宠回复是确定性模板，不是自由生成文本；C 用户仍可自由输入还价/接受/拒绝。
- 平台满减规则固定，商家让利单独计入报价；85% 硬底价与 10% 最大让利同时生效，实际更严格的是 90%。
- 审批后的 C 端需要点「刷新状态」，下一版可加轮询/通知。
- CApp 只有在有最近商品上下文时直接打开砍价面板；没有商品上下文时回退到选择商品的旧确认层。
