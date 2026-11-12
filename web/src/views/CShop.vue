<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getJson, postJson } from "../api";

const route = useRoute();
const products = ref([]);
const productsLoading = ref(true);
const productsError = ref("");
const companion = ref(null);
const companionError = ref("");
const quote = ref(null);
const quoteError = ref("");
const quoteDraft = ref(null);
const quoteOrder = ref(null);
const quoteBusy = ref(false);
const negotiationBusy = ref(false);
const negotiationBudget = ref(500);
const message = ref("");
const categoryFilter = ref("全部");
const searchKeyword = ref("");
const sortMode = ref("default");
const selectedProduct = ref(null);
const selectedSku = ref(null);
const detailQuantity = ref(1);
const detailImageIndex = ref(0);
const detailImageErrors = ref({});
const productImageErrors = ref({});
const running = ref(false);
const agentError = ref("");
const reply = ref("");
const draft = ref(null);
const order = ref(null);
const threadId = ref("");
const decisionLoading = ref(false);
const lastAction = ref("");
const merchantFriendId = computed(() =>
  typeof route.query.friend_id === "string" ? route.query.friend_id : ""
);
const merchantId = computed(() =>
  typeof route.query.merchant_id === "string" ? route.query.merchant_id : ""
);
const merchantName = computed(() => {
  if (typeof route.query.merchant_name === "string") return route.query.merchant_name;
  if (quote.value?.merchant_name) return quote.value.merchant_name;
  return merchantId.value;
});
const shopScopeLabel = computed(() => merchantName.value || "小鱼精选");
const isMerchantShop = computed(() => Boolean(merchantFriendId.value));

const featuredProduct = computed(() => products.value.find((p) => p.category === "运动") || products.value[0] || null);
const categories = computed(() => {
  const unique = [];
  for (const product of products.value) {
    const category = String(product.category || "").trim();
    if (category && !unique.includes(category)) unique.push(category);
  }
  return ["全部", ...unique];
});
const filteredProducts = computed(() => {
  const keyword = String(searchKeyword.value || "").trim().toLowerCase();
  let list = products.value.filter((product) => {
    if (categoryFilter.value !== "全部" && product.category !== categoryFilter.value) return false;
    if (!keyword) return true;
    const haystack = [product.title, product.category, product.brand]
      .map((value) => String(value || "").toLowerCase())
      .join(" ");
    return haystack.includes(keyword);
  });
  list = [...list];
  if (sortMode.value === "price-asc") {
    list.sort((a, b) => productPrice(a) - productPrice(b));
  } else if (sortMode.value === "price-desc") {
    list.sort((a, b) => productPrice(b) - productPrice(a));
  } else if (sortMode.value === "stock-desc") {
    list.sort((a, b) => productStock(b) - productStock(a));
  }
  return list;
});
const hasDraft = computed(() => !!draft.value);
const hasOrder = computed(() => !!order.value);
const canSend = computed(() => !running.value && !decisionLoading.value && !hasDraft.value && message.value.trim().length > 0);

