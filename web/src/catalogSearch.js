// 商品搜索的轻量语义匹配：品类口语（茶叶/绿茶）映射到真实 category/title。
const CATEGORY_ALIASES = {
  茶叶: ["茶", "绿茶", "红茶", "乌龙茶", "普洱茶", "白茶", "黑茶", "花茶", "龙井", "碧螺春", "毛尖", "单丛", "银针"],
  茶: ["茶", "绿茶", "红茶", "乌龙茶", "普洱茶", "白茶", "黑茶", "花茶", "龙井", "碧螺春", "毛尖", "单丛", "银针"],
  绿茶: ["绿茶", "龙井", "碧螺春", "毛尖", "银针"],
  红茶: ["红茶", "正山小种", "金骏眉"],
  黑茶: ["黑茶", "茶砖", "砖茶"],
  白茶: ["白茶", "白牡丹", "银针"],
  乌龙: ["乌龙茶", "乌龙", "单丛", "大红袍"],
  普洱: ["普洱茶", "普洱", "熟茶", "生茶"],
  花茶: ["花茶", "茉莉", "银针"],
  户外: ["户外", "登山", "露营", "冲锋衣"],
  跑鞋: ["跑鞋", "运动鞋", "鞋"],
  双肩包: ["双肩包", "背包", "包"],
  水壶: ["水壶", "保温杯", "杯"],
};
const STOPWORDS = new Set(["产品", "商品", "东西", "一下", "推荐", "想要", "想买", "有没有", "什么", "哪些", "帮我", "看看"]);
const BROWSE_WORDS = ["全部", "所有", "什么", "东西", "商品", "产品", "货", "推荐"];

function normalize(value) {
  return String(value || "").trim().toLowerCase().replace(/[\s，。！？、；：,.!?;:/\\|()（）\[\]【】"'“”‘’]+/g, "");
}

function matchedCategoryKeys(raw) {
  const matched = Object.keys(CATEGORY_ALIASES).filter((key) => raw.includes(key));
  if (!matched.length) return [];
  const longest = Math.max(...matched.map((key) => key.length));
  return matched.filter((key) => key.length === longest);
}

export function catalogQueryTerms(keyword) {
  const raw = normalize(keyword);
  if (!raw) return new Set();
  const terms = new Set([raw]);
  for (const key of matchedCategoryKeys(raw)) {
    CATEGORY_ALIASES[key].forEach((item) => terms.add(normalize(item)));
  }
  if (raw.length >= 2) {
    for (let index = 0; index < raw.length - 1; index += 1) terms.add(raw.slice(index, index + 2));
  }
  for (const stopword of STOPWORDS) terms.delete(stopword);
  return terms;
}

export function productMatchesQuery(product, keyword) {
  if (!String(keyword || "").trim()) return true;
  const text = normalize([
    product?.title,
    product?.category,
    product?.brand,
    ...(Array.isArray(product?.skus) ? product.skus.map((sku) => sku?.spec) : []),
  ].join(" "));
  if (!text) return false;
  const raw = normalize(keyword);
  if (raw && text.includes(raw)) return true;
  const hasCategory = matchedCategoryKeys(raw).length > 0;
  if (!hasCategory && BROWSE_WORDS.some((word) => raw.includes(normalize(word)))) return true;
  return [...catalogQueryTerms(keyword)].some((term) => term.length >= 2 && text.includes(term));
}
