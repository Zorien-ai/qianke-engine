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
├── sqlite_repository.py   默认 SQLite 实现（只读查询 + 事务化库存预占/订单写入/状态机/取消退款）
├── postgres_repository.py PostgreSQL 实现（同一契约；独立 schema；P2-A / task-51）
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
| `QIANKE_MERCHANT_BACKEND` | `sqlite` | 默认后端名：`sqlite` / `postgres` / 已注册的自定义后端 |
| `QIANKE_MERCHANT_SEED_DIR` | `<仓库根>/data/merchant` | 种子目录（测试/临时环境可覆盖） |
| `QIANKE_MERCHANT_PG_HOST` | `RAG_PG_HOST` → `127.0.0.1` | PostgreSQL host（§14） |
| `QIANKE_MERCHANT_PG_PORT` | `RAG_PG_PORT` → `5432` | PostgreSQL 端口 |
| `QIANKE_MERCHANT_PG_USER` | `RAG_PG_USER` → `postgres` | PostgreSQL 用户 |
| `QIANKE_MERCHANT_PG_PASSWORD` | `RAG_PG_PASSWORD` → `123456` | PostgreSQL 密码（生产必须用密钥管理注入） |
| `QIANKE_MERCHANT_PG_DBNAME` | `vec_db` | PostgreSQL 业务库 |
| `QIANKE_MERCHANT_PG_SCHEMA` | `merchant_v1` | 商家表独立 schema（绝不写 public/其他业务表） |

> PostgreSQL 连接细节与测试见 §14；默认仍是 SQLite，没装 psycopg2/没配 PG 不影响离线路径。

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
  兼容旧种子文件。v1.3 的取消/退款列（`cancelled_at / refund_amount / refunded_at`）同样按
  可选列解析：当前种子文件未包含，加载为 `None`（历史 CANCELLED 订单保持原样，不自动补退款）。

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

> 内置 PostgreSQL adapter 已在 P2-A（task-51）落地，见 §14；本节仍以「接真实 OMS」为例，
> 说明 adapter 协议与硬约束。

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
   `MerchantWriteRepository`（内置 SQLite / PostgreSQL adapter 两者都实现）。真实 OMS 的写操作
   必须走 OMS 的受控接口 + 人工确认——**不要把 OMS 写权限给只读查询 adapter**；
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
# 结果：137 passed（45 只读/种子用例 + 92 写接口/状态机/取消/退款/退货入库用例；离线，约 13s）

uv run python -m pytest tests/test_merchant_postgres.py -q
# 结果：17 passed（真实 PostgreSQL 16，独立 schema，约 22s；无 PG 时自动 skip）

