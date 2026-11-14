# C 端业务流程图与说明（审阅版）

日期：2026-11-14  
范围：消费者 C 端（`/v2/#/c/*`、`/c/login`）可确认的消费、IM、伙伴关系、个人中心与横切能力。  
说明：本报告按代码、接口、测试和页面当前实现整理；资料不足或实现未闭环的部分集中在第 12 节「待确认项」，不把推测写成流程。

---

## 0. 统一口径与总览

### 0.1 角色与系统

| 代号 | 角色/系统 | 在 C 端流程中的职责 |
|---|---|---|
| C 用户 | 消费者 / buyer | 浏览、聊天、加购、确认订单、发起售后、IM、设置 |
| 小鱼 | C 伙伴 Agent | 陪伴、购物参谋、订单查询、交易草稿；按模式限权 |
| 店宠 | 商家店宠 Agent | 商品/SOP/报价；在 C 端表现为商家好友会话 |
| 商家 B 端 | 商家工作台 | 履约、发货、售后审批/验收、报价和订单侧状态 |
| 平台 A 端 | 管理员 | 售后审批、退款/退货验收、审计；不属于消费者流程但为下游 |
| 系统 | 后端/存储/任务 | 认证、商品目录、报价、订单、库存、IM、定时任务、PWA |

### 0.2 统一节点与状态口径

| 名称 | 含义 | 主要状态 |
|---|---|---|
| 登录会话 | Cookie 会话 + `/whoami` 身份 | 已登录 / 未登录 / 不可用 |
| 报价 quote | 谈判/合并报价，引用商品与平台优惠 | `PENDING` → `CONSUMED` / `CANCELLED` |
| 订单草稿 DRAFT | 待用户确认的订单，含确认 token；预占商家库存 | `DRAFT` → `CONFIRMED` / 取消 |
| C 订单 | 消费者订单 | `CONFIRMED` / `CANCELLED` / `REFUNDED` |
| 商家订单 | 商家域履约单 | `CREATED` / `PAID` / `SHIPPED` / `COMPLETED` / `CANCELLED` / `REFUNDED`（页面按商家域展示） |
| 售后工单 | 发货后的退款/退货退款 | `OPEN` → `REJECTED` / `APPROVED`；退货退款另有 `RETURN_PENDING` → `RETURN_SHIPPED` |
| C 端六 Tab | 当前导航 | 首页 / 聊 / 逛 / 订单 / 消息 / 我的（CShell/CApp 已统一为 6 项） |

### 0.3 C 端业务总览图

```text
[C1 账号接入]
      │ 登录成功
      ▼
[C2 首页 / 市集] ──────► [C3 小鱼会话]
      │                      │
      │ 商品/加购             │ 购物参谋 / 交易
      ▼                      ▼
[C4 购物车 + 双宠谈判 + 报价] ──► [C5 订单草稿/确认/生命周期]
                                        │
                                        ├──► [C6 售后/退款/退货]
                                        │
                                        └──► [C8 伙伴关系/回访]
[C7 IM：好友/店宠/群聊] ──► 结构化报价/订单入口 ──► C4/C5
[C9 我的：名片/设置] ──► C1（退出）/ C3（昵称）
[C10 PWA/离线/未读] ══ 横切 C2/C3/C5/C7
```

---

## 1. C1 账号与接入

**起点**：未登录用户访问 C 端页面。  
**终点**：建立登录会话并进入对应角色首页；或停留登录页。  
**参与角色**：C 用户、认证服务、短信服务（开发模式为本地验证码）、系统。  
**关键产出**：consumer 账号、Cookie 会话、`/whoami` 身份。

### 主流程

