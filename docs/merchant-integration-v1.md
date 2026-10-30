# 商家数据层 v1（商品 / SKU / 库存 / 订单）

> 状态：v1 已实现并通过单测（离线 SQLite + 种子数据）。
> 定位：**可替换的商家数据层（Merchant Repository），不是真实 OMS 对接。**
> 生产接入真实商家系统时，必须实现 `MerchantRepository` 协议并注册新的 adapter（见第 7 节）。

## 1. 为什么先做独立数据层

B 端下一步需要「真实商家的商品 / 库存 / 订单」来做经营分析与导购；直接把这些查询写进
Agent / API 会有三个问题：

1. **数据源未定**：现在没有真实 OMS，先把数据访问抽象成 Repository，
   以后接 OMS / PostgreSQL 只换 adapter，不动业务层；
2. **租户安全**：商家数据必须按 `merchant_id` 隔离。把「按租户过滤」收敛在数据层一处，
   比在每个调用点记得加 `WHERE merchant_id = ?` 可靠；
3. **可测试**：用确定性种子数据（CSV）+ 离线 SQLite，不依赖模型、不依赖网络、不依赖 PG，
   单测可在 2 秒内跑完，且**金额/引用完整性可以逐分核对**。

v1 的查询路径是**只读**；v1.1（task-43）在 SQLite adapter 内追加了**本地库存预占/订单写入**
（reserve/commit/release/create_order，事务化 + 幂等 + 失败关闭，见 §10），但它仍
**不是真实 OMS 写通道**：没有支付/对账/商家鉴权，也尚未接入 API / Agent 的交易链路。
真实交易写必须在接 OMS 时按「人工确认 + 独立写通道」再设计，不能由 Agent 直接写库。

## 2. 模块结构

```text
src/rag_demo/merchant/
├── __init__.py            对外导出（get_merchant_repository / get_merchant_write_repository…）
├── models.py              frozen dataclass：Product / SKU / Inventory / Reservation / Order…
├── limits.py              limit 钳制纯函数（DEFAULT=20, MAX=100）
├── errors.py              结构化错误（稳定 code：CONFIG / SEED / DATA / STOCK / CONFLICT…）
├── repository.py          MerchantRepository（只读）+ MerchantWriteRepository（写）协议
├── seeds.py               data/merchant/*.csv 读取 + 校验 + 规模下限
├── sqlite_repository.py   默认 SQLite 实现（只读查询 + 事务化库存预占/订单写入）
└── factory.py             后端注册 / 选择 / 进程内缓存 / 写能力检查
data/merchant/
├── products.csv  skus.csv  inventory.csv  orders.csv  order_items.csv
```

## 3. 快速使用

```python
from rag_demo.merchant import get_merchant_repository

repo = get_merchant_repository()          # 默认 SQLite；首次访问自动建库 + 灌种子
products = repo.list_products("m_tea_001", keyword="龙井", limit=10)
sku = repo.get_product_sku("SKU-TEA-001-250G", merchant_id="m_tea_001")
inventory = repo.get_inventory("SKU-GEAR-002-PRO")
orders = repo.list_orders("m_tea_001", buyer_id="b_1001", status="PAID", limit=20)
order = repo.get_order("ORD-20261001-0001", merchant_id="m_tea_001")

print(products[0].title, products[0].status)
print(sku.price)                 # Decimal('298.00')，不是 float
print(inventory.available_qty, inventory.in_stock)   # 0 False（无库存 ≠ 不存在）
print(order.total_amount, order.item_count)
```

## 4. 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `QIANKE_MERCHANT_DB` | `<仓库根>/var/merchant_v1.sqlite` | SQLite 文件位置；`var/` 已被 `.gitignore` 忽略 |
| `QIANKE_MERCHANT_BACKEND` | `sqlite` | 默认后端名；接真实 OMS 时改为注册过的名字 |
| `QIANKE_MERCHANT_SEED_DIR` | `<仓库根>/data/merchant` | 种子目录（测试/临时环境可覆盖） |

> 种子数据属于「数据」：商品数量、库存记录数、订单数都来自 CSV，业务代码里没有写死。
> 代码只强制**验收下限**：≥8 商品、≥20 条库存记录、≥5 订单（见 `seeds.py` 常量）。

## 5. 接口契约（只读 `MerchantRepository`）

