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

/**
 * 状态显示：优先后端新增的 merchant_status（商家域状态），
 * 没有时回退旧字段 status，保证老订单仍能正常展示。
 */
const STATUS_LABELS = {
  CREATED: "已创建",
  PENDING: "待确认",
  CONFIRMED: "已确认",
  PAID: "已支付",
  SHIPPED: "已发货",
  DELIVERING: "配送中",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  CANCELED: "已取消",
};

function orderStatus(order) {
  const raw = String(order?.merchant_status || order?.status || "").trim();
  if (!raw) return "已确认";
  return STATUS_LABELS[raw.toUpperCase()] || raw;
}

function orderStatusTone(order) {
  const raw = String(order?.merchant_status || order?.status || "").toUpperCase();
  if (raw === "CANCELLED" || raw === "CANCELED") return "is-cancelled";
  if (raw === "CREATED" || raw === "PENDING") return "is-created";
  if (raw === "SHIPPED" || raw === "DELIVERING") return "is-shipped";
  if (raw === "COMPLETED") return "is-completed";
  return "";
}

/* ---------- 状态时间线 / 物流（merchant 数据；老订单没有 merchant 字段时保持原样式） ---------- */
const ORDER_FLOW = [
  { status: "CREATED", label: "已创建" },
  { status: "PAID", label: "已支付" },
  { status: "SHIPPED", label: "已发货" },
  { status: "COMPLETED", label: "已完成" },
];

function statusKey(value) {
  return String(value || "").trim().toUpperCase();
}

/** 有商家域状态或时间线才画时间线；旧平台订单不出现这一段 */
function hasMerchantFlow(order) {
  return !!(
    statusKey(order?.merchant_status) ||
    (Array.isArray(order?.merchant_timeline) && order.merchant_timeline.length)
  );
}

function hasLogistics(order) {
  return !!(order?.merchant_tracking_no || order?.merchant_carrier);
}

function shortMinute(value) {
  const text = String(value || "").replace("T", " ");
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!match) return text.slice(0, 16);
  return `${match[2]}-${match[3]} ${match[4]}:${match[5]}`;
}

/**
 * 时间线节点：标准四步（已创建/已支付/已发货/已完成）+ 已取消。
 * - 后端给了 merchant_timeline 就按它标记已到达节点与时间；
 * - 没给时间线但有 merchant_status 时按状态顺序推断已到达节点（不编造时间）；
 * - 时间只显示后端明确给出的（时间线条目 / merchant_status_at）。
 */
function orderTimeline(order) {
  const history = Array.isArray(order?.merchant_timeline) ? order.merchant_timeline : [];
  const reachedFromHistory = new Set(
    history.map((entry) => statusKey(entry?.status)).filter(Boolean)
  );
  const atByStatus = {};
  for (const entry of history) {
    const key = statusKey(entry?.status);
    if (key && !atByStatus[key] && entry?.at) atByStatus[key] = entry.at;
  }

  const current = statusKey(order?.merchant_status);
  const cancelled = current === "CANCELLED" || current === "CANCELED";
  const currentIndex = ORDER_FLOW.findIndex((step) => step.status === current);

  const steps = ORDER_FLOW.map((step, index) => {
    let reached;
    if (history.length) reached = reachedFromHistory.has(step.status);
    else if (currentIndex >= 0) reached = index <= currentIndex;
    else reached = false;
    return {
      status: step.status,
      label: step.label,
      at: atByStatus[step.status] || (current === step.status ? order?.merchant_status_at : "") || "",
      reached,
      current: !cancelled && current === step.status,
    };
  });

  if (cancelled) {
    steps.push({
      status: "CANCELLED",
      label: STATUS_LABELS.CANCELLED,
      at: atByStatus.CANCELLED || atByStatus.CANCELED || order?.merchant_status_at || "",
      reached: true,
      current: true,
      cancelled: true,
    });
  }
  return steps;
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
            <p v-if="order.merchant_order_id" class="order-merchant">
              商家单号 <code>{{ order.merchant_order_id }}</code>
            </p>
          </div>
          <span class="order-status" :class="orderStatusTone(order)">{{ orderStatus(order) }}</span>
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

        <!-- 状态时间线：仅 merchant 订单出现，老订单保持原有简洁样式 -->
        <section v-if="hasMerchantFlow(order)" class="order-timeline" aria-label="订单状态时间线">
          <div class="order-timeline-head">
            <span>状态时间线</span>
            <span v-if="order.merchant_status_at" class="order-timeline-at">
              最近更新 {{ shortMinute(order.merchant_status_at) }}
            </span>
          </div>
          <ol class="timeline-steps">
            <li
              v-for="step in orderTimeline(order)"
              :key="step.status"
              class="timeline-step"
              :class="{
                'is-reached': step.reached,
                'is-current': step.current,
                'is-cancelled': step.cancelled,
              }"
            >
              <span class="timeline-dot" aria-hidden="true" />
              <span class="timeline-label">{{ step.label }}</span>
              <span class="timeline-time">{{ step.at ? shortMinute(step.at) : "" }}</span>
            </li>
          </ol>
        </section>

        <!-- 物流信息：承运商 + 运单号 -->
        <div v-if="hasLogistics(order)" class="order-logistics">
          <div class="logistics-row">
            <span>承运商</span>
            <strong>{{ order.merchant_carrier || "—" }}</strong>
          </div>
          <div class="logistics-row">
            <span>运单号</span>
            <code>{{ order.merchant_tracking_no || "—" }}</code>
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
  white-space: nowrap;
}

