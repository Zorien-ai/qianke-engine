# B 端商品手册 / SOP 自动同步

日期：2026-11-15

## 目标

商品手册、SOP、用户 CSV 文件变更后，自动上传到商家导入数据空间；构建前保留人工确认。

## 脚本

```text
scripts/b_import_sync.py
```

默认监听：

```text
data/samples/merchant_users.csv
data/samples/m_sim_tea_products.md
data/samples/m_sim_tea_sop.md
```

## 使用

```powershell
$env:B_IMPORT_PASSWORD = "Sim2026!"

# 检查一次；有变化就上传，生成待确认批次
python scripts/b_import_sync.py --once

# 人工确认后构建
python scripts/b_import_sync.py --confirm

# 持续监听，每 10 秒
python scripts/b_import_sync.py --watch --interval 10
```

安全边界：

- 只自动上传，不自动构建
- `--confirm` 后才写入商户数据空间
- 上传批次、字段映射写 `var/b_import_pending.json`
- 文件指纹写 `var/b_import_sync_state.json`
- 没有变化时重复执行是 no-op

## 当前已上传内容

```text
merchant_users.csv       30 行交易
m_sim_tea_products.md    山岚茶事 3 款商品手册
m_sim_tea_sop.md         发货 / 退换 / 价格 / 售后 SOP
```

构建结果：

```text
数据集：mch_m_sim_tea
导入用户：10
规则文档：2 篇 / 12 个切片
索引：22 条
数据状态：fresh
```

![商品手册与 SOP 构建完成](docs/design/b-profile-product-sop-built.png)

## 边界

- 本文档同步的是 **SOP / 商品说明知识**，进入导入数据空间的文档池。
- 结构化商品目录（m_product / m_sku / 库存）仍来自商家 OMS / 商家商品库；如果要做商品 CSV 导入，需要另建商品导入接口。
