# 千客 B 端 2.0：批量库存与支付/完成审计契约设计

2026-11-14 · v0.1 · 仅设计评审，不是已实现的 API

本稿在现有 P0 商品/SKU、订单抽屉和模拟确认界面上补充数据与服务契约。只新增本文，不修改生产代码、不提交 PR。示例商家、仓库、SKU、订单、数量、金额、操作者和时间均为虚构模拟。

## 1. 基线、已有事实与待确认项

代码基线：`28183d5761a5b757d727b1cc13957e40b8091271`，本次获取的 `origin/b-end-2.0-p0`，已包含 P0 壳层和上一篇设计文档。本稿为契约设计，不替代 PR #5 的代码审查或线上验收。

| 证据 | 当前实现 | 对本稿的约束 |
| --- | --- | --- |
| [库存模型](../../src/rag_demo/merchant/models.py)：InventoryRecord、WarehouseStock、Inventory | 库存按商家/SKU/仓库读取；available_qty、reserved_qty、safety_stock、updated_at 已有；汇总跨仓相加，没有 version 字段 | UI“锁定”实际对应 reserved_qty；跨仓汇总不能直接作为单仓写入对象；updated_at 不当作可靠并发版本 |
| [写仓储协议](../../src/rag_demo/merchant/repository.py)：reserve/commit/release | 预占扣 available、加 reserved；提交预占时 reserved 转出，available 保持扣减；存在取消恢复和退货入库 | 不能说系统“没有库存写入”；缺的是 B 端手工调整/批量盘点契约 |
| [PG 仓储](../../src/rag_demo/merchant/postgres_repository.py)：_allocate_stock、_consume_allocations、_restore_committed_allocations | 事务、锁行、条件扣减、按 SKU 顺序加锁已有；不同库存写路径共同影响数量 | 新版并发号必须覆盖所有写路径，不能只在新增批量接口递增 |
| [SQLite 仓储](../../src/rag_demo/merchant/sqlite_repository.py) | 同样提供预占、提交、释放、取消、退款、退货等交易写能力 | 新契约必须明确双后端支持或拒绝能力，不允许静默退化成无版本写入 |
| [B API](../../src/rag_demo/api/b_workbench.py) | 有库存告警扫描/处理及商品图片写接口；无手工库存数量调整接口 | operate_inventory 不能直接推导“任何库存调整都已支持”；权限需细分或明确映射 |
| B API WorkbenchOrderStatusIn / workbench_update_order | PATCH /orders/{id}/status 接收 PAID/SHIPPED/COMPLETED/CANCELLED 和物流字段；使用 operate_orders | 未见本稿要求的请求幂等、expected_version、模拟来源、操作者审计契约 |
| 商家 Order 模型与状态仓储 | paid_at、completed_at、refund_amount、refunded_at 已有；状态推进写时间，同状态重放保留原时间 | 不重复新增时间字段；不能把旧文档的“无时间字段”沿用为事实 |
| [P0 页面](../../web/src/b-workbench.js)：onOrderAction、orderDetailDrawer、productsView | 模拟支付/完成已有二次确认；库存页提示保存、版本和部分失败待接入 | 只补预览/提交面板与结果反馈，不重画订单/商品表 |

现有商品图片审计、Super-agent 执行审计不等于所有库存调整、订单状态推进都有统一业务审计。本文新增的是明确覆盖这些操作的契约，不否认已有其他审计能力。

已确认：当前继续模拟交易，流水按完成时间，仓库关注商品数据更新。以下为待确认设计建议：首版每批单仓、最多 50 个 SKU；优先支持可售量调整，实物盘点依赖完整占用模型；独立库存/订单动作权限；审计保留期与幂等重放期；未来真实支付模式的独立接入流程。未确认即不应作为已批准上线规则。

相关设计：[产品决策](./b-end-2.0-decisions.md)、[P0 设计](./b-end-2.0-p0-design.md)、[客服与完成口径报告](./b-end-2.0-customer-service-report.md)。退款跨月细节沿用后一份文档的建议，不重复扩展客服/报告内容。

## 2. 库存数量语义：先区分可售与实物

### 2.1 字段定义与不变量

