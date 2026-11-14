# B / 企业端定向复验报告

日期：2026-11-14  
代码基线：`b-end-2.0-p0` / `5348656`  
测试账号：test_b_image（企业管理员 / 山雾茶业）

## 结论

```text
Codex #1 渐变：通过（当前页面 CSS 渐变 = 0）
Codex #3 浮动侧栏：通过（B 端 + 企业端均 72 → 240 / 16px 外距 / 20px 圆角）
Codex #4 窄屏溢出：通过（320 / 390 的 Agent、账单、离线评测均无整页横溢）
B 端售后接口 N+1：已修（p50 726ms → 56.5ms）
```

## 1. 售后接口 N+1

改前：

```text
全量 29 条售后
→ 每条 get_order()
→ 每条再查商家订单
API p50 726ms / p95 870ms / 并发 5 p95 2,139ms
```

改法：

```text
c_end.store.list_after_sales(..., merchant_id=...)
  c_after_sale JOIN c_order ON order_id
  在 DB 层按 merchant_id 过滤

b_workbench.workbench_after_sales()
  直接使用 merchant_id 过滤结果，不再逐条查单/查商家仓库
```

改后实测（本地，B 账号）：

| 指标 | 改前 | 改后 |
|---|---:|---:|
| 顺序 p50 | 726ms | **56.5ms** |
| 顺序 p95 | 870ms | **71.5ms** |
| 并发 5 p95 | 2,139ms | **83.5ms** |
| 返回 tickets | 0（当前商家） | 0（当前商家） |

测试：

```text
tests/test_b_workbench_api.py::test_after_sales_only_for_bound_merchant PASS
断言返回工单订单的 merchant_id 均等于当前商家
```

## 2. B / 企业侧栏

桌面 1440 实测：

```text
企业端：
  x=16, y=16, width=72, height=968, radius=20px
  hover width=240

B 工作台：
  x=16, y=84, width=72, height=900, radius=20px
  hover width=240
```

满足：16px 外距、20px 圆角、72→240、文字延迟 80ms、32px 组距、固定用户区。

## 3. 窄屏溢出

修复前：

```text
390px 账单：scrollWidth 412 / clientWidth 380
320px 账单：scrollWidth 316 / clientWidth 310
```

根因：`.billing-grid > .card` 受表格 min-content 撑开，`.wallet-main` 的 280px min-width 在 320px 下超宽。

修复：

```text
.billing-grid > .card { min-width: 0 }
.billing-grid .table-wrap { max-width: 100%; overflow-x: auto }
@media (max-width:420px) { .wallet-main { min-width: 0 } }
```

修复后实测：

| 页面 | 390 | 320 |
|---|---|---|
| Agent 智能助理 | 390/390 | 310/310 |
| Token 账单 | 380/380 | 310/310 |
| 离线评测 | 390/390 | 320/320 |

顶部操作（菜单 / 主题 / 中文 / 退出）均落在视口内。

截图：

![账单 390](docs/design/b-ui-fixed-billing-390.png)

![账单 320](docs/design/b-ui-fixed-billing-320.png)

![Agent 390](docs/design/b-ui-fixed-agent-390.png)

![离线评测 390](docs/design/b-ui-fixed-eval-390.png)

## 4. 构建、测试与控制台

```text
web build：PASS（约 5.5s）
pytest：823 passed, 6 skipped
Chrome DevTools：账单页 console error/warn = 0
Playwright：上述页面 document.scrollWidth == clientWidth
```

## 仍待处理

```text
1. 离线评测页当前租户数据为空，JSON 示例无法实测；页面宽度已通过。
2. #5 原生中文输入法候选窗仍需真实设备补证；合成事件已通过。
3. 商家商品接口 5 并发 p95 约 870ms，属于 P1 观察项，不阻断。
```
