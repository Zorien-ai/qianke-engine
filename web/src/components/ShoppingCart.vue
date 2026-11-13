<script setup>
import { computed, ref } from "vue";
import { getJson } from "../api";
import { cart, cartItemKey, cartLineMax, cartTotal, cartCheckoutPayload } from "../cart";

defineProps({ busy: Boolean });
const emit = defineEmits(["checkout"]);
const items = cart.items;
const error = ref("");
const budgets = ref({});
const editing = ref(null);
const options = ref([]);
const selectedSku = ref("");
const quantity = ref(1);
const loading = ref(false);
const groups = computed(() => {
  const result = new Map();
  for (const item of items.value) {
    if (!result.has(item.friend_id)) result.set(item.friend_id, { id: item.friend_id, name: item.merchant_name || "店铺", items: [] });
    result.get(item.friend_id).items.push(item);
  }
  return [...result.values()];
});
const activeSku = computed(() => options.value.find((sku) => sku.sku === selectedSku.value));
const count = computed(() => items.value.reduce((sum, item) => sum + item.quantity, 0));

async function edit(item) {
  editing.value = item;
  selectedSku.value = item.sku;
  quantity.value = item.quantity;
  options.value = [];
  error.value = "";
  loading.value = true;
  try {
    if (!item.friend_id) throw new Error("缺少商家信息，请移除后重新加入商品");
    const data = await getJson(`/api/c/merchant/products?friend_id=${encodeURIComponent(item.friend_id)}&limit=50`);
    if (editing.value !== item) return;
    const product = data?.products?.find((entry) => entry.product_id === item.product_id);
    if (!product) throw new Error("商品已下架或不在当前店铺");
    options.value = (product.skus || []).filter((sku) => sku?.sku);
  } catch (e) {
    if (editing.value === item) error.value = e.detail || e.message || "规格读取失败";
  } finally {
    if (editing.value === item) loading.value = false;
  }
}
function save() {
  try {
    cart.edit(editing.value, activeSku.value, quantity.value);
    editing.value = null;
    error.value = "";
  } catch (e) { error.value = e.message; }
}
function checkout(group) {
  error.value = "";
  try {
    const budget = Number(budgets.value[group.id] ?? Math.max(1, Math.ceil(cartTotal(group.items))));
    if (!Number.isFinite(budget) || budget < 1 || budget > 100000) throw new Error("预算须在 1–100000 元之间");
    emit("checkout", { ...cartCheckoutPayload(group.items), budget });
  } catch (e) { error.value = e.message; }
}
</script>