| 方法 | 语义 | 租户/边界 |
| --- | --- | --- |
| `list_products(merchant_id, keyword=None, limit=20)` | 按商家列商品；keyword 对标题/类目/品牌做大小写不敏感子串匹配，按 `product_id` 升序 | `merchant_id` **必填**，空值抛 `MerchantDataError`（失败关闭，禁止全表读） |
| `get_product_sku(sku, *, merchant_id=None)` | 按 SKU 取规格与价格 | 传 `merchant_id` 时不匹配返回 `None` |
| `list_product_skus(product_id, *, merchant_id=None)` | 商品下全部 SKU（商品页） | 同上 |
| `get_inventory(sku, *, merchant_id=None)` | 跨仓库存汇总：`available_qty / reserved_qty / safety_stock / in_stock / warehouses[]` | 无记录返回 `None`；有记录但可售 0 返回对象且 `in_stock=False` |
| `list_orders(merchant_id, buyer_id=None, status=None, limit=20)` | 按商家列订单（含订单行快照），按 `created_at` 倒序 | `merchant_id` 必填；`status` 大小写不敏感 |
| `get_order(order_id, *, merchant_id=None, buyer_id=None)` | 按订单号取订单 | 作用域不匹配返回 `None` |
| `describe()` / `close()` | 后端自描述 / 释放资源 | `close()` 后再查询抛 `MerchantUnavailableError` |

**limit 钳制**：所有列表方法内部走 `clamp_limit` —— `None`→默认 20，`<=0`→1，
`>100`→100，非法值→默认。目的是防止 LLM / 前端传 `limit=100000` 把大商家全表读进内存，
同时查询接口不因一个数字直接报错。

**金额**：模型里是 `Decimal`；`to_dict()` 输出十进制字符串（如 `"298.00"`），
跨 API / LLM 时不丢精度。adapter 不得用 float 中转。

**错误码**（结构化，调用方可分支）：

| code | 含义 |
| --- | --- |
| `MERCHANT_CONFIG` | 后端名未知 / 配置非法 / 该后端没有写能力 |
| `MERCHANT_SEED` | 种子文件缺失、列缺失、引用不一致、金额对不上、低于规模下限 |
| `MERCHANT_DATA` | 查询参数非法（如多租户查询缺 `merchant_id`） |
| `MERCHANT_UNAVAILABLE` | 数据层已关闭 / 文件不可读写 |
| `MERCHANT_INVALID` | 写请求参数非法（数量非正、SKU 重复、金额与订单行不一致…） |
| `MERCHANT_NOT_FOUND` | 写操作引用的对象不存在，或不属于当前租户（统一按不存在处理） |
| `MERCHANT_CONFLICT` | 幂等/状态冲突（同 id 不同 payload、已释放/已提交、order_id 被其他商家占用） |
| `MERCHANT_EXPIRED` | 预占已过期（提交时发现，库存已释放） |
| `MERCHANT_STOCK` | 库存不足（失败关闭，`to_dict()["details"]` 带 sku/requested/available） |
| `MERCHANT_INTERNAL` | 库存账实不一致等内部数据问题（需人工排查） |

## 6. 种子数据（`data/merchant/`）

当前种子（两个商家，用于租户隔离测试；**数量以 `load_seed_data().counts()` 为准**）：

- 商家：`m_tea_001`（山雾茶业）、`m_gear_002`（峰行户外，含与 C 端商城对齐的 P001–P006）；
- 18 个商品、30 个 SKU、34 条库存记录（含跨仓与 1 条零库存）、8 个订单、13 个订单行；
- 文件：`products.csv` / `skus.csv` / `inventory.csv` / `orders.csv` / `order_items.csv`，
  表头与字段含义见文件首行；金额为十进制字符串，时间为 ISO-8601 文本（`+08:00`）。
- `orders.csv` 自 v1.2 起带物流/生命周期列：`tracking_no / carrier / shipped_at / completed_at`；
  已有 SHIPPED / COMPLETED 订单已补齐物流单号、承运商与状态时间。新列是**可选列**，缺省空值
  兼容旧种子文件。

`seeds.load_seed_data()` 在入库前做完整性校验：

