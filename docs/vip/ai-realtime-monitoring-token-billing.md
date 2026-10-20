# AI 实时监控与 Token 计费产品方案（VIP）

> 交付形态：产品方案 / PRD  
> 适用范围：千客引擎 RAG 工作台  
> 付费模式：按 Token 计量收费  
> 当前阶段：方案确认后开发  
> 分支：`vip`（本地开发，不推 GitHub）

---

## 1. 产品定位

### 1.1 一句话

为使用 AI 能力的企业提供一条**可观测、可计量、可收费**的全链路监控通道：

> 每一次问答、检索、SQL、生成、裁判调用，都有一条可追踪的 Trace；  
> 每一个 Token，都能落到租户、功能、模型和账单上。

### 1.2 卖点

| 传统 AI 监控 | 本方案 |
|---|---|
| 只看接口是否 200 | 看全链路：检索 → SQL → 生成 → 安全审查 |
| 只看总量 | 按租户 / 功能 / 模型 / 时间切片 |
| 不知道钱花在哪 | Token 账本 + 成本 + 套餐余额 |
| 出问题靠日志翻 | Trace ID 一键下钻 |
| 监控只是成本 | 监控本身可产品化，按 Token 收费 |

### 1.3 目标客户

- 使用 RAG / AI 客服 / 营销文案 / 离线评测的企业
- 需要给内部业务方或外部客户出具 AI 用量账单的服务商
- 对数据隔离、Token 成本、回答质量和安全有要求的 B 端客户

---

## 2. 监控范围：全链路

### 2.1 请求级

一次用户请求生成一个 `trace_id`，记录：

- 租户 `tenant_id` / 数据集 `dataset`
- 入口：问答 / 营销文案 / 离线评测 / 数据导入
- 用户 ID、角色、账号等级
- 开始/结束时间、总耗时
- 最终状态：成功 / 失败 / 超时 / 用户取消
- 是否命中缓存
- 是否被安全策略替换
- 返回来源列表数量

### 2.2 RAG 检索级

- 原问题、改写问题（可脱敏）
- 向量召回数、BM25 召回数、稀疏召回数
- 跨路合并数、去重数
- 精排前后候选数
- 进入上下文的画像数 / 文档数
- 检索耗时、精排耗时、首字延迟

### 2.3 SQL / Text2SQL 级

- 是否触发 SQL
- SQL 生成耗时
- SQL 执行耗时、返回行数
- 是否执行失败
- SQL 原文仅对具备 `sql` 能力的账号可见；监控元数据不默认存原文

### 2.4 LLM 调用级

每一次上游模型调用记录：

- 调用用途：query rewrite / answer / SQL / judge / marketing / embedding / rerank
- 模型名、Provider
- Prompt Tokens
- Completion Tokens
- Reasoning Tokens
- Total Tokens
- 单价、成本
- 首 Token 延迟、总延迟
- 状态、错误码
- 是否流式
- `trace_id` / `span_id` / `parent_span_id`
- 重试次数
- 幂等键

> 流式调用必须在最后一个 chunk 请求 `stream_options.include_usage=true`，读取 usage；当前 `generate_events` 流式路径尚未消费 usage，这是开发阶段第一优先改造点。

### 2.5 安全与质量级

- `answer_guard` 是否触发
- 是否替换整段回答
- 敏感信息命中类型
- 预测性内容拦截
- 引用覆盖率
- 用户反馈：有用 / 无用 / 纠错
- 离线评测通过率 / 失败题

### 2.6 系统级

- QPS、并发数
- P50 / P95 / P99 延迟
- 错误率、超时率
- 模型限流 / 失败率
- 缓存命中率
- 数据库慢查询
- 队列积压

---

## 3. Token 计费设计

### 3.1 计费对象

按**监控到的 LLM Token**收费，不按用户输入字数收费。

计费 Token 建议包含：

```text
billable_tokens =
  prompt_tokens
+ completion_tokens
+ reasoning_tokens
```

其中：

- `completion_tokens` 是最终答案
- `reasoning_tokens` 是深度思考产生的推理 Token
- 流式调用以最终 usage 为准
- 失败且上游未返回 usage 的调用：先记 `estimated`，不直接扣费
- 缓存命中：模型成本为 0，Token 计费为 0；可另收极低的请求费（本方案默认不收）

