# B 端独立商家工作台（/v2/b.html）

> 独立静态入口，不经过 Vue SPA / `router.js` / `App.vue`；由 `web/src/b-workbench.js` + `web/src/b-workbench.css` 直接渲染。

## 入口与构建

```text
web/b.html            独立 HTML 入口（title：千客 · 商家工作台）
web/src/b-workbench.js 原生 JS 渲染：订单 / 售后 / 商品三视图
web/src/b-workbench.css 白色极简样式（中性色 + 低饱和强调色）
web/vite.config.js    build.rollupOptions.input = { main: index.html, b: b.html }
```

`npm run build` 产出 `dist/index.html`（原 SPA，保持不变）与 `dist/b.html`；后端仍把 `web/dist` 挂在 `/v2/`，因此访问 **`/v2/b.html`**。资源使用相对路径（`./assets/...`），不依赖 `/v2/` 的 URL 前缀。

## 接口

```text
GET   /api/b/workbench/me                          → 商家信息（merchant_name / merchant_id）
GET   /api/b/workbench/products                    → {products}
GET   /api/b/workbench/orders?status=&limit=100    → {orders}
PATCH /api/b/workbench/orders/{order_id}/status    {status: PAID|SHIPPED|COMPLETED|CANCELLED, tracking_no?, carrier?}
GET   /api/b/workbench/after-sales?status=&limit=100 → {tickets}
PATCH /api/b/workbench/after-sales/{ticket_id}     {approved}
POST  /api/b/workbench/after-sales/{ticket_id}/receive {accepted}
```

## UI 与状态

- 未登录（401）：显示「请先登录」+ **去登录（`/v2/`）** 链接，不白屏；403 / 服务异常显示错误页 + 重试 + 去登录入口。
- 顶部：商家名 + `merchant_id`；三视图 tab：订单 / 售后 / 商品。
- 订单：状态筛选（全部/待支付/已支付/已发货/已完成/已取消/已退款）、订单号、买家、商品、金额、物流；行内操作：
  - `CREATED` → 标记已支付 / 取消订单（行内二次确认）
  - `PAID` → 发货（物流单号必填、至少 4 位；承运商可选）/ 取消订单
  - `SHIPPED` → 完成订单
- 售后：状态筛选；列表字段工单/订单/类型/状态/退款金额/原因/时间，寄回时展示退回运单与入库时间；操作：
  - `OPEN`：仅退款 → 通过/拒绝；退货退款 → 同意退货/拒绝
  - `RETURN_SHIPPED` → 验收通过/拒收
  - `RETURN_PENDING` → 显示等待买家寄回
- 商品：只读列表（product_id / 标题 / 价格 / 库存 / 分类 / 更新时间）。
- 所有写操作：`detail.message`（兼容字符串与 `{code,message}`）以 toast + 行内提示展示；操作中禁用按钮，成功后刷新当前视图。
- 白色极简、移动端卡片式布局与单列表单，页面不横向溢出。