```text
[C1-01 访问 /v2/#/c/*]
        │
        ▼
[C1-02 页面初始化 /whoami]
        ├─ 已登录 consumer ──► [C2 首页] 或 [C3 对话]
        └─ 未登录/非 consumer ──► [C1-03 /c/login]
[C1-03 /c/login]
        ├─ [登录]
        │    ├─ 手机号 → POST /api/c/auth/sms/send
        │    │       ├─ 开发模式：返回 dev_code，页面提示
        │    │       └─ 生产：短信服务发送
        │    ├─ 验证码登录 POST /api/c/auth/login/code
        │    └─ 密码登录 POST /auth/login
        │           │
        │           └─ 成功：设置会话 Cookie → /whoami → 角色跳转
        └─ [注册]
             [手机号+验证码+昵称+密码+同意协议]
                → POST /api/c/auth/register
                → 创建 consumer → 自动登录 → /c/app
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 是否已有有效会话 | 是 | 直接进入 C 端 |
| 登录方式 | 验证码 / 密码 | 两个登录接口 |
| 注册输入校验 | 手机号、验证码、昵称、密码、协议 | 任一不通过停留表单 |
| 账号类型 | consumer / 非 consumer | consumer 进 C 端；其他角色按系统角色页处理 |
| 短信环境 | dev / provider | 开发态显示 dev_code；生产发短信 |

### 异常与回流

```text
验证码错误/过期 → 停留登录页，提示重试
发送过于频繁/超上限 → 429，倒计时/提示
手机号已注册 → 409，切回登录
密码错误/账号不可用 → 401/提示，停留登录页
协议未勾选、密码不足 8 位 → 前端校验，不提交
```

**与其他业务线衔接**：登录成功进入 C2；退出登录在 C9 触发 `/auth/logout` 回 `/home`；C3/C9 的昵称/头像依赖当前 consumer 会话。  
**待确认**：C 登录页未展示“忘记密码”入口（`/password` 页面存在，但是否作为找回密码流程未确认）；生产短信服务配置属于部署项。

---

## 2. C2 首页与商品浏览

**起点**：已登录用户进入 `/c/home` 或 `/c`。  
**终点**：进入聊天、商品详情、购物车/报价或订单；或停留在异常/空态。  
**参与角色**：C 用户、首页/市集页面、商品目录、商家商品仓库、店宠。  
**关键产出**：商品曝光、SKU 选择、加购入口、聊天入口。

### 主流程

```text
[C2-01 /c/home]
        ├─ [C2-02 和小鱼聊聊] ─────────────► [C3 小鱼会话]
        ├─ [C2-03 去逛市集] ───────────────► [C2-05 /c 市集]
        ├─ [C2-04 快捷入口]
        │    ├─ 市集 ─────► /c
        │    ├─ 找小鱼 ───► /c/app
        │    ├─ 订单 ─────► /c/orders
        │    └─ 消息 ─────► /c/social
        └─ [C2-06 商品卡] ──► /c（当前统一跳市集，不是单品详情）
[C2-05 /c 市集]
        → 加载商品（优先 store_demo 真实商家商品，失败回退 /api/c/products）
        → 搜索 / 分类 / 排序
        → [C2-07 商品详情] → 选择 SKU → 
             ├─ 加入购物车 ─────────────► [C4 购物车/报价]
             ├─ 问问小鱼/店宠 ─────────► CShop 助手（通用走 C3 Agent；店铺走 C7 店宠）
             └─ 查看详情/图片
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 商品来源 | 商家商品 / C 商品种子回退 | 有真实 SKU 才能稳定加购 |
| 是否有库存 | 有 / 无 | 有库存显示加购；缺货禁用/提示 |
| 用户动作 | 加购 / 问小鱼 / 详情 | 分别进入 C4 / C3 / 详情 |
| 店铺上下文 | 有 `friend_id`/`merchant_id` | 走该商家商品；无则通用市集 |

### 异常与回流

```text
商品接口失败 → 页面错误态 + 重试/空态
搜索无结果 → 清除筛选/换关键词
图片加载失败 → 图片占位，不影响商品信息
SKU 缺货 → 禁用加购/提示
无商家绑定 → 加购失败，提示先建立商家会话（C7 发现店宠）
```

**与其他业务线衔接**：C2 → C3（问问小鱼）、C4（加购）、C7（店宠店铺/发现店宠）；C3 推荐结果也可跳回 C2 的商品/店铺。  
**待确认**：首页商品卡目前统一跳 `/c`，没有带 `product_id` 的单品深链；通用市集与多商家聚合口径需产品确认。

---

## 3. C3 小鱼会话与意图路由

**起点**：C 用户在 `/c/app` 输入消息（或从商品/订单入口带入需求）。CShop 右侧的通用助手也调用同一个 `/api/c/agent/run`，但它是 CShop 页面内独立的面板；店铺助手走 C7 店宠会话。  
**终点**：普通回复、商品卡、订单草稿/待确认，或可重试错误。  
**参与角色**：C 用户、小鱼（C Agent）、问题 Router、工具层、商家商品/订单仓库。  
**关键产出**：模式、回复、`product_refs`、订单草稿、错误/重试状态。

### 主流程