### 3.2 计费公式

```text
单次费用 = 计费 Token / 1000 × 每千 Token 单价
月度费用 = Σ 单次费用
应付金额 = max(0, 月度费用 - 套餐包含额度)
```

每千 Token 单价按模型配置，例如：

| 模型 | 输入（元/1K） | 输出（元/1K） | 说明 |
|---|---:|---:|---|
| DeepSeek Flash | 0.001 | 0.002 | 示例价，开发前需确认 |
| DeepSeek Chat | 0.002 | 0.008 | 示例价 |
| Embedding / Rerank | 单独按调用量或节点成本核算 |  | 本地模型需按机器分摊 |

> 以上价格只是模型表单结构，不代表最终售价。最终售价 = 模型成本 × 毛利率 + 监控服务费。

### 3.3 套餐模型

建议提供三档套餐，既卖监控能力，也卖 Token：

| 套餐 | 月费 | 含监控 Token | 超出单价 | 适合 |
|---|---:|---:|---:|---|
| 体验版 | ¥0 | 100K | 不可超 | 试用 |
| 团队版 | ¥899 | 2M | ¥0.08 / 1K | 中小企业 |
| 企业版 | ¥4,999 | 20M | ¥0.05 / 1K | 多租户服务商 |

另售 Token 包：

- 1M Token 包
- 5M Token 包
- 20M Token 包
- 年度预付包（折扣）

### 3.4 Token 钱包

- 每个租户一个 `token_wallet`
- 字段：余额、赠送额度、已用、冻结、套餐 ID、账期
- 扣费顺序：赠送额度 → 套餐额度 → 钱包余额 → 超额/停用
- 余额低于阈值：站内通知 + 邮件/Webhook
- 余额为 0：只读监控可继续，AI 调用按策略阻断或降级
- 所有扣费必须幂等，重试不会重复扣

### 3.5 计费口径边界

以下规则必须在开发前写死：

1. 缓存命中不计 Token
2. 失败调用不计费（除非上游已产生用量）
3. 重试只计最终一次，或按实际上游 usage 合并
4. 用户中途断开：上游已生成部分仍计费
5. 深度思考的 reasoning tokens 计入
6. 离线评测的 Judge 调用计入
7. 数据导入的 embedding 调用是否计入，可单独开关

---

## 4. 数据模型

建议使用**中央控制库**存储监控与账单，按 `tenant_id` 严格隔离查询；不把全量原始问答内容默认写入监控库。

### 4.1 `ai_traces`

```sql
CREATE TABLE ai_traces (
  trace_id       UUID PRIMARY KEY,
  tenant_id      TEXT NOT NULL,
  dataset        TEXT NOT NULL,
  entrypoint     TEXT NOT NULL,
  account_id     TEXT,
  status         TEXT NOT NULL,
  cache_hit      BOOLEAN DEFAULT FALSE,
  guard_hit      BOOLEAN DEFAULT FALSE,
  started_at     TIMESTAMPTZ NOT NULL,
  finished_at    TIMESTAMPTZ,
  total_ms       INTEGER,
  first_token_ms INTEGER,
  input_summary  TEXT,          -- 脱敏摘要，可选
  meta           JSONB
);
```

### 4.2 `ai_spans`

```sql
CREATE TABLE ai_spans (
  span_id        UUID PRIMARY KEY,
  trace_id       UUID NOT NULL,
  tenant_id      TEXT NOT NULL,
  parent_span_id UUID,
  kind           TEXT NOT NULL,   -- retrieval / sql / llm / guard / cache
  name           TEXT NOT NULL,
  model          TEXT,
  prompt_tokens  INTEGER,
  completion_tokens INTEGER,
  reasoning_tokens  INTEGER,
  total_tokens   INTEGER,
  cost_amount    NUMERIC(12,6),
  latency_ms     INTEGER,
  status         TEXT,
  error_code     TEXT,
  meta           JSONB,
  started_at     TIMESTAMPTZ
);
```

### 4.3 `ai_usage_events`

记账唯一事实表，**只追加不更新**：