1. 主键唯一（product_id / sku / order_id；库存 (sku, warehouse_id) 唯一）；
2. 引用完整（SKU→商品、库存→SKU、订单行→SKU、订单行→订单），且**商家归属一致**；
3. 每个商品至少一个 SKU；
4. `订单总额 == Σ 行小计`，`行小计 == 数量 × 单价`（Decimal 精确比较）；
5. 状态/物流一致性：SHIPPED/COMPLETED 必须有 `tracking_no` 与 `shipped_at`；COMPLETED 还必须有
   `completed_at` 且不早于 `shipped_at`；物流单号全局唯一；时间列必须是合法 ISO-8601；
6. 规模下限（≥8/20/5）。

**重置**：SQLite adapter 提供 `repo.seed(force=True)`（清空 m_* 表后重灌，仅限本地调试；
不对外暴露 API）。正常启动是幂等的：库中已有商品时不重复插入。

## 7. 替换为真实 OMS / PostgreSQL（生产接入）

数据层通过 `MerchantRepository` 协议解耦，迁移步骤：

```python
from rag_demo.merchant import MerchantRepository, register_repository_backend


class OmsMerchantRepository:          # 真实 OMS / PG 适配器
    backend = "oms"

    def __init__(self, *, dsn: str):  # 从配置/密钥管理读连接信息
        self._dsn = dsn

    def describe(self) -> dict: ...
    def list_products(self, merchant_id, keyword=None, limit=20):
        # 关键：merchant_id 来自**已认证的会话/租户上下文**，绝不来自用户输入；
        #       limit 必须 clamp_limit；金额 Decimal；返回 models.Product
        ...
    # 其余方法与协议同名同签名


register_repository_backend("oms", lambda **_: OmsMerchantRepository(dsn=...))
repo = get_merchant_repository(backend="oms", seed=False)
```

适配器必须遵守的硬约束：

1. **租户隔离**：`merchant_id` 由调用方从登录态推导后传入；数据层空值失败关闭；
   OMS adapter 不能信任请求体里的商家 ID；
2. **只读与写能力分离**：查询实现 `MerchantRepository`；库存预占/订单写入实现
   `MerchantWriteRepository`（SQLite adapter 两者都实现）。真实 OMS 的写操作必须走 OMS 的
   受控接口 + 人工确认——**不要把 OMS 写权限给只读查询 adapter**；
3. **limit 钳制**：内部必须 `clamp_limit`，不能把调用方 limit 直接拼进 SQL；
4. **参数化查询**：禁止字符串拼 SQL（种子/搜索关键词都可能是外部输入）；
5. **金额 Decimal**、时间 ISO-8601、返回模型而不是裸 dict；
6. 连接/密钥从环境变量或密钥管理读取，不写进代码与文档。

接入 Agent / API（已落地）：

- 店宠 Agent `rag_demo.c_end.store_agent` 的商品/库存/订单工具已直接调用 `MerchantRepository`：
  - `search_catalog`：商品 + 首 SKU + 库存（P001–P006 与 C 端商城商品 ID 对齐）；
  - `search_inventory`：按 SKU 查询跨仓汇总库存；
  - `search_my_orders`：按当前买家映射查询真实商家订单，只返回自己的订单；
  - 工具结果带 `source=merchant_v1`，Agent 元数据写入 `product_refs` / `order_refs`。
- C 伙伴 Agent `rag_demo.c_end.agent` 也接入同一数据层：
  - `recommend_products`：商品 + 首 SKU + 库存 + 商家来源；
  - `query_my_orders`：当前买家自己的商家订单与物流状态，不能查其他买家；
  - 实测“查一下我的物流”已返回 `ORD-20261007-0007` / `ORD-20261004-0004`，不再回答“没有工具”。
- 买家映射：`buyer_1 → b_2001`、`buyer_2 → b_2002`（集中定义在 `store_agent.merchant_buyer_id`）。
- C 端只读 API：
  - `GET /api/c/merchant/products?keyword=&limit=`
  - `GET /api/c/merchant/inventory/{sku}`
  - `GET /api/c/merchant/orders?status=&limit=`
  - `GET /api/c/merchant/orders/{order_id}`
- 实测：店宠回答跑鞋时返回 `SKU-GEAR-P001-STD`、库存 20；物流问题返回 `ORD-20261007-0007` 等真实商家订单。
- **边界**：C 商城下单已通过 §10 写层完成「商家库存预占 → 商家订单写入 → 提交预占」（1.8.4）；
  订单状态流转（PAID/SHIPPED/COMPLETED）已由 §11 的 `update_order_status` 提供数据层能力，
  C 端订单时间线/物流展示由负责人接入；真实交易接入仍需 OMS 写通道 + 用户确认，见 §9/§11。

