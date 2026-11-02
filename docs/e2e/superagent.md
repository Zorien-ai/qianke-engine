# Super-agent MVP E2E

> 日期：2026-11-02 · 状态：通过（真实 Deep Agents Worker + DeepSeek）

## 1. 架构

```text
事件入口（CApp / IM / Webhook）
  → Router（Fast Path 规则 + Slow Path LLM 语义分类）
  → Thread / WorkItem（SQLite 控制面）
  → 批量 Trigger 归并
  → Deep Agents Worker（只读调查）
  → 结论 + 人工审批
  → 常驻 Watchdog（RUNNING 超时标记）
```

写操作不在 Super-agent 内执行；订单/退款/退货仍走现有受控 API + 人工确认。

## 2. 模块

```text
src/rag_demo/superagent/
├─ store.py      Thread / Trigger / WorkItem / Approval
├─ router.py     Fast Path + LLM 语义分类 + 批量事件
├─ worker.py     Deep Agents + 只读子代理
├─ runtime.py    后台 Worker / 协作式 stop
├─ triggers.py   CApp/IM 自动 Trigger + 通用 Webhook
└─ watchdog.py   常驻 Watchdog
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
POST /api/superagent/events/batch
POST /api/superagent/webhooks/{provider}
GET  /api/superagent/wecom/callback
POST /api/superagent/wecom/callback
GET  /api/superagent/threads
GET  /api/superagent/work-items
GET  /api/superagent/jobs
GET  /api/superagent/work-items/{id}
POST /api/superagent/work-items/{id}/run
POST /api/superagent/work-items/{id}/stop
POST /api/superagent/work-items/{id}/approve
POST /api/superagent/watchdog
```

自动 Trigger：

```text
CApp 好友消息 → capp:friend:<buyer>:<friend> Thread
CApp 群消息   → capp:group:<group_id> Thread
外部 Webhook  → X-Superagent-Secret + POST /webhooks/{provider}
企业微信回调  → AES/签名校验后 POST /wecom/callback

企业微信配置与真实协议测试见：[superagent-wecom.md](superagent-wecom.md)
```

环境变量：

```text
QIANKE_SUPERAGENT_AUTO_TRIGGER=1
QIANKE_SUPERAGENT_AUTO_RUN=1
QIANKE_SUPERAGENT_LLM_ROUTER=1
QIANKE_SUPERAGENT_WEBHOOK_SECRET=<shared-secret>
QIANKE_SUPERAGENT_WATCHDOG_ENABLED=1
QIANKE_SUPERAGENT_WATCHDOG_INTERVAL=60
QIANKE_SUPERAGENT_WATCHDOG_TIMEOUT=180
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

Router：

```text
Fast Path：订单号 / 售后 / 物流 / 退款 / 退货等关键词
Slow Path：没有明显关键词时，用 LLM 判断是否为业务请求
Batch：POST /events/batch 一次处理多条 Trigger，同一 Thread 只建一个 WorkItem
```

真实语义分类/批量验证：

```text
batch: total=3 / accepted=2 / work_items=1
semantic accepted: "我上周买的东西到现在还没到" → SEMANTIC:用户反映已购买商品未收到
semantic rejected: "今天天气不错，随便聊聊" → SEMANTIC_REJECT
```

## 3.1 Worker 异步与 Watchdog

```text
POST /work-items/{id}/run   → 后台线程启动，接口立即返回
POST /work-items/{id}/stop  → 协作式取消；模型调用中无法强杀，返回 CANCELLED
POST /watchdog              → 手动扫描；常驻 Watchdog 每 60s 自动扫描
```

真实 Watchdog 启动日志：

```text
Super-agent Watchdog 已启动 interval=60s timeout=180s
Super-agent Watchdog 标记卡住工作项: ['saw_6a7a025...']
```

## 3.2 对比 Eval

```bash
python scripts/superagent_eval.py
# 输出 tests/superagent_eval_results.json
```

结果：

```text
5 个案例
Super-agent 平均分 0.9
当前 B Agent 平均分 0.6
Super-agent 胜 2 / B Agent 胜 0 / 平 3
```

注意：这是不同工具域对比——Super-agent 能读商家订单/售后，当前 B Agent 只有用户画像和知识库；因此不能把 0.9 > 0.6 解释成通用能力全面提升。详见：

[superagent-eval.md](superagent-eval.md)

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
POST /approve {"approved": true, "action_params": {"sale_type": "REFUND_ONLY"}}
→ EXECUTING
→ 白名单动作执行
→ DONE / EXECUTION_FAILED
```