```text
[C3-01 输入消息]
   → POST /api/c/agent/run
      { message, thread_id?, client_message_id?, mode? }
   → [C3-02 幂等/线程检查]
   → [C3-03 route_question]
        ├─ 客户端显式 mode → 指定模式
        ├─ 交易词（确认订单/下单/买…）→ transaction
        ├─ 订单/物流/售后词 → order
        ├─ 偏好/否定表达 → companion
        ├─ 商品/价格/图片/推荐词 → advisor
        └─ 其他/空消息 → companion
   → [C3-04 按模式构图与工具]
        companion: 无工具
        advisor: recommend_products
        order: query_my_orders / query_tracking
        transaction: recommend_products + 订单/物流 + prepare_order
   → [C3-05 LLM ↔ Tool 循环]
        ├─ 普通工具结果 → 继续 LLM
        ├─ prepare_order → interrupt 挂起 → 返回 draft
        └─ 无工具调用 → 生成回复
   → [C3-06 提取回复/商品卡/草稿/订单]
   → CApp 渲染气泡、商品卡、草稿确认卡
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 是否显式指定模式 | 是 / 否 | 显式优先；否则规则路由 |
| 路由类别 | companion / advisor / order / transaction | 决定可用工具和回复规则 |
| 会话内模式变化 | 与上一轮不同 | 追加模式切换 SystemMessage，不丢历史 |
| 工具是否产生草稿 | 是 | `interrupted=true`，等待用户确认/取消 |
| 是否已有待确认草稿 | 是 | 新消息被阻止，先处理草稿 |
| 商品结果 | 有 / 无 | 有则渲染商品卡；无则如实说明 |

### 异常与回流

```text
LLM/工具异常 → 502 / 前端错误提示 + 重试（复用 client_message_id）
client_message_id 重复 → 幂等回放；内容不一致 → 409
待确认草稿未处理 → 409「有待确认订单」
商品图片误说“发不了” → 由模式规则和商品卡纠正（当前 prompt 约束）
```

**与其他业务线衔接**：C3 → C2（商品/店铺）、C4（顾问推荐后加购/报价）、C5（transaction 生成草稿）、C6（order 模式查询售后状态）、C8（记忆写入）；CShop 通用助手复用 C3 的 Agent 接口，店铺助手复用 C7 店宠消息。  
**待确认**：Router 是规则优先；未命中默认 companion 置信度约 0.62，低置信度场景是否需要 LLM 二次分类尚未产品化；`product_refs` 只取本轮新增工具结果（本轮修复），历史消息卡片是否回填需单独确认。

---

## 4. C4 购物车、双宠谈判与报价

**起点**：商品详情/商品卡执行“加入购物车”，或从会话进入砍价。  
**终点**：生成 `PENDING` 报价供 C5 使用；或被拒绝并给出原因。  
**参与角色**：C 用户、小鱼、店宠、商家商品/库存仓库、平台优惠规则。  
**关键产出**：购物车、谈判 transcript、结构化 quote（商品、SKU、单价、数量、平台满减）。

### 主流程

```text
[C4-01 商品/SKU] → 加入购物车 → [C4-02 本地购物车]
        │
        ├─ [C4-03 让小鱼去砍价 / 购物车合并报价]
        │      → POST /api/c/negotiations
        │        { need, budget, quantity, friend_id, sku? / items? }
        │      → [C4-04 解析商家 + 候选 SKU]
        │         ├─ 无匹配/无库存 → REJECTED
        │         ├─ 合计超预算 → REJECTED
        │         └─ 接受 → 创建 quote PENDING
        │      → [C4-05 报价卡 + transcript]
        │
        └─ [C4-06 C5 订单准备]
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 是否购物车合并 | 单商品 / items | 单商品按 need+sku；items 合并报价 |
| 商家是否可解析 | 是 / 否 | 用 friend→merchant；无匹配则拒绝 |
| SKU/库存 | 有 / 无 | 无货拒绝；数量超库存拒绝 |
| 平台满减 | 满 299 / 满 599 / 不满 | 减 30 / 减 80 / 无优惠 |
| 合计 vs 预算 | 预算内 / 超预算 | 生成 PENDING quote / `BUDGET_TOO_LOW` |
| 多商家购物车 | 同商家 / 跨商家 | 同商家可合并；跨商家要求分开结算 |

### 异常与回流

