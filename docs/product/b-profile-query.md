# B 端画像查询（千客用户 / 导入用户 / 全部用户）

> 状态：已实现（2026-11-14）。原用户画像查询并入商家工作台，商户登录后只保留 `/v2/b.html` 一个入口。

## 目标

商户在同一个工作台里查三类用户：

| 范围 | 数据来源 | 口径 |
|---|---|---|
| 千客用户 | `b_qianke_user_profile`（控制面） | 与本商户产生过**会话或交易**的 C 买家并集；按 buyer_id 去重 |
| 导入用户 | `mch_<merchant_id>` 数据集的 `user_profile_vectors` | 商户自己上传 CSV 构建出的画像 |
| 全部用户 | 上面两池 | 两池并列展示，不跨池去重；buyer_id 与 CSV user_id 没有共同主键 |

## 单入口

```text
商户登录 → /v2/b.html（唯一入口）
  └─ 画像查询
       ├─ 用户查询：千客用户 / 导入用户 / 全部用户 + 搜索 + 问小千
       └─ 数据接入：示例数据 / CSV 上传 / 字段确认 / 构建进度
```

企业管理员/系统管理员仍保留原 SPA 画像页；商家账号访问 `/v2/#/kb/profiles`、`/v2/#/chat` 会被路由守卫送回 `/v2/b.html`。

## 千客用户池

### 归属规则

- 订单：`c_order.merchant_id = 当前商户`；`merchant_id` 为空时，按订单明细商品 `c_product.merchant_id` 兜底归属。
- 会话：`b_chat_user_profile` 当前商户外，加上通过 `c_merchant_store_friend` 映射到该商户、发过消息的买家。
- 归属不到任何商户的订单（如 `m_demo` 商品）不进入任何商户池。
- 同一买家有多条订单/会话时按 `merchant_id + buyer_id` 合并。

### 订单统计口径

- 排除 `CANCELLED`；`order_count / order_amount / avg_order_amount` 按有效订单计算。
- `last_order_at` 取最大下单时间；`top_category` 取订单明细商品分类的众数。
- 最近消息（最多 3 条）作为确定性会话证据写入 `profile_text`；手机号/邮箱/证件号做脱敏。

### 表

```text
b_qianke_user_profile
  profile_key / merchant_id / buyer_id
  profile_json / profile_text
  order_count / order_amount / avg_order_amount
  last_order_at / top_category
  has_order / has_chat / chat_profile_json
  confidence / source_message_count / chat_extracted_at
  updated_at

b_qianke_user_profile_vector
  profile_key / merchant_id / buyer_id / embedding(1024) / updated_at
```

### 刷新

- 单商户：`POST /api/b/workbench/profile-pool/refresh`（owner/admin）。
- 常驻：`python scripts/b_qianke_pool_worker.py --interval 300`，日志 `logs/b_qianke_pool_worker.log`。
- 刷新是快照；订单/会话更新后需要等 worker 或手动刷新。

## 导入用户数据空间

- 数据集命名：`mch_<merchant_id>`，库名 `vec_db_mch_<merchant_id>`。
- 启动时从 `c_merchant_tenant` 恢复注册；第一次构建才真正建库。
- wizard 作用域：系统管理员 → `test`；企业管理员 → 企业库；其他商户成员 → 商户库；都没有则 403。
- 只有 owner/admin 能导入/构建；staff 只读。
- 上传批次归属：`upload_owner.merchant_id`，同商户 owner/admin 可构建，跨商户 403。
- 示例数据：`data/samples/merchant_users.csv`（30 行 / 10 位用户）+ `merchant_rules.md`，走与真实上传相同的落盘/字段识别/构建链路。

## 问小千

| 范围 | 链路 | 说明 |
|---|---|---|
| 导入用户 | `pipeline.answer_question(force_rag=True, use_cache=False)` | 原 RAG + Text2SQL + answer_guard + 人设 guard；问题不再被通用闲聊分类器拦下 |
| 千客用户 | 池语义/文本检索 → 一次 `generate` | 不跑 Text2SQL；回答带池摘要与覆盖说明 |
| 全部用户 | 导入侧 `pipeline.prepare` + 千客池检索 → 一次 `generate` | SQL 只覆盖导入用户，回答必须标注口径 |

- 姓名在卡片、来源、回答中脱敏。
- 原始 SQL 仅 owner/admin 可见；staff 只能看到回答、来源和行数。
- 池为空/未构建返回可读空态或 409，不回落平台 demo 数据。

## API

```text
GET  /api/b/workbench/profile-sources
GET  /api/b/workbench/profiles?source=qianke|imported|all&query=&page=&size=
POST /api/b/workbench/profile-query      {question, source}
POST /api/b/workbench/profile-pool/refresh
POST /api/b/workbench/profile-import/sample
GET/POST /api/wizard/upload、/build、/build/{task_id}（商家 owner/admin）
```

错误码：`PROFILE_SOURCE_INVALID`(400)、`PROFILE_DB_NOT_READY`(409)、`PROFILE_IMPORT_FORBIDDEN`(403)、`PROFILE_QUESTION_TOO_LONG`(400)。

## 权限

| 角色 | 查看/搜索/问小千 | 刷新千客池 | 导入/构建 |
|---|---|---|---|
| owner | ✅ | ✅ | ✅ |
| admin | ✅ | ✅ | ✅ |
| staff | ✅ | ❌ | ❌ |

## 边界与已知限制

- 不向商家开放平台 8110 条 demo 画像。
- 全部用户是两池并列，不是跨池合并排序。
- 千客/全部范围不做精确全量统计；SQL 仅用于导入用户。
- 千客池单次刷新最多 500 人/商户，超出截断并记录。
- 不做流式输出；回答一次性返回。
- 原 `/kb/profiles` 页面保留给企业/系统管理员，不删除。

## 验证

- `pytest tests/`：823 passed / 6 skipped（新增 18 例）。
- 评测集（`scripts/run_eval.py --dataset demo`，33 题）：29/33 = 87.9%，来源命中 97.8% / 96.7%，阈值 85% 通过；失败项 OPT-04、DA-03、SV-01、SY-01 未逐题复核是否与本次改动相关。
- 浏览器 E2E：真实 CSV 上传 + 构建、staff 只读、跨商户隔离、单入口重定向、移动端；详见 `docs/e2e/b-profile-query.md`。
- 截图：`docs/design/b-end-profile-query-desktop.png`、`b-end-profile-query-mobile.png`、`b-end-profile-query-import.png`、`b-end-profile-query-import-sample.png`、`b-end-profile-query-upload.png`、`b-end-profile-query-staff.png`、`b-end-profile-query-cross-merchant.png`。
