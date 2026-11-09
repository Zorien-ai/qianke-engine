# C 端伙伴长期记忆（P1）

> 日期：2026-11-09 · 状态：已实现 · 范围：C 端伙伴对话，不改订单与工具权限

## 目标

让「小鱼」记住用户明确说过的偏好和边界，同时保证：

```text
只记住用户明确陈述的内容
不把每句话都塞进记忆
用户能看见、能逐条删除、能清空
记忆不能覆盖价格/库存/订单事实
不保存手机号、邮箱、身份证、银行卡等 PII
```

## 数据模型

```sql
CREATE TABLE c_companion_memory (
    memory_id  TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL,
    kind       TEXT NOT NULL,          -- preference / boundary / fact / event
    content    TEXT NOT NULL,
    source     TEXT NOT NULL,          -- extracted
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (owner_id, kind, content)
);
```

SQLite 与 PostgreSQL 双后端 schema 已同步。

## 确定性抽取

不调用 LLM，规则命中才保存：

```text
我喜欢… / 我不喜欢…     -> preference
我穿…码 / 我的预算…元   -> preference
别给我推荐… / 不要推荐… -> boundary
我对…过敏               -> boundary
```

以下情况跳过：

```text
疑问句：吗 / ？ / ? / 什么 / 哪些 / 哪款
含手机号、邮箱、身份证、银行卡号
超过 300 字
```

## API

```text
GET    /api/c/companion/memories
DELETE /api/c/companion/memories/{memory_id}
DELETE /api/c/companion/memories
```

`POST /api/c/agent/run` 成功后自动抽取并保存；响应新增：

```json
{"memories_added": 3}
```

幂等重放不会重复写记忆。

## Prompt 注入

`build_system_prompt` 会把最近 8 条记忆放到：

```text
【你记得的事】
- preference：喜欢跑步
- preference：预算 500 元
- boundary：不要推荐跑鞋
```

并明确：

```text
只作为上下文参考
价格/库存/订单仍以工具结果为准
用户当前说法与记忆冲突时以当前说法为准
```

## UI

C 端右侧上下文面板新增「小鱼记得的事」：

```text
显示偏好/边界
逐条删除
清空
空状态提示：直接说“我喜欢…”或“别推荐…”，小鱼会记住
```

## 验证

```text
689 passed, 5 skipped
```

真实 API：

```text
第一次输入：我喜欢跑步，我的预算 500 元，别给我推荐跑鞋
memories_added=3
mode=companion
reply=跑步这事记下了，500 元的预算也记着，不碰跑鞋……

追问：你还记得我喜欢什么吗
memories_added=0
reply=记得。你喜欢跑步，提过预算 500 元，也说过不要推荐跑鞋……
记忆总数仍为 3
```

浏览器：

```text
C 端对话中显示「小鱼记得的事」
偏好：喜欢跑步
偏好：预算 500 元
边界：不要推荐跑鞋
每条有删除按钮，顶部有清空
```

## 已知限制

- 抽取是规则优先，不是语义模型；复杂表达可能漏记。
- 当前只支持删除/清空，不支持用户手动编辑；P1 暂不扩展。
- 记忆未做静态加密；敏感信息规则直接跳过，不写入。
- 跨端/跨租户不共享记忆。
- 数据保留策略：用户清空会话不会自动清记忆，需要显式删除/清空；后续可增加保留期限。
