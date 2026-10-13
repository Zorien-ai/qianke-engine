# reranker 会挤掉 wiki

## AI 分析

诊断结论非常清晰：

| 阶段 | wiki 是否在 | 说明 |
|---|---|---|
| RRF Top-20 | ✅ 在第 2 位 | 融合层没问题 |
| Rerank Top-5 | ❌ 消失 | 精排层把 wiki 挤掉了 |

## 为什么 reranker 会挤掉 wiki

bge-reranker-v2-m3 是 Cross-Encoder，它对 (query, passage) 打分倾向于字面与 query 高度重叠的完整叙述文本。

对比一下：

- 画像文本："用户U7508（高有明）：45岁女，深圳人……偏好美妆……客单价908元"
  - 命中 query 的：「女性」「美妆」「客单」
  - reranker 打分：0.9353
- wiki 文本："h1: 用户标签口径说明 h2: 高客单用户 定义：近90天平均客单价≥1000元……"
  - 命中 query 的：「高客单」，但整体像"规则说明"而非"用户描述"
  - reranker 打分：可能 0.65-0.75，被挤出 Top-5

这不是 bug，是 cross-encoder 的固有局限——它擅长"文本相似度"，不擅长"区分事实陈述和规则陈述"。

## 正确的解法：分来源 rerank

用户画像场景天然需要「数据 + 规则」同时呈现——画像告诉你"谁是高客单"，规则告诉你"高客单的定义是什么"。所以不能让它们在一个池子里竞争。

改成分开精排、各自取名额、再合并：

```python
# 修改 reranker.py，加一个新函数
def rerank_by_source(query, candidates, top_k_profile=3, top_k_wiki=2):
    """
    分来源精排：
    - 画像类（user_profile）：取 Top-N
    - 文档类（*.md）：取 Top-M
    - 合并后按 rerank_score 重排
    """
    profiles = [c for c in candidates if not c["source"].endswith(".md")]
    wikis = [c for c in candidates if c["source"].endswith(".md")]

    reranked_profiles = rerank(query, profiles, top_k=top_k_profile) if profiles else []
    reranked_wikis = rerank(query, wikis, top_k=top_k_wiki) if wikis else []

    combined = reranked_profiles + reranked_wikis
    combined.sort(key=lambda x: -x.get("rerank_score", 0))
    return combined
```

## 经过重新入库后的结果

```json
{
  "answer": "根据高客单口径：累计平均客单价 ≥ 1000 元 [来源4]。结合“女性”“偏好品类为美妆”筛选现有资料，结果如下（姓名与用户ID已脱敏）：\n\n**符合“高客单、喜欢美妆、女性”的用户：**\n\n1. **用户 U65\\*\\***（姓名脱敏：高\\*琛）  \n   - **事实**：31岁女性，成都人；累计订单1笔，总消费1850元，平均客单价1850元，偏好品类为美妆；最近一次购买在2024-09-04；活跃平台：ecommerce_data [来源2]。  \n   - **推断**：平均客单价1850元 ≥ 1000元，且为女性、偏好美妆，因此符合“高客单、喜欢美妆的女性用户”条件 [来源2][来源4]。\n\n2. **用户 U27\\*\\***（姓名脱敏：高\\*文）  \n   - **事实**：30岁女性，成都人；累计订单2笔，总消费5080元，平均客单价2540元，偏好品类为美妆；最近一次购买在2024-10-23；活跃平台：ecommerce_data、淘宝 [来源3]。  \n   - **推断**：平均客单价2540元 ≥ 1000元，且为女性、偏好美妆，因此符合“高客单、喜欢美妆的女性用户”条件 [来源3][来源4]。\n\n**不符合高客单口径的示例：**\n\n- **用户 U75\\*\\***（姓名脱敏：高\\*明）  \n  - **事实**：45岁女性，深圳人；累计订单2笔，总消费1816元，平均客单价908元，偏好品类为美妆；最近一次购买在2024-12-01；活跃平台：ecommerce_data [来源1]。  \n  - **推断**：平均客单价908元 < 1000元，按高客单定义不属于高客单用户 [来源1][来源4]。\n\n**结论**：根据现有资料，符合“高客单、喜欢美妆的女性用户”条件的是 **用户 U65\\*\\* 和用户 U27\\*\\***。现有资料未提供其他用户信息，因此无法确定是否还有更多符合者。",
  "sources": [
    {
      "index": 1,
      "source": "user_profile",
      "text": "用户U7508（高有明）：45岁女，深圳人。累计订单2笔，总消费1816元，平均客单价908元，偏好品类为美妆。最近一次购买在2024-12-01，活跃平台：ecommerce_data。"
    },
    {
      "index": 2,
      "source": "user_profile",
      "text": "用户U6569（高生琛）：31岁女，成都人。累计订单1笔，总消费1850元，平均客单价1850元，偏好品类为美妆。最近一次购买在2024-09-04，活跃平台：ecommerce_data。"
    },
    {
      "index": 3,
      "source": "user_profile",
      "text": "用户U2765（高江文）：30岁女，成都人。累计订单2笔，总消费5080元，平均客单价2540元，偏好品类为美妆。最近一次购买在2024-10-23，活跃平台：ecommerce_data,淘宝。"
    },
    {
      "index": 4,
      "source": "tag_definitions.md",
      "text": "h1: 用户标签口径说明 h2: 高客单用户\n定义：累计平均客单价 ≥ 1000 元。\n（注：当前画像数据为累计口径，T+1 更新）\n负责人：数据部-用户价值组。\n用途：高客单价商品推荐、VIP 服务"
    }
  ]
}
```
