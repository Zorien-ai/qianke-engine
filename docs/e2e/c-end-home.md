# C 端首页 + B 端入口

日期：2026-11-14

## C 端首页

```text
路由：/v2/#/c/home
组件：web/src/views/CHome.vue
外壳：CShell
底部导航：首页 / 聊 / 逛 / 订单 / 消息
```

内容：

```text
今日想买点什么
和小鱼聊聊 / 去逛市集
快捷入口：市集、找小鱼、订单、消息
小鱼精选：真实 /api/c/products 商品，最多 8 个
模拟交易说明
```

真实数据：

```text
商品卡：8 个
无横向溢出
390 视口：390 / 390
5 个底部 Tab 均分，每个 76px
```

![C 端首页桌面](docs/design/c-end-home-desktop.png)

![C 端首页手机](docs/design/c-end-home-mobile.png)

## B 端入口

```text
B 端顶部：C 端首页 ↗
B 端工作首页日期区：C 端首页 ↗
目标：/v2/#/c/home，新标签打开
```

## 验证

```text
前端 build：PASS
1440 / 390 视觉检查通过
无后端变更；pytest 基线 798 passed / 6 skipped
```
