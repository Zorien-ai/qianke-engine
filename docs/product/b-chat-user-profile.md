# B 端会话用户画像

## 目标

从 **C 买家 ↔ 商家店宠/客服 AI** 的会话中抽取用户画像，30 分钟无新消息后生成一次；B 商家工作台的“小千”可以：

- 按 `buyer_id` 精确查询画像摘要 + JSON；
- 按自然语言条件在当前商家内做语义搜索。

管理端可以查看全部商家的画像，只读并支持删除/失效。

## 数据归属

```text
UNIQUE(merchant_id, buyer_id)
```

同一个人在不同商家下是不同画像，跨商家不可见。

表：

```text
b_chat_user_profile
  profile_id / merchant_id / buyer_id / version
  profile_json / profile_text / confidence
  source_message_count / source_session_ids
  last_message_at / extracted_at / status

b_chat_user_profile_vector
  profile_id / merchant_id / buyer_id / embedding vector(1024)
```

`b_chat_user_profile` 与现有 CSV 批量画像 `user_profile_vectors` **完全分离**，重建索引不会清空会话画像。

## 抽取流程

```text
c_message（store_demo 会话）
→ 扫描最后消息 >= 30 分钟前
→ 消息数 > 上次抽取的消息数
→ LLM 输出结构化 JSON
→ PII 过滤 / 字段校验
→ embedding
→ 按 merchant + buyer upsert
```

幂等：同一会话消息数未增加时不会重复抽取；重复扫描不会重复生成。

## 调度

单次：

```bash
python scripts/b_profile_extract.py
python scripts/b_profile_extract.py --owner buyer_112
```

常驻（推荐本地演示）：

```bash
python scripts/b_profile_worker.py --interval 60
```

生产可用 systemd / 容器常驻；日志 `logs/b_profile_worker.log`。

## B 端 AI

Tool Contract：

```text
get_chat_user_profile(buyer_id)
search_chat_user_profiles(query, limit)
```

- B 商家：强制当前 `merchant_id`；
- 系统管理员：必须显式传 `merchant_id`；
- 未绑定商家：结构化拒绝 `NO_MERCHANT`；
- 不返回原始聊天记录。

## 管理端

```text
GET    /api/c/admin/chat-profiles
DELETE /api/c/admin/chat-profiles/{merchant_id}/{buyer_id}
```

仅系统管理员；只读列表 + 删除/失效。

## 已知限制

- 当前店宠会话固定 `store_demo` / `m_gear_002`；多商家实时接入时需从会话绑定解析 merchant_id。
- 图片、语音消息不进入画像抽取。
- LLM 抽取失败时不写入，不阻塞后续任务。
- embedding 使用远程 BGE-M3；失败时画像正文仍保存，语义搜索退回文本匹配。
