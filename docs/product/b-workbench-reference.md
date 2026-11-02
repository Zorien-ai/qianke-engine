# B 端独立商家工作台（/v2/b.html）

> 独立静态入口，不经过 Vue SPA / `router.js` / `App.vue`；由 `web/src/b-workbench.js` + `web/src/b-workbench.css` 直接渲染。

## 入口与构建

```text
web/b.html            独立 HTML 入口（title：千客 · 商家工作台）
web/src/b-workbench.js 原生 JS 渲染：订单 / 售后 / 商品 / Super-agent 四视图
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
- 顶部：商家名 + `merchant_id`；四视图 tab：订单 / 售后 / 商品 / Super-agent。
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

## Super-agent（事件调查 + 人工审批）

第四个视图「Super-agent」用于把业务事件交给只读调查 Agent，并由人工复核结论；**不会自动改订单/退款**。

```text
POST /api/superagent/events                       {source:"manual", channel:"b-workbench", content, auto_run:false}
                                                  → {accepted, reason, work_item:{work_item_id,status,...}, thread}
GET  /api/superagent/work-items?limit=50          → {work_items}
GET  /api/superagent/work-items/{id}              → work item + triggers
POST /api/superagent/work-items/{id}/run
POST /api/superagent/work-items/{id}/stop         → {work_item_id,status:"CANCELLED",stopped:true}；状态不允许时 409
POST /api/superagent/work-items/{id}/approve      {approved, note, action_params}
                                                  approved=true 时入队 ACTION Job，返回 status=EXECUTING / execution_pending=true；
                                                  最终由 GET 单条变为 DONE / EXECUTION_FAILED；approval.execution_status: NONE | EXECUTED | FAILED
                                                  action_params: CREATE_AFTER_SALE 必填 {sale_type:"REFUND_ONLY"|"RETURN_REFUND"}（缺失 400）；
                                                  SHIP_ORDER 可传 {tracking_no, carrier}
POST /api/superagent/watchdog                     {timeout_seconds}
```

- 顶部固定说明「只读调查 + 人工审批，不会自动改订单/退款」；
- 输入业务事件（示例：`请查订单 order_xxx，买家反馈物流异常要售后`）→「提交给 Super-agent」，提交后展示 `work_item_id` 与状态；不受理展示 `reason`；
- 工作项列表展示状态、标题、创建/更新时间、审批状态；
  - `PENDING`：显示「运行调查」与「停止调查」；RUNNING 显示「停止调查」；stop 成功后状态变 `CANCELLED`/「已停止」，失败（如 409 状态不允许）toast + 行内 detail.message 并保持原状态；
  - `RUNNING` / `EXECUTING`：列表每 2s 轮询 `work-items`（有 RUNNING 或 EXECUTING 时），全部结束（无 RUNNING/EXECUTING）后自动停止；切换视图时停止；
  - `WAITING_APPROVAL`：展示结论摘要 + 审批按钮；若 `result.action`（或 `approval.action`）存在，先展示「建议动作」卡（中文动作名、订单号、原因/参数），明确标注「通过后会调用受控接口执行，不只是记录审批」；
    - 动作卡下方为「审批参数」：`CREATE_AFTER_SALE` 单选「仅退款 / 退货退款」，默认不选，未选中时「通过并执行」禁用；`SHIP_ORDER` 必填物流单号 + 可选承运商（动作已有值则预填，未填时禁用）；`CANCEL_ORDER` / `COMPLETE_ORDER` 无额外参数；
    - 有动作时按钮为「通过并执行」，无动作仍为「通过」；点击通过先展开二次确认（动作类型 + 订单号 + 最终参数；无动作时说明无可执行动作），**取消不发请求**；确认时 POST 携带 `action_params`；后端 400（如缺 sale_type）toast + 行内 detail，并保留已填/已选参数；
    - approve 成功后 toast「已通过，正在执行…」，工作项进入 `EXECUTING`/「执行中」：按钮显示「执行中…」并禁用，同时每 2s GET 单条直到 `DONE` / `EXECUTION_FAILED` / `REJECTED` / `CANCELLED` 等终态后停止；
    - 终态后按 `approval.execution_status/execution_result` 或 `result.execution` 展示执行结果：成功「已执行：动作（订单号 · 参数）」、无动作「未执行动作」、失败「执行失败：error」；状态为 `DONE` 或 `EXECUTION_FAILED`；
    - 驳回只记录审批结果、不执行动作，状态变 `REJECTED`；
  - `DONE`：展示结果摘要与执行结果；`REJECTED`：展示已驳回（未执行动作）；`FAILED` / `STUCK`：展示错误详情；`CANCELLED`：展示已手动停止；
  - 「查看详情」按需 GET 单条工作项，展示线程与触发事件；「扫描卡死」调用 watchdog（默认 180s）并提示标记数量；
- **结论安全渲染**：先 `escapeHtml` 整体转义，再按行还原换行与 `- / 1.` 简单列表；不使用原文 innerHTML，杜绝 Markdown/LLM 输出注入 HTML；
- 轮询刷新会保留事件输入框焦点与光标；错误统一 toast + 行内 `detail.message`；移动端不横向溢出。