# task 验收组合命令
uv run python -m pytest tests/test_merchant_store.py tests/test_merchant_write.py tests/test_merchant_postgres.py -q
# 结果：154 passed
```

覆盖：
- 只读/种子：规模下限与完整性、初始化幂等/force 重灌、env 路径覆盖、工厂缓存与重置、
  商品/SKU/库存/订单查询、**租户隔离**（跨商家、`get_*` 作用域、缺 `merchant_id` 失败关闭）、
  无库存 vs 不存在、limit 钳制（纯函数 + 查询路径）、可替换后端注册（Fake adapter）、
  坏种子（引用缺失/规模不足/目录不存在/物流字段缺失）结构化拒绝、关闭后不可用、
  种子 SHIPPED/COMPLETED 物流字段、`Order.to_dict()` 生命周期与取消/退款字段、
  旧种子文件缺取消/退款列时兼容解析；
- 写接口：reserve 成功/幂等/冲突/库存不足/参数非法/未知 SKU/过期、commit 幂等与库存口径、
  release 幂等与已提交拒绝、过期 commit/release 语义、**并发同 id 只扣一次**、
  **并发竞争不超卖**、create_order 幂等/金额不一致拒绝/租户隔离/促销价/来源引用、
  写操作 merchant_id 必填、写错误结构化；
- 订单状态机（task-45）：CREATED→PAID→SHIPPED→COMPLETED 全链路与时间字段、同状态幂等
  不重写时间戳、SHIPPED 必须带合法物流单号（格式规则）、非法迁移 `MERCHANT_CONFLICT`、
  取消规则（CREATED/PAID→CANCELLED，保留 paid_at）、跨租户 NotFound、并发同迁移幂等、
  物流字段只允许出现在 SHIPPED、状态更新不影响订单行/金额、老库自动迁移后状态机可用；
- 取消/模拟退款（task-47）：CREATED 取消退款 0、PAID 取消全额模拟退款、按已提交预占
  allocations 精确恢复库存并标记 REVERSED、重复取消不重复退款/恢复、`request_id` 幂等
  与跨订单冲突、SHIPPED/COMPLETED 拒绝、跨租户 NotFound、并发同 request_id 只补偿一次、
  无预占订单不凭空补库存、`update_order_status(CANCELLED)` 与 `cancel_order` 同语义、
  老库迁移后取消/退款可用、旧种子 CANCELLED 订单幂等兼容；
- 售后退款/REFUNDED（task-49）：SHIPPED/COMPLETED 部分/全额退款、默认不恢复库存
  （有已提交预占也不动）、金额边界（>0/<=total/最多 2 位小数/NaN/Inf/布尔拒绝）、
  重复退款幂等与金额/`request_id` 冲突、非法状态（CREATED/PAID 引导 cancel_order、
  CANCELLED 拒绝、REFUNDED 终态）、`update_order_status(REFUNDED)` 拒绝、跨租户/未知订单、
  并发同 request_id 只写一次、状态筛选与 `to_dict()` 输出、老库迁移后售后退款可用；
- 退货验收入库（task-54）：SHIPPED/COMPLETED 退货入库按 COMMITTED allocations 恢复库存、
  订单状态不变、`returned_at` 写入、重复幂等不重复恢复、`request_id` 跨订单冲突、
  无预占订单 Conflict（种子订单）、CREATED/PAID/CANCELLED/REFUNDED 拒绝、
  租户隔离、取消后/退款后拒绝、SQLite 老库迁移 + PG schema 迁移幂等、并发同 request_id 只恢复一次；
- PostgreSQL adapter（task-51）：真实 PG16 独立 schema（自动 DROP 清理）、种子/describe/
  stats、商品/SKU/库存/订单读、租户隔离与 limit、reserve 幂等/commit/release/库存不足、
  create_order 幂等/金额校验、状态机、取消退款库存补偿、售后退款幂等、
  **并发预占不超卖**（SELECT FOR UPDATE）、seed(force=True) 重置、factory env 切换、
  schema 表清单隔离；无 PG/无 psycopg2 时整模块 skip。
- 另：`tests/test_c_end_store_agent_merchant.py`、`tests/test_c_end_agent_merchant.py`
  覆盖 C 端只读接入（由对应改动方负责，本任务未修改）。

## 9. 已知限制（v1，明确不是真实 OMS）

1. **不是真实 OMS 对接**：没有商家侧鉴权/签名/支付/对账；种子是工作区里的静态样例数据；
2. **写通道是本地 SQLite / PostgreSQL adapter**：reserve/commit/release/create_order 事务化、
   幂等、失败关闭，但它们是**本地演示/集成实现**，不是真实库存/交易系统；
   真实写必须接 OMS 受控接口 + 人工确认；
3. **无分页游标 / 时间范围过滤**：列表只有 limit + 买家/状态过滤；大商家需要补 offset/cursor；
4. **无价格历史 / 库存流水**：模型只有当前快照；经营分析若需要「改价/补货历史」要另建表；
5. **无多语言/多币种**：种子仅 CNY；模型保留了 currency 字段但无汇率逻辑；
6. **SQLite 适合开发/演示，PG adapter 用于单机/共享集成**：SQLite 只保证单机单写者语义
   （`BEGIN IMMEDIATE` + busy timeout）；PostgreSQL adapter 用事务 + `SELECT ... FOR UPDATE`
   + 唯一索引，支持多连接并发预占不超卖，但**仍不是高可用/分库分表方案**（§14）；
7. **已接 API / Agent，但真实交易仍受控**：店宠与 C 端只读 API、C 商城下单写商家订单
   已接（1.8.4）；本地写层（§10/§12）具备预占、订单写入、状态流转、取消退款能力，
   但**不是真实 OMS/支付网关**，真实交易需 OMS 写通道 + 用户确认；
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
| `update_order_status(merchant_id, order_id, status, tracking_no=None, carrier=None)` | 订单状态机流转（见 §11）：写状态时间与物流字段；`CANCELLED` 与 §12 的取消语义一致；返回 `Order` | 非法迁移 `MERCHANT_CONFLICT`；未知状态/物流字段非法 `MERCHANT_INVALID`；未知/跨租户 `MERCHANT_NOT_FOUND` |
| `cancel_order(merchant_id, order_id, request_id=None)` | 取消订单（见 §12）：CREATED/PAID→CANCELLED、PAID 写模拟退款、按已提交预占恢复库存；幂等；返回 `Order` | 非法状态 `MERCHANT_CONFLICT`；`request_id` 冲突/参数非法 `MERCHANT_CONFLICT`/`MERCHANT_INVALID`；未知/跨租户 `MERCHANT_NOT_FOUND` |
| `refund_order(merchant_id, order_id, amount=None, request_id=None)` | 售后退款（见 §13）：SHIPPED/COMPLETED→REFUNDED、部分/全额、默认不恢复库存；幂等；返回 `Order` | 非发货状态/终态 `MERCHANT_CONFLICT`；金额非法/`update_order_status(REFUNDED)` `MERCHANT_INVALID`；`request_id` 冲突 `MERCHANT_CONFLICT`；未知/跨租户 `MERCHANT_NOT_FOUND` |
| `receive_return(merchant_id, order_id, request_id=None)` | 退货验收入库（见 §15）：SHIPPED/COMPLETED 按 COMMITTED allocations 恢复库存、订单状态不变、写 returned_at；幂等；返回 `Order` | 非发货状态/无预占 `MERCHANT_CONFLICT`；`request_id` 冲突 `MERCHANT_CONFLICT`；参数非法 `MERCHANT_INVALID`；未知/跨租户 `MERCHANT_NOT_FOUND` |

### 10.3 状态机与库存账目口径

```text
reserve ──> RESERVED ──commit──> COMMITTED   (available 保持 -q，reserved 回到基线)
              │                    │
              │                    └──cancel order──> REVERSED  (available +q 按 allocations；task-47)
              ├──release──> RELEASED         (available +q，reserved -q)
              └──expire───> EXPIRED          (库存释放；懒触发)