.order-status.is-created {
  background: var(--warn-soft);
  color: var(--warn);
}

.order-status.is-shipped {
  background: var(--primary-soft);
  color: var(--primary);
}

.order-status.is-completed {
  background: var(--success-soft);
  color: var(--success);
}

.order-status.is-cancelled {
  background: var(--danger-soft);
  color: var(--danger);
}

.order-merchant {
  margin-top: 4px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.5;
  word-break: break-all;
}

.order-merchant code {
  color: var(--text-2);
  font-family: var(--mono);
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

/* ---------- 状态时间线 ---------- */
.order-timeline {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.order-timeline-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 9px;
  color: var(--muted);
  font-size: 10px;
}

.order-timeline-at {
  font-family: var(--mono);
  font-size: 9px;
  white-space: nowrap;
}

.timeline-steps {
  display: flex;
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline-step {
  position: relative;
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
  padding-right: 10px;
  color: var(--muted);
}

.timeline-step::before {
  position: absolute;
  top: 4px;
  right: 0;
  left: 11px;
  height: 1px;
  background: var(--border);
  content: "";
}

.timeline-step:last-child::before {
  display: none;
}

.timeline-dot {
  width: 9px;
  height: 9px;
  border: 1px solid var(--border-strong);
  border-radius: 50%;
  background: var(--surface);
  z-index: 1;
}

.timeline-label {
  overflow: hidden;
  max-width: 100%;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline-time {
  overflow: hidden;
  max-width: 100%;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline-step.is-reached {
  color: var(--text-2);
}

.timeline-step.is-reached::before {
  background: var(--border-strong);
}

.timeline-step.is-reached .timeline-dot {
  border-color: var(--text-2);
  background: var(--text-2);
}

.timeline-step.is-current .timeline-label {
  color: var(--text);
  font-weight: 600;
}

.timeline-step.is-current .timeline-dot {
  border-color: var(--primary);
  background: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}

.timeline-step.is-cancelled {
  color: var(--danger);
}

.timeline-step.is-cancelled .timeline-dot {
  border-color: var(--danger);
  background: var(--danger);
}

.timeline-step.is-cancelled .timeline-label {
  color: var(--danger);
}

/* ---------- 物流信息 ---------- */
.order-logistics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 20px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
  color: var(--muted);
  font-size: 10px;
}

.logistics-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.logistics-row strong {
  color: var(--text-2);
  font-weight: 500;
}

.logistics-row code {
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 10px;
  word-break: break-all;
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

  .timeline-step {
    padding-right: 6px;
  }

  .timeline-label {
    font-size: 9.5px;
  }

  .timeline-time {
    font-size: 8.5px;
  }

  .order-total {
    flex-wrap: wrap;
    justify-content: flex-start;
  }
}
</style>