## 8. 测试

```bash
uv run python -m pytest tests/test_merchant_store.py tests/test_merchant_write.py -q
# 结果：101 passed（42 只读/种子用例 + 59 写接口/状态机用例；离线，约 10s）
```

覆盖：
- 只读/种子：规模下限与完整性、初始化幂等/force 重灌、env 路径覆盖、工厂缓存与重置、
  商品/SKU/库存/订单查询、**租户隔离**（跨商家、`get_*` 作用域、缺 `merchant_id` 失败关闭）、
  无库存 vs 不存在、limit 钳制（纯函数 + 查询路径）、可替换后端注册（Fake adapter）、
  坏种子（引用缺失/规模不足/目录不存在/物流字段缺失）结构化拒绝、关闭后不可用、
  种子 SHIPPED/COMPLETED 物流字段与 `Order.to_dict()` 生命周期字段；
- 写接口：reserve 成功/幂等/冲突/库存不足/参数非法/未知 SKU/过期、commit 幂等与库存口径、
  release 幂等与已提交拒绝、过期 commit/release 语义、**并发同 id 只扣一次**、
  **并发竞争不超卖**、create_order 幂等/金额不一致拒绝/租户隔离/促销价/来源引用、
  写操作 merchant_id 必填、写错误结构化；
- 订单状态机（task-45）：CREATED→PAID→SHIPPED→COMPLETED 全链路与时间字段、同状态幂等
  不重写时间戳、SHIPPED 必须带合法物流单号（格式规则）、非法迁移 `MERCHANT_CONFLICT`、
  取消规则（CREATED/PAID→CANCELLED，保留 paid_at）、跨租户 NotFound、并发同迁移幂等、
  物流字段只允许出现在 SHIPPED、状态更新不影响订单行/金额、老库自动迁移后状态机可用。
- 另：`tests/test_c_end_store_agent_merchant.py`、`tests/test_c_end_agent_merchant.py`
  覆盖 C 端只读接入（由对应改动方负责，本任务未修改）。

## 9. 已知限制（v1，明确不是真实 OMS）

1. **不是真实 OMS 对接**：没有商家侧鉴权/签名/支付/对账；种子是工作区里的静态样例数据；
2. **写通道仅本地 SQLite**：reserve/commit/release/create_order 事务化、幂等、失败关闭，
   但它是**本地演示/测试实现**，不是真实库存/交易系统；真实写必须接 OMS 受控接口 + 人工确认；
3. **无分页游标 / 时间范围过滤**：列表只有 limit + 买家/状态过滤；大商家需要补 offset/cursor；
4. **无价格历史 / 库存流水**：模型只有当前快照；经营分析若需要「改价/补货历史」要另建表；
5. **无多语言/多币种**：种子仅 CNY；模型保留了 currency 字段但无汇率逻辑；
6. **SQLite 单文件**：只适合开发/演示；并发写、备份、权限需由 PG adapter 承担
   （写事务用 `BEGIN IMMEDIATE` + 10s busy timeout，只保证**单机单写者**语义）；
7. **已接 API / Agent，但交易仍只读**：店宠与 C 端只读 API 已接；本地写层（§10）尚未接入
   下单接口/Agent 工具，C 商城仍用 `c_product/c_order`，商家库存只作参考；
8. **关键词搜索是 LIKE 子串**：不是全文检索；大语料应交给 PG/ES adapter 实现；
9. **预占过期是懒清理**：没有后台定时任务，过期库存在下一次 commit/release/reserve 时
   才释放；真实 OMS 应由其库存服务负责 TTL 回收；
10. **预占与订单未做强绑定**：`commit_reservation(order_id=...)` 只记录订单号，
    不强制该订单已存在（推荐顺序：reserve → create_order → commit；先 commit 后补订单也可，
    由调用方保证幂等与补偿）。

## 10. 写入能力（v1.1 / task-43：本地 SQLite 预占 + 订单写入）