```

- 预占成功：`available_qty -= q`，`reserved_qty += q`；
- commit：**available 不再变化**（货已卖掉），`reserved_qty -= q`；
- release：`available_qty += q`，`reserved_qty -= q`（按预占时记录的**仓库扣减明细**
  精确恢复，不按当前库存重新猜）；
- **取消订单（REVERSED）**：COMMITTED 预占按 allocations 逐仓 `available_qty += q`
  （reserved 已转出，不再变化），随后预占标记 REVERSED；这是取消/退款的库存补偿路径，
  与 release 的区别是：release 只发生在 COMMITTED 之前；
- 过期（TTL 默认 900s，上限 7 天）：在 commit/release/reserve 该 id 时懒检测；
  commit 过期预占会**先释放库存并标记 EXPIRED，再抛 `MERCHANT_EXPIRED`**；
  release 过期预占返回 `EXPIRED`（幂等，不重复恢复）；reserve 复用过期 id 会先恢复旧库存再新建；
- 终态 id（RELEASED / COMMITTED / EXPIRED / REVERSED）**不能复用**，需换新 `reservation_id`。

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
  物流/生命周期列；v1.3 增加 `cancelled_at / refund_amount / refunded_at` 与内部幂等键
  `cancel_request_id`；v1.4 增加内部幂等键 `refund_request_id`；v1.5 增加
  `returned_at` 与内部幂等键 `restock_request_id`；request_id/退货列均走部分唯一索引
  （允许多个 NULL）；全部允许 NULL（历史订单没有这些信息是正常状态）；
- **老库自动迁移**：初始化时用 `PRAGMA table_info` 检查并 `ALTER TABLE` 补列（幂等），
  v1/v1.1/v1.2/v1.3 的 `var/merchant_v1.sqlite` 不需要手工重建；
- `seed(force=True)` 会连同 `m_reservation` 一起重置（仅本地调试，不对外暴露）。

## 11. 订单状态机与物流字段（v1.2 / task-45）

> 仍然**不是真实 OMS 写通道**：状态流转是本地 SQLite 的确定性实现，用于在接 OMS 前
> 固定订单生命周期语义；真实支付回调/物流轨迹/退款售后必须由 OMS + 人工确认链路负责。

### 11.1 状态机

```text
CREATED ──PAID──> PAID ──SHIPPED──> SHIPPED ──COMPLETED──> COMPLETED
   │                │                  │                      │
   └──CANCELLED─────┴──CANCELLED──> CANCELLED                │
                                        REFUNDED <────────────┘
                                           ▲
                                           └── SHIPPED ──REFUNDED（售后退款，§13）
```

- 合法迁移：`CREATED→PAID`、`PAID→SHIPPED`、`SHIPPED→COMPLETED`；
  `CREATED→CANCELLED`、`PAID→CANCELLED`；
  `SHIPPED/COMPLETED→REFUNDED`（**只能**经 `refund_order(amount=...)`，见 §13）；
- **终态** `COMPLETED` 只能去 `REFUNDED`；`CANCELLED` / `REFUNDED` 是终态，不再允许任何迁移
  （同状态重复调用是幂等重放，不属于迁移）；
- 同状态重复调用：返回已有订单，**不重写时间戳**；
- 非法迁移 → `MERCHANT_CONFLICT`（文案带当前状态与允许的下一步）；
- 未知状态/参数非法 → `MERCHANT_INVALID`；未知订单/其他租户 → `MERCHANT_NOT_FOUND`；`merchant_id` 必填；
  `update_order_status(status=REFUNDED)` 一律 `MERCHANT_INVALID`（必须走带金额的 `refund_order`）。

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
| `status` | 只接受 `CREATED/PAID/SHIPPED/COMPLETED/CANCELLED/REFUNDED`（大小写不敏感，统一转大写）；`REFUNDED` 必须走 §13 的 `refund_order`，本方法传入会 `MERCHANT_INVALID` |
| `tracking_no` | 流转到 `SHIPPED` **必填**；v1 规则：4~64 位，字母/数字开头，可含 `-_.`；其他状态携带 → `MERCHANT_INVALID` |
| `carrier` | 可选（如「顺丰速运」）；最长 64 字符、不允许控制字符；仅 `SHIPPED` 允许携带 |
| 幂等 | 同状态重复调用返回已有订单；SHIPPED 重放若物流单号/承运商与已保存不同 → `MERCHANT_CONFLICT`（防止悄悄改单号） |
| 时间字段 | `PAID`→写 `paid_at`；`SHIPPED`→写 `shipped_at`；`COMPLETED`→写 `completed_at`；`CANCELLED`→写 `cancelled_at` 并触发模拟退款/库存补偿（语义同 §12 的 `cancel_order`，保留 `paid_at` 供对账）；`REFUNDED` 由 §13 写 `refunded_at`/`refund_amount` |
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

1. 本地状态机不是真实 OMS 回调：没有支付网关验签、物流轨迹、真实退款通道、售后/逆向流程
   （§12 的退款是本地模拟账目，不是支付网关退款）；
2. `PAID` 只是状态与时间戳，没有支付流水号/金额对账字段（真实接入需扩展 `payment_*`）；
3. 状态流转不可逆（CANCELLED / REFUNDED 后不能复活），没有「拒绝收货/部分退货多次退款」等
   扩展状态；已发货/已完成的本地模拟售后退款见 §13，真实退货退款仍需 OMS；
4. 未接入 API / Agent 的自动状态推进（管理员状态操作 API 与 C 端展示由接入方负责，
   数据层只提供确定性能力）；
5. 并发保证仍是 SQLite 单机单写者语义；PG/OMS adapter 需自行实现同等事务与幂等。

## 12. 订单取消 / 模拟退款与库存补偿（v1.3 / task-47）

> 仍然**不是真实支付网关**：取消与退款是本地 SQLite 的确定性模拟，用于在接 OMS/支付之前
> 固定「取消 → 模拟退款 → 库存补偿」的语义与事务边界；真实退款必须走支付网关/OMS 受控链路，
> 并保留人工确认与对账。

### 12.1 方法契约

```python
# CREATED / PAID 订单取消；PAID 自动写全额模拟退款
cancelled = writer.cancel_order("m_tea_001", "ORD-20261003-0003")

