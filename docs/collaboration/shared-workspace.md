# 共享工作区：CShop × CApp 共享购物车

> 这是 DeepSeek 与 Codex（Pachat 群 `vibe coding之神`）协作开发该任务的工作分支说明。
> 主分支不直接改动；所有提交先进入 `shared/cshop-cart`，再通过 PR 合回 `agent`。

## 基本信息

```text
仓库：https://github.com/Zorien-ai/qianke-engine
工作分支：shared/cshop-cart
合并目标：agent
基线：agent @ a646c18
```

## 任务

让 CApp 和 CShop 共用同一份购物车：

```text
CApp 加购 / 改规格 / 改数量
→ CShop 能读取同一购物车
→ CShop 合并报价
→ 下单成功后清空购物车
```

## 验收标准

1. CApp 加购后，CShop 购物车能看到同一商品、SKU、数量。
2. 规格 / 数量修改在两个入口保持一致，或明确以共享 store 为准。
3. 合并报价的金额、SKU、数量与后端 `items[]` 一致。
4. 下单成功后购物车清空。
5. 桌面和手机端可用，现有 pytest 不回归。

## 关键代码入口

```text
web/src/views/CApp.vue
  CApp 购物车 localStorage（qianke:cart）、全局抽屉、改规格

web/src/views/CShop.vue
  CShop 商品、报价面板、准备订单/确认订单

src/rag_demo/c_end/negotiation.py
  单商品/购物车 items[] 合并报价

src/rag_demo/c_end/store.py
  报价转订单草稿、商家库存预占、确认订单
```

## 本地运行

```bash
git clone -b shared/cshop-cart https://github.com/Zorien-ai/qianke-engine.git
cd qianke-engine

# 后端
python -m pytest tests/ -q

# 前端
cd web
npm install
npm run build
```

## 协作边界

```text
DeepSeek：
  - 合并报价 / 订单 / 库存后端
  - 共享 store 的接口与数据契约
  - 最终合并、测试、验收

Codex：
  - 前端共享购物车 UI
  - CApp / CShop 读取同一 cart store
  - 规格、数量、清空等交互
  - 不直接改 main / agent
```

## 提交与回报

- 每个提交保持单一职责，提交信息写清改动范围。
- 完成后在 Pachat 群回报：
  - 改动文件
  - 测试命令与结果
  - 未解决风险
- 如没有仓库写权限，在本地生成补丁并发到 Pachat：

```bash
git diff agent...HEAD > cshop-cart.patch
```

由 DeepSeek 审核后合入 `shared/cshop-cart` → `agent`。

## 安全

- 不要把 token、密钥、配对码写入仓库或群聊。
- 不提交 `certs/`、本地 `.env`、运行时上传文件。
- 不直接修改 `main`。
