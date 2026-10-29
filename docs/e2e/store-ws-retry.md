# 店宠 WebSocket 重试 E2E 与幂等 TTL 清理记录

- 日期：2026-10-30
- 范围：`src/rag_demo/c_end/idempotency.py` TTL 清理 + 店宠 IM WebSocket `client_message_id` 重试幂等
- 运行环境：Windows · Python 3.12.4（仓库 `.venv`）· pytest 9.1.1 · FastAPI 0.142.4 / Starlette 1.7.0
- 说明：本记录为**真实执行**结果，未做浏览器点击操作（由 Lead 最终验收，见文末“浏览器 UI 验收”）。

## 1. 覆盖内容

### 1.1 幂等 TTL 清理（`tests/test_c_end_idempotency.py`）

| 用例 | 验证点 |
| --- | --- |
| `test_default_ttl_is_seven_days_and_env_override` | 默认 TTL = 7 天；`QIANKE_C_IDEMPOTENCY_TTL_SECONDS` 可覆盖；非法/非正数回退默认；显式参数优先 |
| `test_prune_removes_expired_completed_and_stale_in_progress` | 过期 COMPLETED 与超时 IN_PROGRESS 被删；新鲜记录保留 replay / in_progress；过期后同 ID 可重新 claim |
| `test_prune_does_not_remove_fresh_replay` | 默认 TTL 下刚完成的记录不被删，replay 仍命中缓存 |
| `test_prune_uses_env_ttl` | 环境变量控制过期阈值（1 天保留、60 秒删除） |
| `test_auto_prune_runs_on_claim` | `claim()` 按节流间隔自动触发清理，且不破坏 claim 语义 |

### 1.2 HTTP 幂等包装（`tests/test_c_end_store_idempotency.py`）

| 用例 | 验证点 |
| --- | --- |
| `test_store_send_replays_without_second_agent_call` | 同一 `client_message_id` 第二次回放，`social.send_message` 只调用一次 |
| `test_expired_store_idempotency_re_executes_after_prune` | TTL 到期被 prune 后同 ID 允许重新执行；新记录仍能返回 IDEMPOTENCY_CONFLICT |

### 1.3 店宠 WebSocket 重试 E2E（`tests/test_c_end_ws_retry_e2e.py`）

用 `FastAPI TestClient` 的 WebSocket 通道直接驱动真实的 `/api/c/ws/chat/store_demo` 路由；
测试内用 monkeypatch 替换 `auth.resolve_session`（不改生产 auth）与
`c_end.social.send_message`（不触发真实 LLM，只统计调用次数），SQLite 使用临时库。

| 用例 | 验证点 |
| --- | --- |
| `test_ws_resend_same_client_message_id_only_calls_social_once` | 同 ID 重发 → 第二次响应 `idempotent_replay=true`，`social.send_message` 只调用 1 次，回放回复与首次一致 |
| `test_ws_same_client_message_id_different_content_conflicts` | 同 ID 不同内容 → `type=error` / `IDEMPOTENCY_CONFLICT`，只执行一次 |
| `test_ws_rejects_invalid_client_message_id` | 非法 `client_message_id` → `INVALID_CLIENT_MESSAGE_ID`，不触达店宠 Agent |
| `test_ws_without_client_message_id_keeps_legacy_behavior` | 不带 ID 保持旧行为：每条消息都执行 |
| `test_ws_rejects_unauthenticated_connection` | 无有效会话 Cookie → WebSocket 关闭（1008），不执行店宠 Agent |

## 2. 真实执行命令与结果

```bash
python -m pytest tests/test_c_end_idempotency.py tests/test_c_end_store_idempotency.py tests/test_c_end_ws_retry_e2e.py -v
```

实际输出（节选，完整 15 条全部 PASSED）：