> **定位不变：这不是真实 OMS 写通道。** 本节描述的是本地 SQLite adapter 的写接口契约，
> 用于在接真实 OMS 之前把「库存预占 / 订单写入」的语义、事务边界与幂等规则先固定下来。
> 真实交易写必须走 OMS 受控接口 + 人工确认，不能由 Agent 直接写库。

### 10.1 能力边界与取得方式

- 查询：`get_merchant_repository()` → `MerchantRepository`（只读协议）。
- 写：`get_merchant_write_repository()` → `MerchantWriteRepository`；
  只读 adapter 未实现写协议时，工厂直接抛 `MERCHANT_CONFIG`（而不是运行期才炸）。
- SQLite adapter 同时实现两个协议；`describe()["write_capable"] is True`，
  `describe()["reservations"]` 为当前预占记录数。

```python
from decimal import Decimal
from rag_demo.merchant import get_merchant_write_repository

writer = get_merchant_write_repository()

# 1) 预占（默认 15 分钟 TTL；库存不足抛 MERCHANT_STOCK，失败关闭）
held = writer.reserve_inventory(
    "m_tea_001",
    "RSV-20261030-0001",
    [{"sku": "SKU-TEA-001-250G", "quantity": 2}],
    ttl_seconds=900,
    buyer_id="b_1001",
)

# 2) 写订单（幂等：重复调用返回已有订单；不改库存）
order = writer.create_order(
    "m_tea_001", "ORD-20261030-0001", "b_1001",
    [{"sku": "SKU-TEA-001-250G", "quantity": 2}],
    Decimal("596.00"),
    source_ref="quote-42",
)

# 3) 提交预占（available 保持扣减，reserved 转出；重复提交幂等）
writer.commit_reservation("m_tea_001", held.reservation_id, order_id=order.order_id)
```

### 10.2 方法契约（`MerchantWriteRepository`）

| 方法 | 语义 | 失败/边界 |
| --- | --- | --- |
| `reserve_inventory(merchant_id, reservation_id, items, ttl_seconds=900, *, buyer_id=None)` | 按当前库存预占：`available_qty` 扣减、`reserved_qty` 增加；返回 `Reservation` | 库存不足 `MERCHANT_STOCK`；未知 SKU/商品 `MERCHANT_NOT_FOUND`；参数非法 `MERCHANT_INVALID`；同 id 不同 payload `MERCHANT_CONFLICT` |
| `commit_reservation(merchant_id, reservation_id, order_id=None)` | 预占转订单占用：available 保持扣减、reserved 转出；返回 `Reservation(status=COMMITTED)` | 未知/跨租户 `MERCHANT_NOT_FOUND`；已释放/已提交到其他订单 `MERCHANT_CONFLICT`；过期 `MERCHANT_EXPIRED`（库存已释放） |
| `release_reservation(merchant_id, reservation_id)` | 释放预占、恢复库存；返回 `Reservation(status=RELEASED/EXPIRED)` | 未知/跨租户 `MERCHANT_NOT_FOUND`；已提交 `MERCHANT_CONFLICT`；重复释放/过期释放幂等 |
| `create_order(merchant_id, order_id, buyer_id, items, total_amount, source_ref=None)` | 幂等写订单 + 行快照；**不改库存**；返回 `Order` | 金额不一致/参数非法 `MERCHANT_INVALID`；未知 SKU/商品 `MERCHANT_NOT_FOUND`；order_id 属其他商家 `MERCHANT_CONFLICT` |
| `update_order_status(merchant_id, order_id, status, tracking_no=None, carrier=None)` | 订单状态机流转（见 §11）：写状态时间与物流字段；返回 `Order` | 非法迁移 `MERCHANT_CONFLICT`；未知状态/物流字段非法 `MERCHANT_INVALID`；未知/跨租户 `MERCHANT_NOT_FOUND` |

### 10.3 状态机与库存账目口径

```text
reserve ──> RESERVED ──commit──> COMMITTED   (available 保持 -q，reserved 回到基线)
              │
              ├──release──> RELEASED         (available +q，reserved -q)
              └──expire───> EXPIRED          (库存释放；懒触发)
```

- 预占成功：`available_qty -= q`，`reserved_qty += q`；
- commit：**available 不再变化**（货已卖掉），`reserved_qty -= q`；
- release：`available_qty += q`，`reserved_qty -= q`（按预占时记录的**仓库扣减明细**
  精确恢复，不按当前库存重新猜）；
