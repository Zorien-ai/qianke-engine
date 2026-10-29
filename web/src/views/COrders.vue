<script setup>
import { onMounted, ref } from "vue";
import { getJson } from "../api";

const orders = ref([]);
const loading = ref(true);
const error = ref("");

function money(value) {
  return Number(value || 0).toFixed(2);
}

function shortDate(value) {
  return (value || "").replace("T", " ").slice(0, 19);
}

async function loadOrders() {
  loading.value = true;
  error.value = "";
  try {
    const data = await getJson("/api/c/orders?limit=50");
    orders.value = data?.orders || [];
  } catch (e) {
    error.value = e?.detail || e?.message || "订单加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(loadOrders);
</script>

<template>
  <div class="orders-page">
    <header class="orders-head">
      <div>
        <p class="orders-kicker">C-END · AUDIT</p>
        <h2>我的订单</h2>
        <p class="orders-subtitle">
          订单保留聊天报价、活动政策和用户确认结果；用于 C 端交易追溯。
        </p>
      </div>
      <button class="ghost-btn" type="button" :disabled="loading" @click="loadOrders">
        {{ loading ? "刷新中…" : "刷新" }}
      </button>
    </header>

    <p v-if="error" class="state-line state-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="state-line" role="status">正在加载订单…</p>
    <p v-else-if="!orders.length" class="empty-card">还没有已确认订单。</p>

    <section v-else class="order-list" aria-label="订单列表">
      <article v-for="order in orders" :key="order.order_id" class="order-card">
        <div class="order-top">
          <div>
            <span class="order-id">{{ order.order_id }}</span>
            <p class="order-date">{{ shortDate(order.confirmed_at || order.created_at) }}</p>
          </div>
          <span class="order-status">已确认</span>
        </div>

        <ul class="order-items">
          <li v-for="item in order.items" :key="item.product_id">
            <span>{{ item.title || item.product_id }}</span>
            <span>× {{ item.quantity }}</span>
            <span>¥{{ money(item.unit_price * item.quantity) }}</span>
          </li>
        </ul>

        <div class="order-audit">
          <div v-if="order.quote_id">
            <span>报价</span>
            <code>{{ order.quote_id }}</code>
          </div>
          <div v-if="order.policy_ids?.length">
            <span>政策</span>
            <span v-for="policy in order.policy_ids" :key="policy" class="audit-chip">{{ policy }}</span>
          </div>
        </div>

        <div class="order-total">
          <span>原价 ¥{{ money(order.original_amount) }}</span>
          <span v-if="order.discount_amount" class="discount">优惠 ¥{{ money(order.discount_amount) }}</span>
          <strong>应付 ¥{{ money(order.total_amount) }}</strong>
        </div>
      </article>
    </section>
  </div>
</template>

<style scoped>
.orders-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 8px 0 40px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.orders-head {
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

.orders-kicker {
  margin: 0 0 6px;
  color: var(--primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.orders-head h2 {
  font-size: 24px;
}

.orders-subtitle {
  max-width: 620px;
  margin-top: 7px;
  color: var(--text-2);
  font-size: 13px;
}

.empty-card {
  padding: 44px 20px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius);
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}

.order-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.order-card {
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.order-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.order-id {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 600;
}

.order-date {
  margin-top: 3px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}

.order-status {
  padding: 3px 7px;
  border-radius: 4px;
  background: var(--success-soft);
  color: var(--success);
  font-size: 10px;
}

.order-items {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 12px 0;
  padding: 9px 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  list-style: none;
}

.order-items li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 48px 80px;
  gap: 8px;
  color: var(--text-2);
  font-size: 12px;
}

.order-items li span:last-child {
  text-align: right;
}

.order-audit {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  color: var(--muted);
  font-size: 10px;
}

.order-audit > div {
  display: flex;
  align-items: center;
  gap: 5px;
}

.order-audit code {
  color: var(--text-2);
  font-size: 10px;
}

.audit-chip {
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--primary-soft);
  color: var(--primary);
}

.order-total {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 10px;
  color: var(--muted);
  font-size: 10px;
}

.order-total strong {
  color: var(--text);
  font-family: var(--mono);
  font-size: 14px;
}

.order-total .discount {
  color: var(--success);
}

@media (max-width: 640px) {
  .orders-head {
    flex-direction: column;
  }

  .order-total {
    flex-wrap: wrap;
    justify-content: flex-start;
  }
}
</style>