<template>
  <section class="shared-cart" aria-label="购物车">
    <header><h3>购物车 <small>{{ count }} 件</small></h3><strong>¥{{ cartTotal(items).toFixed(2) }}</strong></header>
    <p class="cart-note">与聊天中的购物车同步。按店铺合并报价；成交前仍需你确认，最终金额以订单草稿为准。</p>
    <p v-if="!items.length" class="cart-note">购物车还是空的，可从聊天或店铺商品详情加入商品。</p>
    <fieldset v-for="group in groups" :key="group.id" :disabled="busy" class="cart-group">
      <legend>{{ group.name }}</legend>
      <div v-for="item in group.items" :key="cartItemKey(item)" class="cart-row">
        <div class="cart-copy"><strong>{{ item.title }}</strong><small>{{ item.spec }} · {{ item.sku }}</small><span>¥{{ Number(item.price).toFixed(2) }} × {{ item.quantity }}</span></div>
        <div class="cart-controls">
          <button type="button" :aria-label="`减少 ${item.title} 数量`" :disabled="item.quantity <= 1" @click="cart.setQuantity(item, item.quantity - 1)">−</button>
          <b>{{ item.quantity }}</b>
          <button type="button" :aria-label="`增加 ${item.title} 数量`" :disabled="item.quantity >= cartLineMax(item)" @click="cart.setQuantity(item, item.quantity + 1)">＋</button>
          <button type="button" @click="edit(item)">改规格</button>
          <button type="button" :aria-label="`移除 ${item.title}`" @click="cart.remove(item)">移除</button>
        </div>
      </div>
      <footer><label>预算 ¥ <input :value="budgets[group.id] ?? Math.max(1, Math.ceil(cartTotal(group.items)))" type="number" min="1" max="100000" step="0.01" @input="budgets[group.id] = $event.target.value" /></label><button type="button" class="cart-checkout" @click="checkout(group)">合并报价 · ¥{{ cartTotal(group.items).toFixed(2) }}</button></footer>
    </fieldset>
    <p v-if="busy" class="cart-note">正在处理报价或订单草稿，请先完成或取消。</p>
    <p v-if="error && !editing" class="cart-error" role="alert">{{ error }}</p>
    <div v-if="editing" class="cart-edit-mask" @click.self="editing = null">
      <section class="cart-editor" role="dialog" aria-modal="true" aria-labelledby="shop-cart-edit-title">
        <h3 id="shop-cart-edit-title">修改 {{ editing.title }} 的规格</h3>
        <p v-if="loading" role="status">正在读取最新规格…</p>
        <label>规格<select v-model="selectedSku" :disabled="loading || busy" @change="quantity = Math.max(1, Math.min(quantity, cartLineMax(activeSku)))"><option v-for="sku in options" :key="sku.sku" :value="sku.sku" :disabled="sku.in_stock === false || !cartLineMax(sku)">{{ sku.spec || '默认规格' }} · ¥{{ Number(sku.price).toFixed(2) }}{{ cartLineMax(sku) ? '' : ' · 缺货' }}</option></select></label>
        <label>数量<input v-model.number="quantity" type="number" min="1" :max="cartLineMax(activeSku)" step="1" :disabled="loading || busy" /></label>
        <p v-if="activeSku" class="cart-note">最多 {{ cartLineMax(activeSku) }} 件；改为已有规格时会合并数量。</p>
        <p v-if="error" class="cart-error" role="alert">{{ error }}</p>
        <footer><button type="button" @click="editing = null">取消</button><button type="button" class="cart-checkout" :disabled="loading || busy || !activeSku || !cartLineMax(activeSku)" @click="save">保存规格</button></footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.shared-cart { padding: 22px 24px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface, #fff); }
header, footer, .cart-row, .cart-controls { display: flex; align-items: center; gap: 12px; }
header, footer { justify-content: space-between; flex-wrap: wrap; }
h3 { margin: 0; font-size: 18px; } h3 small, .cart-note, .cart-copy small { color: var(--text-3, #78716c); font-size: 12px; }
.cart-note { line-height: 1.7; margin: 12px 0; }
.cart-group { min-width: 0; margin: 18px 0 0; padding: 12px; border: 1px solid var(--border); border-radius: 8px; }
legend { padding: 0 6px; font-size: 13px; }
.cart-row { justify-content: space-between; flex-wrap: wrap; padding: 12px 0; border-bottom: 1px solid var(--border); }
.cart-copy { display: grid; gap: 5px; min-width: 0; flex: 1 1 220px; overflow-wrap: anywhere; font-size: 13px; }
.cart-controls { gap: 8px; flex-wrap: wrap; }
button, input, select { font: inherit; color: inherit; border: 1px solid var(--border); border-radius: 6px; background: var(--surface, #fff); padding: 8px 10px; }
button { cursor: pointer; } button:disabled { opacity: .45; cursor: not-allowed; }
footer { margin-top: 12px; font-size: 13px; } footer input { width: 100px; }
.cart-checkout { background: var(--text, #292524); color: var(--surface, #fff); }
.cart-error { color: #a12622; font-size: 13px; }
.cart-edit-mask { position: fixed; inset: 0; z-index: 150; display: grid; place-items: center; padding: 16px; background: #0006; }
.cart-editor { width: min(440px, 100%); max-height: 90dvh; overflow: auto; box-sizing: border-box; padding: 24px; border-radius: 12px; background: var(--surface, #fff); }
.cart-editor label { display: grid; gap: 8px; margin-top: 16px; font-size: 13px; }
.cart-editor select, .cart-editor input { width: 100%; min-width: 0; box-sizing: border-box; }
@media (max-width: 600px) { .shared-cart { padding: 18px 14px; } .cart-row { align-items: flex-start; } .cart-controls { width: 100%; } }
</style>