```text
无候选商品 → REJECTED: MERCHANT_NO_MATCH / SKU_NOT_AVAILABLE
库存不足 → REJECTED: INSUFFICIENT_STOCK
超预算 → REJECTED: BUDGET_TOO_LOW，可改数量/等平台活动
购物车变化 → 阻止准备/确认，要求重新合并报价
报价取消 → quote CANCELLED，回到购物车/商品
商家数据不可用 → MerchantError 结构化错误，禁止编造价格
```

**与其他业务线衔接**：C2 → C4；C4 → C5（quote prepare）；C7（店宠报价可直接跳 `/c?friend_id=...&quote=...` 走 C5）；C4 报价也是 A 端审计的输入。  
**待确认**：谈判为确定性单轮/有限候选方案，不是自由多轮博弈；`MAX_ROUNDS=3` 但购物车路径是单轮合并；平台满减为当前固定规则；真实改价/发券不允许。

---

## 5. C5 订单准备、确认与生命周期

**起点**：C4 的 `PENDING` 报价，或 C3 transaction 模式生成的 `prepare_order` 草稿。  
**终点**：C 订单 `CONFIRMED` 并进入履约；或取消/失败回到草稿/购物车。  
**参与角色**：C 用户、C 端存储、商家仓库、商家 B 端、平台 A 端（退款/售后）。  
**关键产出**：`DRAFT` 草稿、确认 token、商家订单、C 订单、库存预占/扣减。

### 主流程

```text
[C5-01a quote PENDING]
        │ POST /api/c/quotes/{id}/prepare
        ▼
[C5-02 DRAFT 草稿]  ◄──── [C5-01b C3 transaction prepare_order]
        │                  （直接生成草稿）
        │ + 商家库存预占
        │ + confirmation_token
        ▼
[C5-03 用户核对草稿]
        ├─ 取消草稿 → POST /api/c/orders/{draft_id}/cancel
        │                → 释放预占，草稿终止
        └─ 确认 → POST /api/c/orders/{draft_id}/confirm
                     { confirmation_token, request_id }
                     → 校验 token/价格/库存
                     → 创建商家订单 + 提交预占
                     → 扣减 C 商品库存
                     → C 订单 CONFIRMED
                     → quote CONSUMED
                     → 奖励伙伴 + 安排购后回访
                     → [C5-04 订单页/时间线]
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 来源 | 报价 / 直接 item | quote 价格快照 / C 商品价校验 |
| token 与状态 | 有效 DRAFT / 已处理 | 可确认 / 不能重复确认 |
| 价格/库存 | 未变 / 变化 | 确认 / `ORDER_CHANGED`、重准备 |
| 商家预占 | 成功 / 失败 | 继续 / 回滚并报错 |
| 确认后 | 正常 / 幂等重放 | 新订单 / 返回已有订单 |
| 订单取消 | 商家 `CREATED`/`PAID` 且 C 侧可取消 | 取消 + 模拟退款 + 恢复库存 |
| 发货后 | 商家 `SHIPPED`/`COMPLETED` | 可进入 C6 售后 |

### 异常与回流

```text
缺 token/草稿不存在 → 400/404，提示重新准备
重复确认 → ORDER_NOT_DRAFT，返回已有订单或提示
价格变化 → ORDER_CHANGED，重新准备
库存不足 → INSUFFICIENT_STOCK，草稿不可确认
商家创建订单/提交预占失败 → MerchantError，回滚 C 草稿，提示重试
request_id 重放 → 幂等返回；不同订单复用 → 409
```

**状态机**

```text
DRAFT ──确认──► CONFIRMED ──取消（商家 CREATED/PAID）──► CANCELLED
  │                 │
  └─取消草稿─► 终止   └──售后通过──► REFUNDED