# 带 request_id 的幂等取消：重试/并发重放返回同一结果，不重复退款/恢复库存
cancelled = writer.cancel_order(
    "m_tea_001", "ORD-20261003-0003", request_id="cancel-req-20261030-01",
)
```

| 参数/规则 | 说明 |
| --- | --- |
| 允许状态 | 只允许 `CREATED` / `PAID` → `CANCELLED`；`SHIPPED` / `COMPLETED` → `MERCHANT_CONFLICT`；已 `CANCELLED` → 幂等返回已有订单 |
| 模拟退款 | `PAID` 取消：`refund_amount = total_amount`、`refunded_at = now`；`CREATED` 取消：`refund_amount = 0`、`refunded_at = None` |
| `cancelled_at` | 取消动作写入；重复取消/幂等重放不重写 |
| 库存补偿 | 只按 `m_reservation.order_id` 关联且状态 `COMMITTED` 的预占 allocations 逐仓 `available += q`，随后预占标记 `REVERSED`；**无预占的订单允许取消但不补库存**（不凭空造库存） |
| `request_id` | 幂等键（≤128 字符）：同 key 重放返回同一结果；同 key 用于其他订单 → `MERCHANT_CONFLICT`；空串/纯空白 → `MERCHANT_INVALID` |
| 事务 | `BEGIN IMMEDIATE`：状态、取消/退款字段、库存补偿、预占状态同事务提交，异常整体回滚 |
| 租户/必填 | `merchant_id` 必填；未知订单/其他租户 → `MERCHANT_NOT_FOUND`（不泄露存在性） |
| 与 `update_order_status` 关系 | `update_order_status(..., CANCELLED)` 走同一补偿逻辑，区别只是没有 `request_id` 幂等键；业务取消应优先用 `cancel_order` |

### 12.2 补偿口径 / 库存账目

```text
reserve:   available -q, reserved +q
commit:    available 不变, reserved -q        (货已卖出)
cancel:    available +q (按 allocations 原仓库), 预占 COMMITTED -> REVERSED
```

- 取消补偿只加 `available_qty`，不再动 `reserved_qty`（commit 时已转出）；
- 库存恢复按预占时记录的**仓库扣减明细**精确恢复，不按当前库存重算；
- 同一订单存在多笔已提交预占（异常/人工数据）时全部补偿并全部标记 `REVERSED`；
- 已取消订单对应的预占不能再 `commit`（`MERCHANT_CONFLICT`）；`release` 对 `REVERSED`
  幂等返回，不会二次恢复；
- 无预占订单（种子订单 / 直接 `create_order`）取消时库存不变——取消本身合法，只是没有可补偿的扣减；
- `update_order_status(CANCELLED)` 与 `cancel_order` 共用同一事务内实现，避免绕过退款/库存补偿。

### 12.3 幂等 / 并发 / 安全

- **天然幂等**：订单状态 + `cancelled_at`；重复取消直接返回已有订单，绝不二次退款/恢复库存；
- **request_id 幂等**：落在 `m_order.cancel_request_id`（部分唯一索引，允许多个 NULL）；
  同 key 跨订单 → `MERCHANT_CONFLICT`；并发同 key 只有一个真正写入，其余幂等返回；
- **并发**：所有取消在 `BEGIN IMMEDIATE` 下串行；唯一索引兜底捕获 `sqlite3.IntegrityError`
  并转结构化 `MERCHANT_CONFLICT`；
- **租户隔离**：取消前先按 `order_id + merchant_id` 校验，未知/跨租户一律 NotFound；
- **参数化 SQL**：全部写 SQL 使用占位符；金额仍用 `Decimal`/字符串，不用 float。

### 12.4 模型 / 表字段 / 迁移

- `Order` 新增（均可为 None）：`cancelled_at`、`refund_amount`（`Decimal`，序列化为字符串）、
  `refunded_at`；`to_dict()` 同步输出，未取消订单为 `None`；
- `m_order` 新增列：`cancelled_at TEXT, refund_amount TEXT, refunded_at TEXT, cancel_request_id TEXT`
  （内部幂等键，不进 `Order` 公共模型），以及部分唯一索引
  `idx_m_order_cancel_request (cancel_request_id) WHERE cancel_request_id IS NOT NULL`；
- **老库自动迁移**：初始化时 `PRAGMA table_info(m_order)` 检查并逐列 `ALTER TABLE`（幂等），
  补列后再创建唯一索引；v1/v1.1/v1.2 的 `var/merchant_v1.sqlite` 无需手工重建；
- **种子兼容**：`orders.csv` 的取消/退款列是可选列，当前种子文件没有该列 → 全部 `None`；
  历史 `CANCELLED` 种子订单重复取消保持原样（不自动补退款）。

### 12.5 限制

1. 不是真实支付网关：没有退款单号、支付流水、通道回调、部分退款/多次退款；
   `refund_amount` 固定为订单全额（或 CREATED 的 0），只是本地模拟账目；
2. 只能取消**未发货**订单；已发货/已完成订单的售后退款见 §13（本地模拟、默认不恢复库存），
   真实退货退款/逆向物流仍由 OMS 负责；
3. 没有取消原因、操作人、审核人等审计字段；`request_id` 只做幂等键，不代表操作身份；
4. 种子里的历史 `CANCELLED` 订单没有退款字段（保持原样，不自动补）；
5. 库存补偿依赖预占记录；若预占记录缺失/被清理，取消不会凭空补库存（宁可不补，也不制造假库存）；
6. 并发保证仍是 SQLite 单机单写者语义；PG/OMS adapter 需实现同等事务、幂等与库存补偿。

## 13. 售后退款与 REFUNDED 状态（v1.4 / task-49）

> 仍然**不是真实支付网关**：本节的退款是本地 SQLite 的模拟账目，用于固定「发货后退款」
> 的状态、金额与幂等语义；真实退款/退货退款必须走支付网关/OMS 受控链路 + 人工确认 + 对账。

### 13.1 方法契约

```python
# 全额退款（amount=None → 默认订单 total_amount）
refunded = writer.refund_order("m_gear_002", "ORD-20261004-0004")

