# C 端聊天不泄漏商品卡

日期：2026-11-14

## 问题

```text
用户只发“你能陪我聊聊天吗”
回复接住了情绪，但下面仍带上一轮商品的卡片
```

## 原因

```text
run_c_agent 的 product_refs 从整个 checkpoint 消息历史提取
上一轮 recommend_products 的 ToolMessage 还在 state 里
companion 轮次也会把它重新提取出来
```

## 修复

```text
只从本轮新增消息提取 product_refs
previous_message_count = invoke 前的 state.messages 数量
new_messages = state.messages[previous_message_count:]
```

## 验证

```text
先 advisor 推荐跑鞋 → product_refs 有值
同一 thread 再说“你能陪我聊聊天吗”
mode = companion
product_refs = []
CApp 最新气泡商品卡数量 = 0
```

测试：

```text
tests/test_c_end_agent.py::test_companion_turn_does_not_reuse_previous_product_cards
C agent 测试：12 passed
```

截图：docs/design/c-app-companion-no-products.png