```

**与其他业务线衔接**：C3 transaction → C5；C4 quote → C5；C5 → C6（发货后售后）、C8（完成后的回访）、B 端履约、A 端审计。  
**待确认**：当前订单是模拟交易，没有真实支付网关；C 订单确认即视为已确认，页面可能展示商家 `PAID` 状态，但 C 端没有支付动作；“支付/已支付”应由谁推进、是否接真实支付未确认。

---

## 6. C6 售后、退款与退货

**起点**：C 订单已确认，且商家订单处于 `SHIPPED` 或 `COMPLETED`。  
**终点**：售后通过并退款（C 订单 `REFUNDED`）、被拒（`REJECTED`），或退货验收完成/拒绝。  
**参与角色**：C 用户、商家 B 端、平台 A 端、商家仓库、物流。  
**关键产出**：`c_after_sale` 工单、退货物流、退款/库存恢复。

### 主流程

```text
[C6-01 订单页（可售后）]
   → 选择 REFUND_ONLY / RETURN_REFUND + 原因
   → POST /api/c/orders/{order_id}/after-sales
   → [C6-02 OPEN]
        │
        ├─ 拒绝 → REJECTED（结束）
        ├─ 仅退款通过 → 商家退款 → APPROVED + C 订单 REFUNDED
        └─ 退货退款通过 → RETURN_PENDING
              → 用户填写退回运单
              → POST /orders/{order_id}/after-sales/{ticket_id}/return-shipment
              → RETURN_SHIPPED
              → 商家验收入库
                   ├─ 拒绝 → REJECTED
                   └─ 通过 → 恢复库存 + 商家退款 → APPROVED + C 订单 REFUNDED
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 订单是否可售后 | 已发货/已完成 / 其他 | 可申请 / `AFTER_SALE_NOT_ALLOWED` |
| 是否已有售后 | 无 / 处理中或已通过 | 可创建 / `AFTER_SALE_EXISTS` |
| 售后类型 | REFUND_ONLY / RETURN_REFUND | 直接退款 / 先退货 |
| 审批 | 通过 / 拒绝 | 退款/退货 / REJECTED |
| 退货验收 | 通过 / 拒绝 | 恢复库存并退款 / REJECTED |
| 与取消的关系 | 未发货可取消 / 已发货走售后 | 取消是 C5 分支，售后是 C6 |

### 异常与回流

```text
未发货/未完成 → 售后不允许，提示走取消或等待发货
已有 OPEN 工单 → 不能重复申请
退货运单为空/格式不对 → RETURN_SHIPMENT_INVALID
当前状态不能提交运单/验收 → AFTER_SALE_NOT_RETURNABLE
商家退款/验收失败 → MerchantError，不伪造退款结果
```

**与其他业务线衔接**：C5 商家状态 → C6；C6 → B/A 售后审批与验收；退款依赖商家模拟退款，不接真实支付；订单页展示售后状态/退款金额。  
**待确认**：C 端没有审批能力，审批在 B/A；C 端售后通知/状态推送未接入推送服务；退款到账时间为模拟展示还是真实回调未确认。

---

## 7. C7 IM 社交与店宠会话

**起点**：C 用户进入 `/c/social` 消息页，或从 CApp 选择好友/店宠/群会话。  
**终点**：发送消息并收到回复/结构化报价/订单入口；未读状态更新。  
**参与角色**：C 用户、好友、店宠、群成员、WebSocket 服务、IM 存储。  
**关键产出**：好友/店宠关系、消息、未读/@、结构化报价链接。

### 主流程

```text
[C7-01 /c/social]
   → GET /api/c/friends
   → 选择好友
   → GET /api/c/friends/{friend_id}/messages
   → 发送：
        ├─ WS /api/c/ws/chat/{friend_id}
        │     ├─ chat 消息 → 追加消息
        │     ├─ reply / companion_message → 追加回复
        │     └─ error → 提示
        └─ WS 不可用 / fallback → POST /api/c/friends/{friend_id}/messages
   → 店宠好友：@店宠 唤醒 → 结构化 quote/policy/product_refs
        → 去商城确认 /c?friend_id=...&quote=...
[C7-02 发现店宠]
   → GET /api/c/merchants/available
   → POST /api/c/friends/merchants → 建立好友会话
[C7-03 CApp 群聊]
   → GET /api/c/groups → 选择群
   → GET/POST /api/c/groups/{group_id}/messages
   → WS /api/c/ws/group/{group_id}
   → @提及：/api/c/mentions；未读：/api/c/threads/unread + read
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 会话类型 | 好友 / 店宠 / 群 | 三种消息和回复路径 |
| 发送通道 | WS 可用 / 不可用 | WS 实时 / HTTP 回退 |
| 是否 @店宠 | 是 / 否 | 触发店宠；普通消息不触发 Agent |
| 是否有未读/提及 | 有 / 无 | 角标、@N、标读 |
| 报价是否生成 | 有 / 无 | 显示“去商城确认” / 普通回复 |

### 异常与回流

```text
WS 连接失败/断线 → 状态 fallback → HTTP 发送；定时重连
好友列表/消息加载失败 → 错误态 + 重试/空态
发送失败 → 保留草稿或错误提示，可重试
群/好友权限不足 → 403/404
发现店宠为空 → 空结果，不伪造商家
```

**与其他业务线衔接**：C7 店宠报价 → C4/C5；C7 好友/群 → CApp 会话；未读/@ → CApp 角标和 C9 通知偏好（仅本机）；C7 发现店宠 → C2 店铺商品。  
**待确认**：当前 IM 为 mock IM/店宠 Agent，不是真实第三方 IM；群创建 UI、普通好友添加入口、已读回执的跨端同步未确认；CApp 群聊与 CShell 消息页是两套会话壳。

---

## 8. C8 伙伴关系经营：记忆、日记、主动关心

**起点**：用户聊天、订单完成、每日任务或主动打开 App。  
**终点**：记忆/日记/主动回访消息写入并影响下一次会话；或被用户暂停/关闭。  
**参与角色**：C 用户、小鱼、记忆提取/每日任务、订单服务。  
**关键产出**：`c_companion_memory`、digest、diary、checkin、rhythm 状态。

### 主流程

```text
[C8-01 聊天消息]
   → POST /api/c/agent/run
   → 规则匹配“我喜欢/预算/别推荐/我穿…”等明确声明
   → store.save_memories → 活跃记忆
   → 下次 system prompt 注入记忆/压缩记忆（最多 8 条）

