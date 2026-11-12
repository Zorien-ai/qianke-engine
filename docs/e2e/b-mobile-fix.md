# B 端手机端适配修复

日期：2026-11-12

## 问题

在 360 / 390px 手机宽度复现：

```text
1. 顶部 7 个视图 tab 横向被裁切，只露出前 5 个
2. 切换 tab 后导航不会自动滚到当前项
3. 顶部“返回入口”在窄屏只是小号文字，触控目标偏小
4. 商品页“只看低库存”按钮被压成两行
5. 执行审计宽表格没有明显的横向滑动提示
```

截图（修复前）：

![B 端修复前](b-mobile-before.png)

## 修复

### 手机端短标签

```text
用户画像 → 画像
Super-agent → Super
动作策略 → 策略
执行审计 → 审计
```

桌面端仍显示完整标签。

### 导航

- 手机端 nav sticky。
- 当前 tab 渲染后自动滚到可视区域。
- 增加横向滚动惯性、scroll-snap。
- 短标签在 360px 宽度下 7 个 tab 全部可见。

### 顶部

- “返回入口”改为边框 pill，触控目标更大。
- 商家名/商家 ID 字号在手机端收紧。

### 商品库存提醒

- 文案和“只看低库存”按钮允许换行。
- 按钮不换行，不再被压成两行。

### 执行审计

- 宽表格增加横向滚动惯性。
- 表格底部增加“左右滑动查看”提示。
- 工具栏允许换行。

## 修复后

360px 订单页：

![B 端 360 订单](b-mobile-after-360.png)

360px 商品页：

![B 端商品页](b-mobile-products-after.png)

360px 执行审计：

![B 端执行审计](b-mobile-audit-after.png)

桌面回归：

![B 端桌面](b-desktop-after.png)

## 验证

```text
viewport 360x780:
  document scrollWidth = clientWidth = 345
  nav 标签: 订单 / 售后 / 商品 / 画像 / Super / 策略 / 审计
  7 个 tab 全部可见

viewport 390x844:
  document 无横向溢出
  商品库存提醒按钮单行
  执行审计表格可横向滚动

viewport 1280x900:
  desktop 标签仍为完整文案
  document scrollWidth = clientWidth = 1265
```

代码：

```text
web/src/b-workbench.css
web/src/b-workbench.js
```

只改前端 B 工作台，后端接口未改。

## 已知限制

1. 当前只验证了 360 / 390 / 1280 三个宽度，未覆盖所有安卓 WebView。
2. 审计宽表格仍需要横向滑动，只是增加了提示和惯性。
3. B 端页面没有底部 Tab，仍采用顶部滚动导航；后续可评估改成底部 5 项主 Tab。


## 字号调整（2026-11-12）

B 端字号整体上调两次，最终：

```text
正文：13px → 17px（手机 18px）
辅助文字：10/11px → 13/14px
表格/表单：12px → 15/16px
标题：15–18px → 20–22px
按钮触控高度：34px → 38px（手机）
```

手机导航按钮左右 padding 收紧到 4px、字号 15px，保证 360px 宽度下 7 个短标签仍全部可见；`b-meta` 标签列宽度从 54px 加到 68px，避免“安全库存 / 更新时间”折行。

验证：

```text
360px: body font-size = 18px
360px: nav 7 个标签全部可见，scrollWidth = clientWidth = 345
1280px: body font-size = 17px，无横向溢出
```

截图：

![B 端手机订单字号](b-mobile-font2-orders.png)

![B 端手机商品字号](b-mobile-font2-products.png)

![B 端手机审计字号](b-mobile-font2-audit.png)

![B 端桌面字号](b-desktop-font2-after.png)