| 字段 | 本稿含义 | 调整权限 |
| --- | --- | --- |
| available_qty（A） | 当前允许销售的数量，已排除预占和已提交订单消耗 | 本稿受控调整目标；不得为负 |
| reserved_qty（R） | 尚未提交的临时预占数量，UI 建议解释为“预占锁定” | 操作者只读，必须通过原预占服务释放/提交，不得手填清零 |
| safety_stock（S） | 提醒阈值，不是实际库存，也不是额外扣除项 | 首版批量数量调整保持不变；修改阈值需独立动作/权限/审计 |
| committed_unshipped_qty（C） | 已提交为订单但实物尚未出库的占用 | 新增或由完整可信分配记录推导，当前模型未直接提供 |
| blocked_qty（B） | 包括在盘点范围内、但不可销售且不属于 R/C 的残次/冻结量 | 新增待确认，不能默认为 0 |
| inventory_version（V） | 单商家、单仓、单 SKU 的单调版本 | 服务端维护，所有相关变更递增 |

A/R/S 必须为有限非负整数；布尔值、小数、NaN、Infinity、字符串隐式转换一律拒绝。S 可以大于 A，它表示提醒阈值而非“库存不足不能保存”。数量上限由 capability 给出并在数据库类型安全范围内，本稿不编造已有业务上限。商品停用、库存行缺失、仓库停用均需要明确错误，不在调整时隐式创建库存行。

### 2.2 两种录入方式

**SET_AVAILABLE：调整可售数量（首版建议）。** 操作者明确填写“此仓此 SKU 允许销售的目标量”，新 A=target_available，R/C/B/S 不变。允许 A 小于 R，因为 A 与 R 是互斥的库存部分，而非包含关系。该动作必须有原因和差额确认，不能把盘点总数直接填进可售量。

**PHYSICAL_COUNT：盘点实物总量（依赖满足后开放）。** 只有盘点范围能完整区分可售、临时预占、已下单未出库、残次冻结，且各部分互斥时，才可使用：

```text
目标可售量 A_new = 盘点实物量 P − 临时预占 R − 已提交未出库 C − 不可售冻结 B
约束：P >= R + C + B；所有数值已知且来自同一有效快照
```

当前 commit_reservation 会将 reserved 转出，因此 `P − reserved_qty` 不一定等于可售库存。对缺少订单分配/出库或残次覆盖的历史 SKU，PHYSICAL_COUNT 必须返回 PHYSICAL_COUNT_UNSUPPORTED，而不是把缺失的 C/B 当零。若商家需要全仓真实盘点，先补库存账本、单据和盘点期间变动处理。

物理盘点还需要 counted_at、计数开始/截止范围和出入库冻结或变动对账。version 只能阻止“预览后”的变化，不能修复“开始盘点到形成预览前”已经发生的移动；无有效盘点会话/冻结证明时不开放该模式。首版 SET_AVAILABLE 不伪称实物盘点。

模拟例：A=8、R=2、C=4、B=1，实物 P=20，则目标 A=13、差额 +5；仅算 20−2 会错误得到 18。若 P=6，小于 2+4+1，拒绝；若 C 未知，不能得出 A。另一个可售调整例中 target_available=0、R=2 是合法数量关系，不应套用 P>=R 的实物约束。

### 2.3 单仓与跨仓

一次批次绑定一个已授权 warehouse_id；每个 SKU 仅一行。多仓汇总只读，必须选择具体仓再编辑。首版不把“总量设为 100”自动分配到多个仓；跨仓调拨另有出入库一致性需求，不纳入本契约。

前端可以跨页选择明确 SKU ID，但提交最多 50 行（建议上限，以 capability 为准）。超过时提示分批，不自动把未知全量选择拆成后台写任务；“选择全部筛选结果”必须先得到服务端范围快照和明确数量。当前只加载部分商品时不得声称已选全店。

## 3. 并发、幂等与批量事务

### 3.1 原子单行契约

库存调整的业务原子单位是一个 `(merchant_id, warehouse_id, sku)`。按已认证商家查询并锁行后检查版本、权限、仓库/SKU 状态、动作参数和数量约束；在同一事务内完成：数量更新、V+1、成功审计事件、幂等项结果。任一步失败则该行全部回滚。

建议的条件更新形状如下，仅表示设计，参数必须绑定：

```sql
UPDATE m_inventory
SET available_qty = :target_available,
    version = version + 1,
    updated_at = :server_now
WHERE merchant_id = :authenticated_merchant
  AND warehouse_id = :warehouse
  AND sku = :sku
  AND version = :expected_version;
```

零行更新不能回退为无条件 UPDATE，应在授权范围内区分不存在、版本冲突。preview 不持有数据库长锁；commit 重新验证。不能把客户端上报 before 值当作审计事实。

版本必须覆盖预占、提交、释放/过期释放、取消恢复、退货入库、手工调整，以及盘点公式依赖的占用/冻结变化。已下单未出库量因发货改变时也必须使相关盘点快照失效。若同一 SKU 的占用存于多表，需要相同锁顺序和统一版本/快照机制；单独新增一个 version 列而不改其他写路径不够。