[C8-02 每日任务]
   → 记忆降权 → 超过活跃上限则压缩/归档 → 生成 digest
   → 若开启日记：按当天消息生成日记（PII 命中则放弃）

[C8-03 购后主动关心]
   → 商家订单 COMPLETED
   → 签收 + 24h 后 checkin due
   → 用户打开 CApp → POST /api/c/companion/checkin
   → rhythm（启用/暂停/免打扰）允许 → 写入/显示主动消息
   → 订单取消/退款 → checkin SKIPPED

[C8-04 用户控制]
   → PATCH /api/c/companion/rhythm（启用/暂停/安静时段）
   → PATCH /api/c/companion/diary（开启/关闭）
   → GET /api/c/companion/memories；删除单条/清空
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 消息是否命中记忆声明 | 是 / 否 | 写入记忆 / 不写 |
| 活跃记忆是否超限 | 是 / 否 | 压缩/归档 / 保留 |
| 日记是否开启 | 是 / 否 | 生成 / 跳过 |
| 订单是否完成 | 是 / 否 | 安排回访 / 不投递 |
| 签收后 24h | 已到 / 未到 | 允许 checkin / 继续等待 |
| rhythm 状态 | 启用 / 暂停/免打扰 | 投递 / 不投递 |

### 异常与回流

```text
记忆写入失败 → 不影响主对话
日记生成失败/PII 命中 → 放弃当天日记，不影响主链路
订单取消/退款 → checkin SKIPPED；未完成 → 保留 PENDING
用户关闭日记/暂停节奏 → 后续不投递或跳过
```

**与其他业务线衔接**：C3 对话注入记忆；C5 订单完成触发回访；C9 个人中心展示昵称/头像；C10 未读/主动消息在 CApp 呈现。  
**待确认**：主动关心目前依赖用户打开 App 触发 checkin（无系统推送）；记忆提取是规则表达，不保证覆盖所有偏好；日记只对开启用户生成。

---

## 9. C9 个人中心与设置

**起点**：C 用户从导航进入 `/c/me`。  
**终点**：保存昵称/本机偏好、查看名片、修改密码、退出登录。  
**参与角色**：C 用户、认证服务、伙伴存储、浏览器本地存储。  
**关键产出**：个人名片、昵称、通知/隐私偏好、退出会话。

### 主流程