- 过期（TTL 默认 900s，上限 7 天）：在 commit/release/reserve 该 id 时懒检测；
  commit 过期预占会**先释放库存并标记 EXPIRED，再抛 `MERCHANT_EXPIRED`**；
  release 过期预占返回 `EXPIRED`（幂等，不重复恢复）；reserve 复用过期 id 会先恢复旧库存再新建；
- 终态 id（RELEASED / COMMITTED / EXPIRED）**不能复用**，需换新 `reservation_id`。

### 10.4 幂等 / 并发 / 安全规则

- **事务**：所有写走 `BEGIN IMMEDIATE`（SQLite 单写者），库存变动与预占/订单记录同事务提交；
  任何异常整体回滚，不留「扣了库存但没写预占」的中间态；
- **幂等**：同 `reservation_id` 同 payload → 返回已有预占，不重复扣；同 `order_id` →
  返回已有订单，不重复写（首写生效，后续不同 payload 也返回首次订单）；
- **并发**：同一预占 id 并发只扣一次；两个预占竞争同一库存时，因 `BEGIN IMMEDIATE` 串行化
  + 扣减守卫，**只有一个成功，另一个收到 `MERCHANT_STOCK`，不会超卖**；
- **租户必填**：四个写方法 `merchant_id` 均必填；空值抛 `MERCHANT_DATA`；其他租户的对象
  一律按「不存在」处理（不泄露存在性），order_id 跨商家冲突抛 `MERCHANT_CONFLICT`；
- **参数化 SQL**：全部写 SQL 使用占位符；金额 `Decimal` 精确比较（传 `total_amount` 不等于
  订单行合计直接拒绝，一行不写）；
- **items 规则**：每项至少 `sku` 或 `product_id` + 正整数 `quantity`（≤50 行）；
  同一 SKU 不得重复；`product_id` 仅在「该商品只有一个可售 SKU」时自动解析，多规格必须显式选 SKU；
  停用的商品/SKU 拒绝下单；`unit_price` 可覆盖（促销价），缺省用 SKU 当前价；
- **create_order 不改库存**：需要库存控制时先 reserve/commit；推荐顺序
  `reserve → create_order → commit`（先 commit 后补订单也可，但需调用方保证补偿/重试幂等）。

### 10.5 表结构 / 迁移

- 新增 `m_reservation`：`reservation_id / merchant_id / buyer_id / status / expires_at /
  items_json / created_at / updated_at / order_id`；`items_json` 同时保存请求行与
  `allocations`（实际扣减的仓库明细），释放/提交按它精确回滚；
- `m_order` 新增 `source_ref`（来源引用）与 v1.2 的 `tracking_no / carrier / shipped_at / completed_at`
  物流/生命周期列；全部允许 NULL（历史订单没有物流信息是正常状态）；
- **老库自动迁移**：初始化时用 `PRAGMA table_info` 检查并 `ALTER TABLE` 补列（幂等），
  v1/v1.1 的 `var/merchant_v1.sqlite` 不需要手工重建；
- `seed(force=True)` 会连同 `m_reservation` 一起重置（仅本地调试，不对外暴露）。

## 11. 订单状态机与物流字段（v1.2 / task-45）

> 仍然**不是真实 OMS 写通道**：状态流转是本地 SQLite 的确定性实现，用于在接 OMS 前
> 固定订单生命周期语义；真实支付回调/物流轨迹/退款售后必须由 OMS + 人工确认链路负责。

### 11.1 状态机

```text
CREATED ──PAID──> PAID ──SHIPPED──> SHIPPED ──COMPLETED──> COMPLETED
   │                │
   └──CANCELLED─────┴──CANCELLED──> CANCELLED
```

- 合法迁移：`CREATED→PAID`、`PAID→SHIPPED`、`SHIPPED→COMPLETED`；
  `CREATED→CANCELLED`、`PAID→CANCELLED`；
- **终态** `COMPLETED` / `CANCELLED` 不允许任何迁移（同状态重复调用是幂等重放，不属于迁移）；
- 同状态重复调用：返回已有订单，**不重写时间戳**；
- 非法迁移 → `MERCHANT_CONFLICT`（文案带当前状态与允许的下一步）；
- 未知状态/参数非法 → `MERCHANT_INVALID`；未知订单/其他租户 → `MERCHANT_NOT_FOUND`；`merchant_id` 必填。

