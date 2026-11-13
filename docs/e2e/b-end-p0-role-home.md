# B 端 2.0 P0：角色工作首页 + 订单表格/详情

日期：2026-11-13

## 本轮范围

```text
壳层：左侧分组导航、顶部商家/角色/模拟交易
工作首页：当前已交付店主视角；客服/仓库结构保留，但真实服务端角色映射未实现
订单：桌面表格 + 详情抽屉；手机保留卡片
语义：模拟支付/模拟完成明确标注
```

本轮补充：

```text
商品/SKU 桌面表格 + 手机卡片
订单操作移入详情抽屉
模拟支付/模拟完成二次确认
订单多选、批量预览禁用态、选中 CSV 导出
多店切换禁用态
``` 

未完成：

```text
批量发货/改库存接口
多店切换后端契约
客服会话
支付/完成的服务端审计与模拟标记
```

## 实现

```text
web/src/b-workbench.js
  workspaceRole：owner/admin 店主视角；仓库/客服分支保留，待服务端角色映射
  loadOverview：并行读取订单、售后、商品、库存告警、工作项
  overviewView：角色首页
  orderTableRow / orderDrawerMarkup：订单表格与详情抽屉

web/src/b-workbench.css
  灰青 token、18px 正文、分组侧栏、角色首页、订单表格、抽屉
```

## 真实接口验收

PostgreSQL/Docker 恢复后，使用 B 端账号 `test_b_image` 完成真实接口浏览器验收：

```text
GET /api/b/workbench/me                 200
GET /api/b/workbench/orders?limit=100   200
GET /api/b/workbench/after-sales?limit=100 200
GET /api/b/workbench/products           200
GET /api/b/workbench/inventory/alerts?limit=100 200
GET /api/superagent/work-items?limit=50 200
console errors / warnings               0
```

真实数据：

```text
订单 11 笔
商品 8 个
工作首页：当前加载完成流水（当前加载范围、非全店汇总）、1 笔待发货
订单表格：11 行；详情抽屉显示 order_1579fdd829d7443a
商品表格：8 行；价格范围、可售、锁定、低库存列正常
商品搜索“龙井”：1 个商品；SKU 视图：2 行（250g / 50g）
手机 390 视口：document.scrollWidth = clientWidth = 375
```

之前静态 mock 验证仍然保留，作为无后端时的布局回归。2026-11-14 代码审查后补充：日期按 Asia/Shanghai 营业日转 UTC 左闭右开；订单搜索转义 `%`/`_`；API limit 上限 100；全选可取消；CSV 增加公式注入防护；模拟动作文案改为“写入当前商家订单状态/时间”，不再声称不写库；状态筛选重置 offset/选择；去掉“今日”假口径和前端角色预览，仓库/客服角色等待服务端映射。

```text
桌面 1440×1000
- 8 个导航入口，工作首页 active
- 店主首页：4 张指标卡、4 条优先处理
- 订单表格 4 行
- 点击详情打开 570px 抽屉，显示模拟交易说明
- 抽屉内“模拟支付（演示）”先出现影响确认，再提交状态
- 商品视图：2 行商品表格，价格范围/可售/锁定/低库存
- document.scrollWidth = clientWidth = 1440

手机 390×844
- document.scrollWidth = clientWidth = 375
- 订单表格隐藏，卡片显示
- 商品表格隐藏，商品卡片显示
- 首页 4 张指标卡纵向排列
```

## 截图

```text
docs/design/b-end-2.0-p0-prod-overview.png
docs/design/b-end-2.0-p0-prod-orders.png
docs/design/b-end-2.0-p0-prod-products.png
docs/design/b-end-2.0-p0-prod-order-drawer.png
docs/design/b-end-2.0-p0-prod-batch.png
docs/design/b-end-2.0-p0-prod-search.png
docs/design/b-end-2.0-p0-prod-pagesize.png
docs/design/b-end-2.0-p0-prod-sku-search.png
docs/design/b-end-2.0-p0-prod-mobile-nav.png
docs/design/b-end-2.0-p0-prod-mobile.png
```

## 已知限制

```text
- 首页数字来自“当前加载范围”，不是全店汇总
- 经营报告、客服会话、批量能力仍为待接入/禁用态
- 订单操作已移入详情抽屉并加入模拟支付/完成确认；真实支付/完成仍待后端契约
- 批量发货/改库存接口尚未接入；当前只支持选中导出的前端 CSV 样例
- 真实接口已验收；测试订单 order_1579fdd829d7443a 仍在数据中，待清理
- 页大小支持 10/20/50/100，已真实接口验证
- 商品搜索当前为前端当前加载范围过滤；大目录需接服务端查询
```
