import { ref } from "vue";

export const CART_STORAGE_KEY = "qianke:cart";
export const cartItemKey = (item) => JSON.stringify([String(item.friend_id || ""), String(item.sku || "")]);
export const cartLineMax = (item) => Math.max(0, Math.min(20, Math.floor(Number(item?.stock ?? 20) || 0)));
export const cartTotal = (items) => items.reduce((sum, item) => sum + Math.round(Number(item.price) * 100) * item.quantity, 0) / 100;

function normalize(items) {
  if (!Array.isArray(items)) return [];
  const result = new Map();
  for (const item of items) {
    if (!item || !String(item.sku || "").trim() || !Number.isInteger(Number(item.quantity)) || Number(item.quantity) <= 0) continue;
    const line = {
      friend_id: String(item.friend_id || "").trim(),
      merchant_name: String(item.merchant_name || ""),
      product_id: String(item.product_id || ""),
      title: String(item.title || ""),
      image_url: String(item.image_url || ""),
      sku: String(item.sku).trim(),
      spec: String(item.spec || ""),
      price: Number.isFinite(Number(item.price)) && Number(item.price) >= 0 ? Number(item.price) : 0,
      stock: Math.max(0, Math.floor(Number(item.stock ?? 20) || 0)),
      quantity: Math.min(20, Number(item.quantity)),
    };
    const key = cartItemKey(line);
    const previous = result.get(key);
    if (previous) line.quantity = Math.min(20, previous.quantity + line.quantity);
    result.set(key, line);
  }
  return [...result.values()];
}

export function cartCheckoutPayload(items) {
  if (!items.length) throw new Error("购物车为空");
  const friendId = String(items[0].friend_id || "").trim();
  if (!friendId) throw new Error("缺少商家信息，请重新加入商品");
  if (items.some((item) => item.friend_id !== friendId)) throw new Error("请按商家分别合并报价");
  if (items.length > 10) throw new Error("一次最多合并 10 个规格，请减少商品后重试");
  return {
    friend_id: friendId,
    items: items.map(({ sku, quantity }) => {
      if (!sku || !Number.isInteger(quantity) || quantity < 1 || quantity > 20) throw new Error("商品数量必须为 1–20 的整数");
      return { sku, quantity };
    }),
  };
}

// One store for both routes; storage events also update other tabs on this origin.
// Keep the existing array format so carts created by CApp continue to work.
export function createCartStore(storage, events) {
  const items = ref([]);
  function reload() {
    if (!storage) return;
    try { items.value = normalize(JSON.parse(storage.getItem(CART_STORAGE_KEY) || "[]")); }
    catch { /* Keep the in-memory cart when storage is unavailable or corrupted. */ }
  }
  function persist() {
    try { storage?.setItem(CART_STORAGE_KEY, JSON.stringify(items.value)); }
    catch { /* The shared in-memory cart still works for this page lifetime. */ }
  }
  function find(item) { return items.value.find((line) => cartItemKey(line) === cartItemKey(item)); }
  function add(item) {
    const [line] = normalize([item]);
    if (!line || !line.friend_id || !line.product_id || !cartLineMax(line)) throw new Error("请选择有库存的商品和规格");
    const existing = find(line);
    line.quantity = Math.min(cartLineMax(line), line.quantity + (existing?.quantity || 0));
    if (existing) Object.assign(existing, line);
    else items.value.push(line);
    persist();
  }
  function remove(item) {
    items.value = items.value.filter((line) => cartItemKey(line) !== cartItemKey(item));
    persist();
  }
  function setQuantity(item, quantity) {
    const line = find(item);
    if (!line || !cartLineMax(line)) return;
    line.quantity = Math.max(1, Math.min(cartLineMax(line), Math.floor(Number(quantity) || 1)));
    persist();
  }
  function edit(item, sku, quantity) {
    const original = find(item);
    if (!original) throw new Error("购物车已变化，请关闭后重新选择商品");
    if (!sku?.sku || sku.in_stock === false || !cartLineMax(sku)) throw new Error("这个规格暂时缺货");
    if (!Number.isInteger(Number(quantity)) || Number(quantity) < 1) throw new Error("数量必须为正整数");
    const next = { ...original, ...sku, quantity: Math.max(1, Math.min(cartLineMax(sku), Math.floor(Number(quantity) || 1))) };
    const duplicate = find(next);
    if (duplicate && duplicate !== original) {
      next.quantity = Math.min(cartLineMax(sku), duplicate.quantity + next.quantity);
      items.value = items.value.filter((line) => line !== duplicate);
    }
    Object.assign(original, next);
    persist();
  }
  function clearMerchant(friendId) {
    items.value = items.value.filter((item) => item.friend_id !== friendId);
    persist();
  }
  function consumeOrder(quote, order) {
    // Never clear on quotation, draft preparation, cancellation or failed confirmation.
    if (order?.status !== "CONFIRMED" || !quote?.friend_id || !Array.isArray(order.items)) return;
    let orderedItems = order.items;
    if (orderedItems.some((item) => !item.sku)) {
      // The current HTTP order serializer omits SKU/spec. Recover them only from
      // this order's quote, after verifying its product/price/quantity totals.
      const refs = quote.product_refs;
      if (!quote.quote_id || order.quote_id !== quote.quote_id || !Array.isArray(refs) || refs.some((item) => !item.sku)) return;
      const signature = (lines) => {
        const totals = new Map();
        for (const line of lines) {
          const price = Number(line.unit_price ?? line.price);
          const quantity = Number(line.quantity);
          if (!line.product_id || !Number.isFinite(price) || !Number.isInteger(quantity) || quantity <= 0) return null;
          const key = JSON.stringify([line.product_id, Math.round(price * 100)]);
          totals.set(key, (totals.get(key) || 0) + quantity);
        }
        return JSON.stringify([...totals].sort(([a], [b]) => a.localeCompare(b)));
      };
      const confirmed = signature(order.items);
      if (!confirmed || confirmed !== signature(refs)) return;
      orderedItems = refs;
    }
    for (const ordered of orderedItems) {
      const line = find({ friend_id: quote.friend_id, sku: ordered.sku });
      if (!line || line.product_id !== ordered.product_id) continue;
      const quantity = Number(ordered.quantity);
      if (!Number.isInteger(quantity) || quantity <= 0) continue;
      line.quantity = Math.max(0, line.quantity - quantity);
    }
    items.value = items.value.filter((line) => line.quantity > 0);
    persist();
  }
  function onStorage(event) {
    if (event.key !== CART_STORAGE_KEY && event.key !== null) return;
    if (event.storageArea && event.storageArea !== storage) return;
    try { items.value = normalize(JSON.parse(event.newValue || "[]")); } catch { /* Ignore malformed writes. */ }
  }
  reload();
  events?.addEventListener("storage", onStorage);
  return { items, reload, add, remove, setQuantity, edit, clearMerchant, consumeOrder,
    dispose: () => events?.removeEventListener("storage", onStorage) };
}

let storage;
try { storage = globalThis.localStorage; } catch { /* Browser privacy settings may deny access. */ }
export const cart = createCartStore(storage, globalThis.window);
if (import.meta.hot) import.meta.hot.dispose(() => cart.dispose());
