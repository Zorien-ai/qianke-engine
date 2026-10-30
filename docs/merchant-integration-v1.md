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

本版本**只读**：没有订单写入、没有库存预占/释放、没有真实鉴权。
这些能力必须在接真实 OMS 时，按「人工确认 + 独立写通道」再设计，不能由 Agent 直接写库。

## 2. 模块结构

```text
src/rag_demo/merchant/
├── __init__.py            对外导出（get_merchant_repository / 模型 / 错误 / clamp_limit…）
├── models.py              frozen dataclass：Product / SKU / Inventory / Order / OrderItem
├── limits.py              limit 钳制纯函数（DEFAULT=20, MAX=100）
├── errors.py              结构化错误（稳定 code：MERCHANT_CONFIG / SEED / DATA / UNAVAILABLE）
├── repository.py          MerchantRepository 协议（跨 adapter 契约，可 runtime_checkable）
├── seeds.py               data/merchant/*.csv 读取 + 校验 + 规模下限
├── sqlite_repository.py   默认 SQLite 实现（m_* 表，只读查询）
└── factory.py             后端注册 / 选择 / 进程内缓存
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

## 5. 接口契约（`MerchantRepository`）

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
| `MERCHANT_CONFIG` | 后端名未知 / 配置非法 |
| `MERCHANT_SEED` | 种子文件缺失、列缺失、引用不一致、金额对不上、低于规模下限 |
| `MERCHANT_DATA` | 查询参数非法（如多租户查询缺 `merchant_id`） |
| `MERCHANT_UNAVAILABLE` | 数据层已关闭 / 文件不可读写 |

## 6. 种子数据（`data/merchant/`）

当前种子（两个商家，用于租户隔离测试）：

- 商家：`m_tea_001`（山雾茶业·8 商品）、`m_gear_002`（峰行户外·4 商品）；
- 12 个商品、24 个 SKU、28 条库存记录（含跨仓与 1 条零库存）、6 个订单、10 个订单行；
- 文件：`products.csv` / `skus.csv` / `inventory.csv` / `orders.csv` / `order_items.csv`，
  表头与字段含义见文件首行；金额为十进制字符串，时间为 ISO-8601 文本（`+08:00`）。

`seeds.load_seed_data()` 在入库前做完整性校验：

1. 主键唯一（product_id / sku / order_id；库存 (sku, warehouse_id) 唯一）；
2. 引用完整（SKU→商品、库存→SKU、订单行→SKU、订单行→订单），且**商家归属一致**；
3. 每个商品至少一个 SKU；
4. `订单总额 == Σ 行小计`，`行小计 == 数量 × 单价`（Decimal 精确比较）；
5. 规模下限（≥8/20/5）。

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
2. **只读**：v1 不做订单/库存写入；OMS 写操作（下单、改库存）必须走人工确认的独立通道；
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
- **边界**：C 商城下单仍走 `c_product/c_order` 表，商家库存目前是只读参考，没有和 C 端扣减做双写/预占；真实交易接入需 OMS 写通道 + 用户确认，见 §9。

## 8. 测试

```bash
uv run python -m pytest tests/test_merchant_store.py tests/test_c_end_store_agent_merchant.py tests/test_c_end_agent_merchant.py -q
# 结果：45 passed（商家数据层 + 店宠 Agent + C 伙伴 Agent 接入）
```

覆盖：种子规模下限与完整性、初始化幂等/force 重灌、env 路径覆盖、工厂缓存与重置、
商品/SKU/库存/订单查询、**租户隔离**（跨商家、`get_*` 作用域、缺 `merchant_id` 失败关闭）、
无库存 vs 不存在、limit 钳制（纯函数 + 查询路径）、可替换后端注册（Fake adapter）、
坏种子（引用缺失/规模不足/目录不存在）结构化拒绝、关闭后不可用。

## 9. 已知限制（v1，明确不是真实 OMS）

1. **不是真实 OMS 对接**：没有商家侧鉴权/签名/对账；种子是工作区里的静态样例数据；
2. **只读**：无订单创建/状态流转、无库存预占/释放、无退款；写能力等真实 OMS + 人工确认链路；
3. **无分页游标 / 时间范围过滤**：列表只有 limit + 买家/状态过滤；大商家需要补 offset/cursor；
4. **无价格历史 / 库存流水**：模型只有当前快照；经营分析若需要「改价/补货历史」要另建表；
5. **无多语言/多币种**：种子仅 CNY；模型保留了 currency 字段但无汇率逻辑；
6. **SQLite 单文件**：只适合开发/演示；并发写、备份、权限需由 PG adapter 承担；
7. **已接 API / Agent，但交易仍只读**：店宠与 C 端只读 API 已接；下单/扣库存/预占仍未接，
   C 商城仍用 `c_product/c_order`，商家库存只作参考；
8. **关键词搜索是 LIKE 子串**：不是全文检索；大语料应交给 PG/ES adapter 实现。

## 10. 变更记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v1 | 2026-10-30 | 新增可替换的商家数据层：模型/协议/SQLite adapter/种子校验/工厂与 38 例离线单测 |