```sql
CREATE TABLE ai_usage_events (
  event_id       UUID PRIMARY KEY,
  idempotency_key TEXT UNIQUE NOT NULL,
  trace_id       UUID,
  tenant_id      TEXT NOT NULL,
  feature        TEXT NOT NULL,
  model          TEXT NOT NULL,
  prompt_tokens  INTEGER NOT NULL,
  completion_tokens INTEGER NOT NULL,
  reasoning_tokens INTEGER DEFAULT 0,
  billable_tokens INTEGER NOT NULL,
  input_price    NUMERIC(12,8),
  output_price   NUMERIC(12,8),
  amount         NUMERIC(12,6) NOT NULL,
  usage_source   TEXT NOT NULL,  -- provider / estimated / reconciled
  status         TEXT NOT NULL,
  created_at     TIMESTAMPTZ DEFAULT now()
);
```

### 4.4 `token_wallets`

```sql
CREATE TABLE token_wallets (
  tenant_id      TEXT PRIMARY KEY,
  balance_tokens BIGINT NOT NULL DEFAULT 0,
  frozen_tokens  BIGINT NOT NULL DEFAULT 0,
  plan_id        TEXT,
  period_start   DATE,
  period_end     DATE,
  updated_at     TIMESTAMPTZ DEFAULT now()
);
```

### 4.5 `token_transactions`

充值、赠送、扣费、退款、调整，全部流水化。

### 4.6 `monitor_alert_rules` / `monitor_alerts`

- 规则：Token 燃烧速率、余额阈值、P95 延迟、错误率、安全命中率
- 通道：站内、邮件、Webhook
- 去重与恢复通知

### 4.7 `usage_daily`

按租户 / 天 / 功能 / 模型预聚合，避免监控页实时扫明细。

---

## 5. 采集架构

```text
用户请求
  │
  ▼
FastAPI /qa/stream
  │  trace_id
  ├─ RAG 检索 span
  ├─ SQL span
  ├─ LLM span（含 usage）
  ├─ Guard span
  └─ cache span
  │
  ▼
UsageRecorder（进程内队列 + 后台批量写）
  │
  ├─ ai_traces / ai_spans（监控库）
  └─ ai_usage_events（计费事实表）
        │
        ▼
  TokenLedger（幂等扣费）
        │
        ▼
  Wallet / Quota / Alerts / Invoice
```

### 5.1 采集原则

- **异步落库**：不阻塞问答主链路；批量写 + 失败重试
- **双写可恢复**：监控事件与 usage event 分开表，避免账单依赖日志
- **幂等**：`idempotency_key = tenant + trace + span + attempt`
- **采样**：Trace 元数据全量，Prompt/Completion 原文默认不存；需要排障时按开关短时采样
- **租户上下文**：采集线程必须显式传递 `tenant_id` / `dataset`，不能依赖全局变量

### 5.2 流式 usage 的关键改造

当前 `/qa/stream` 的流式生成路径没有消费最终 chunk 的 usage。开发时必须：

1. 调用 `chat_completion(..., stream=True, stream_options={"include_usage": True})`
2. 在流结束时读取 `chunk.usage`
3. 写入 LLM span
4. 若 provider 未返回 usage：记录 `usage_source=estimated`，不直接扣费，等待对账

### 5.3 现有系统切入点

| 位置 | 改动 |
|---|---|
| `src/rag_demo/generation/generator.py` | `chat_completion` 增加 usage 采集；流式读取最终 usage |
| `src/rag_demo/api/main.py` | `/qa/stream` 创建 trace，stage 事件记录 span |
| `src/rag_demo/pipeline.py` | 检索 / SQL / 精排阶段耗时与数量 |
| `src/rag_demo/answer_guard.py` | guard 命中事件 |
| `src/rag_demo/cache.py` | cache hit/miss |
| `src/rag_demo/api/marketing.py` / `tenant_eval.py` | 营销文案与 Judge 的 LLM usage |
| `src/rag_demo/db/schema.py` | 监控/账本表与初始化 |

---

## 6. API 设计

### 6.1 内部采集

```http
POST /internal/ai/usage-events
X-Internal-Token: ...
```

服务间调用，不接受浏览器直接上报。

### 6.2 监控查询

```http
GET /api/monitor/overview?range=1h|24h|7d
GET /api/monitor/timeseries?metric=tokens|cost|latency|errors&range=24h
GET /api/monitor/traces?page=1&size=20&status=error
GET /api/monitor/traces/{trace_id}
GET /api/monitor/alerts
```

### 6.3 计费

