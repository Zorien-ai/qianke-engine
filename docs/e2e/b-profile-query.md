# B 端画像查询 E2E

日期：2026-11-14  
范围：`/v2/b.html` → 画像查询（千客用户 / 导入用户 / 全部用户 / 数据接入）、单入口守卫、移动端  
工具：Playwright MCP（交互/截图）+ Chrome DevTools MCP（console/network）  
测试账号：本地 `test_b_merchant`（绑定 `m_gear_002`）。验收前重置了该本地测试账号的密码，本文不记录密码；正式环境请用真实登录。

## 1. 登录与单入口

```text
DevTools 页面执行 fetch('/auth/login') → 200
跳转 /v2/b.html → 200
访问 /v2/#/kb/profiles → 3s 后 URL 变为 /v2/b.html
```

DevTools network：

```text
GET /v2/b.html                          200
GET /api/b/workbench/me                 200
GET /api/b/workbench/orders?limit=100   200
GET /api/b/workbench/after-sales?...    200
GET /api/b/workbench/products           200
```

Console：无消息。

## 2. 画像查询首屏

```text
点击侧栏「画像查询」
GET /api/b/workbench/profile-sources                       200
GET /api/b/workbench/profiles?source=all&page=1&size=12    200
```

结果：千客用户 1 人（buyer_1，会话）；导入用户 10 人（qk_u001…qk_u010）。

截图：`docs/design/b-end-profile-query-desktop.png`

## 3. 数据范围与搜索

- 切「千客用户」：显示 buyer_1（会话）。
- 切「导入用户」：显示 10 位导入用户，卡片含订单/客单价/品类。
- 搜索「户外装备」：返回 qk_u010 / qk_u005 / qk_u001 等；标题显示「10 人 · 按相关度」。
- 清除搜索后恢复分页列表。

## 4. 问小千

来源：全部用户；问题：「最近想买户外装备的客户有哪些」。

```text
route=rag
cards=5
sources=8
回答：偏好户外装备且近期有购买记录的客户 3 位（qk_u001 / qk_u005 / qk_u010）
覆盖说明：千客用户池 1 人（0 有订单 / 1 有会话），本次检索 0 人；
         导入用户 10 人，本次检索 8 人；SQL 只覆盖导入用户
```

回答明确区分「历史购买」与「想买推断」，并说明当前数据无法算流失天数。

## 5. 数据接入

```text
切「数据接入」→ 导入用户 10 · 千客用户 1
点击「载入示例数据」→ merchant_users.csv（30 行）→ 字段自动映射
点击「开始构建」→ 构建完成：画像 10 个用户（30 行交易），索引 14 条，fresh
```

截图：`docs/design/b-end-profile-query-import.png`、`docs/design/b-end-profile-query-import-sample.png`

## 6. 移动端

390×844：

- 侧栏隐藏，底部导航显示；通过「更多 → 画像查询」进入。
- 文档宽度 375，无横向溢出。
- 搜索/问小千输入字号 16px，避免 iOS 自动缩放。

截图：`docs/design/b-end-profile-query-mobile.png`

## 7. 测试

```text
python -m pytest tests/ -q
823 passed, 6 skipped
```

新增用例：

```text
tests/test_b_user_pool.py            4 passed
tests/test_b_profile_query_api.py    8 passed
tests/test_mvp_merchant_scope.py     6 passed
```

评测集（`scripts/run_eval.py --dataset demo`，33 题）：

```text
29/33 = 87.9% | 来源命中 97.8% / 96.7% | 阈值 85% 通过
失败项：OPT-04、DA-03、SV-01、SY-01
```

失败项未逐题复核是否与本次改动相关；本次改动默认路径不变，B 端新增逻辑通过 `force_rag` 开关隔离。

## 8. 已知限制

- 千客用户池是快照；订单/会话更新后需要 worker 或手动刷新。
- 「全部用户」两池并列，不做跨池去重。
- 千客/全部范围不跑 Text2SQL；精确统计请切「导入用户」。
- 不做流式输出。

## 9. 补充验收（2026-11-14）

### 9.1 真实 CSV 上传

- `#b-profile-file` 选择 `data/samples/merchant_users.csv` → `POST /api/wizard/upload` 200。
- 向导显示 `merchant_users.csv / 30 行`，字段自动映射（`user_id` 选中）。
- 点击「开始构建」→ 构建完成：10 个画像、14 条索引、0.6s，数据状态 fresh。
- 截图：`docs/design/b-end-profile-query-upload.png`
- 修复：上传接口直接返回 state，示例接口返回 `{state}`；前端原先只读 `payload.state`，已兼容两种结构。

### 9.2 staff 只读

- 临时将 `test_b_merchant` 的商户角色改为 `staff`，重载 `/v2/b.html`。
- 结果：用户查询不显示「刷新千客池」；数据接入只显示「当前角色只读。」，无「载入示例数据 / 上传 CSV / 开始构建」。
- 验收后已恢复 `owner`。
- 截图：`docs/design/b-end-profile-query-staff.png`

### 9.3 跨商户隔离

- 使用 `m_tea_001` 的 owner 会话打开 `/v2/b.html`。
- `GET /api/b/workbench/profile-sources` 返回 `merchant_id=m_tea_001`；导入用户未构建、千客用户 0 人。
- 页面不出现 `m_gear_002` 的 `qk_u001` 或 `buyer_1`。
- 截图：`docs/design/b-end-profile-query-cross-merchant.png`
