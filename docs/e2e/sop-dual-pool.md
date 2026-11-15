# SOP 池 / 画像池双池检索

日期：2026-11-15

## 结论

SOP 没有消失。

之前的问题：

```text
商家 owner 同时是企业管理员
→ wizard 构建走了企业库 ent_44
→ B 端画像读取商户库 mch_m_sim_tea
→ 导入池显示未构建，看起来像 SOP 没了
```

修复后：

```text
有商户绑定的 owner/admin
→ 优先构建到商户库 mch_<merchant_id>
→ 即使同时是企业管理员
```

## 双池数据实际位置

| 池 | 数据位置 | 内容 |
|---|---|---|
| 千客用户池 | 控制面 `b_qianke_user_profile` + 向量 | 会话 + 交易用户 |
| 导入用户池 | 商户库 `mch_<merchant_id>` | 导入用户画像 + SOP/规则文档 |

导入池里不是只有用户：

```text
user_profile_vectors   导入用户画像
wiki_vectors            SOP / 规则文档切片
search_index            画像 + 文档的 BM25/稀疏检索索引
```

所以“画像池 + SOP 池”是同一个导入数据空间里的两个检索池，不是两张平台级用户表。

## 当前验收结果

示例数据构建完成：

```text
导入用户：10
索引：14 条
规则文档：1 篇（merchant_rules.md，4 个切片）
千客用户：14
```

数据接入页：

```text
上传 CSV
上传规则文档
merchant_users.csv · 30 行 · 1 篇规则文档
规则文档：merchant_rules.md · 4 个切片
```

![SOP 导入](docs/design/b-profile-sop-import.png)

“全部用户”问小千：

```text
客单价怎么定义？同时列出最近买过绿茶的千客用户
```

返回：

- SOP 口径来自 merchant_rules.md
- 千客用户卡牌 5 人
- 导入用户卡牌 5 人
- coverage 明确区分：千客池 14 人、导入池 10 人

![双池检索](docs/design/b-profile-dual-pool.png)

## API 口径

```text
全部用户 = 千客用户池 + 导入用户池
问小千 = 导入侧 pipeline.prepare（画像 + SOP 文档）+ 千客池检索
SQL = 只覆盖导入用户池
```

## 验证

```text
pytest tests/test_mvp_merchant_scope.py：6 passed
web build：PASS
浏览器：SOP 文件可见、双池问小千同时返回两类卡牌和 SOP 来源
```