### 3.2 与现有交易原子性的关系

现有 MerchantWriteRepository 规定订单/预占操作全有或全无，这一规则保留。新增批量库存服务只是协调多个独立的单行调整，不调用“部分成功的下单/预占”。不把原 reserve/commit/release 行为改成部分成功，也不复用 create_order 作为库存调整入口。

批次中的 A 行可以成功、B 行失败，但每行内部不能出现“库存已改、审计未落”或“结果返回成功、幂等未保存”。已成功的 A 不因 B 失败自动回滚。批次级错误（身份/权限、非法结构、重复 SKU、超上限、预览失效）发生在任何库存行执行前时，整批不执行。

执行中途租户权限撤销则停止尚未开始的行，并标明 ABORTED_AUTH；已提交行保留。不能把后续失败响应描述为整批从未发生。身份被撤销后查询批次不得泄漏结果，由有权限管理员复核。

### 3.3 幂等与恢复

- commit 必填 client_request_id，服务端生成 batch_id；幂等作用域建议为 merchant + actor + operation + client_request_id。相同键、相同规范化参数返回同一批次；相同键不同仓/模式/项目/预览版本返回 IDEMPOTENCY_CONFLICT。
- 重放先鉴权并查已有幂等记录；已受理批次即使原 preview 已到期也返回原结果，不重新执行。只有创建新批次时校验预览仍有效。
- 每项 item_id 在批次内唯一，持久化 `(batch_id,item_id)` 状态与内容摘要。执行成功行重放不会重复修改版本、数量或审计；失败行重放也返回原失败，不悄悄重试。
- 幂等查询前仍检查当前权限。重试不能靠更换请求 ID 绕过已执行状态；客户端超时先查 batch，不把超时当失败。
- 批次可持久化后异步推进；状态 QUEUED/RUNNING/SUCCEEDED/PARTIAL_SUCCESS/FAILED/ABORTED。进程崩溃后只恢复未终结行，需租约/执行令牌防止两个 worker 重复执行。
- 行事务把库存、审计和终态结果一起提交，所以“已改库存但没有成功结果”的窗口不能存在。批次汇总可由持久化行结果重算；只有所有行终结才能显示最终完成。
- 重试失败项必须先重新读取和预览，使用新批次和新的 request_id，只携带用户选中的失败项；成功项不自动加入。
- 幂等重放保留期待确认。到期后旧键不能被静默当新请求再次执行；可保留不可重用的键摘要/墓碑并返回 REQUEST_EXPIRED，要求用户先核对历史再新建操作。

## 4. 库存 API 提议与示例

以下均为拟新增接口，不是当前已存在能力；JSON 值均为模拟样例。

| 方法/路径 | 用途 | 核心约束 |
| --- | --- | --- |
| GET /api/b/inventory/capabilities | 返回允许模式、max_items、数量上限、仓库范围和审计能力 | 服务端根据当前成员计算，不能由前端写入 |
| GET /api/b/inventory/snapshots | 查询指定仓/SKU 的数量、版本和模型覆盖情况 | 显式 SKU、数量上限、商家隔离；不猜未知数量 |
| POST /api/b/inventory/adjustment-previews | 校验目标，产生不可变预览 | 返回每行 before/after/delta/errors、preview_id、expires_at；不改库存 |
| POST /api/b/inventory/adjustment-batches | 确认预览中的有效行并提交 | client_request_id、preview_id、明确 item_ids、confirmed_partial；不能改写预览内容 |
| GET /api/b/inventory/adjustment-batches/{id} | 查处理结果、超时恢复 | 按商家与能力读取逐行状态及计数 |
| GET /api/b/inventory/adjustment-batches/{id}/results | 分页结果/可下载失败清单 | 受控字段；文件不是公开永久链接；不含凭据 |

### 4.1 预览请求与结果

```json
{
  "warehouse_id": "DEMO-WH-1",
  "mode": "SET_AVAILABLE",
  "reason_code": "MANUAL_RECONCILIATION",
  "reason": "模拟样例：核对可售量后调整",
  "items": [
    {"item_id":"demo-i1","sku":"DEMO-SKU-A","expected_version":7,"target_available":13},
    {"item_id":"demo-i2","sku":"DEMO-SKU-B","expected_version":4,"target_available":0}
  ]
}
```

服务端从会话推导 merchant 和 actor，不接受客户端声称的角色、before 数量、模拟/真实模式、审计操作者。新增 DTO 对这些敏感额外字段显式拒绝，不静默相信。预览中绑定规范化参数与主体；用户改变任一目标、原因、模式、仓库或选择范围都重新预览。

