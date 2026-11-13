# C 端问题 Router + 稳定会话

日期：2026-11-13

## 背景

之前 C 端小鱼有四个问题：

```text
1. detect_mode 只是关键词判断，不是真正路由
2. 同一个 thread 创建后 mode 被锁死
3. 刷新页面 liveThreadId 丢失，待确认草稿无法恢复
4. 用户要“像同一个 Agent”，但跨会话只有历史消息，没有稳定会话
```

## 第一版 Router

新增 `src/rag_demo/c_end/router.py`，只做路由，不生成答案。

```text
companion    陪伴 / 情绪 / 闲聊
shopping     商品 / 图片 / 预算 / 对比
order        订单 / 物流 / 售后查询
transaction  下单 / 确认 / 取消 / 改单
```

规则优先级：

```text
显式模式 > 交易动作 > 订单查询 > 偏好陈述 > 购物意图 > 陪伴
```

输出结构化槽位：

```json
{
  "route": "shopping",
  "mode": "advisor",
  "confidence": 0.86,
  "slots": {"query": "推荐一款绿茶", "budget": 500}
}
```

第一版是确定性 Router，保证低延迟和可测试；LLM 兜底尚未接入，低置信度暂时回到陪伴模式。

## 同会话模式切换

`run_c_agent` 不再把 thread 的 mode 锁死：

```text
existing_mode != 新 Router 的 mode
→ 重建工具图
→ 注入“模式切换”SystemMessage
→ 保留历史消息
→ 继续同一个 thread
```

工具集按模式隔离：

```text
companion    []
advisor      recommend_products
order        query_my_orders / query_tracking
transaction  全部交易工具
```

实测：

```text
第一轮：陪我聊聊，今天有点累
→ mode=companion, route=companion

第二轮：推荐一款绿茶
→ mode=advisor, route=shopping
→ 推荐明前龙井 / 洞庭碧螺春
→ 返回 3 张商品图片卡
```

## 稳定会话 ID

服务端按 `buyer_id` 生成：

```text
c_conv_{sha256(buyer_id)[:24]}
```

接口：

```text
GET /api/c/agent/session
→ thread_id / mode / interrupted / draft / status
```

CApp 启动时先取稳定会话，再加载历史消息；刷新、换设备后仍是同一个 thread。

如果该 thread 有待确认草稿：

```text
session.draft 恢复为 liveDraft
→ 页面展示待确认面板
→ 不会自动确认订单
```

## 验证

```text
Router 单测：16 passed
C Agent 模式切换 / 会话恢复：11 passed
全量 pytest：787 passed, 5 skipped
前端购物车：12 passed
前端语义搜索：4 passed
前端 build：PASS
浏览器：session ID 稳定、companion → advisor 同 thread 切换、商品图片卡正常
PWA：v23
```

## 限制

- Router 目前是规则路由；LLM 兜底和 40 条路由 Eval 留在下一阶段。
- 稳定会话 ID 由 buyer_id 派生，不含新表；如果未来需要多 Agent 实例、多设备并发写，需要独立会话表和写锁。
- 长期记忆、人格、偏好已经跨会话共享；任务状态的完整恢复仍以 checkpoint + app message 为准。
- 当前只有 CApp 小鱼使用稳定会话；店宠/群聊沿用各自 thread。