```text
[C9-01 /c/me]
   → 并行 GET /whoami + GET /api/c/companion
   → 加载中：骨架屏
   ├─ 失败：错误卡片 + 重新加载
   ├─ 账号为空：空状态 + 刷新/重新登录
   └─ 成功：
        [C9-02 个人名片] → “查看名片主页”弹层
        [C9-03 账号资料]
             昵称编辑 → PATCH /api/c/companion → toast
             登录账号只读
             修改密码 → /password
        [C9-04 通知偏好] → 本机 localStorage + toast
        [C9-05 隐私与通用] → 本机 localStorage + toast
             在线状态 / 已读回执 / 恢复默认
        [C9-06 退出登录] → confirm → POST /auth/logout → /home
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 资料加载 | 成功 / 失败 / 空 | 卡片 / 错误 / 空状态 |
| 昵称输入 | 空 / >12 字 / 合法 | 报错 / 保存 |
| 偏好开关 | 通知 / 隐私 | 写 localStorage + toast |
| 修改密码 | 链接 `/password` | 离开个人中心 |
| 退出 | 确认 / 取消 | 清会话 / 留下 |

### 异常与回流

```text
/whoami 或 companion 失败 → 个人中心错误态，重试
昵称保存失败 → toast 错误，保留编辑内容
头像 URL 不存在 → 首字占位，不发请求
本机存储不可用 → 当前会话状态仍生效，持久化失败不阻断
退出失败 → toast，停留当前页
```

**与其他业务线衔接**：C1 退出登录；C3 使用昵称/头像/伙伴设置；C8 设置节奏/日记入口在 CApp 侧（C9 当前只展示通知/隐私本机偏好）；C2/C7 导航统一 6 Tab。  
**待确认**：通知偏好和隐私开关当前只存本机，未接推送/服务端偏好表；个人中心不重复做头像上传；账号 `display_name` 是否允许修改未确认（当前修改的是伙伴 `user_nickname`）。

---

## 10. C10 横切：PWA、离线、未读与通知

**起点**：浏览器首次访问/安装、网络变化、未读轮询或伙伴主动消息。  
**终点**：安装提示、离线提示、未读角标或回访消息；或失败降级。  
**参与角色**：浏览器/PWA、Service Worker、CApp、后端未读接口、伙伴 checkin。  
**关键产出**：安装状态、离线 UI、未读计数、主动消息。

### 主流程

```text
[C10-01 首次访问]
   → manifest + service worker + iOS 安装提示
   → 用户“添加到主屏幕”/关闭提示

[C10-02 网络变化]
   → offline 事件 → 离线横幅
   → 恢复 online → 隐藏横幅，继续请求

[C10-03 未读]
   → CApp 每 20s GET /api/c/threads/unread
   → 会话角标 / @N
   → 打开会话 POST /threads/{id}/read

[C10-04 主动消息]
   → 用户打开 CApp → POST /api/c/companion/checkin
   → rhythm 允许且订单完成 24h → 投放伙伴消息
