# B 端 2.0 P0：角色工作首页 + 订单表格/详情

日期：2026-11-13

## 本轮范围

```text
壳层：左侧分组导航、顶部商家/角色/模拟交易
角色工作首页：店主 / 客服 / 仓库三种视角
订单：桌面表格 + 详情抽屉；手机保留卡片
语义：模拟支付/模拟完成明确标注
```

未完成：

```text
真实 API 端到端验收（本地 PostgreSQL/Docker 停止）
商品/SKU 表格重构
批量发货/改库存/导出
多店切换后端契约
客服会话
```

## 实现

```text
web/src/b-workbench.js
  workspaceRole：owner/admin、仓库、客服视角
  loadOverview：并行读取订单、售后、商品、库存告警、工作项
  overviewView：角色首页
  orderTableRow / orderDrawerMarkup：订单表格与详情抽屉

web/src/b-workbench.css
  灰青 token、18px 正文、分组侧栏、角色首页、订单表格、抽屉
```

## 静态验证

本地 API 因 PostgreSQL/Docker 停止不可用，使用构建产物 + Playwright 路由 mock 验证布局和交互，不是生产接口验收。

```text
桌面 1440×1000
- 8 个导航入口，工作首页 active
- 店主首页：4 张指标卡、4 条优先处理
- 订单表格 4 行
- 点击详情打开 570px 抽屉，显示模拟交易说明
- document.scrollWidth = clientWidth = 1440

手机 390×844
- document.scrollWidth = clientWidth = 375
- 订单表格隐藏，卡片显示
- 首页 4 张指标卡纵向排列
```

## 截图

```text
docs/design/b-end-2.0-p0-prod-overview.png
docs/design/b-end-2.0-p0-prod-orders.png
docs/design/b-end-2.0-p0-prod-mobile.png
```

## 已知限制

```text
- 首页数字来自“当前加载范围”，不是全店汇总
- 经营报告、客服会话、批量能力仍为待接入/禁用态
- 订单表格的支付/完成动作尚未加入二次确认（P1）
- 本地没有 API 运行环境，尚未做真实接口浏览器验收
```
