<script setup>
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { getJson } from "../api";

const products = ref([]);
const loading = ref(true);
const error = ref("");
const imageErrors = ref({});

function money(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function productPrice(product) {
  const skus = Array.isArray(product?.skus) ? product.skus : [];
  const prices = skus.map((sku) => Number(sku.price)).filter((value) => Number.isFinite(value));
  if (prices.length) return Math.min(...prices);
  return Number(product?.price ?? 0);
}

function productStock(product) {
  const skus = Array.isArray(product?.skus) ? product.skus : [];
  const stocks = skus.map((sku) => Number(sku.stock)).filter((value) => Number.isFinite(value));
  if (stocks.length) return stocks.reduce((sum, value) => sum + value, 0);
  return Number(product?.stock ?? 0);
}

function onImageError(product) {
  imageErrors.value = { ...imageErrors.value, [product.product_id]: true };
}

async function loadProducts() {
  loading.value = true;
  error.value = "";
  try {
    const data = await getJson("/api/c/products?limit=8");
    products.value = Array.isArray(data?.products) ? data.products : [];
  } catch (e) {
    error.value = e?.detail || e?.message || "商品加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  loadProducts();
});
</script>

<template>
  <div class="c-home">
    <section class="c-home-hero">
      <p class="c-home-kicker">C-END · HOME</p>
      <h2>今天想买点什么？</h2>
      <p class="c-home-lead">让小鱼先帮你挑，再决定买不买。成交前需要你逐单确认。</p>
      <div class="c-home-actions">
        <RouterLink class="c-home-btn c-home-btn-primary" to="/c/app">和小鱼聊聊</RouterLink>
        <RouterLink class="c-home-btn" to="/c">去逛市集</RouterLink>
      </div>
    </section>

    <section class="c-home-quick" aria-label="快捷入口">
      <RouterLink class="c-home-quick-item" to="/c">
        <span class="c-home-quick-mark">逛</span>
        <span><b>市集</b><small>看看店里有什么</small></span>
      </RouterLink>
      <RouterLink class="c-home-quick-item" to="/c/app">
        <span class="c-home-quick-mark">聊</span>
        <span><b>找小鱼</b><small>按预算挑商品</small></span>
      </RouterLink>
      <RouterLink class="c-home-quick-item" to="/c/orders">
        <span class="c-home-quick-mark">单</span>
        <span><b>订单</b><small>确认与售后</small></span>
      </RouterLink>
      <RouterLink class="c-home-quick-item" to="/c/social">
        <span class="c-home-quick-mark">信</span>
        <span><b>消息</b><small>店宠与好友</small></span>
      </RouterLink>
    </section>

    <section class="c-home-products">
      <div class="c-home-section-head">
        <div>
          <p class="c-home-kicker">PICKS</p>
          <h3>小鱼精选</h3>
        </div>
        <RouterLink to="/c">全部商品</RouterLink>
      </div>

      <p v-if="loading" class="c-home-state">正在看看店里有什么…</p>
      <p v-else-if="error" class="c-home-state is-error" role="alert">{{ error }}</p>
      <p v-else-if="!products.length" class="c-home-state">暂时没有可展示的商品。</p>

      <div v-else class="c-home-grid">
        <RouterLink
          v-for="product in products"
          :key="product.product_id"
          class="c-home-card"
          to="/c"
        >
          <div class="c-home-card-media">
            <img
              v-if="product.image_url && !imageErrors[product.product_id]"
              :src="product.image_url"
              :alt="product.title"
              loading="lazy"
              @error="onImageError(product)"
            />
            <span v-else class="c-home-card-placeholder">{{ (product.category || "商").slice(0, 1) }}</span>
          </div>
          <div class="c-home-card-body">
            <p class="c-home-card-category">{{ product.category || "精选" }}</p>
            <h4>{{ product.title }}</h4>
            <p class="c-home-card-meta">
              <b>¥{{ money(productPrice(product)) }}</b>
              <span>{{ productStock(product) > 0 ? "有货" : "缺货" }}</span>
            </p>
          </div>
        </RouterLink>
      </div>
    </section>

    <p class="c-home-note">模拟交易 · 不接真实支付 · 下单前需人工确认</p>
  </div>
</template>

<style scoped>
.c-home {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 18px 16px 28px;
}

.c-home-hero {
  padding: 22px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: var(--surface);
}

.c-home-kicker {
  margin: 0 0 8px;
  color: var(--primary);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.16em;
}

.c-home-hero h2 {
  margin: 0;
  color: var(--text);
  font-size: 28px;
  line-height: 1.25;
}

.c-home-lead {
  margin: 10px 0 0;
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.75;
}

.c-home-actions {
  display: flex;
  gap: 8px;
  margin-top: 18px;
}

.c-home-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 0 16px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
}

.c-home-btn-primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.c-home-quick {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.c-home-quick-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
  color: var(--text);
  text-decoration: none;
}

.c-home-quick-mark {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 10px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 14px;
  font-weight: 700;
}

.c-home-quick-item b,
.c-home-quick-item small {
  display: block;
}

.c-home-quick-item b {
  font-size: 14px;
}

.c-home-quick-item small {
  margin-top: 2px;
  color: var(--text-3);
  font-size: 11px;
}

.c-home-section-head {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.c-home-section-head h3 {
  margin: 0;
  color: var(--text);
  font-size: 20px;
}

.c-home-section-head a {
  color: var(--text-3);
  font-size: 12px;
  text-decoration: none;
}

.c-home-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.c-home-card {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
  color: var(--text);
  text-decoration: none;
}

.c-home-card-media {
  display: grid;
  height: 118px;
  place-items: center;
  background: var(--surface-3);
}

.c-home-card-media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.c-home-card-placeholder {
  color: var(--text-3);
  font-size: 28px;
  font-weight: 700;
}

.c-home-card-body {
  padding: 10px 11px 12px;
}

.c-home-card-category {
  margin: 0 0 4px;
  color: var(--primary);
  font-size: 10px;
  font-weight: 700;
}

.c-home-card h4 {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: var(--text);
  font-size: 14px;
  line-height: 1.4;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.c-home-card-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin: 8px 0 0;
}

.c-home-card-meta b {
  color: var(--primary-strong);
  font-size: 15px;
}

.c-home-card-meta span {
  color: var(--text-3);
  font-size: 10px;
}

.c-home-state {
  margin: 0;
  padding: 18px;
  border: 1px dashed var(--border);
  border-radius: 14px;
  color: var(--text-3);
  font-size: 13px;
  text-align: center;
}

.c-home-state.is-error {
  color: var(--primary-strong);
}

.c-home-note {
  margin: 0;
  color: var(--text-3);
  font-size: 11px;
  text-align: center;
}
</style>