`CREATE_AFTER_SALE` 必须由人工选择 `REFUND_ONLY / RETURN_REFUND`，缺失时 400 不执行。

企业微信结果回写见：[superagent-wecom-reply.md](superagent-wecom-reply.md)

动作白名单：

```text
CANCEL_ORDER / CREATE_AFTER_SALE / SHIP_ORDER / COMPLETE_ORDER
```

真实取消订单 E2E：

```text
order_6165c9addb24431c CONFIRMED
→ Worker 建议 CANCEL_ORDER
→ 人工通过
→ status=DONE / execution_status=EXECUTED
→ C 端 CANCELLED / 商家 CANCELLED
```

详见：[superagent-actions.md](superagent-actions.md)

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

停止调查：
→ PENDING 工作项显示「停止调查」
→ 点击后 POST /stop
→ 已停止 / CANCELLED，不再继续调查
```

同时验证：结论安全转义、无脚本注入、移动端无横向溢出、无 console error。
截图：`.mcp/playwright-output/b-superagent-real.png`。

## 6. 测试与构建

```bash
pytest tests/ -q
# 617 passed, 5 skipped, 1 warning

pytest tests/test_superagent.py -q
# 12 passed

npm run build
# ✓ built in 4.27s
# dist/b.html 已生成
```

覆盖：

```text
Router 过滤闲聊 / 语义 Slow Path / 批量归并
CApp 自动 Trigger
Webhook 共享密钥校验
业务事件创建 Thread/WorkItem
同 thread_key 复用活跃 WorkItem
Worker 失败时确定性回退
人工审批 / 协作式取消 / 受控动作执行
Watchdog 超时标记与常驻启动
```

## 7. 已知限制

```text
CApp 自动 Trigger + 企业微信原生回调已接入（只处理文本消息，不是群机器人 Webhook）
企业微信内审批命令已接入：同意/驳回 + 售后类型/物流参数
Worker 只读；协作式取消无法中断 Deep Agents 单次 invoke 内部
Watchdog 已常驻，但只标记 STUCK，不自动恢复
Router 批量是 HTTP 批量入口，不是跨渠道自动合批
没有 Thread 多订阅、链式召回、存算分离、端侧 daemon
Deep Agents 是 Beta，文件系统工具未做细粒度权限隔离
对比 Eval 的 B Agent 数据域不同，分数不能代表通用能力
受控执行只有 4 个白名单动作，没有回滚/补偿/双人复核
执行器同步执行，没有分布式锁/多实例竞争保护
```

Worker 队列：

```text
sa_job PENDING → 原子 claim → RUNNING
API 重启 → dispatcher 恢复 PENDING/过期租约
失败 → 最多重试 2 次
审批动作 → ACTION Job 异步执行
```

详见：[superagent-queue.md](superagent-queue.md)

租户隔离详见：[superagent-multitenant.md](superagent-multitenant.md)
独立 Worker / PostgreSQL 队列详见：[superagent-worker.md](superagent-worker.md)

## 8. 下一步

```text
1. 企业微信/飞书更多消息类型与群事件
2. 持久化任务队列与多实例锁
3. Worker streaming 中断/恢复
4. Watchdog 自动恢复与告警
5. 多租户/权限隔离
```