function money(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function productSkus(product) {
  const skus = Array.isArray(product?.skus) ? product.skus : [];
  const normalized = skus
    .filter((sku) => sku && sku.sku)
    .map((sku) => ({
      sku: String(sku.sku),
      spec: String(sku.spec || "默认规格"),
      price: Number(sku.price ?? product.price ?? 0),
      stock: Number(sku.stock ?? 0),
      in_stock: sku.in_stock !== false && Number(sku.stock ?? 0) > 0,
    }));
  if (normalized.length) return normalized;
  return [{
    sku: String(product?.sku || ""),
    spec: "默认规格",
    price: Number(product?.price ?? 0),
    stock: Number(product?.stock ?? 0),
    in_stock: Number(product?.stock ?? 0) > 0,
  }];
}

function defaultSku(product) {
  return productSkus(product)[0] || null;
}

function productPrice(product) {
  return Number(defaultSku(product)?.price ?? product?.price ?? 0);
}

function productStock(product) {
  return Number(defaultSku(product)?.stock ?? product?.stock ?? 0);
}

function productHint(product) {
  const stock = productStock(product);
  return stock > 0 ? `库存 ${stock}` : "暂时缺货";
}

function stockTone(product) {
  const stock = productStock(product);
  if (stock <= 0) return "out";
  if (stock <= 15) return "low";
  return "in";
}

function stockLabel(product) {
  const stock = productStock(product);
  if (stock <= 0) return "暂时缺货";
  if (stock <= 15) return `仅剩 ${stock} 件`;
  return `库存 ${stock}`;
}

function skuStockLabel(sku) {
  const stock = Number(sku?.stock ?? 0);
  if (stock <= 0) return "暂时缺货";
  if (stock <= 15) return `仅剩 ${stock} 件`;
  return `库存 ${stock}`;
}

function productImageVisible(product) {
  return Boolean(product?.image_url) && !productImageErrors.value[product.product_id];
}

function onProductImageError(product) {
  if (!product?.product_id) return;
  productImageErrors.value = { ...productImageErrors.value, [product.product_id]: true };
}

function productGallery(product) {
  const items = Array.isArray(product?.images) ? product.images : [];
  const normalized = items
    .filter((item) => item && item.url)
    .map((item) => ({
      url: String(item.url),
      thumb_url: String(item.thumb_url || item.url),
    }));
  if (!normalized.length && product?.image_url) {
    return [{ url: product.image_url, thumb_url: product.image_url }];
  }
  return normalized;
}

const detailSkus = computed(() => (selectedProduct.value ? productSkus(selectedProduct.value) : []));
const activeSku = computed(() => selectedSku.value || detailSkus.value[0] || null);
const detailMaxQuantity = computed(() =>
  Math.max(1, Math.min(20, Number(activeSku.value?.stock ?? 1) || 1))
);

const detailImages = computed(() => productGallery(selectedProduct.value));
const activeDetailImage = computed(() => detailImages.value[detailImageIndex.value] || null);
const detailImageVisible = computed(() => {
  const image = activeDetailImage.value;
  return Boolean(image?.url) && !detailImageErrors.value[image.url];
});

function selectDetailImage(index) {
  detailImageIndex.value = Number(index) || 0;
}

function onDetailImageError() {
  const url = activeDetailImage.value?.url;
  if (!url) return;
  detailImageErrors.value = { ...detailImageErrors.value, [url]: true };
}

function productTone(product) {
  const category = String(product?.category || "");
  const map = { 绿茶: "sage", 白茶: "stone", 红茶: "clay", 普洱茶: "amber", 礼盒: "rose", 运动: "stone" };
  return map[category] || "stone";
}

function speciesLabel(species) {
  const labels = {
    digital_companion: "数字伙伴",
    cat: "猫",
    fish: "鱼",
    robot: "机器人",
    brand_mascot: "品牌吉祥物",
  };
  return labels[species] || species || "伙伴";
}

async function loadCompanion() {
  companionError.value = "";
  try {
    companion.value = await getJson("/api/c/companion");
  } catch (e) {
    companionError.value = e?.detail || e?.message || "伙伴状态加载失败";
  }
}

async function loadQuote() {
  const quoteId = typeof route.query.quote === "string" ? route.query.quote : "";
  if (!quoteId) return;
  try {
    quote.value = await getJson(`/api/c/quotes/${encodeURIComponent(quoteId)}`);
  } catch (e) {
    quoteError.value = e?.detail || e?.message || "聊天报价不存在或已失效";
  }
}

async function prepareQuote() {
  if (!quote.value || quoteBusy.value) return;
  quoteBusy.value = true;
  quoteError.value = "";
  try {
    quoteDraft.value = await postJson(`/api/c/quotes/${encodeURIComponent(quote.value.quote_id)}/prepare`, {});
  } catch (e) {
    quoteError.value = e?.detail || e?.message || "报价转订单失败";
  } finally {
    quoteBusy.value = false;
  }
}

async function confirmQuote() {
  if (!quoteDraft.value || quoteBusy.value) return;
  quoteBusy.value = true;
  quoteError.value = "";
  try {
    const requestId = `c_quote_${Date.now()}`;
    quoteOrder.value = await postJson(
      `/api/c/orders/${encodeURIComponent(quoteDraft.value.order_id)}/confirm`,
      {
        confirmation_token: quoteDraft.value.confirmation_token,
        request_id: requestId,
      }
    );
    quoteDraft.value = null;
    await loadCompanion();
  } catch (e) {
    quoteError.value = e?.detail || e?.message || "订单确认失败";
  } finally {
    quoteBusy.value = false;
  }
}

async function cancelDraft() {
  if (!quoteDraft.value || quoteBusy.value) return;
  quoteBusy.value = true;
  quoteError.value = "";
  try {
    await postJson(`/api/c/orders/${encodeURIComponent(quoteDraft.value.order_id)}/cancel`, {});
    quoteDraft.value = null;
  } catch (e) {
    quoteError.value = e?.detail || e?.message || "草稿取消失败";
  } finally {
    quoteBusy.value = false;
  }
}

async function cancelQuote() {
  if (!quote.value || quoteBusy.value) return;
  quoteBusy.value = true;
  quoteError.value = "";
  try {
    await postJson(`/api/c/quotes/${encodeURIComponent(quote.value.quote_id)}/cancel`, {});
    quote.value = null;
  } catch (e) {
    quoteError.value = e?.detail || e?.message || "报价取消失败";
  } finally {
    quoteBusy.value = false;
  }
}

async function loadProducts() {
  productsLoading.value = true;
  productsError.value = "";
  try {
    const endpoint = merchantFriendId.value
      ? `/api/c/merchant/products?friend_id=${encodeURIComponent(merchantFriendId.value)}&limit=12`
      : "/api/c/products?limit=12";
    const data = await getJson(endpoint);
    products.value = (data?.products || []).map((product) => ({
      ...product,
      category: product.category || "精选",
      stock: Number(product.stock ?? 0),
    }));
    productImageErrors.value = {};
  } catch (e) {
    productsError.value = e?.detail || e?.message || "商品加载失败";
  } finally {
    productsLoading.value = false;
  }
}

async function ensureMerchantFriend() {
  if (!isMerchantShop.value || !merchantId.value) return;
  try {
    await postJson("/api/c/friends/merchants", { merchant_id: merchantId.value });
  } catch {
    // 加好友失败不影响逛店；CApp 仍可用已有会话。
  }
}

async function loadQuoteById(quoteId) {
  if (!quoteId) return;
  quote.value = await getJson(`/api/c/quotes/${encodeURIComponent(quoteId)}`);
  quoteDraft.value = null;
  quoteOrder.value = null;
  quoteError.value = "";
}

async function runAgent() {
  if (!canSend.value) return;
  running.value = true;
  agentError.value = "";
  lastAction.value = "";
  try {
    if (isMerchantShop.value) {
      const content = message.value.trim();
      const woken = content.startsWith("@店宠") ? content : `@店宠 ${content}`;
      const data = await postJson(
        `/api/c/friends/${encodeURIComponent(merchantFriendId.value)}/messages`,
        {
          content: woken,
          client_message_id: `cshop_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        }
      );
      const replyData = data?.reply || {};
      reply.value = replyData.content || "店宠暂时没有回复。";
      if (replyData.metadata?.quote_id) {
        await loadQuoteById(replyData.metadata.quote_id);
        lastAction.value = "店宠已给出报价，可在上方确认";
      } else {
        lastAction.value = "店宠已回复";
      }
      return;
    }
    const data = await postJson("/api/c/agent/run", { message: message.value.trim() });
    reply.value = data?.reply || "";
    threadId.value = data?.thread_id || "";
    if (data?.requires_confirmation && data?.draft) {
      draft.value = data.draft;
      order.value = null;
      lastAction.value = "请核对订单后确认";
    } else if (data?.order) {
      order.value = data.order;
      draft.value = null;
      lastAction.value = "订单已确认";
    }
  } catch (e) {
    agentError.value = e?.detail || e?.message || "导购服务暂时不可用";
  } finally {
    running.value = false;
  }
}

async function decide(approved) {
  if (!threadId.value || !hasDraft.value || decisionLoading.value) return;
  decisionLoading.value = true;
  agentError.value = "";
  try {
    const data = await postJson("/api/c/agent/resume", {
      thread_id: threadId.value,
      approved,
    });
    reply.value = data?.reply || reply.value;
    if (data?.order) {
      order.value = data.order;
      lastAction.value = "订单已确认";
    } else {
      lastAction.value = approved ? "确认完成" : "订单已取消";
    }
    draft.value = null;
    threadId.value = "";
    if (approved) await loadCompanion();
  } catch (e) {
    agentError.value = e?.detail || e?.message || "订单确认失败";
  } finally {
    decisionLoading.value = false;
  }
}

async function runMerchantNegotiation(needOverride = "", sku = "", quantity = 1) {
  if (!isMerchantShop.value || negotiationBusy.value) return;
  negotiationBusy.value = true;
  agentError.value = "";
  lastAction.value = "";
  try {
    const need =
      String(needOverride || "").trim() ||
      quote.value?.product_refs?.[0]?.title ||
      message.value.trim() ||
      products.value[0]?.title ||
      "商品";
    const data = await postJson("/api/c/negotiations", {
      need: need.slice(0, 80),
      budget: Math.max(1, Number(negotiationBudget.value) || 500),
      quantity: Math.max(1, Math.min(20, Number(quantity) || 1)),
      friend_id: merchantFriendId.value,
      ...(sku ? { sku } : {}),
    });
    const transcript = Array.isArray(data?.transcript) ? data.transcript : [];
    reply.value = transcript.map((item) => `${item.name}：${item.text}`).join("\n\n");
    if (data?.quote?.quote_id) {
      await loadQuoteById(data.quote.quote_id);
      lastAction.value = "双宠谈判达成，报价已生成";
    } else {
      lastAction.value = "这轮没有谈成，可调整需求再试";
    }
  } catch (e) {
    agentError.value = e?.detail || e?.message || "双宠谈判暂时不可用";
  } finally {
    negotiationBusy.value = false;
  }
}

function rememberProduct(product, sku = null, quantity = 1) {
  try {
    const selected = sku || defaultSku(product);
    localStorage.setItem("qianke:lastProduct", JSON.stringify({
      merchant_id: String(product?.merchant_id || merchantId.value || "").trim(),
      product_id: String(product?.product_id || "").trim(),
      title: String(product?.title || "").trim(),
      sku: String(selected?.sku || "").trim(),
      spec: String(selected?.spec || "").trim(),
      price: Number(selected?.price ?? product?.price ?? 0),
      quantity: Math.max(1, Math.min(20, Number(quantity) || 1)),
    }));
  } catch {
    // 本地存储不可用时不影响浏览
  }
}

function productNeedText(product, sku = null) {
  const selected = sku || defaultSku(product);
  const spec = selected?.spec && selected.spec !== "默认规格" ? ` ${selected.spec}` : "";
  const price = Number(selected?.price ?? product.price ?? 0);
  return `我想买 ${product.title}${spec}，预算 ${Math.ceil(price)} 元`;
}

function useProduct(product) {
  rememberProduct(product, defaultSku(product), 1);
  message.value = productNeedText(product, defaultSku(product));
}

function openProductDetail(product) {
  rememberProduct(product, defaultSku(product), 1);
  detailImageIndex.value = 0;
  detailImageErrors.value = {};
  selectedSku.value = defaultSku(product);
  detailQuantity.value = 1;
  selectedProduct.value = product;
}

function closeProductDetail() {
  selectedProduct.value = null;
  selectedSku.value = null;
}

function selectSku(sku) {
  selectedSku.value = sku;
  detailQuantity.value = 1;
  if (selectedProduct.value) rememberProduct(selectedProduct.value, sku, 1);
}

function changeQuantity(delta) {
  const next = Number(detailQuantity.value || 1) + Number(delta || 0);
  detailQuantity.value = Math.max(1, Math.min(detailMaxQuantity.value, next));
  if (selectedProduct.value) rememberProduct(selectedProduct.value, selectedSku.value, detailQuantity.value);
}

function askProduct(product, sku = null) {
  const selected = sku || selectedSku.value || defaultSku(product);
  closeProductDetail();
  rememberProduct(product, selected, detailQuantity.value);
  message.value = productNeedText(product, selected);
  window.setTimeout(() => document.getElementById("shop-message")?.focus(), 50);
}

function negotiateProduct(product, sku = null) {
  const selected = sku || selectedSku.value || defaultSku(product);
  closeProductDetail();
  if (!isMerchantShop.value) {
    askProduct(product, selected);
    return;
  }
  rememberProduct(product, selected, detailQuantity.value);
  message.value = productNeedText(product, selected);
  runMerchantNegotiation(product.title, selected?.sku || "", detailQuantity.value);
}

onMounted(() => {
  loadProducts();
  ensureMerchantFriend();
  loadCompanion();
  loadQuote();
});
</script>

<template>
  <div class="shop-page">
    <header class="shop-head">
      <div>
        <p class="shop-kicker">C-END · MARKET</p>
        <h2>今天想逛什么？</h2>
        <p class="shop-subtitle">
          {{ merchantFriendId ? `正在逛 ${shopScopeLabel}，价格和库存来自这家店。` : "小鱼替你从店里挑了这些。先看看，不急着买；需要时再问她。" }}
        </p>
      </div>
      <div class="shop-head-meta">
        <span v-if="merchantFriendId" class="shop-scope">{{ shopScopeLabel }}</span>
        <span class="shop-status" role="status">
          <span class="status-dot" />
          模拟订单 · 不接真实支付
        </span>
      </div>
    </header>

    <section v-if="featuredProduct" class="market-note" aria-label="今日手记">
      <p class="market-note-kicker">TODAY'S NOTE</p>
      <h3>{{ featuredProduct.title }}</h3>
      <p class="market-note-text">
        {{ featuredProduct.category }} · {{ productHint(featuredProduct) }}。小鱼说：先看合不合用，再决定要不要买。
      </p>
    </section>

    <section class="shop-grid" aria-label="商品与导购">
      <div class="catalog-panel">
        <div class="panel-head">
          <div>
            <h3>{{ merchantFriendId ? shopScopeLabel : "市集选物" }}</h3>
            <p>{{ merchantFriendId ? "该商家的真实商品与库存" : "价格和库存来自真实商品库" }}</p>
          </div>
          <span class="count">{{ filteredProducts.length }} / {{ products.length }} 件</span>
        </div>

        <div class="catalog-tools">
          <label class="product-search">
            <span class="sr-only">搜索商品</span>
            <span class="search-icon" aria-hidden="true">⌕</span>
            <input v-model.trim="searchKeyword" type="search" placeholder="搜商品、品牌或分类" />
          </label>
          <label class="product-sort">
            <span>排序</span>
            <select v-model="sortMode">
              <option value="default">综合</option>
              <option value="price-asc">价格从低到高</option>
              <option value="price-desc">价格从高到低</option>
              <option value="stock-desc">库存优先</option>
            </select>
          </label>
        </div>

        <div v-if="categories.length > 1" class="product-filters" role="group" aria-label="商品分类">
          <button
            v-for="category in categories"
            :key="category"
            type="button"
            class="product-filter"
            :class="{ active: categoryFilter === category }"
            @click="categoryFilter = category"
          >{{ category }}</button>
        </div>

        <p v-if="productsLoading" class="state-line" role="status">正在加载商品…</p>
        <p v-else-if="productsError" class="state-line state-error" role="alert">{{ productsError }}</p>
        <div v-else-if="!products.length" class="state-box">
          <strong>暂无商品</strong>
          <p>商品库为空，暂时无法推荐。</p>
        </div>
        <div v-else-if="!filteredProducts.length" class="state-box">
          <strong>没有匹配的商品</strong>
          <p>换个关键词，或者清除筛选。</p>
          <button type="button" class="ghost-btn" @click="searchKeyword = ''; categoryFilter = '全部'">清除筛选</button>
        </div>
        <div v-else class="product-list">
          <article
            v-for="product in filteredProducts"
            :key="product.product_id"
            class="product-row"
            @click="openProductDetail(product)"
          >
            <div
              class="product-mark"
              :class="[`tone-${productTone(product)}`, { 'has-photo': productImageVisible(product) }]"
              aria-hidden="true"
            >
              <img
                v-if="productImageVisible(product)"
                class="product-photo"
                :src="product.image_url"
                :alt="product.title"
                loading="lazy"
                @error="onProductImageError(product)"
              />
              <span class="product-mark-char">{{ product.category.slice(0, 1) }}</span>
              <span class="product-mark-brand">{{ product.brand || product.category }}</span>
            </div>
            <div class="product-main">
              <div class="product-top">
                <h4>{{ product.title }}</h4>
                <span class="category">{{ product.category }}</span>
              </div>
              <p class="product-story">
                <span class="stock-pill" :class="`is-${stockTone(product)}`">{{ stockLabel(product) }}</span>
                · 店宠可咨询
              </p>
              <div class="product-side">
                <strong>¥{{ money(productPrice(product)) }}</strong>
                <div class="product-actions">
                  <button class="ghost-btn" type="button" @click.stop="useProduct(product)">
                    {{ isMerchantShop ? "问店宠" : "问问小鱼" }}
                  </button>
                  <button class="ghost-btn product-detail-btn" type="button" @click.stop="openProductDetail(product)">详情</button>
                </div>
              </div>
            </div>
          </article>
        </div>
      </div>

      <div class="assistant-panel">
        <div class="panel-head">
          <div>
            <h3>{{ isMerchantShop ? "问问店宠" : "和小鱼说说" }}</h3>
            <p>{{ isMerchantShop ? "商品咨询 → 报价 → 商城确认" : "推荐 → 草稿 → 你确认 → 模拟下单" }}</p>
          </div>
          <span class="agent-badge">{{ isMerchantShop ? "Store Pet" : "LangGraph" }}</span>
        </div>

        <div v-if="companion && !isMerchantShop" class="companion-box">
          <div class="companion-mark" aria-hidden="true">{{ companion.name.slice(0, 1) }}</div>
          <div class="companion-main">
            <span class="companion-label">我的伙伴</span>
            <strong>{{ companion.name }}</strong>
            <p>{{ speciesLabel(companion.species) }} · Lv.{{ companion.level }}</p>
          </div>
          <div class="companion-stats">
            <span>饱食度</span>
            <div
              class="satiety-track"
              role="progressbar"
              :aria-valuenow="companion.satiety"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-label="`${companion.name} 饱食度`"
            >
              <span :style="{ width: `${companion.satiety}%` }" />
            </div>
            <small>{{ companion.satiety }}/100</small>
          </div>
        </div>
        <p v-if="companionError" class="state-line state-error" role="alert">{{ companionError }}</p>

        <section v-if="quote" class="quote-panel" aria-label="聊天报价">
          <div class="quote-panel-head">
            <div>
              <span class="quote-kicker">来自聊天的结构化报价</span>
              <h4>{{ quote.quote_id }}</h4>
            </div>
            <span class="quote-status">{{ quoteOrder ? "已确认" : "待确认" }}</span>
          </div>
          <div class="quote-chips">
            <span v-for="product in quote.product_refs" :key="product.product_id" class="quote-chip">
              {{ product.title || product.product_id }} × {{ product.quantity || 1 }}
            </span>
            <span v-for="policy in quote.policy_refs" :key="policy.policy_id" class="quote-chip policy">
              {{ policy.title || policy.policy_id }}
            </span>
          </div>
          <p v-if="quoteDraft" class="quote-hint">
            草稿金额 ¥{{ money(quoteDraft.original_amount) }}
            <template v-if="quoteDraft.discount_amount"> · 优惠 ¥{{ money(quoteDraft.discount_amount) }}</template>
            · 应付 ¥{{ money(quoteDraft.total_amount) }}
          </p>
          <p v-else class="quote-hint">报价只做引用；确认后才会扣库存。</p>
          <p v-if="quoteError" class="state-line state-error" role="alert">{{ quoteError }}</p>

          <div v-if="quoteOrder" class="quote-order" role="status">
            已创建 {{ quoteOrder.order_id }} · 应付 ¥{{ money(quoteOrder.total_amount) }}
          </div>
          <div v-else-if="quoteDraft" class="quote-actions">
            <button class="ghost-btn" type="button" :disabled="quoteBusy" @click="cancelDraft">
              取消草稿
            </button>
            <button class="primary-btn" type="button" :disabled="quoteBusy" @click="confirmQuote">
              {{ quoteBusy ? "提交中…" : "确认并创建模拟订单" }}
            </button>
          </div>
          <div v-else class="quote-actions">
            <button class="ghost-btn" type="button" :disabled="quoteBusy" @click="cancelQuote">
              取消报价
            </button>
            <button class="primary-btn" type="button" :disabled="quoteBusy" @click="prepareQuote">
              {{ quoteBusy ? "准备中…" : "使用此报价准备订单" }}
            </button>
          </div>
        </section>

        <label class="field-label" for="shop-message">{{ isMerchantShop ? "想问店宠什么？" : "你想买什么？" }}</label>
        <textarea
          id="shop-message"
          v-model="message"
          class="shop-input"
          rows="3"
          :disabled="running || hasDraft"
          :placeholder="isMerchantShop ? '例如：问商品、活动和优惠' : '例如：我想买什么，预算多少'"
          @keydown.ctrl.enter="runAgent"
          @keydown.meta.enter="runAgent"
        />
        <div class="send-row">
          <span class="hint">Ctrl / ⌘ + Enter 发送</span>
          <button class="primary-btn" type="button" :disabled="!canSend" @click="runAgent">
            <span v-if="running" class="spinner" aria-hidden="true" />
            {{ running ? (isMerchantShop ? "店宠思考中…" : "导购思考中…") : isMerchantShop ? "发送给店宠" : "发送给导购" }}
          </button>
        </div>

        <div v-if="isMerchantShop" class="negotiation-row">
          <label class="negotiation-budget">
            <span>预算 ¥</span>
            <input v-model.number="negotiationBudget" type="number" min="1" max="100000" step="10" />
          </label>
          <button
            class="ghost-btn"
            type="button"
            :disabled="negotiationBusy || running"
            @click="runMerchantNegotiation"
          >{{ negotiationBusy ? "双宠谈判中…" : "让小鱼去砍价" }}</button>
          <span>平台满减规则内协商，成交仍需确认</span>
        </div>

        <p v-if="agentError" class="state-line state-error" role="alert">{{ agentError }}</p>

        <div v-if="reply" class="reply-box" aria-live="polite">
          <span class="reply-label">{{ isMerchantShop ? "店宠回复" : "导购回复" }}</span>
          <p>{{ reply }}</p>
        </div>

        <section v-if="hasDraft && !isMerchantShop" class="confirm-box" aria-live="polite">
          <div class="confirm-head">
            <div>
              <span class="confirm-kicker">待确认</span>
              <h4>订单草稿</h4>
            </div>
            <strong>¥{{ money(draft.total_amount) }}</strong>
          </div>
          <ul class="draft-items">
            <li v-for="item in draft.items" :key="item.product_id">
              <span>{{ item.title }}</span>
              <span>{{ item.quantity }} × ¥{{ money(item.unit_price) }}</span>
            </li>
          </ul>
          <p class="confirm-note">确认前不会扣库存；商品价格或库存变化后需要重新准备。</p>
          <div class="confirm-actions">
            <button class="ghost-btn" type="button" :disabled="decisionLoading" @click="decide(false)">
              取消
            </button>
            <button class="primary-btn" type="button" :disabled="decisionLoading" @click="decide(true)">
              <span v-if="decisionLoading" class="spinner" aria-hidden="true" />
              {{ decisionLoading ? "提交中…" : "确认并创建模拟订单" }}
            </button>
          </div>
        </section>

        <section v-if="hasOrder && !isMerchantShop" class="order-box" aria-live="polite">
          <span class="confirm-kicker">已创建</span>
          <h4>模拟订单 {{ order.order_id }}</h4>
          <p>{{ order.items?.map((item) => `${item.title} × ${item.quantity}`).join(" / ") }}</p>
          <strong>¥{{ money(order.total_amount) }}</strong>
        </section>

        <p v-if="lastAction && !hasOrder" class="action-line" role="status">{{ lastAction }}</p>
      </div>
    </section>
  </div>

  <div v-if="selectedProduct" class="product-detail-mask" @click.self="closeProductDetail">
    <section class="product-detail" role="dialog" aria-modal="true" :aria-label="`${selectedProduct.title} 商品详情`">
      <header class="product-detail-head">
        <div>
          <span class="product-detail-kicker">PRODUCT · {{ selectedProduct.category }}</span>
          <h3>{{ selectedProduct.title }}</h3>
        </div>
        <button type="button" class="product-detail-close" aria-label="关闭商品详情" @click="closeProductDetail">×</button>
      </header>
      <div class="product-detail-body">
        <div class="product-detail-gallery">
          <div
            class="product-detail-art"
            :class="[`tone-${productTone(selectedProduct)}`, { 'has-photo': detailImageVisible }]"
          >
            <img
              v-if="detailImageVisible"
              class="product-photo"
              :src="activeDetailImage.url"
              :alt="selectedProduct.title"
              @error="onDetailImageError"
            />
            <span class="product-mark-char">{{ selectedProduct.category.slice(0, 1) }}</span>
            <span class="product-mark-brand">{{ selectedProduct.brand || selectedProduct.category }}</span>
          </div>
          <div v-if="detailImages.length > 1" class="product-detail-thumbs" aria-label="商品图片">
            <button
              v-for="(image, index) in detailImages"
              :key="image.url"
              type="button"
              class="product-detail-thumb"
              :class="{ active: detailImageIndex === index }"
              :aria-label="`查看第 ${index + 1} 张图片`"
              @click="selectDetailImage(index)"
            >
              <img :src="image.thumb_url || image.url" alt="" loading="lazy" />
            </button>
          </div>
        </div>
        <div class="product-detail-info">
          <p class="product-detail-store">{{ shopScopeLabel }} · 店宠在线</p>
          <p class="product-detail-brand">{{ selectedProduct.brand || "店铺商品" }} · {{ selectedProduct.category }}</p>
          <div class="product-detail-price">
            <strong>¥{{ money(activeSku?.price ?? selectedProduct.price) }}</strong>
            <span>{{ activeSku ? skuStockLabel(activeSku) : productHint(selectedProduct) }}</span>
          </div>
          <div class="product-detail-tags">
            <span>模拟订单</span><span>{{ activeSku ? skuStockLabel(activeSku) : productHint(selectedProduct) }}</span><span>7 天无理由</span>
          </div>
          <div v-if="detailSkus.length" class="sku-selector">
            <p class="field-label">规格</p>
            <div class="spec-row" role="group" aria-label="选择规格">
              <button
                v-for="sku in detailSkus"
                :key="sku.sku"
                type="button"
                class="spec-chip"
                :class="{ active: activeSku?.sku === sku.sku, soldout: !sku.in_stock }"
                :disabled="!sku.in_stock"
                @click="selectSku(sku)"
              >
                <span>{{ sku.spec }}</span>
                <small>¥{{ money(sku.price) }}</small>
                <em v-if="!sku.in_stock">缺货</em>
              </button>
            </div>
          </div>
          <div class="quantity-selector">
            <span class="field-label">数量</span>
            <div class="quantity-stepper">
              <button type="button" aria-label="减少数量" :disabled="detailQuantity <= 1" @click="changeQuantity(-1)">−</button>
              <strong>{{ detailQuantity }}</strong>
              <button type="button" aria-label="增加数量" :disabled="detailQuantity >= detailMaxQuantity" @click="changeQuantity(1)">＋</button>
              <small>当前规格最多 {{ detailMaxQuantity }} 件</small>
            </div>
          </div>
          <dl class="product-detail-meta">
            <div><dt>商品编号</dt><dd>{{ selectedProduct.product_id }}</dd></div>
            <div v-if="activeSku?.sku"><dt>SKU</dt><dd>{{ activeSku.sku }}</dd></div>
            <div><dt>店铺</dt><dd>{{ shopScopeLabel }}</dd></div>
          </dl>
          <div class="product-detail-service">
            <strong>店铺服务</strong>
            <p>现货 48 小时内发出 · 支持 7 天无理由 · 成交前需逐单确认</p>
          </div>
          <div class="product-detail-actions">
            <button type="button" class="primary-btn" @click="askProduct(selectedProduct, activeSku)" :disabled="activeSku && !activeSku.in_stock">
              {{ isMerchantShop ? "问店宠" : "问问小鱼" }}
            </button>
            <button v-if="isMerchantShop" type="button" class="ghost-btn" :disabled="negotiationBusy || (activeSku && !activeSku.in_stock)" @click="negotiateProduct(selectedProduct, activeSku)">
              {{ negotiationBusy ? "谈判中…" : "让小鱼去砍价" }}
            </button>
          </div>
          <p class="product-detail-note">报价与订单均为模拟，不接真实支付。</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.shop-page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 8px 0 40px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.shop-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.shop-kicker,
.confirm-kicker {
  margin: 0 0 6px;
  color: var(--primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.shop-head h2 {
  font-size: 24px;
}

.shop-subtitle {
  max-width: 650px;
  margin-top: 7px;
  color: var(--text-2);
  font-size: 13px;
}

.shop-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: 0 0 auto;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-2);
  font-size: 11px;
  white-space: nowrap;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
}

.shop-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(380px, 0.95fr);
  gap: 18px;
  align-items: start;
}

.catalog-panel,
.assistant-panel {
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 13px;
  border-bottom: 1px solid var(--border);
}

.panel-head h3 {
  font-size: 16px;
}

.panel-head p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.count,
.agent-badge {
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--surface-3);
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 11px;
  white-space: nowrap;
}

.companion-box {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.companion-mark {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 50%;
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 700;
}

.companion-main {
  min-width: 0;
  flex: 1;
}

.companion-label {
  display: block;
  color: var(--muted);
  font-size: 10px;
}

.companion-main strong {
  display: block;
  font-size: 13px;
}

.companion-main p {
  margin-top: 2px;
  color: var(--muted);
  font-size: 11px;
}

.companion-stats {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 4px;
  flex: 0 0 86px;
  color: var(--muted);
  font-size: 10px;
}

.satiety-track {
  width: 86px;
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--border);
}

.satiety-track > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
}

.companion-stats small {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 9px;
}

.quote-panel {
  margin-top: 12px;
  padding: 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.quote-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.quote-kicker {
  color: var(--primary);
  font-size: 10px;
  font-weight: 700;
}

.quote-panel-head h4 {
  margin-top: 3px;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 500;
}

.quote-status {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 9px;
}

.quote-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}

.quote-chip {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 10px;
}

.quote-chip.policy {
  background: var(--primary-soft);
  color: var(--primary);
}

.quote-hint {
  margin-top: 8px;
  color: var(--muted);
  font-size: 10px;
}

.quote-actions {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
  margin-top: 9px;
}

.quote-order {
  margin-top: 9px;
  padding: 7px 8px;
  border-radius: var(--radius-xs);
  background: var(--success-soft);
  color: var(--success);
  font-size: 11px;
}

.product-list {
  display: flex;
  flex-direction: column;
}

.product-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}

.product-row:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.product-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  border-radius: var(--radius-xs);
  background: var(--surface-3);
  color: var(--text-2);
  font-weight: 700;
}

.product-main {
  min-width: 0;
  flex: 1;
}

.product-top {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.product-top h4 {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category {
  flex: 0 0 auto;
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 10px;
}

.product-main p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
}

.product-side {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 5px;
  flex: 0 0 auto;
}

.product-side strong {
  font-family: var(--mono);
  font-size: 13px;
}

.field-label {
  display: block;
  margin: 15px 0 6px;
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}

.shop-input {
  width: 100%;
  resize: vertical;
  min-height: 78px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text);
  font: inherit;
  font-size: 13px;
  line-height: 1.6;
}

.shop-input:focus {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.shop-input:disabled {
  cursor: not-allowed;
  opacity: 0.68;
}

.send-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 9px;
}

.hint {
  color: var(--muted);
  font-size: 11px;
}

.primary-btn,
.ghost-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  border-radius: var(--radius-xs);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.primary-btn {
  padding: 0 13px;
  border: 1px solid var(--primary);
  background: var(--primary);
  color: #fff;
}

.primary-btn:hover:not(:disabled) {
  background: var(--primary-strong);
}

.primary-btn:disabled,
.ghost-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.ghost-btn {
  padding: 0 10px;
  border: 1px solid var(--border-strong);
  background: transparent;
  color: var(--text-2);
}

.ghost-btn:hover:not(:disabled) {
  background: var(--surface-2);
}

.spinner {
  width: 11px;
  height: 11px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.state-line {
  margin-top: 13px;
  color: var(--muted);
  font-size: 12px;
}

.state-error {
  color: var(--danger);
}

.state-box {
  padding: 28px 12px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
}

.state-box strong {
  display: block;
  margin-bottom: 4px;
  color: var(--text-2);
}

.reply-box,
.confirm-box,
.order-box {
  margin-top: 14px;
  padding: 13px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.reply-label {
  display: block;
  margin-bottom: 5px;
  color: var(--muted);
  font-size: 11px;
}

.reply-box p {
  color: var(--text-2);
  font-size: 13px;
  white-space: pre-wrap;
}

.confirm-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.confirm-head h4 {
  font-size: 14px;
}

.confirm-head strong {
  font-family: var(--mono);
  font-size: 16px;
}

.draft-items {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 11px 0 0;
  padding: 10px 0 0;
  border-top: 1px solid var(--border);
  list-style: none;
}

.draft-items li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-2);
  font-size: 12px;
}

.confirm-note {
  margin-top: 11px;
  color: var(--muted);
  font-size: 11px;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 13px;
}

.order-box h4 {
  margin-top: 3px;
  font-size: 14px;
}

.order-box p {
  margin: 7px 0;
  color: var(--text-2);
  font-size: 12px;
}

.order-box strong {
  font-family: var(--mono);
  font-size: 16px;
}

.action-line {
  margin-top: 12px;
  color: var(--text-2);
  font-size: 12px;
}

@media (max-width: 920px) {
  .shop-grid {
    grid-template-columns: 1fr;
  }

  .shop-head {
    flex-direction: column;
  }
}

@media (max-width: 560px) {
  .shop-head,
  .catalog-panel,
  .assistant-panel {
    padding: 14px;
  }

  .send-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .primary-btn {
    width: 100%;
  }
}

/* ---------- 暖白市集 · 编辑风 ---------- */
.shop-page {
  --bg: #f7f3ea;
  --surface: #fffdf8;
  --surface-2: #f7f3ea;
  --surface-3: #efe7da;
  --border: #e4dccd;
  --text: #1e1b16;
  --text-2: #6b6258;
  --muted: #8a7f72;
  --primary: #d95f3b;
  --primary-soft: #f6e3da;
  --danger: #a33f36;
  --radius: 14px;
  --radius-xs: 9px;
  --shadow-sm: none;
  color: var(--text);
}

.shop-head,
.catalog-panel,
.assistant-panel,
.market-note {
  border-color: var(--border);
  background: var(--surface);
  box-shadow: none;
}

.shop-head {
  padding: 18px 18px 16px;
  border-radius: 16px;
}

.shop-kicker,
.market-note-kicker {
  margin: 0 0 6px;
  color: var(--primary);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.18em;
}

.shop-head h2,
.market-note h3,
.panel-head h3,
.product-top h4 {
  font-family: Georgia, "Noto Serif SC", "Songti SC", serif;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.shop-head h2 {
  margin: 0;
  font-size: 26px;
  line-height: 1.25;
}

.shop-subtitle {
  max-width: 36em;
  color: var(--text-2);
  font-size: 11px;
  line-height: 1.7;
}

.shop-status {
  border-color: var(--border);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 10px;
}

.market-note {
  padding: 15px 16px;
  border: 1px solid var(--border);
  border-radius: 14px;
}

.market-note h3 {
  margin: 0 0 5px;
  font-size: 20px;
  line-height: 1.35;
}

.market-note-text {
  margin: 0;
  color: var(--text-2);
  font-size: 10px;
  line-height: 1.7;
}

.panel-head h3 {
  font-size: 17px;
}

.panel-head p {
  color: var(--muted);
  font-size: 10px;
}

.catalog-panel,
.assistant-panel {
  padding: 15px;
  border-radius: 14px;
}

.product-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.product-row {
  display: flex;
  align-items: stretch;
  flex-direction: column;
  gap: 0;
  overflow: hidden;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
}

.product-mark {
  width: 100%;
  height: 92px;
  margin: 0;
  border: 0;
  border-radius: 0;
  display: grid;
  place-items: center;
  color: rgba(30, 27, 22, 0.36);
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 38px;
  font-weight: 600;
}

.product-row:nth-child(1) .product-mark { background: linear-gradient(145deg, #d9ccb7, #b6a084 58%, #efe5d3); }
.product-row:nth-child(2) .product-mark { background: linear-gradient(145deg, #cdd5c5, #81927b 60%, #e6e9df); }
.product-row:nth-child(3) .product-mark { background: linear-gradient(145deg, #e6d2c2, #c38d70 65%, #f2e5d9); }
.product-row:nth-child(4) .product-mark { background: linear-gradient(145deg, #d8d2c7, #a89a87 62%, #ece5da); }
.product-row:nth-child(5) .product-mark { background: linear-gradient(145deg, #e4d9c2, #bda474 62%, #f1e8d8); }
.product-row:nth-child(6) .product-mark { background: linear-gradient(145deg, #d9d9d1, #999a8e 62%, #ecece5); }

.product-main {
  width: 100%;
  padding: 10px;
}

.product-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 6px;
}

.product-top h4 {
  margin: 0;
  font-size: 13px;
  line-height: 1.4;
}

.product-top .category {
  flex: none;
  color: var(--primary);
  font-size: 9px;
}

.product-story {
  margin: 5px 0 0;
  color: var(--text-2);
  font-size: 10px;
  line-height: 1.55;
}

.product-side {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-top: 9px;
}

.product-side strong {
  color: var(--primary);
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 13px;
}

.ghost-btn {
  padding: 5px 8px;
  border-color: var(--border);
  border-radius: 999px;
  background: transparent;
  color: var(--text-2);
  font-size: 10px;
}

.ghost-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.primary-btn {
  border-radius: 999px;
  background: var(--primary);
  color: #fffdf8;
}

.primary-btn:hover {
  background: #b4492f;
}

.field-label {
  color: var(--text-2);
  font-size: 11px;
}

.shop-input {
  border-color: var(--border);
  border-radius: 12px;
  background: var(--surface-2);
  color: var(--text);
  font-size: 12px;
}

.shop-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}

.companion-box,
.reply-box,
.confirm-box,
.order-box,
.quote-panel {
  border-color: var(--border);
  background: var(--surface-2);
  box-shadow: none;
}

.agent-badge,
.count,
.quote-status {
  border-color: var(--border);
  background: var(--surface-2);
  color: var(--text-2);
}

.reply-label,
.confirm-kicker,
.quote-kicker {
  color: var(--primary);
}

@media (max-width: 360px) {
  .product-list {
    grid-template-columns: 1fr;
  }

  .shop-head h2 {
    font-size: 23px;
  }
}



.shop-head-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.shop-scope {
  padding: 5px 9px;
  border: 1px solid #d95f3b;
  border-radius: 999px;
  color: #b74b2d;
  background: #f8e6dd;
  font-size: 11px;
}


.negotiation-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 0 8px;
}

.negotiation-row span {
  color: var(--muted);
  font-size: 10px;
}


.negotiation-budget {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--muted);
  font-size: 10px;
}

.negotiation-budget input {
  width: 72px;
  padding: 5px 6px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 11px;
}


/* ---------- 商品卡 / 商品详情（JD 信息层级，暖白 CShop 风格） ---------- */
.product-filters {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 10px 0 12px;
}

.product-filter {
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: transparent;
  color: var(--text-2);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.product-filter.active {
  border-color: var(--text);
  background: var(--text);
  color: var(--surface);
}

.product-row {
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease;
}

.product-row:hover {
  transform: translateY(-2px);
  border-color: rgba(217, 95, 59, 0.45);
}

.product-mark {
  position: relative;
  flex-direction: column;
  gap: 4px;
  overflow: hidden;
  transition: filter 0.15s ease;
}

.product-mark::after {
  content: "";
  position: absolute;
  right: 12%;
  bottom: 14%;
  width: 42%;
  height: 10%;
  border-radius: 50%;
  background: rgba(30, 27, 22, 0.12);
  filter: blur(5px);
}

.product-mark-char {
  position: relative;
  z-index: 1;
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 38px;
  line-height: 1;
  color: rgba(30, 27, 22, 0.58);
  text-shadow: 0 1px 0 rgba(255, 253, 248, 0.5);
}

.product-mark-brand {
  position: relative;
  z-index: 1;
  color: rgba(30, 27, 22, 0.52);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.product-mark.tone-sage { background: linear-gradient(145deg, #d9e1cf, #9bab8b 60%, #edf0e4) !important; }
.product-mark.tone-stone { background: linear-gradient(145deg, #e4e0d6, #b8b1a5 60%, #f1ede4) !important; }
.product-mark.tone-clay { background: linear-gradient(145deg, #e8cfbf, #c88f74 62%, #f3e6dc) !important; }
.product-mark.tone-amber { background: linear-gradient(145deg, #ecd9bd, #c5a06d 62%, #f5ebdc) !important; }
.product-mark.tone-rose { background: linear-gradient(145deg, #e8d1ca, #c99c92 62%, #f5e8e4) !important; }

.product-side {
  align-items: flex-end;
  flex-direction: column;
  gap: 8px;
}

.product-actions {
  display: flex;
  gap: 5px;
  width: 100%;
}

.product-actions .ghost-btn {
  flex: 1;
  min-height: 28px;
  padding: 0 7px;
  border-radius: 7px;
  font-size: 10px;
}

.product-actions .product-detail-btn {
  flex: 0 0 auto;
  color: var(--muted);
}

.product-detail-mask {
  position: fixed;
  inset: 0;
  z-index: 85;
  display: grid;
  place-items: center;
  padding: 22px;
  background: rgba(30, 27, 22, 0.36);
  backdrop-filter: blur(3px);
}

.product-detail {
  width: min(760px, 100%);
  max-height: calc(100dvh - 44px);
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: var(--surface);
  box-shadow: 0 24px 70px rgba(30, 27, 22, 0.2);
}

.product-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 17px 20px 14px;
  border-bottom: 1px solid var(--border);
}

.product-detail-kicker {
  color: var(--primary);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.product-detail-head h3 {
  margin: 4px 0 0;
  font-family: Georgia, "Noto Serif SC", serif;
  font-size: 23px;
  line-height: 1.3;
  font-weight: 600;
}

.product-detail-close {
  flex: none;
  width: 30px;
  height: 30px;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: transparent;
  color: var(--text-2);
  font: inherit;
  font-size: 19px;
  line-height: 1;
  cursor: pointer;
}

.product-detail-body {
  display: grid;
  grid-template-columns: 0.95fr 1.05fr;
  gap: 0;
}

.product-detail-art {
  position: relative;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  min-height: 340px;
  margin: 20px;
  border-radius: 15px;
  background: linear-gradient(145deg, #d9e1cf, #9bab8b 60%, #edf0e4);
}

.product-detail-art.tone-stone { background: linear-gradient(145deg, #e4e0d6, #b8b1a5 60%, #f1ede4); }
.product-detail-art.tone-clay { background: linear-gradient(145deg, #e8cfbf, #c88f74 62%, #f3e6dc); }
.product-detail-art.tone-amber { background: linear-gradient(145deg, #ecd9bd, #c5a06d 62%, #f5ebdc); }
.product-detail-art.tone-rose { background: linear-gradient(145deg, #e8d1ca, #c99c92 62%, #f5e8e4); }

.product-detail-art .product-mark-char {
  font-size: 92px;
  color: rgba(30, 27, 22, 0.55);
}

.product-detail-art .product-mark-brand {
  font-size: 12px;
}

.product-detail-info {
  padding: 20px 22px 22px 4px;
}

.product-detail-store {
  margin: 0;
  color: var(--text-2);
  font-size: 11px;
}

.product-detail-brand {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 11px;
}

.product-detail-price {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-top: 16px;
}

.product-detail-price strong {
  color: var(--primary);
  font-family: var(--mono);
  font-size: 30px;
  font-weight: 600;
}

.product-detail-price span {
  color: var(--muted);
  font-size: 10px;
}

.product-detail-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 9px;
}

.product-detail-tags span {
  padding: 3px 7px;
  border-radius: 5px;
  background: var(--primary-soft);
  color: #9d4c31;
  font-size: 9px;
}

.product-detail-meta {
  display: grid;
  gap: 6px;
  margin: 16px 0 0;
  padding: 11px 12px;
  border-radius: 9px;
  background: var(--surface-2);
}

.product-detail-meta > div {
  display: flex;
  gap: 12px;
  font-size: 10px;
}

.product-detail-meta dt {
  flex: 0 0 58px;
  color: var(--muted);
}

.product-detail-meta dd {
  margin: 0;
  color: var(--text-2);
  word-break: break-all;
}

.product-detail-service {
  margin-top: 14px;
}

.product-detail-service strong {
  color: var(--text);
  font-size: 11px;
}

.product-detail-service p {
  margin: 4px 0 0;
  color: var(--text-2);
  font-size: 10px;
  line-height: 1.7;
}

.product-detail-actions {
  display: flex;
  gap: 8px;
  margin-top: 18px;
}

.product-detail-actions .primary-btn,
.product-detail-actions .ghost-btn {
  flex: 1;
  min-height: 38px;
  border-radius: 9px;
  font-size: 12px;
}

.product-detail-actions .ghost-btn {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: #9d4c31;
}

.product-detail-note {
  margin: 10px 0 0;
  color: var(--muted);
  font-size: 9px;
  text-align: center;
}

@media (max-width: 820px) {
  .product-detail-mask {
    place-items: end center;
    padding: 0;
  }

  .product-detail {
    width: 100%;
    max-height: 92dvh;
    border-radius: 18px 18px 0 0;
  }

  .product-detail-body {
    display: block;
  }

  .product-detail-gallery {
    padding: 14px 14px 0;
  }

  .product-detail-art {
    min-height: 210px;
    margin: 0;
  }

  .product-detail-art .product-mark-char {
    font-size: 66px;
  }

  .product-detail-info {
    padding: 14px 16px calc(18px + env(safe-area-inset-bottom));
  }

  .product-detail-actions {
    position: sticky;
    bottom: 0;
    padding-top: 8px;
    background: var(--surface);
  }
}

.product-detail-gallery {
  min-width: 0;
  padding: 20px 0 20px 20px;
}

.product-detail-gallery .product-detail-art {
  margin: 0;
}

.product-detail-thumbs {
  display: flex;
  gap: 7px;
  margin-top: 9px;
  overflow-x: auto;
}

.product-detail-thumb {
  flex: 0 0 54px;
  width: 54px;
  height: 54px;
  padding: 2px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  cursor: pointer;
}

.product-detail-thumb.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px var(--primary);
}

.product-detail-thumb img {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 5px;
  object-fit: cover;
}

/* ---------- 商品照片 ---------- */
.product-photo {
  position: absolute;
  inset: 0;
  z-index: 2;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.product-mark.has-photo {
  flex: 0 0 auto;
  height: auto;
  aspect-ratio: 4 / 3;
}

.product-mark.has-photo::after {
  display: none;
}

.product-mark.has-photo .product-mark-char,
.product-mark.has-photo .product-mark-brand,
.product-detail-art.has-photo .product-mark-char,
.product-detail-art.has-photo .product-mark-brand {
  display: none;
}

.product-detail-art {
  overflow: hidden;
}

.product-detail-art .product-photo {
  border-radius: inherit;
}

/* ---------- P2 搜索 / 排序 / SKU ---------- */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.catalog-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0 8px;
}

.product-search {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
}

.product-search .search-icon {
  color: var(--muted);
  font-size: 16px;
  line-height: 1;
}

.product-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 12px;
}

.product-search input::placeholder {
  color: var(--muted);
}

.product-sort {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  color: var(--muted);
  font-size: 10px;
}

.product-sort select {
  height: 34px;
  max-width: 118px;
  padding: 0 7px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
  color: var(--text-2);
  font: inherit;
  font-size: 10px;
}

.stock-pill {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  padding: 0 5px;
  border-radius: 4px;
  font-size: 9px;
  font-weight: 600;
}

.stock-pill.is-in {
  color: var(--sage, #6f7f63);
  background: var(--sage-soft, #e9eee3);
}

.stock-pill.is-low {
  color: #9d4c31;
  background: var(--accent-soft, #f6e3da);
}

.stock-pill.is-out {
  color: var(--muted);
  background: var(--surface-2, #f7f3ea);
}

.sku-selector {
  margin-top: 14px;
}

.sku-selector .field-label {
  margin: 0 0 7px;
}

.spec-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.spec-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text-2);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.spec-chip small {
  color: var(--muted);
  font-size: 9px;
}

.spec-chip.active {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: #9d4c31;
  font-weight: 600;
}

.spec-chip.active small {
  color: #9d4c31;
}

.spec-chip.soldout {
  cursor: not-allowed;
  opacity: 0.55;
}

.spec-chip em {
  color: var(--danger, #a33f36);
  font-size: 9px;
  font-style: normal;
}

@media (max-width: 560px) {
  .catalog-tools {
    align-items: stretch;
    flex-direction: column;
  }

  .product-sort {
    justify-content: flex-end;
  }

  .product-sort select {
    flex: 1;
    max-width: none;
  }
}


.quantity-selector {
  margin-top: 13px;
}

.quantity-selector .field-label {
  margin: 0 0 7px;
}

.quantity-stepper {
  display: flex;
  align-items: center;
  gap: 7px;
}

.quantity-stepper button {
  width: 30px;
  height: 30px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 15px;
  cursor: pointer;
}

.quantity-stepper button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.quantity-stepper strong {
  min-width: 26px;
  text-align: center;
  font-size: 12px;
}

.quantity-stepper small {
  color: var(--muted);
  font-size: 9px;
}

</style>
