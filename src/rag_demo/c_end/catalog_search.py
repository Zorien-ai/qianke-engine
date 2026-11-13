"""C 端商品目录的轻量语义检索。

商家商品量很小（几十个 SPU），没有必要为每次推荐建立向量索引。
这里用「品类同义词 + 中文分词/字面命中 + 标题相似度」做确定性召回，
再由 Agent 负责解释和推荐；不引入额外模型调用或外部服务。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable

# 把用户的口语/品类词映射到商品标题和 category 里真实出现的词。
# key 匹配用户 query，value 是商品文本里可能出现的别名。
CATEGORY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "茶叶": ("茶", "绿茶", "红茶", "乌龙茶", "普洱茶", "白茶", "黑茶", "花茶", "龙井", "碧螺春", "毛尖", "单丛", "银针"),
    "茶": ("茶", "绿茶", "红茶", "乌龙茶", "普洱茶", "白茶", "黑茶", "花茶", "龙井", "碧螺春", "毛尖", "单丛", "银针"),
    "绿茶": ("绿茶", "龙井", "碧螺春", "毛尖", "银针"),
    "红茶": ("红茶", "正山小种", "金骏眉"),
    "黑茶": ("黑茶", "茶砖", "砖茶"),
    "白茶": ("白茶", "白牡丹", "银针"),
    "乌龙": ("乌龙茶", "乌龙", "单丛", "大红袍"),
    "普洱": ("普洱茶", "普洱", "熟茶", "生茶"),
    "花茶": ("花茶", "茉莉", "银针"),
    "户外": ("户外", "登山", "露营", "冲锋衣"),
    "跑鞋": ("跑鞋", "运动鞋", "鞋"),
    "双肩包": ("双肩包", "背包", "包"),
    "水壶": ("水壶", "保温杯", "杯"),
}

# 这些词不参与商品匹配，避免“推荐一下产品”把“产品”当成商品名。
STOPWORDS = {
    "产品", "商品", "东西", "一下", "推荐", "想要", "想买", "有没有",
    "什么", "哪些", "帮我", "看看", "一个", "一些", "可以", "适合",
}
_PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:/\\|()（）\[\]【】\"'“”‘’]+")


def normalize(text: str) -> str:
    return _PUNCT_RE.sub("", str(text or "").strip().lower())


def _matched_category_keys(raw: str) -> list[str]:
    matched = [key for key in CATEGORY_SYNONYMS if key in raw]
    if not matched:
        return []
    longest = max(len(key) for key in matched)
    return [key for key in matched if len(key) == longest]


def query_terms(query: str) -> set[str]:
    """展开同义词，并补充中文二元/三元片段，兼容“茶叶”“茶”等表达。"""
    raw = normalize(query)
    if not raw:
        return set()
    terms: set[str] = {raw}
    for key in _matched_category_keys(raw):
        terms.update(normalize(item) for item in CATEGORY_SYNONYMS[key])
    if len(raw) >= 2:
        terms.update(raw[index:index + 2] for index in range(len(raw) - 1))
    if len(raw) >= 3:
        terms.update(raw[index:index + 3] for index in range(len(raw) - 2))
    terms.discard("")
    terms.difference_update(STOPWORDS)
    return terms


def _product_text(product: Any) -> str:
    parts = [
        getattr(product, "title", ""),
        getattr(product, "category", ""),
        getattr(product, "brand", ""),
    ]
    return normalize(" ".join(str(part or "") for part in parts))


def _score(product: Any, raw_query: str, terms: set[str]) -> float:
    text = _product_text(product)
    if not text:
        return 0.0
    score = 0.0
    if raw_query and raw_query in text:
        score += 120.0
    for key in _matched_category_keys(raw_query):
        aliases = CATEGORY_SYNONYMS[key]
        for alias in aliases:
            normalized_alias = normalize(alias)
            if normalized_alias and normalized_alias in text:
                # 更长的别名更具体，优先于泛化的“茶”。
                score += 40.0 + min(len(normalized_alias), 6) * 6.0
                break
    for term in terms:
        if len(term) < 2:
            continue
        if term in text:
            score += 18.0 if len(term) == 2 else 28.0
    # 处理“龙井茶”“毛尖绿茶”这类标题写法：短词相似度作为兜底。
    title = normalize(getattr(product, "title", ""))
    if raw_query and title:
        ratio = SequenceMatcher(None, raw_query, title).ratio()
        if ratio >= 0.5:
            score += ratio * 20.0
    return score


def is_browse_query(query: str) -> bool:
    """「你家有什么」「全部商品」这类泛浏览，不要求具体品类。"""
    raw = normalize(query)
    if not raw:
        return False
    if any(key in raw for key in CATEGORY_SYNONYMS):
        return False
    return any(word in raw for word in ("什么", "东西", "全部", "所有", "商品", "产品", "货", "推荐"))


def rank_product_matches(products: Iterable[Any], query: str, limit: int = 20) -> list[Any]:
    """按语义匹配分数排序；没有命中时返回空列表，由调用方决定是否跨店兜底。"""
    raw = normalize(query)
    if not raw or not str(query or "").strip():
        return []
    terms = query_terms(query)
    ranked: list[tuple[float, str, Any]] = []
    for product in products:
        score = _score(product, raw, terms)
        if score <= 0:
            continue
        # 同分时按标题稳定排序，避免 SQL / 字典顺序导致结果抖动。
        ranked.append((score, normalize(getattr(product, "title", "")), product))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [product for _, _, product in ranked[:max(1, int(limit))]]