```json
{
  "preview_id":"DEMO-PREVIEW-1",
  "simulation_mode":"SIMULATED",
  "expires_at":"2026-11-14T01:10:00Z",
  "max_items":50,
  "valid_count":2,
  "invalid_count":0,
  "items":[
    {"item_id":"demo-i1","sku":"DEMO-SKU-A","version":7,
     "before":{"available_qty":8,"reserved_qty":2,"safety_stock":3},
     "after":{"available_qty":13,"reserved_qty":2,"safety_stock":3},
     "delta_available":5,"status":"READY"},
    {"item_id":"demo-i2","sku":"DEMO-SKU-B","version":4,
     "before":{"available_qty":2,"reserved_qty":1,"safety_stock":2},
     "after":{"available_qty":0,"reserved_qty":1,"safety_stock":2},
     "delta_available":-2,"status":"READY"}
  ]
}
```

示例 expires_at 只表达结构，不宣称预览实际有效期。预览包含无效行时仍逐行列出原因，但默认禁止提交；用户可明确“仅提交所列有效行”，提交精确 item_ids 并令 confirmed_partial=true。不得静默丢弃错误行。提交后的并发部分失败与预览时筛掉无效行是两件事，界面分别解释。

### 4.2 提交与部分失败

```json
{
  "client_request_id":"DEMO-REQUEST-1",
  "preview_id":"DEMO-PREVIEW-1",
  "item_ids":["demo-i1","demo-i2"],
  "confirmed_partial":false
}
```

建议受理返回 HTTP 202 与 batch_id/status_url。批次查询 HTTP 200 返回业务状态，不能只以 HTTP 成功表示全部 SKU 成功。以下示例中 A 成功，B 因预览后库存变化而失败：

```json
{
  "batch_id":"DEMO-BATCH-1",
  "client_request_id":"DEMO-REQUEST-1",
  "status":"PARTIAL_SUCCESS",
  "total":2,"succeeded":1,"failed":1,"pending":0,"unchanged":0,
  "items":[
    {"item_id":"demo-i1","sku":"DEMO-SKU-A","warehouse_id":"DEMO-WH-1",
     "status":"SUCCEEDED","before_version":7,"after_version":8,
     "before_available":8,"after_available":13,"delta_available":5,
     "audit_event_id":"DEMO-AUDIT-I1"},
    {"item_id":"demo-i2","sku":"DEMO-SKU-B","warehouse_id":"DEMO-WH-1",
     "status":"FAILED","error":{"code":"VERSION_CONFLICT","message":"库存已变化，请重新预览"},
     "expected_version":4,"current_version":5}
  ]
}
```

未变化行可返回 UNCHANGED，不改数量/版本，不伪造库存变更事件，但保留操作结果记录；计数恒满足 total=succeeded+failed+pending+unchanged。逐行失败包含结构化 code、字段或约束信息；只有已授权对象才返回 current_version/当前数量。

### 4.3 错误分类

| 错误码 | 响应范围 | 行为 |
| --- | --- | --- |
| UNAUTHENTICATED / FORBIDDEN | HTTP 401/403 | 不接受新批次，不泄漏对象；中途撤权见 §3 |
| INVALID_REQUEST / DUPLICATE_SKU / BATCH_LIMIT_EXCEEDED | HTTP 422 | 非法顶层结构、重复 SKU、超批量上限整批不执行 |
| INVALID_QUANTITY / PHYSICAL_COUNT_UNSUPPORTED / COUNT_BELOW_COMMITTED | 预览逐行错误；提交时仍复核 | 不写该行；明确字段与原因；后者包括 R+C+B 保护约束 |
| NOT_FOUND | 单行或资源 HTTP 404 | 未知和其他租户对象同样处理，不暴露他人数量 |
| VERSION_CONFLICT / IDEMPOTENCY_CONFLICT / PREVIEW_EXPIRED | HTTP 409 或已受理批次逐行错误 | 不无条件覆盖；不得把并发冲突自动当作可重试写 |
| REQUEST_EXPIRED | HTTP 409 | 旧幂等键不可重用；先查历史 |
| AUDIT_UNAVAILABLE / STORAGE_FAILURE | 批次逐行失败或 HTTP 503 | 同行事务回滚；先查询结果再决定重试 |
| RATE_LIMITED | HTTP 429 | 返回重试信息；不会因此生成第二份批次 |

外层错误统一 `{error:{code,message,request_id,details}}`。逐行结果按 code 处理，不用中文错误字符串判断。错误原因不包含 SQL、连接信息、令牌或其他租户对象细节。