```http
GET  /api/billing/wallet
GET  /api/billing/usage?from=...&to=...
GET  /api/billing/invoices
GET  /api/billing/invoices/{id}
POST /api/billing/token-packs
POST /api/billing/recharge       (管理员/财务)
```

### 6.4 管理端

```http
GET  /admin/monitor/tenants
GET  /admin/billing/tenants
POST /admin/billing/plans
```

所有接口的 tenant 过滤由登录态推导，**不接受前端传 tenant_id**。

---

## 7. 前端页面

### 7.1 `/v2/#/monitor` 实时监控

顶部指标：

- 当前 Token/min
- 今日 Token / 成本
- 请求量 / 错误率
- P95 延迟 / 首字延迟
- 缓存命中率
- 安全拦截数

图表：

- Token 趋势
- 成本趋势
- 延迟 P50/P95
- 错误率
- 按功能 / 模型分布

列表：

- 最近异常 Trace
- 告警列表
- Top 消耗功能

### 7.2 `/v2/#/monitor/traces` 链路追踪

- Trace 列表：时间、入口、耗时、Token、状态、租户
- 详情：瀑布图
  - 检索
  - SQL
  - 精排
  - LLM 生成
  - Guard
  - 写缓存
- 可查看脱敏摘要，不默认展示完整回答

### 7.3 `/v2/#/billing` Token 账单

- 当前套餐、余额、本周期已用
- Token 趋势
- 按功能明细
- 充值 / 购买 Token 包
- 发票记录
- 余额不足提示

### 7.4 管理端

- 全部租户 Token / 成本排行
- 套餐配置
- 手工调账
- 告警规则配置

---

## 8. 权限与安全

- 监控数据只显示当前账号所属租户
- 平台管理员可看跨租户汇总，但不能直接读取其他租户原文
- 账单接口要求企业管理员
- Trace 原文默认关闭；开启采样需审计
- 内部采集接口使用独立 token，不走用户会话
- 所有金额、套餐变更写审计日志
- Token 账本只允许追加，不允许 UPDATE 改历史
- 幂等键防重复扣费
- 数据保留：监控明细 30 天，聚合 365 天，账单永久

---

## 9. 开发阶段与工作量

### Phase 1：全链路可观测（约 2–3 人天）

- Trace / Span 数据结构
- `/qa/stream` 埋点
- LLM usage（含流式）
- 监控总览 API + 页面
- 基础告警

### Phase 2：Token 账本（约 2–3 人天）

- usage event 写入
- 幂等扣费
- Token 钱包
- 套餐 / 余额
- 账单页

### Phase 3：付费闭环（约 3–4 人天）

- 购买 Token 包
- 发票
- 管理端套餐配置
- 告警通知
- 对账 / 压测

**合计约 7–10 人天**，不含支付渠道接入和财务开票资质。

---

## 10. 验收标准

- [ ] 每次问答有唯一 `trace_id`
- [ ] 每次 LLM 调用有模型、Token、延迟、状态
- [ ] 流式调用 Token 与 provider 账单一致（误差 < 0.5%）
- [ ] 租户之间看不到彼此 Trace / 账单
- [ ] 余额不足时按策略阻断或降级
- [ ] 重复上报不会重复扣费
- [ ] 监控页能实时看到 Token / 成本 / 延迟 / 错误
- [ ] 企业管理员能查看账单与充值记录
- [ ] 平台管理员能看跨租户汇总，但不能读原文

---

## 11. 待确认的关键决策

开发前需要确认：

1. **卖什么**：卖监控平台订阅，还是按 Token 转售 AI 调用，还是两者组合？
2. **Token 单价**：按模型成本加价，还是统一按“监控 Token”定价？
3. **是否计 reasoning tokens**：建议计，因为上游会计费。
4. **失败/重试口径**：失败是否计费？
5. **缓存命中**：是否收请求费？
6. **离线评测 Judge**：是否计入客户 Token 费用？
7. **支付渠道**：微信/支付宝/对公转账？
8. **发票**：是否需要自动开票？

---

## 12. 建议的第一版范围

不要一次做全。

建议第一版只做：

> 全链路 Trace + LLM Token 用量 + 监控总览 + Token 钱包扣减  
> 不做自动支付、不做发票、不做复杂套餐。

这样可以在 **5–7 人天**内看到真实数据，再根据客户反馈补商业化能力。