### 11.2 方法契约

```python
order = writer.update_order_status(
    "m_tea_001",
    "ORD-20261003-0003",
    "PAID",
)
order = writer.update_order_status(
    "m_tea_001", "ORD-20261003-0003", "SHIPPED",
    tracking_no="SF1435267890123", carrier="顺丰速运",
)
order = writer.update_order_status("m_tea_001", "ORD-20261003-0003", "COMPLETED")
```

| 参数/规则 | 说明 |
| --- | --- |
| `status` | 只接受 `CREATED/PAID/SHIPPED/COMPLETED/CANCELLED`（大小写不敏感，统一转大写） |
| `tracking_no` | 流转到 `SHIPPED` **必填**；v1 规则：4~64 位，字母/数字开头，可含 `-_.`；其他状态携带 → `MERCHANT_INVALID` |
| `carrier` | 可选（如「顺丰速运」）；最长 64 字符、不允许控制字符；仅 `SHIPPED` 允许携带 |
| 幂等 | 同状态重复调用返回已有订单；SHIPPED 重放若物流单号/承运商与已保存不同 → `MERCHANT_CONFLICT`（防止悄悄改单号） |
| 时间字段 | `PAID`→写 `paid_at`；`SHIPPED`→写 `shipped_at`；`COMPLETED`→写 `completed_at`；`CANCELLED` 只改状态（保留 `paid_at` 供对账） |
| 事务 | `BEGIN IMMEDIATE`：状态、物流字段、时间字段同事务提交；并发同迁移只有一个真正写入，其余幂等返回 |
| 订单行/金额 | 状态更新**不改**订单行、金额、来源引用 |

### 11.3 模型 / 表字段

`Order` 新增（均允许 `None`）：
`tracking_no`、`carrier`、`shipped_at`、`completed_at`；`paid_at` 已有。
`to_dict()` 同步输出这些字段，C 端订单时间线与物流展示可直接消费。

`m_order` 新增列：`tracking_no TEXT, carrier TEXT, shipped_at TEXT, completed_at TEXT`；
**老库自动迁移**：初始化时 `PRAGMA table_info(m_order)` 检查并逐列 `ALTER TABLE`（幂等），
v1/v1.1 的 `var/merchant_v1.sqlite` 无需手工重建（迁移后可继续走完整状态机）。

### 11.4 种子数据

`data/merchant/orders.csv` 追加列：`tracking_no, carrier, shipped_at, completed_at`；
已有 SHIPPED / COMPLETED 订单补上物流单号、承运商与状态时间（时间顺序校验）：
SHIPPED/COMPLETED 必须有 `tracking_no`+`shipped_at`，COMPLETED 另有 `completed_at`，
且物流单号全局唯一。列是**可选列**：缺省空值兼容旧种子文件（PAID/CREATED/CANCELLED 无物流）。

### 11.5 限制

1. 本地状态机不是真实 OMS 回调：没有支付网关验签、物流轨迹、退款/售后/逆向流程；
2. `PAID` 只是状态与时间戳，没有支付流水号/金额对账字段（真实接入需扩展 `payment_*`）；
3. 状态流转不可逆（CANCELLED 后不能复活），没有「拒绝收货/退货退款」等扩展状态；
4. 未接入 API / Agent 的自动状态推进（管理员状态操作 API 与 C 端展示由接入方负责，
   数据层只提供确定性能力）；
5. 并发保证仍是 SQLite 单机单写者语义；PG/OMS adapter 需自行实现同等事务与幂等。

## 12. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1 | 2026-10-30 | 新增可替换的商家数据层：模型/协议/SQLite adapter/种子校验/工厂与 38 例离线单测 |
| v1.1 | 2026-10-30 | 新增本地写入能力：`MerchantWriteRepository`、`m_reservation`、事务化 reserve/commit/release/create_order（幂等、库存不足失败关闭、租户必填）、`m_order.source_ref` 与老库自动迁移；新增 30 例写接口单测（合计 68 例） |
| v1.2 | 2026-10-30 | 新增订单状态机与物流字段：`update_order_status`、`Order.tracking_no/carrier/shipped_at/completed_at`、`m_order` 四列与老库自动迁移、种子 SHIPPED/COMPLETED 物流数据与校验；新增 31 例状态机/物流/迁移测试（合计 101 例） |