## 5. 支付与完成语义

### 5.1 可信模式与字段

| 字段 | 设计含义 | 当前/新增 |
| --- | --- | --- |
| transaction_mode | SIMULATED / REAL / LEGACY_UNKNOWN，不允许普通前端改变 | 新增，可信服务端来源决定 |
| is_simulated | 由模式派生：SIMULATED=true，REAL=false，未知=null | 新增；不使用“缺失=false”默认值 |
| payment_method | SIMULATED 或未来经确认的 ONLINE/OFFLINE 等方式 | 新增枚举待定；方法与事实来源分离 |
| payment_source | MERCHANT_SIMULATION / VERIFIED_CALLBACK / VERIFIED_OFFLINE_RECORD 等 | 新增；由授权事件类型决定，不是自由文本 |
| paid_at | 首次有效支付/模拟支付发生时间 | 已有，重放不得改写；模拟模式不表示实际收款 |
| completion_source | MERCHANT_SIMULATION / BUYER_CONFIRM / AUTO_CONFIRM 等 | 新增；来源必须满足相应证据和权限 |
| completed_at | 首次有效完成事件时间 | 已有；作为完成归属依据，退款不得删除 |
| order_version | 订单状态/金额/来源等关键变更版本 | 新增，所有相关写路径统一维护 |
| source_event_id / action_id | 关联外部可信事件或内部模拟动作 | 新增去重引用，不保存密钥/原始签名 |

模式建议由创建渠道和部署边界确定，并在订单存续期不可随意切换。旧订单仅在可信导入批次/环境证据足够时回填 SIMULATED；其余 LEGACY_UNKNOWN，相关写操作受限，报告显示未分类数据质量项。新真实模式不能通过把旧模拟订单的 is_simulated 改成 false 得到。

模拟支付只允许 CREATED→PAID，模拟完成只允许 SHIPPED→COMPLETED；原因、操作人和前后状态必须记录。当前前端已有确认，但服务端仍需独立检查模式、状态、版本、金额币种及权限。审计中的“模拟支付”明确无资金结算。

模拟不等于只改前端样例：动作会持久改变业务库中的订单状态和时间，并影响后续取消、退款、库存恢复等流程的条件。界面可以说明“不产生真实资金”，不能笼统承诺“不写业务数据/不影响库存流程”。离线设计原型的内存演练与接入服务器的模拟交易须明确区分。

### 5.2 提议的动作接口

新增 `POST /api/b/orders/{id}/simulation-actions`，不混入真实支付回调；动作枚举 SIMULATE_PAYMENT、SIMULATE_COMPLETION。请求示例：

```json
{
  "client_request_id":"DEMO-COMPLETE-1",
  "action":"SIMULATE_COMPLETION",
  "expected_version":12,
  "expected_status":"SHIPPED",
  "expected_amount":"298.00",
  "expected_currency":"CNY",
  "reason":"模拟样例：验证完成状态与审计"
}
```

expected_amount/currency 用于确认对象一致，不能改订单金额；金额为十进制字符串，服务端按既有金额精度校验。请求不接受 paid_at/completed_at、actor、source、is_simulated 等可信字段。服务器生成时间和来源，动作、状态更新、审计、幂等响应在一个事务中提交。

```json
{
  "action_id":"DEMO-ACTION-1",
  "order_id":"DEMO-ORDER-1",
  "is_simulated":true,
  "transaction_mode":"SIMULATED",
  "before_status":"SHIPPED",
  "after_status":"COMPLETED",
  "order_version":13,
  "completion_source":"MERCHANT_SIMULATION",
  "completed_at":"2026-11-14T01:00:00Z",
  "audit_event_id":"DEMO-AUDIT-O1",
  "idempotent_replay":false
}
```

同键同参数重放返回原 action/event/time；同键不同参数返回冲突。不同键请求已达目标状态时，返回 ALREADY_APPLIED 并指向允许查看的原事件，不能追加第二次完成事件。历史目标状态没有可信事件时返回 LEGACY_STATE_UNVERIFIED，不伪造原操作人。

另需 `GET /api/b/order-actions/by-request/{request_id}` 查回超时结果，以及受控订单审计读取接口。未认证或权限撤销时不能通过该接口枚举结果。错模式返回 MODE_MISMATCH，错误前置状态 STATE_CONFLICT，版本不符 VERSION_CONFLICT，确认金额变化 CONFIRMATION_MISMATCH。

