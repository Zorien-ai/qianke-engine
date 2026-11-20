# 身份消歧与客户寻址 · Phase 3B

> 状态：Phase 3B 已落地  
> 目标：把「一个称呼 / 手机号 / 买家 ID」安全地解析为当前商家下的唯一 `buyer_id`；解析失败或冲突时先补问，不读取/写入记忆。

## 1. 为什么需要

用户说「老王」「林小满」「13810000001」或「buyer_193」时，系统不能直接拿这个字符串去查画像/记忆：

- 可能是重名；
- 可能是别的商家的客户；
- 可能是过期或错误的历史别名；
- 直接用错身份，比查不到更危险。

所以身份消歧必须先于：

```text
记忆读取
画像查询
画像/记忆写入
交易与订单动作
```

## 2. 唯一主键

```text
tenant_id   = b_merchant:<merchant_id>
customer_id = buyer_id
```

- `buyer_id` 是系统内唯一客户标识，不接受客户端自报覆盖。
- 商户只能解析自己 `merchant_id` 下的客户。
- 不跨商户、不跨租户、不把平台级画像返回给商户。

## 3. 别名来源（Phase 3B）

当前可用的精确别名来源：

| 来源 | 字段 | 说明 |
|---|---|---|
| 主键 | `buyer_id` | `buyer_<account_id>` |
| C 端账号 | `display_name` | 消费者昵称 |
| C 端账号 | `username` | 登录名 |
| C 端账号 | `contact` | 手机号 / 邮箱，仅用于精确匹配，不原样返回 |
| 商家客户池 | `b_chat_user_profile` / `b_qianke_user_profile` | 只决定“这个 buyer_id 属于当前商户” |
| 订单 | `buyer_id` | 后续可接入收货人，Phase 3B 不启用 |

Phase 3B **不做模糊匹配**：

```text
只匹配：归一化后的完全相等
不匹配：拼音、包含、编辑距离、LLM 猜测
```

## 4. 解析结果

```json
{
  "status": "RESOLVED | AMBIGUOUS | NOT_FOUND | FORBIDDEN",
  "tenant_id": "b_merchant:m_sim_tea",
  "customer_id": "buyer_193",
  "confidence": 1.0,
  "evidence": ["buyer_id", "display_name"],
  "candidates": [],
  "needs_clarification": false,
  "next_action": "USE | ASK | REJECT"
}
```

规则：

| 情况 | status | 行为 |
|---|---|---|
| 恰好一个匹配 | `RESOLVED` | 继续读取/写入 |
| 多个匹配 | `AMBIGUOUS` | 返回脱敏候选，先补问 |
| 无匹配 | `NOT_FOUND` | 先补问或走冷启动 |
| 跨商户 / 无权限 | `FORBIDDEN` | 拒绝并审计 |

多命中时**不自动选择置信度最高者**；Phase 3B 的精确匹配都是 `1.0`，没有可靠的排序依据。

## 5. 输出脱敏

- 可以返回：`buyer_id`、`display_name`、匹配字段名。
- 不返回：完整手机号、邮箱、收货地址、原始聊天内容。
- 手机号只显示 `138****0001` 这类掩码，用于人工确认。
- 任何消费方不得把候选列表当作已确认客户。

## 6. 入口

### B 端 HTTP

```text
POST /api/b/workbench/identity/resolve
{ "query": "林小满" }
```

权限：`view_profiles`；商户来自登录账号绑定，不接受请求体指定。

### Agent Tool

```text
resolve_customer_identity(query)
```

Tool Contract：

- 输入：`query`（必填），管理员可选 `merchant_id`；
- 输出：上述解析结果；
- 无写操作、无读聊天原文、无跨商户；
- Agent 必须先拿到 `RESOLVED` 才能调用画像/记忆工具。

## 7. 与记忆链路的关系

```text
resolve_customer_identity
  ├─ AMBIGUOUS / NOT_FOUND → 补问，不读取记忆
  └─ RESOLVED
       → memory_context.resolve_authenticated_identity
       → 多源读取
       → 上下文组装
       → Agent
```

记忆写入也必须复用同一个 `customer_id`；不允许写入端重新解析出另一个客户。

## 8. 验收用例

```text
identity_exact_buyer_id
identity_exact_display_name
identity_alias_collision
identity_not_found
identity_cross_merchant
identity_phone_not_returned_raw
identity_agent_tool_contract
identity_ambiguous_does_not_read_memory
```

## 9. 非目标

```text
- 拼音/模糊/LLM 语义猜身份
- 跨商户全局客户搜索
- 返回原始手机号/邮箱/地址
- 自动合并两个 buyer_id
- 用订单收货人做跨账号合并（后续单独设计）
```


## 10. 实现状态（2026-11-20）

| 能力 | 状态 | 位置 |
|---|---|---|
| 精确 buyer_id / display_name / username / contact 匹配 | ✅ | `src/rag_demo/b_end/identity.py` |
| 多命中 AMBIGUOUS | ✅ | 同文件 |
| 当前商户边界 | ✅ | 候选只取 `list_chat_user_profiles` / `list_qianke_user_profiles` |
| 联系信息脱敏 | ✅ | `masked_contact` |
| B 端 HTTP 入口 | ✅ | `POST /api/b/workbench/identity/resolve` |
| Agent Tool + Tool Contract | ✅ | `resolve_customer_identity` |
| 单测 | ✅ | `tests/test_b_identity.py` |

验证：

```text
pytest tests/test_b_identity.py tests/test_agent_architecture.py        tests/test_agent_execution_safety.py tests/test_b_chat_profile.py -q
46 passed
```

Phase 3B 不做模糊/拼音/LLM 猜身份；下一阶段再接订单收货人别名与冲突版本。
