# Super-agent MVP E2E

> 日期：2026-11-02 · 状态：通过（真实 Deep Agents Worker + DeepSeek）

## 1. 架构

```text
事件入口
  → Router（确定性 Fast Path 过滤）
  → Thread / WorkItem（SQLite 控制面）
  → Deep Agents Worker（只读调查）
  → 结论 + 人工审批
  → Watchdog（RUNNING 超时标记）
```

写操作不在 Super-agent 内执行；订单/退款/退货仍走现有受控 API + 人工确认。

## 2. 模块

```text
src/rag_demo/superagent/
├─ store.py     Thread / Trigger / WorkItem / Approval / Watchdog
├─ router.py    Fast Path 事件过滤与 Thread 归并
└─ worker.py    Deep Agents + 只读子代理
src/rag_demo/api/superagent.py
```

Worker 子代理：

```text
order_analyst  查询订单 / 售后 / 商品库存
policy_advisor 查询售后 / 发货 / 平台政策
```

## 3. API

```text
POST /api/superagent/events
GET  /api/superagent/threads
GET  /api/superagent/work-items
GET  /api/superagent/work-items/{id}
POST /api/superagent/work-items/{id}/run
POST /api/superagent/work-items/{id}/approve
POST /api/superagent/watchdog
```

事件示例：

```json
{
  "source": "im",
  "channel": "group",
  "content": "请查订单 order_5695476eb1c8441e，买家说物流异常要售后",
  "thread_key": "api-superagent-e2e"
}
```

## 4. 真实 Worker 结果

真实 API：

```text
accepted True
run 200 {"work_item_id":"saw_...","status":"RUNNING"}
```

Deep Agents Worker 查询后输出：

```text
结论：订单存在，但“物流异常”目前无法证实，先不要给买家任何赔付或退款承诺。
- order_5695476eb1c8441e：保温杯 ×1，实付 ¥89.00，顺丰 SF-B-0001
- 可售后=True，但当前没有售后工单
- 关键阻断点：物流轨迹与异常标记查不到
- 数据不一致：C 端 CONFIRMED / 商家 COMPLETED
建议：人工核实运单与状态后再决定补发/退款/退货
需要人工确认：是
```

审批：

```text
POST /approve {"approved": true}
→ DONE / APPROVED
```

Watchdog：

```text
POST /api/superagent/watchdog {"timeout_seconds": 180}
→ 将超过阈值的 RUNNING WorkItem 标为 STUCK
```

## 5. 真实浏览器 E2E

入口：

```text
http://127.0.0.1:8000/v2/b.html
→ Super-agent
```

真实操作：

```text
输入：请查订单 order_5695476eb1c8441e，买家说物流异常要售后
→ 提交给 Super-agent
→ 已受理 saw_f8934d1c5d5345a4 / 待运行
→ 运行调查
→ 调查中（2s 轮询）
→ 待审批
→ 结论：需要人工介入，状态不一致 + 无物流轨迹 + 无售后工单
→ 通过
→ 已完成 / 审批已通过
```

同时验证：结论安全转义、无脚本注入、移动端无横向溢出、无 console error。
截图：`.mcp/playwright-output/b-superagent-real.png`。

## 6. 测试与构建

```bash
pytest tests/ -q
# 591 passed, 5 skipped, 1 warning

pytest tests/test_superagent.py -q
# 4 passed

npm run build
# ✓ built in 4.38s
# dist/b.html 已生成
```

覆盖：

```text
Router 过滤闲聊
业务事件创建 Thread/WorkItem
同 thread_key 复用活跃 WorkItem
Worker 失败时确定性回退
人工审批
Watchdog 超时标记
```

## 7. 已知限制

```text
MVP 只有确定性 Fast Path，没有 LLM 语义分类
事件入口目前是 HTTP 手动提交；未接 IM/企业微信/GitHub 自动 Trigger
Worker 只读，不做写操作；没有真实异步 start/stop/取消
Watchdog 是手动 API，不是常驻后台 Control Loop
没有 Router 批处理、Thread 多订阅、链式召回
Deep Agents 是 Beta，文件系统工具未做细粒度权限隔离
还没有接入 CApp 聊天的自动 Trigger（当前 B 工作台手动提交）
```

## 8. 下一步

```text
1. IM/企业微信 Trigger 接入（B 工作台面板已完成）
2. Router 异步 start/stop + 批处理
3. 常驻 Watchdog
4. Eval：Super-agent vs 当前 B Agent
5. 多租户/权限隔离
```