旧 `PATCH /api/b/workbench/orders/{id}/status` 的 PAID/COMPLETED 必须迁移到相同服务端动作处理器或在切换后拒绝无新契约的写请求；仅新增安全入口而保留可绕过的旧入口不成立。SHIPPED/CANCELLED 保持原语义，但也需纳入统一审计/版本覆盖计划。不得在本轮设计中擅自移除现有发货、取消、退款能力。

### 5.3 未来真实模式（依赖规划，不实施）

| 场景 | 可信事实来源 | 权限/证据 | 与模拟模式差异 |
| --- | --- | --- | --- |
| 在线支付 | 验证后的支付服务事件 | 签名验证、商家绑定、事件唯一性、金额币种核对；独立服务身份 | 普通客服/店主按钮不能冒充回调写 PAID |
| 线下收款登记 | 独立人工收款记录 | 专门能力、凭证引用与确认；不称平台在线到账 | 与模拟演练分开操作、审计和报告 |
| 顾客确认完成 | 已验证的该订单顾客动作 | 买家身份、履约前置条件、幂等事件 | B 端不能伪造 BUYER_CONFIRM |
| 自动完成 | 确认后的时效策略与系统任务 | 可审计策略版本、履约证据、任务身份 | 不是客户端填日期或通用状态 PATCH |

真实支付方式、事件协议、退款能力和订单状态拆分需要独立设计/授权和测试，本文不声称已接入。未来若支持支付、履约、售后多维状态，须保持兼容和迁移契约，不能直接用一个 status 解决所有语义。

退款冲减/跨月归属沿用 [完成口径报告 §5](./b-end-2.0-customer-service-report.md)：保留原 completed_at 和完成金额，退款作为独立有效事件；本期退款发生视角与完成订单群净额分开，仍待产品确认。退款不得变成“回滚完成订单”。退货入库与退款是独立事件，不能同时把库存重复加回或把退款重复扣减。

## 6. 权限、租户与审计

现有 owner/admin/staff 与页面店主/客服/仓库视角不同。建议新增能力：inventory.adjust_available、inventory.stocktake、inventory.change_safety、orders.simulate_payment、orders.simulate_completion、inventory.audit_view、orders.audit_view；名称为提议，不能因为选择“仓库视角”就授予写权限。默认映射由管理员/产品确认，未确认前保持关闭。

商家从可信登录成员关系推导，所有 preview、commit、结果查回、审计和文件下载均检查商家、仓库、对象及能力。前端 merchant_id 只可作为上下文一致性校验，不能决定访问范围。查询/更新同时绑定商家与对象键，即使当前数据库键可能全局唯一也不能省略租户条件。未知和跨租户对象同样返回不存在。

### 6.1 成功事件字段（拟新增）

| 字段组 | 必需信息 |
| --- | --- |
| 标识 | event_id、schema_version、merchant_id、resource_type/id、warehouse_id/sku 或 order_id |
| 操作者 | actor_type=human/system/migration、actor_id、当时有效能力/角色快照、认证主体来源 |
| 动作关联 | action_type、batch_id/item_id、request_id、idempotency_key 的安全摘要、parent/corrects_event_id |
| 业务事实 | 服务器读取的 before/after、before_version/after_version、数量差额或金额币种、交易模式、支付/完成来源 |
| 时间 | effective_at（业务生效）、recorded_at（审计入库）；模拟动作均取服务器时间，旧数据来源说明另列 |
| 理由与证据 | reason_code、受限长度 reason、可信 source_event_id/单据引用，不存 cookie/token/签名原文 |
| 结果 | SUCCEEDED/UNCHANGED/REJECTED/FAILED 的明确语义；成功业务事件与失败尝试日志区分 |

成功审计与业务变更同库事务提交。失败尝试可以写独立受控日志，但必须标“未产生业务变更”；审计不可用时不得放行成功写入。限制普通业务账号 UPDATE/DELETE 审计记录；更正通过新事件关联旧事件，不覆盖历史。链式校验/外部归档可后续选型，不能因为写了 hash 字段就宣称不可篡改。

审计查询建议 `GET /api/b/audit/business-events`，支持资源、动作、时间、批次、操作者过滤与分页；租户和字段权限由服务端限定。保留期、下载权限及脱敏策略待确认。无需记录整份顾客档案、完整聊天或无关地址。

## 7. 预览、提交与失败 UI

保持已完成商品/SKU 表和订单详情结构，只在选择栏增加受 capability 控制的“调整可售量”入口。选择具体仓库后打开桌面侧面板，手机使用全屏面板；延续 18px 正文、最低 16px 辅助文字和灰青风格。