```text
collected 15 items

tests/test_c_end_idempotency.py::test_claim_complete_replay PASSED
tests/test_c_end_idempotency.py::test_same_id_different_message_conflicts PASSED
tests/test_c_end_idempotency.py::test_release_allows_retry PASSED
tests/test_c_end_idempotency.py::test_default_ttl_is_seven_days_and_env_override PASSED
tests/test_c_end_idempotency.py::test_prune_removes_expired_completed_and_stale_in_progress PASSED
tests/test_c_end_idempotency.py::test_prune_does_not_remove_fresh_replay PASSED
tests/test_c_end_idempotency.py::test_prune_uses_env_ttl PASSED
tests/test_c_end_idempotency.py::test_auto_prune_runs_on_claim PASSED
tests/test_c_end_store_idempotency.py::test_store_send_replays_without_second_agent_call PASSED
tests/test_c_end_store_idempotency.py::test_expired_store_idempotency_re_executes_after_prune PASSED
tests/test_c_end_ws_retry_e2e.py::test_ws_resend_same_client_message_id_only_calls_social_once PASSED
tests/test_c_end_ws_retry_e2e.py::test_ws_same_client_message_id_different_content_conflicts PASSED
tests/test_c_end_ws_retry_e2e.py::test_ws_rejects_invalid_client_message_id PASSED
tests/test_c_end_ws_retry_e2e.py::test_ws_without_client_message_id_keeps_legacy_behavior PASSED
tests/test_c_end_ws_retry_e2e.py::test_ws_rejects_unauthenticated_connection PASSED

15 passed, 1 warning in 7.35s
```

唯一 warning 为仓库既有的 `torch/pynvml FutureWarning`，与本次改动无关。

## 3. TTL 实现口径

- 默认 TTL：`DEFAULT_TTL_SECONDS = 7 * 24 * 3600`（7 天）。
- 覆盖方式：环境变量 `QIANKE_C_IDEMPOTENCY_TTL_SECONDS=<秒>`；非法/非正数回退默认。
- `prune(max_age_seconds=None)`：
  - COMPLETED：按 `updated_at`（完成时刻）判断过期；
  - IN_PROGRESS：按 `created_at` 判断超时（进程崩溃遗留的执行权）；
  - 单条 DELETE 在 `_LOCK` 内执行，返回删除条数。
- 自动清理：`claim()` 前按 `_PRUNE_INTERVAL_SECONDS = 3600`（1 小时）节流触发 `prune()`；
  清理异常被吞掉，不影响 claim 主流程。
- 语义保证：只删过期行，未过期记录的 claim / replay / conflict 行为不变；
  TTL 到期后同一 `client_message_id` 允许重新执行（幂等缓存有界）。

## 4. 已知限制

- WebSocket E2E 使用 Starlette `TestClient` 的协议内通道，覆盖的是**服务端 WS 协议与幂等逻辑**；
  不模拟真实浏览器断线、重连退避、移动端网络切换等客户端行为。
- 测试用 monkeypatch 替换 auth 与店宠 Agent，不依赖真实账号库/LLM；生产代码未改动。
- 浏览器 UI 已由 Lead 用注入式 WebSocket 验证重试条与重发；未模拟真实移动端断网/重连退避，
  这部分仍需设备网络切换场景补测（见 §6）。

## 5. 浏览器 UI 验收建议（Lead）

1. 打开 C 端 App 店宠会话，确认 WebSocket 在线；
2. 断网/弱网重发同一条消息（客户端重试复用同一 `client_message_id`）→ 店宠只回复一次；
3. 观察第二次响应标记为回放（UI 不重复插入消息/不重复生成报价）；
4. 刷新页面后历史消息仍可正常分页加载。

## 6. Lead 浏览器 UI E2E（已执行）

环境：Playwright + Chromium，真实 C 端页面 `http://127.0.0.1:8000/v2/#/c/app`；为稳定复现客户端错误，
用 `addInitScript` 注入测试用 WebSocket（首次 send 返回 error，第二次 send 返回 chat），生产代码未加测试分支。

步骤：

1. 打开店宠会话，输入 `@店宠 测试 WS 重试` 发送；
2. 断言 `.c-retry-row` 显示“消息没有发出去，内容已保留。重试 / 忽略”；
3. 点击“重试”；
4. 断言消息列表出现“重试成功：店宠已收到。”。

结果：通过。截图：`docs/screenshots/store-ws-retry-e2e.png`。

说明：浏览器 E2E 验证的是前端重试条与同 ID 重发交互；服务端 WS 幂等语义由 §2 的 TestClient E2E 覆盖，
二者组合完成“协议 + UI”验收。真实断网/重连退避仍需在设备网络切换场景补测。