# 部分退款 + request_id 幂等键（重试/并发重放不重复退款）
refunded = writer.refund_order(
    "m_gear_002", "ORD-20261004-0004",
    amount="168.50", request_id="refund-req-20261030-01",
)
```

| 参数/规则 | 说明 |
| --- | --- |
| 允许状态 | 只允许 `SHIPPED` / `COMPLETED` → `REFUNDED`；`CREATED` / `PAID` 未发货 → `MERCHANT_CONFLICT`（提示用 `cancel_order`）；`CANCELLED` → `MERCHANT_CONFLICT`；已 `REFUNDED` → 幂等/冲突判定 |
| `amount` | `None` → 默认 `total_amount`（全额）；否则必须 `>0`、`<=total_amount`、有限数值、最多 2 位小数；非法 → `MERCHANT_INVALID` |
| 写入字段 | `status=REFUNDED`、`refund_amount=amount`、`refunded_at=now`；保留 `paid_at/shipped_at/completed_at`、物流字段；`cancelled_at` 保持 `None` |
| 库存 | **默认且当前不恢复库存**（即使订单关联 COMMITTED 预占也不动）；退货验收入库是独立流程，避免把未验收商品加回可售库存 |
| 重复退款 | 已 `REFUNDED`：同 `request_id`（或未传 request_id）且金额一致 → 返回已有订单；金额不一致/重复退款 → `MERCHANT_CONFLICT` |
| `request_id` | 幂等键（≤128 字符）：同 key 重放返回同一结果（金额必须一致）；同 key 跨订单 → `MERCHANT_CONFLICT`；空白/超长 → `MERCHANT_INVALID`；并发同 key 只有一次写入 |
| 事务 / 租户 | `BEGIN IMMEDIATE`；状态、退款金额、退款时间同事务提交；`merchant_id` 必填；未知/跨租户 → `MERCHANT_NOT_FOUND` |
| 状态机入口 | `update_order_status(status=REFUNDED)` **一律拒绝**（`MERCHANT_INVALID`），必须走本方法以携带金额/幂等键 |

### 13.2 金额与退款账目口径

- 本实现每个订单最多一次退款动作：一旦 `REFUNDED` 即为终态；
  `refund_amount` 记录本次退款金额（可小于 `total_amount`，代表部分退款）；
- 不做多次部分退款累加（真实售后可能需要多次退款，属于后续扩展，需新增 refund 流水表）；
- `amount` 不做四舍五入：超过 2 位小数直接拒绝，避免账面对不上；
- PAID 未发货取消走 §12 `cancel_order`（写退款 + 恢复库存），与本节分开：
  **未发货取消 ≠ 发货后退款**。

### 13.3 库存 / 预占口径

- 本节退款**不恢复库存、不改变预占状态**：SHIPPED/COMPLETED 商品已离开可售库存，
  退货验收入库（质检/上架）是独立流程，不能因为「退款成功」就自动加回可售；
- 取消（§12）才按 COMMITTED 预占 allocations 恢复 available 并标 `REVERSED`；
- 因此退款订单若仍关联 COMMITTED 预占，该预占保持 COMMITTED，直到后续独立退货入库流程处理。

### 13.4 模型 / 表字段 / 迁移

- 订单状态枚举新增 `REFUNDED`；`Order.refund_amount` / `refunded_at` 复用 §12 的字段
  （退款动作写这两个字段）；`to_dict()` 同步输出；
- `m_order` 增加内部幂等键 `refund_request_id TEXT` 与部分唯一索引
  `idx_m_order_refund_request (refund_request_id) WHERE refund_request_id IS NOT NULL`
  （不进 `Order` 公共模型）；
- **老库自动迁移**：初始化时 `PRAGMA table_info(m_order)` 检查并逐列 `ALTER TABLE`（幂等），
  补列后再建索引；v1.x 的 `var/merchant_v1.sqlite` 无需手工重建；
- 种子数据不使用 `REFUNDED` 状态（由真实写操作产生），无需调整 CSV。

### 13.5 限制

1. 不是真实支付网关：没有退款单号、支付流水、通道回调、多次/部分累计退款；
   `refund_amount` 只是本地模拟账目；
2. 每个订单最多一次退款动作（`REFUNDED` 终态）；如需多次部分退款需新增退款流水表与状态扩展；
3. refund_order 本身**不恢复库存、不改预占**；退货验收入库由 `receive_return` 单独负责
   （见 §15，验收入库后才恢复可售库存）；真实逆向物流/退货质检仍由 OMS 负责；
4. 没有退款原因/操作人/审核人审计字段；`request_id` 只做幂等键，不代表操作身份；
5. 并发保证：SQLite 为单机单写者语义；PostgreSQL adapter 已实现事务 + `FOR UPDATE`
   同等语义（§14）；真实 OMS adapter 仍需自行实现同等事务、幂等与唯一约束。

## 14. PostgreSQL 商家 adapter（v2.0 / task-51）

> **仍然不是真实 OMS**：PostgreSQL adapter 只是把同一份商家数据层契约落到 PG 上，
> 用于本地/集成环境的多连接并发验证；真实交易、支付、库存对账仍必须接 OMS 受控接口。

### 14.1 定位与使用

- 新增 `PostgresMerchantRepository`（`src/rag_demo/merchant/postgres_repository.py`），
  同时实现 `MerchantRepository` + `MerchantWriteRepository`，方法与语义与 SQLite adapter 一致：
  商品/SKU/库存读、订单读、reserve/commit/release、create_order、update_order_status、
  cancel_order（含库存补偿）、refund_order（默认不恢复库存）、receive_return（退货入库恢复库存）；
- 默认后端仍是 SQLite；工厂注册 backend `"postgres"`，用环境变量切换；
- **psycopg2 延迟导入**：模块顶层不 import psycopg2，只有真正构造 PG adapter 时才导入，
  未安装驱动/未配置 PG 不会阻断 SQLite 默认路径。

```python
from rag_demo.merchant import PostgresMerchantRepository, get_merchant_repository