| 状态 | 展示 | 可执行动作 |
| --- | --- | --- |
| 未接入/无权限 | 明确不可用原因；无伪造保存成功 | 查看字段说明，返回原表 |
| 编辑中 | SKU、仓库、当前可售/预占/阈值、目标可售量、理由 | 输入/删除行；不允许编辑 reserved |
| 预览中 | 保留输入，校验进度；提交禁用 | 返回编辑；旧请求不能覆盖新输入 |
| 预览有效 | 每行 before/after/delta、版本、影响总行数、有效期 | 二次确认精确范围；展示“执行时仍可能因并发部分失败” |
| 预览有错 | 错误就近显示，默认不提交 | 修正并重新预览，或明确选择仅有效行 |
| 提交中 | batch_id、已完成/失败/待处理数；防重复按钮 | 查询进度；离开页前提示批次仍在执行，不承诺取消 |
| 成功/部分失败 | 逐 SKU 成功、失败原因和审计入口；显示“成功1，失败1” | 下载结果、仅失败项重新预览；不对成功项再提交 |
| 超时/连接断开 | “提交结果待确认”，保留 request_id | 查回结果，不自动生成新请求 |
| 权限撤销/版本冲突 | 清理不可见内容，或展示允许查看的新版本 | 重新授权/读取，原确认失效 |

关闭面板不回滚已提交库存；成功项回到表格后重新读取服务端数量，不用整批输入覆盖表格。失败清单可以导出 SKU/仓库/item_id/code/原因，处理 CSV 公式注入；不把错误 SQL、敏感身份或跨租户对象写入文件。

订单模拟动作确认框继续展示店铺、订单、模拟金额、原状态、目标状态与“无真实资金”。补充显示服务端权限、版本变化、完成时间由服务器记录；确认后等成功响应再更新状态。无法得到审计结果时不能仅弹“成功”。

## 8. 迁移、发布与回滚方案

本节是未来实施计划，本轮不运行迁移。

1. **扩展结构，功能关闭。** 增加库存/订单版本、可信模式/来源、批次与逐行幂等结果、业务审计。新字段允许迁移阶段显式 UNKNOWN；原金额/时间不覆盖。备份并验证恢复流程，记录迁移版本与行数。
2. **覆盖所有写路径。** PG 与 SQLite（或明确仅支持的后端）共用契约；预占、释放、提交、取消、退货、发货相关占用、状态推进和维护脚本都递增适当版本。确认没有旧服务实例仍写而不维护版本。数据库触发器或统一写服务可选，但需一致验证。
3. **回填来源与基线。** 仅依据可证明的部署/导入来源判定模拟模式；未知保持 UNKNOWN。迁移事件记录 MIGRATION_BASELINE 和 migration actor，不假称原支付/完成操作者。保留已有 paid_at/completed_at；历史缺失不拿创建时间填充。
4. **双读核对。** 验证新旧数量一致、预占守恒、金额时间保持、状态计数一致、租户隔离；只读 preview 不执行库存写。审计/幂等不可用时关闭提交。
5. **收口旧入口后开放。** 新旧订单状态入口走同一授权/审计处理器，或旧入口明确拒绝新动作；分批开放可售调整和模拟动作。PHYSICAL_COUNT 在完整库存分类及盘点冻结/对账契约满足前保持禁用。
6. **故障回滚。** 先关新写入口、停止接受新批次，等待/中止未开始行并记录已执行范围；保留审计和结果表。回滚到仍能维护版本且识别模拟模式的兼容版本，不直接回退到任意旧二进制。存在运行中批次时先恢复确定状态再切换。

业务数据回滚不能简单把 before 数量覆盖回去：期间可能发生新销售或预占。需要有权限的纠正操作，读取当前版本、计算可解释差额、重新预览确认，产生新审计事件关联原 event；无法安全纠正就人工核对。数据库备份恢复只用于明确的灾难恢复，不作为撤销单条库存操作手段。

模拟 PAID/COMPLETED 也不提供通用“退回上一状态”按钮。误操作通过另立的纠正流程处理，不删除完成事件或改写 paid_at；未来真实支付更不能用数据库状态回滚代替渠道退款。

## 9. 测试、Eval 与验收要求

以下是实施后的要求，**不是本轮已经通过的系统测试**。