```

### 判断与分支

| 判断点 | 分支 | 结果 |
|---|---|---|
| 安装环境 | 支持 beforeinstallprompt / iOS Safari | 安装按钮 / 手动提示 |
| 网络 | 在线 / 离线 | 正常请求 / 离线横幅 + 降级 |
| 未读 | 有 / 无 | 角标 / 无 |
| 主动回访 | 到点且允许 / 不满足 | 投放 / 跳过/保留 |

### 异常与回流

```text
离线时 API 失败 → 错误提示/重试；不伪造成功
Service Worker 缓存旧资源 → 版本更新/强制刷新（当前 PWA 缓存版本由 sw.js 管理）
推送服务缺失 → 未读轮询/checkin 兜底，不承诺系统推送
```

**与其他业务线衔接**：横切 C2/C3/C5/C7；C9 的通知/隐私偏好目前只影响本机 UI 状态，不驱动推送。  
**待确认**：系统推送、跨设备已读回执、离线写队列未实现；PWA 缓存版本/客户端强制更新流程仍可能需要产品确认。

---

## 11. 业务线衔接矩阵

| 上游 | 下游 | 交接物 | 触发条件 |
|---|---|---|---|
| C1 登录 | C2/C3/C9 | consumer 会话、`/whoami` | 登录成功 |
| C2 商品 | C4 购物车 | 商品/SKU/商家 friend_id | 加入购物车 |
| C2/C3 | C3 会话 | 商品需求/上下文 | 问问小鱼/店宠 |
| C3 transaction | C5 订单 | `prepare_order` 草稿/token | 用户表达购买/下单 |
| C4 谈判 | C5 订单 | `PENDING` quote | 用户准备订单 |
| C5 订单 | C6 售后 | `CONFIRMED` + 商家 `SHIPPED`/`COMPLETED` | 用户申请售后 |
| C5 订单 | C8 回访 | 完成订单/签收时间 | 商家 `COMPLETED` + 24h |
| C7 店宠 | C4/C5 | 结构化报价/商品 | 店宠回复 quote |
| C7 IM | C3 | 会话消息/上下文 | 发送消息 |
| C9 我的 | C1 | 退出/账号资料 | 退出登录/改密 |
| C9 设置 | C10 | 本机通知/隐私偏好 | 开关保存（仅本机） |
| C6 售后 | B/A | 售后工单/退货 | C 用户提交 |
| C 端 | A 审计 | 报价/订单/售后数据 | 管理端只读审计 |

---

## 12. 待确认项（不要当作已实现）

| 编号 | 待确认项 | 当前事实 | 影响 |
|---|---|---|---|
| Q1 | 真实支付 | 订单为模拟交易，确认后直接建单；无支付网关 | C 端无真实支付/对账 |
| Q2 | 通知偏好与推送 | C9 只存 localStorage；无推送服务 | 开关不驱动系统通知 |
| Q3 | 首页商品深链 | 首页商品卡统一跳 `/c` | 无法直达单品详情 |
| Q4 | 通用市集与多商家 | 默认使用 store_demo 真实商家商品，回退 C 商品种子 | 多商家聚合口径未确认 |
| Q5 | 订单支付状态归属 | C 订单确认后为 `CONFIRMED`；商家 `PAID` 由商家域推进 | 谁触发/何时支付待确认 |
| Q6 | 售后通知/到账 | C 端提交后无推送；退款在商家侧模拟完成 | 用户等待体验与退款口径 |
| Q7 | 真实 IM/群创建 | IM 为 mock + WebSocket；群创建 UI 未确认 | 真实社交能力边界 |
| Q8 | 已读回执 | C9 已读回执是本机偏好，IM 后端未实现跨端回执 | 状态展示不可承诺 |
| Q9 | 个人资料字段 | 改的是伙伴 `user_nickname`，账号 `display_name` 是否可改未确认 | 名片名称来源 |
| Q10 | 头像上传入口 | C9 仅展示头像，不重复上传；沿用 CApp 入口 | 用户操作路径 |
| Q11 | PWA 缓存/版本一致性 | `sw.js` 有缓存版本；客户端仍可能持有旧壳 | 用户看到旧 Tab/旧页面 |
| Q12 | 物流服务商 | 快递查询依赖外部配置；失败必须如实说明 | 轨迹可能不可用 |

---

## 13. 证据索引

| 业务线 | 页面 | 后端/接口 | 测试/文档 |
|---|---|---|---|
| 认证 | `api/static/c-login.html` / `c-login.js` | `api/c_auth.py`、`/auth/login` | `tests/test_c_end_store.py` 等 |
| 首页/市集 | `web/src/views/CHome.vue`、`CShop.vue` | `/api/c/products`、`/api/c/merchant/products` | `docs/e2e/c-end-home.md`、CShop E2E 文档 |
| 对话/路由 | `web/src/views/CApp.vue` | `c_end/agent.py`、`router.py`、`/api/c/agent/*` | `tests/test_c_end_router.py`、`test_c_end_agent.py` |
| 谈判/报价 | `CShop.vue`、`CApp.vue` | `c_end/negotiation.py`、`/api/c/negotiations`、`/quotes/*` | `tests/test_c_end_negotiation.py` |
| 订单 | `CApp.vue`、`CShop.vue`、`COrders.vue` | `c_end/store.py`、`/orders/*` | `tests/test_c_end_agent.py`、`test_c_end_merchant_transactions.py` |
| 售后 | `COrders.vue` | `store.py`、`/orders/{id}/after-sales` | 售后/退款测试 |
| IM/店宠 | `CSocial.vue`、`CApp.vue` | `social.py`、`group.py`、`/friends/*`、`/groups/*`、WS | `tests/test_c_end_social.py`、`test_c_end_group.py`、`test_c_end_mentions_unread.py` |
| 伙伴关系 | `CApp.vue`、C9 | `memory_daily.py`、`/companion/*` | `tests/test_c_end_memory.py`、`test_c_end_rhythm.py` |
| 个人中心 | `CMe.vue`、`CShell.vue`、`router.js` | `/whoami`、`/api/c/companion` | `docs/e2e/c-end-me-personal-center.md` |
| PWA/未读 | `sw.js`、`CApp.vue` | `/threads/unread`、`checkin` | `docs/e2e`、PWA 相关测试 |

---

## 14. 审阅建议

1. 先确认第 12 节 Q1/Q2/Q5/Q6（支付与通知）是否属于本阶段范围，否则 C5/C6/C10 的终点只能按模拟流程验收。
2. 再确认 Q3/Q4（首页深链、通用市集口径），这会影响 C2→C4 的转化路径。
3. Q7/Q8（IM 边界）决定 C7 是否按真实 IM 验收，还是按当前 mock IM + 店宠 Agent 验收。
4. C3 的模式路由与 C4/C5 的草稿/确认是安全边界，任何后续改动应同时回归 `test_c_end_router.py`、`test_c_end_agent.py`、`test_c_end_negotiation.py`。