# 方式一：直接构造（可显式指定 schema，便于测试/多环境隔离）
repo = PostgresMerchantRepository(schema="merchant_v1", seed=True)

# 方式二：走统一工厂（推荐业务代码只依赖工厂）
#   QIANKE_MERCHANT_BACKEND=postgres
#   QIANKE_MERCHANT_PG_SCHEMA=merchant_v1
repo = get_merchant_repository()                     # 只读入口
from rag_demo.merchant import get_merchant_write_repository
writer = get_merchant_write_repository()             # 写入口（同一 PG adapter）
```

### 14.2 配置

`QIANKE_MERCHANT_PG_*` 优先，其次复用项目既有 `RAG_PG_*`，最后本机默认（§4 表）：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `QIANKE_MERCHANT_PG_HOST` | `RAG_PG_HOST` → `127.0.0.1` | PG host |
| `QIANKE_MERCHANT_PG_PORT` | `RAG_PG_PORT` → `5432` | PG 端口 |
| `QIANKE_MERCHANT_PG_USER` | `RAG_PG_USER` → `postgres` | 账号 |
| `QIANKE_MERCHANT_PG_PASSWORD` | `RAG_PG_PASSWORD` → `123456` | 密码（生产用密钥管理，不写文档/代码） |
| `QIANKE_MERCHANT_PG_DBNAME` | `vec_db` | 业务库 |
| `QIANKE_MERCHANT_PG_SCHEMA` | `merchant_v1` | 独立 schema；严格白名单校验，不污染 public |

本机 PG16 实测：`127.0.0.1:5432 postgres/******`，业务库 `vec_db`。

### 14.3 schema / 种子 / 迁移语义

- 初始化时执行 `CREATE SCHEMA IF NOT EXISTS` + 7 张表 + 索引（幂等，可重复初始化）；
  所有表名与 SQLite 相同：`m_product / m_sku / m_inventory / m_order / m_order_item /
  m_meta / m_reservation`，只在独立 schema 内可见；
- 表结构、约束、索引与 SQLite 版本对齐：
  - 金额/时间列用 `TEXT` 存十进制字符串 / ISO-8601 文本，**两个 adapter 的 Decimal/时间语义一致**；
    数量/库存用 `INTEGER`；主键/外键/PK 与 SQLite 相同；
  - `m_order` 含 `source_ref`、物流/生命周期字段、取消/退款/退货入库字段，以及
    `cancel_request_id` / `refund_request_id` / `restock_request_id` 三个**部分唯一索引**（幂等键）；
- 种子复用 `data/merchant/*.csv` + `load_seed_data()` 校验，初始化时幂等灌入；
  `seed(force=True)` 清空 m_* 后重灌；`m_meta` 记录 seed_version/seeded_at/文件 sha256；
- **没有 SQLite 老库迁移概念**（PG 是新 schema）；后续 PG 自己的表结构演进仍建议显式迁移脚本，
  adapter 只保证 `CREATE ... IF NOT EXISTS` 幂等。

### 14.4 事务 / 并发 / 幂等

- 每次操作短连接：读操作连接用完即关；写操作在显式事务中执行，异常 `ROLLBACK`、结束即 `CLOSE`；
- 并发预占：`SELECT warehouse_id, available_qty ... FOR UPDATE` 锁住库存行后再扣减，
  两个并发预占竞争同一库存时**只有一个成功，另一个 `MERCHANT_STOCK`，不会超卖**；
- 状态机/取消/退款/退货入库：`SELECT ... FOR UPDATE` 锁订单行与预占行；
  同状态幂等、非法迁移结构化错误；
- `request_id` 幂等键：部分唯一索引兜底并发重复写；同 key 跨订单 → `MERCHANT_CONFLICT`；
- reserve 同 reservation_id / create_order 同 order_id 并发插入：捕获唯一冲突后重试，
  重试路径会命中幂等分支（不会重复扣库存/重复写订单）。

### 14.5 测试

```bash
# 真实 PG（本机 PG16）；无 PG/无 psycopg2 时整模块 skip
uv run python -m pytest tests/test_merchant_postgres.py -q
# 结果：17 passed

# 离线 SQLite 套件不受影响
uv run python -m pytest tests/test_merchant_store.py tests/test_merchant_write.py -q
# 结果：137 passed

# task 验收组合命令
uv run python -m pytest tests/test_merchant_postgres.py tests/test_merchant_store.py tests/test_merchant_write.py -q
# 结果：154 passed
```

测试隔离：每个用例创建唯一 schema `qianke_merchant_test_<uuid>`，结束 `DROP SCHEMA CASCADE`；
覆盖种子/describe/stats、读接口与租户隔离/limit、reserve/commit/release、create_order、
状态机、取消退款库存补偿、售后退款幂等、退货验收入库（库存恢复/幂等/无预占拒绝/迁移）、
seed(force=True)、factory env 切换、schema 表清单隔离、**并发预占不超卖**。

### 14.6 实现说明 / 限制

1. **不是真实 OMS / 不是高可用方案**：没有连接池、读写分离、主从切换、分布式事务、
   跨库分片；短连接适合本地/低并发集成，生产高并发需连接池与超时/重试治理；
2. schema 由 adapter 初始化；生产建议用迁移工具（Alembic/Flyway 等）管理 DDL、
   使用受限账号，并显式授权目标 schema；
3. 一个 adapter 实例绑定一个 schema；多租户/多环境请用不同 schema 或不同实例；
4. 金额/时间用 TEXT 与 SQLite 对齐，便于同一套测试与模型复用；若直接接 BI/审计，
   可后续加 NUMERIC/TIMESTAMPTZ 视图（当前不做，避免语义分叉）；
5. 仍无库存流水/价格历史/退款流水表；订单行/商品标题是快照；
6. 凭证从环境变量读取；生产必须用密钥管理，不要把明文密码写进代码/文档/日志；
7. 真实 OMS 接入仍需受控写接口 + 人工确认；本 adapter 只是标准 PG 落地。

### 14.7 复用与代码边界

- PG adapter 复用 SQLite 模块中的**纯校验/时间/幂等辅助函数**
  （items/金额/物流单号/TTL/request_id 规则，见 `sqlite_repository.py` 底部），
  避免两个 adapter 规则漂移；SQL/事务/行锁实现各自独立；
- factory 采用**延迟导入** `postgres_repository`，SQLite 默认路径不依赖 psycopg2；
- 新增 adapter 不影响既有 C 端/API/Agent 调用（它们只依赖协议与工厂）。

## 15. 退货验收入库 receive_return（v2.1 / task-54）

> **仍然不是真实 OMS/质检系统**：本节的“验收”是确定性数据动作（核对已提交预占 +
> 按原仓库恢复库存 + 记录入库时间），真实退货质检、逆向物流与退款通道仍由 OMS/支付负责。

### 15.1 方法契约

```python
# 退货验收入库（订单状态保持不变）；request_id 可选，作为幂等键
returned = writer.receive_return("m_gear_002", "ORD-20261004-0004")
returned = writer.receive_return(
    "m_gear_002", "ORD-20261004-0004", request_id="return-req-20261031-01",
)
```

| 参数/规则 | 说明 |
| --- | --- |
| 允许状态 | 只允许 `SHIPPED` / `COMPLETED`；`CREATED`/`PAID`（未发货，走 `cancel_order`）、`CANCELLED`、`REFUNDED` → `MERCHANT_CONFLICT` |
| 库存恢复 | 只按该订单 `m_reservation.order_id` 关联且状态 `COMMITTED` 的 allocations 逐仓 `available_qty += q`（reserved 不变），随后预占标记 `REVERSED`；**没有可恢复预占 → `MERCHANT_CONFLICT`**，不猜仓库、不凭空补库存 |
| 订单状态 | **不变**（SHIPPED 仍是 SHIPPED、COMPLETED 仍是 COMPLETED）；退款由 `refund_order` 单独负责 |
| 写入字段 | `returned_at = now`（`Order.to_dict()` 输出）；内部幂等键 `restock_request_id`（部分唯一索引） |
| 幂等 | 同订单重复调用返回已有订单（不重复恢复库存）；`request_id` 同 key 重放返回同一结果，同 key 跨订单 → `MERCHANT_CONFLICT`；空白/超长 → `MERCHANT_INVALID` |
| 业务顺序 | 推荐 `receive_return`（验收入库，恢复库存）→ `refund_order`（退款）；`REFUNDED` 是终态，退款后不能再入库 |
| 事务 / 租户 | SQLite `BEGIN IMMEDIATE`；PG 事务 + `SELECT ... FOR UPDATE`；`merchant_id` 必填，未知/跨租户 → `MERCHANT_NOT_FOUND` |
| 错误结构化 | `MERCHANT_CONFLICT` / `MERCHANT_INVALID` / `MERCHANT_NOT_FOUND` / `MERCHANT_DATA` |

### 15.2 库存口径

```text
commit:        available -q, reserved 转出
refund_order:  写退款字段，不改库存/预占
receive_return: available +q（按 allocations 原仓库）, 预占 COMMITTED -> REVERSED
```

- commit 后 `available` 已扣减、`reserved` 已转出；退货入库只加 `available`，不再动 `reserved`；
- 恢复按预占时记录的**仓库扣减明细**精确恢复，不按当前库存重算；
- 预占标记 `REVERSED` 后不能再次 `commit`；`release_reservation` 对 `REVERSED` 幂等返回；
- 无预占的订单（种子订单 / 直接 `create_order`）不能入库——这是有意的失败关闭：
  没有仓库扣减明细就无法知道该入哪个仓、入多少，不能猜；
- 退款（`refund_order`）**不恢复库存**：先验收退货入库再退款，避免把未验收商品加回可售。

### 15.3 幂等 / 并发 / 安全

- 订单 `returned_at` 天然幂等：重复调用直接返回已有订单，绝不二次恢复库存；
- `request_id` 落在 `m_order.restock_request_id`（部分唯一索引）：同 key 跨订单 Conflict，
  并发同 key/同订单只有一次真正恢复；
- SQLite 单写者事务；PG 订单行 + COMMITTED 预占行 `FOR UPDATE`，唯一索引兜底；
- 租户隔离、`merchant_id` 必填、全部参数化 SQL。

### 15.4 模型 / 表字段 / 迁移

- `Order` 新增 `returned_at`（可空；`to_dict()` 同步输出，未入库为 None）；
  内部 `restock_request_id` 不进公共模型；
- SQLite / PG `m_order` 新增 `returned_at TEXT`、`restock_request_id TEXT` 与部分唯一索引
  `idx_m_order_restock_request (restock_request_id) WHERE restock_request_id IS NOT NULL`；
- **迁移幂等**：SQLite `PRAGMA + ALTER TABLE` 补列再建索引；PG `ALTER TABLE ... ADD COLUMN
  IF NOT EXISTS` 补列后再 `CREATE UNIQUE INDEX IF NOT EXISTS`（先补列后建索引，
  旧 schema 不会因索引引用缺列而失败）；两个 adapter 都可重复初始化；
- 种子 CSV 不变（历史订单 `returned_at` 为 NULL）。

### 15.5 测试

```bash
# SQLite + PostgreSQL 三套（task 验收命令）
uv run python -m pytest tests/test_merchant_store.py tests/test_merchant_write.py tests/test_merchant_postgres.py -q
# 结果：154 passed（45 store + 92 write + 17 PG；PG 部分无 PG 时自动 skip）
```

覆盖：SHIPPED/COMPLETED 入库恢复库存、订单状态不变、重复幂等不重复恢复、request_id 跨订单冲突、
无预占种子订单 Conflict、CREATED/PAID/CANCELLED/REFUNDED 拒绝、退款后拒绝、取消后拒绝、
租户隔离、`to_dict().returned_at`、接收后订单字段/行不变、先入库后退款流程、
并发同 request_id 只恢复一次、SQLite 老库迁移、PG schema 迁移（删列后重新初始化补列+索引）。

### 15.6 限制

1. 不是真实质检/逆向物流：只保证“按预占恢复库存 + 记录入库时间”，没有质检结果、
   不良品、部分入库/多批次入库；这些属于 OMS/售后系统；
2. 每个订单最多一次整单入库（`returned_at` 标记）；部分退货/多次入库需后续扩展
   line-level return ledger；
3. 只允许 SHIPPED/COMPLETED；REFUNDED 终态后拒绝（若先退款，需人工/OMS 特殊处理）；
4. 必须存在该订单的 COMMITTED 预占（C 端下单链路）；种子/直接 `create_order` 无预占 → 拒绝；
5. 入库后订单仍可退款（`refund_order`），但退款不会二次改变库存；
6. 仍是本地实现，真实退货/逆向物流/质检由 OMS 负责。

## 16. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1 | 2026-10-30 | 新增可替换的商家数据层：模型/协议/SQLite adapter/种子校验/工厂与 38 例离线单测 |
| v1.1 | 2026-10-30 | 新增本地写入能力：`MerchantWriteRepository`、`m_reservation`、事务化 reserve/commit/release/create_order（幂等、库存不足失败关闭、租户必填）、`m_order.source_ref` 与老库自动迁移；新增 30 例写接口单测（合计 68 例） |
| v1.2 | 2026-10-30 | 新增订单状态机与物流字段：`update_order_status`、`Order.tracking_no/carrier/shipped_at/completed_at`、`m_order` 四列与老库自动迁移、种子 SHIPPED/COMPLETED 物流数据与校验；新增 31 例状态机/物流/迁移测试（合计 101 例） |
| v1.3 | 2026-10-30 | 新增订单取消与模拟退款：`cancel_order(..., request_id)`、`Order.cancelled_at/refund_amount/refunded_at`、`m_order` 取消/退款列 + `cancel_request_id` 唯一幂等键与老库自动迁移、按已提交预占 allocations 恢复库存并标记 `REVERSED`、`update_order_status(CANCELLED)` 同语义；新增 16 例取消/退款/库存补偿测试（合计 117 例） |
| v1.4 | 2026-10-30 | 新增发货后售后退款与 `REFUNDED` 状态：状态机 `SHIPPED/COMPLETED→REFUNDED`、`refund_order(amount/request_id)`（部分/全额、默认全额、默认不恢复库存）、`m_order.refund_request_id` 唯一幂等键与老库自动迁移、`update_order_status(REFUNDED)` 拒绝；新增 10 例售后退款/金额/幂等/迁移测试（合计 127 例） |
| v2.0 | 2026-10-31 | 新增 PostgreSQL 商家 adapter（P2-A）：`PostgresMerchantRepository` 实现同契约读写、独立 schema（`QIANKE_MERCHANT_PG_SCHEMA`，默认 `merchant_v1`）、幂等建表+种子、事务+`FOR UPDATE` 并发不超卖、psycopg2 延迟导入、factory 注册 `postgres`（SQLite 仍默认）；新增 13 例真实 PG16 集成测试（无 PG 自动 skip，离线 127 例不变） |
| v2.1 | 2026-10-31 | 新增退货验收入库 `receive_return`：SHIPPED/COMPLETED 按该订单 COMMITTED allocations 恢复库存并标记 REVERSED、订单状态不变、写 `returned_at`/`restock_request_id`（唯一幂等键）、无预占 Conflict、REFUNDED/取消后拒绝；SQLite+PG 双 adapter + 幂等迁移；新增 10 例 SQLite + 4 例 PG 测试（三套合计 154 例） |