| 编号 | 场景 | 必须验证 |
| --- | --- | --- |
| INV01 | A/R/S 正常、0、小数/布尔/溢出/负数 | 严格类型；可售0且预占2合法；安全阈值不充当库存 |
| INV02 | 实物20、R2/C4/B1；实物6；C未知 | 分别得到可售13、拒绝、拒绝；盘点期间移动也使会话失效 |
| INV03 | 同 SKU 不同仓、跨商家 SKU、缺库存行 | 不改错仓，不泄漏他人数量，不隐式建行 |
| INV04 | 预览后发生预占/释放/下单/发货/取消/入库 | 相关版本或盘点快照变化，陈旧提交拒绝；所有写路径有覆盖 |
| INV05 | 两个操作者并发设相同 SKU | 仅当前版本者成功，不丢失更新、不越过预占约束 |
| INV06 | 两行一成功一冲突，审计写失败 | 正确部分结果；冲突行不变；审计失败行数量/版本/幂等一起回滚 |
| INV07 | 相同 request 重放、换内容重放、失败项重试 | 不重复加库存/审计；换内容冲突；仅新预览失败项可进入新批次 |
| INV08 | 行事务提交后进程崩溃、worker租约竞争 | 成功行不会再执行；批次结果可恢复；计数守恒 |
| INV09 | 50行边界、51行、重复SKU、预览过期 | 按实际 capability 上限；非法批次在写前拒绝；无静默丢行 |
| INV10 | 修改阈值、跨仓调拨或清锁请求 | 不借用可售调整绕过独立契约 |
| ORD01 | 模拟支付/完成正常与非法前置状态 | 模式/权限/版本/确认金额全检；服务端写来源时间 |
| ORD02 | 同键重放、不同键同目标、超时查回 | 一次业务事件；原 paid_at/completed_at 不漂移 |
| ORD03 | 客户端伪造 source/actor/is_simulated/时间 | 拒绝；未知历史不能冒充真实支付 |
| ORD04 | 从旧PATCH调用、无权限角色或其他租户访问 | 与新入口同等约束；直接URL不能绕过 |
| ORD05 | 已完成后退款、退货入库、跨月 | 原完成时间保留；退款与入库各一次；不把退款等同状态回滚 |
| AUD01 | 事务故障、审计不可用、结果丢失 | 成功审计与业务原子一致，失败尝试不冒充成功 |
| AUD02 | 审计查看/导出、过期请求、权限撤销 | 重新验权、字段脱敏、旧键不重用、结果不泄漏 |
| MIG01 | 旧数据回填、旧服务混跑、代码回滚 | 来源未知不猜测；版本无漏写；兼容回滚且审计保留 |
| UI01 | 桌面/390手机、空/错/加载/部分失败/超时 | 按 §7 明确状态，操作区可见，返回保留上下文，无假成功 |

实施时扩展 [商家写入测试](../../tests/test_merchant_write.py)、[PG 契约测试](../../tests/test_merchant_postgres.py)、[B API 测试](../../tests/test_b_workbench_api.py)及 SQLite/PG 共用参数化契约；必要时新增专门批次/审计测试。订单、预占旧回归必须继续通过，不把新批次部分成功语义带入原订单事务。

如果未来通过 Agent Tool 发起调整，只允许生成待确认草稿；确定性服务执行最终写入。新增/修改 Tool 时同步 Tool Contract 和 Eval，覆盖“忽略锁定量”“切换为他人商家”“伪称主人批准”“让模型直接写SQL”“重复提交”“无证据标真实收款”等诱导场景，预期拒绝越权或要求确认。Agent 核心变化按 AGENTS.md 跑 pytest + Regression Eval，必要时 Benchmark；纯 HTTP 契约变更是否影响 Agent 也需记录评估。

## 10. 需要评审的决策与本轮验证

| 待确认决策 | 本稿建议 | 未确认时 |
| --- | --- | --- |
| 库存首版模式 | 单仓 SET_AVAILABLE，每批至多50 SKU，精确预览/确认 | 接口保持提议；实物盘点不假装已有能力 |
| 物理数量覆盖 | R/C/B 分类完整且有盘点会话/变动控制 | PHYSICAL_COUNT 禁用 |
| 能力映射 | 库存、模拟支付、模拟完成、审计分别授权 | 前端业务视角不直接放权 |
| 部分失败策略 | 单行原子，批次允许部分成功并持久化结果 | 不修改既有订单/预占全有或全无语义 |
| 模式迁移 | 可信证据回填，未知显式保留 | 不把空值改为真实交易 |
| 保留与导出 | 审计/幂等按确定策略保存，结果下载重新验权 | 不编造已经确定的天数或公开链接 |

本轮仅做源码与文档静态核对、引用和 JSON 示例结构检查、数量及批次计数算例核算、变更范围检查。未运行生产测试/Eval、数据库迁移、真实支付、库存写入或浏览器验收；没有可运行的新接口可供此轮验证。上述验收清单供实现阶段使用。
