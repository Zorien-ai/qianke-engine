<script setup>
import { onMounted, ref } from "vue";
import { getJson, postJson } from "../api";

const orders = ref([]);
const loading = ref(true);
const error = ref("");
// 取消订单：pendingCancelId = 当前展开二次确认的订单；cancellingId = 正在请求的订单
const pendingCancelId = ref("");
const cancellingId = ref("");
const cancelError = ref("");
const cancelNotice = ref("");
// 售后：afterSaleOpenId = 展开申请表单的订单；afterSaleBusy = 正在提交的订单
const afterSaleOpenId = ref("");
const afterSaleType = ref("REFUND_ONLY");
const afterSaleReason = ref("");
const afterSaleBusy = ref("");
const afterSaleError = ref("");
const afterSaleNotice = ref("");

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
  REFUNDED: "已退款",
};

function orderStatus(order) {
  const raw = String(order?.merchant_status || order?.status || "").trim();
  if (!raw) return "已确认";
  return STATUS_LABELS[raw.toUpperCase()] || raw;
}

function orderStatusTone(order) {
  const raw = String(order?.merchant_status || order?.status || "").toUpperCase();
  if (raw === "CANCELLED" || raw === "CANCELED") return "is-cancelled";
  if (raw === "REFUNDED") return "is-refunded";
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
      at:
        atByStatus.CANCELLED ||
        atByStatus.CANCELED ||
        order?.merchant_cancelled_at ||
        order?.merchant_status_at ||
        "",
      reached: true,
      current: true,
      cancelled: true,
    });
  }
  return steps;
}

/* ---------- 取消订单 / 退款（can_cancel / merchant_cancelled_at / merchant_refund_amount） ---------- */
function isCancelled(order) {
  const raw = statusKey(order?.merchant_status);
  return raw === "CANCELLED" || raw === "CANCELED" || !!order?.merchant_cancelled_at;
}

/** 只对后端明确允许取消的订单显示入口；已取消/已退款的不能再取消 */
function canCancel(order) {
  return !!order?.can_cancel && !isCancelled(order) && !isRefunded(order);
}

function cancelAt(order) {
  if (order?.merchant_cancelled_at) return order.merchant_cancelled_at;
  return isCancelled(order) ? order?.merchant_status_at || "" : "";
}

/** 后端只给 merchant_refund_amount 时才展示退款金额（0 也照实显示），不推断 */
function refundAmount(order) {
  const value = order?.merchant_refund_amount;
  if (value === null || value === undefined || value === "") return null;
  return Number(value);
}

function apiErrorMessage(e, fallback) {
  const detail = e?.payload?.detail;
  if (detail && typeof detail === "object") {
    return detail.message || detail.code || fallback;
  }
  return e?.detail || e?.message || fallback;
}

function askCancel(order) {
  if (!canCancel(order) || cancellingId.value) return;
  cancelError.value = "";
  pendingCancelId.value = order.order_id;
}

function dismissCancel() {
  if (cancellingId.value) return;
  pendingCancelId.value = "";
  cancelError.value = "";
}

async function confirmCancel(order) {
  if (!order || !canCancel(order) || cancellingId.value) return;
  cancellingId.value = order.order_id;
  cancelError.value = "";
  try {
    const payload = await postJson(
      `/api/c/orders/${encodeURIComponent(order.order_id)}/cancel`,
      {}
    );
    // 契约：成功返回 order（兼容直接返回 order 或 {order} 两种包装）
    const returned = payload?.order || payload || {};
    const refund = returned.merchant_refund_amount;
    cancelNotice.value =
      refund === null || refund === undefined || refund === ""
        ? `订单 ${order.order_id} 已取消`
        : `订单 ${order.order_id} 已取消，退款 ¥${money(refund)} 已原路退回`;
    pendingCancelId.value = "";
    await loadOrders();
  } catch (e) {
    cancelError.value = apiErrorMessage(e, "取消订单失败");
  } finally {
    cancellingId.value = "";
  }
}

/* ---------- 申请售后（can_after_sale / after_sale / REFUNDED） ---------- */
const AFTER_SALE_TYPE_LABELS = {
  REFUND_ONLY: "仅退款",
  RETURN_REFUND: "退货退款",
};

const AFTER_SALE_STATUS_LABELS = {
  OPEN: "待处理",
  PENDING: "待处理",
  PROCESSING: "待处理",
  APPROVED: "已通过",
  ACCEPTED: "已通过",
  REJECTED: "已拒绝",
  REFUNDED: "已退款",
  CANCELLED: "已撤销",
  CANCELED: "已撤销",
};

function afterSaleOf(order) {
  const value = order?.after_sale;
  return value && typeof value === "object" ? value : null;
}

function afterSaleStatus(order) {
  return statusKey(afterSaleOf(order)?.status);
}

/** REFUNDED：订单已退款（商家状态 / 旧 status / 售后工单任一命中），不能再取消或再申请 */
function isRefunded(order) {
  return (
    afterSaleStatus(order) === "REFUNDED" ||
    statusKey(order?.merchant_status) === "REFUNDED" ||
    statusKey(order?.status) === "REFUNDED"
  );
}

/** 有未结束的售后工单时不允许重复申请（后端唯一索引也只允许一个 OPEN） */
function isAfterSaleOpen(order) {
  return ["OPEN", "PENDING", "PROCESSING"].includes(afterSaleStatus(order));
}

function canApplyAfterSale(order) {
  return !!order?.can_after_sale && !isRefunded(order) && !isAfterSaleOpen(order);
}

function afterSaleStatusLabel(order) {
  const status = afterSaleStatus(order);
  return AFTER_SALE_STATUS_LABELS[status] || afterSaleOf(order)?.status || "待处理";
}

function afterSaleTone(order) {
  const status = afterSaleStatus(order);
  if (status === "REFUNDED") return "is-refunded";
  if (status === "APPROVED" || status === "ACCEPTED") return "is-approved";
  if (status === "REJECTED") return "is-rejected";
  return "is-open";
}

function afterSaleTypeLabel(type) {
  const key = statusKey(type);
  return AFTER_SALE_TYPE_LABELS[key] || type || "售后";
}

/** 退款金额优先取售后工单；REFUNDED 时回退订单上的退款金额（都是后端事实，不推断） */
function afterSaleRefundAmount(order) {
  const ticketAmount = afterSaleOf(order)?.refund_amount;
  if (ticketAmount !== null && ticketAmount !== undefined && ticketAmount !== "") {
    return Number(ticketAmount);
  }
  if (isRefunded(order) && order?.merchant_refund_amount !== null && order?.merchant_refund_amount !== undefined && order.merchant_refund_amount !== "") {
    return Number(order.merchant_refund_amount);
  }
  return null;
}

function openAfterSale(order) {
  if (!canApplyAfterSale(order) || afterSaleBusy.value) return;
  afterSaleError.value = "";
  afterSaleNotice.value = "";
  afterSaleOpenId.value = order.order_id;
  afterSaleType.value = "REFUND_ONLY";
  afterSaleReason.value = "";
}

function dismissAfterSale() {
  if (afterSaleBusy.value) return;
  afterSaleOpenId.value = "";
  afterSaleError.value = "";
  afterSaleReason.value = "";
}

async function submitAfterSale(order) {
  if (!order || afterSaleBusy.value) return;
  const reason = afterSaleReason.value.trim();
  if (!reason) {
    afterSaleError.value = "请填写申请原因后再提交";
    return;
  }
  afterSaleBusy.value = order.order_id;
  afterSaleError.value = "";
  try {
    const payload = await postJson(
      `/api/c/orders/${encodeURIComponent(order.order_id)}/after-sales`,
      { type: afterSaleType.value, reason }
    );
    // 契约：返回 ticket（兼容直接返回 ticket 或 {ticket} 包装）
    const ticket = payload?.ticket || payload || {};
    afterSaleNotice.value = ticket?.ticket_id
      ? `售后申请已提交：工单 ${ticket.ticket_id}（处理中）`
      : "售后申请已提交，请等待商家处理";
    afterSaleOpenId.value = "";
    afterSaleReason.value = "";
    await loadOrders();
  } catch (e) {
    afterSaleError.value = apiErrorMessage(e, "售后申请提交失败");
  } finally {
    afterSaleBusy.value = "";
  }
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

    <p v-if="cancelNotice" class="state-line state-ok" role="status">{{ cancelNotice }}</p>
    <p v-if="afterSaleNotice" class="state-line state-ok" role="status">{{ afterSaleNotice }}</p>
    <p v-if="cancelError" class="state-line state-error" role="alert">{{ cancelError }}</p>
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
          <div class="order-top-actions">
            <span class="order-status" :class="orderStatusTone(order)">{{ orderStatus(order) }}</span>
            <button
              v-if="canCancel(order)"
              class="order-cancel-btn"
              type="button"
              :disabled="!!cancellingId"
              @click="askCancel(order)"
            >取消订单</button>
            <button
              v-if="canApplyAfterSale(order)"
              class="order-cancel-btn"
              type="button"
              :disabled="!!afterSaleBusy"
              @click="openAfterSale(order)"
            >申请售后</button>
          </div>
        </div>

        <!-- 售后申请：行内表单，类型 + 原因，提交后才创建工单 -->
        <div v-if="afterSaleOpenId === order.order_id" class="after-sale-form">
          <p class="after-sale-form-title">
            申请售后 <code>{{ order.order_id }}</code>
          </p>
          <div class="after-sale-fields">
            <label class="after-sale-field">
              <span>售后类型</span>
              <select v-model="afterSaleType" @change="afterSaleError = ''">
                <option value="REFUND_ONLY">仅退款</option>
                <option value="RETURN_REFUND">退货退款</option>
              </select>
            </label>
            <label class="after-sale-field after-sale-reason">
              <span>申请原因</span>
              <textarea
                v-model="afterSaleReason"
                rows="2"
                maxlength="200"
                placeholder="请说明问题，例如：商品破损 / 未按时发货"
                @input="afterSaleError = ''"
              ></textarea>
            </label>
          </div>
          <p v-if="afterSaleError" class="after-sale-error" role="alert">{{ afterSaleError }}</p>
          <div class="after-sale-form-foot">
            <span class="after-sale-count">{{ afterSaleReason.length }}/200</span>
            <div class="after-sale-form-actions">
              <button type="button" class="ghost-btn" :disabled="!!afterSaleBusy" @click="dismissAfterSale">
                取消
              </button>
              <button
                type="button"
                class="order-cancel-btn is-primary"
                :disabled="!!afterSaleBusy"
                @click="submitAfterSale(order)"
              >{{ afterSaleBusy === order.order_id ? "提交中…" : "提交申请" }}</button>
            </div>
          </div>
        </div>

        <!-- 二次确认：行内展开，避免误触直接取消 -->
        <div v-if="pendingCancelId === order.order_id" class="order-cancel-confirm">
          <p>
            确认取消订单 <strong>{{ order.order_id }}</strong>？已支付金额将原路退回，取消后不可恢复。
          </p>
          <div class="order-cancel-actions">
            <button type="button" class="ghost-btn" :disabled="!!cancellingId" @click="dismissCancel">
              保留订单
            </button>
            <button
              type="button"
              class="order-cancel-btn is-danger"
              :disabled="!!cancellingId"
              @click="confirmCancel(order)"
            >{{ cancellingId === order.order_id ? "取消中…" : "确认取消" }}</button>
          </div>
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

        <!-- 已取消 / 退款信息：只在订单确实已取消时出现 -->
        <div v-if="isCancelled(order)" class="order-refund">
          <span class="order-refund-tag">已取消</span>
          <div v-if="refundAmount(order) !== null" class="refund-row">
            <span>退款金额</span>
            <strong>¥{{ money(refundAmount(order)) }}</strong>
          </div>
          <div v-if="cancelAt(order)" class="refund-row">
            <span>取消时间</span>
            <code>{{ shortMinute(cancelAt(order)) }}</code>
          </div>
        </div>

        <!-- 售后工单：已申请的订单展示状态/工单号/退款；REFUNDED 不再显示取消与申请入口 -->
        <div v-if="afterSaleOf(order)" class="order-after-sale" :class="afterSaleTone(order)">
          <div class="after-sale-head">
            <span class="after-sale-tag">售后 · {{ afterSaleStatusLabel(order) }}</span>
            <code v-if="afterSaleOf(order).ticket_id" class="after-sale-ticket">
              {{ afterSaleOf(order).ticket_id }}
            </code>
          </div>
          <div class="after-sale-meta">
            <span>{{ afterSaleTypeLabel(afterSaleOf(order).type) }}</span>
            <span v-if="afterSaleOf(order).reason">原因：{{ afterSaleOf(order).reason }}</span>
            <span v-if="afterSaleRefundAmount(order) !== null">
              退款金额 ¥{{ money(afterSaleRefundAmount(order)) }}
            </span>
            <span v-if="afterSaleOf(order).created_at">
              申请于 {{ shortMinute(afterSaleOf(order).created_at) }}
            </span>
            <span v-if="afterSaleOf(order).resolved_at">
              处理于 {{ shortMinute(afterSaleOf(order).resolved_at) }}
            </span>
          </div>
        </div>
        <div v-else-if="isRefunded(order)" class="order-after-sale is-refunded">
          <span class="after-sale-tag">售后 · 已退款</span>
        </div>

        <!-- 状态时间线：仅 merchant 订单出现，老订单保持原有简洁样式 -->
        <section v-if="hasMerchantFlow(order)" class="order-timeline" aria-label="订单状态时间线">
          <div class="order-timeline-head">
            <span>状态时间线</span>
            <span v-if="order.merchant_status_at || cancelAt(order)" class="order-timeline-at">
              最近更新 {{ shortMinute(order.merchant_status_at || cancelAt(order)) }}
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

/* 状态提示：加载 / 错误 / 取消成功 */
.state-line {
  min-height: 18px;
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}

.state-error {
  color: var(--danger);
}

.state-ok {
  color: var(--success);
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

.order-top-actions {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
}

/* 取消订单：低调描边按钮，二次确认才用危险色 */
.order-cancel-btn {
  height: 24px;
  padding: 0 10px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--surface);
  color: var(--muted);
  font: inherit;
  font-size: 10px;
  white-space: nowrap;
  cursor: pointer;
}

.order-cancel-btn:hover:not(:disabled) {
  border-color: var(--danger);
  color: var(--danger);
}

.order-cancel-btn.is-danger {
  border-color: color-mix(in srgb, var(--danger) 45%, var(--border));
  background: var(--danger-soft);
  color: var(--danger);
}

.order-cancel-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.order-cancel-confirm {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--danger) 24%, var(--border));
  border-radius: var(--radius-xs);
  background: color-mix(in srgb, var(--danger-soft) 42%, var(--surface));
}

.order-cancel-confirm p {
  margin: 0;
  color: var(--text-2);
  font-size: 11px;
  line-height: 1.6;
}

.order-cancel-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 9px;
}

.order-cancel-actions .ghost-btn {
  height: 24px;
  padding: 0 10px;
  font-size: 10px;
}

/* 提交售后：主色确认按钮 */
.order-cancel-btn.is-primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.order-cancel-btn.is-primary:hover:not(:disabled) {
  border-color: var(--primary-strong);
  background: var(--primary-strong);
  color: #fff;
}

/* ---------- 售后申请表单 ---------- */
.after-sale-form {
  margin-top: 12px;
  padding: 11px 12px;
  border: 1px solid color-mix(in srgb, var(--primary) 22%, var(--border));
  border-radius: var(--radius-xs);
  background: color-mix(in srgb, var(--primary-soft) 26%, var(--surface));
}

.after-sale-form-title {
  margin: 0 0 9px;
  color: var(--text-2);
  font-size: 11px;
}

.after-sale-form-title code {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}

.after-sale-fields {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 10px;
}

.after-sale-field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
  color: var(--muted);
  font-size: 10px;
}

.after-sale-field select,
.after-sale-field textarea {
  padding: 6px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 11px;
  line-height: 1.5;
}

.after-sale-field select {
  min-width: 128px;
}

.after-sale-reason {
  flex: 1 1 240px;
}

.after-sale-reason textarea {
  width: 100%;
  resize: vertical;
}

.after-sale-error {
  margin: 8px 0 0;
  color: var(--danger);
  font-size: 10px;
}

.after-sale-form-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 9px;
}

.after-sale-count {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 9px;
}

.after-sale-form-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.after-sale-form-actions .ghost-btn {
  height: 24px;
  padding: 0 10px;
  font-size: 10px;
}

/* ---------- 售后工单状态 ---------- */
.order-after-sale {
  margin-top: 10px;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface-2);
}

.order-after-sale.is-open {
  border-color: color-mix(in srgb, var(--warn) 30%, var(--border));
  background: color-mix(in srgb, var(--warn-soft) 34%, var(--surface));
}

.order-after-sale.is-approved,
.order-after-sale.is-refunded {
  border-color: color-mix(in srgb, var(--success) 28%, var(--border));
  background: color-mix(in srgb, var(--success-soft) 30%, var(--surface));
}

.order-after-sale.is-rejected {
  border-color: color-mix(in srgb, var(--danger) 24%, var(--border));
  background: color-mix(in srgb, var(--danger-soft) 28%, var(--surface));
}

.after-sale-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}

.after-sale-tag {
  color: var(--text-2);
  font-size: 10px;
  font-weight: 600;
}

.order-after-sale.is-open .after-sale-tag {
  color: var(--warn);
}

.order-after-sale.is-approved .after-sale-tag,
.order-after-sale.is-refunded .after-sale-tag {
  color: var(--success);
}

.order-after-sale.is-rejected .after-sale-tag {
  color: var(--danger);
}

.after-sale-ticket {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 9px;
  word-break: break-all;
}

.after-sale-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 3px 14px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.55;
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

.order-status.is-refunded {
  background: var(--success-soft);
  color: var(--success);
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

/* ---------- 已取消 / 退款 ---------- */
.order-refund {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 16px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
  color: var(--muted);
  font-size: 10px;
}

.order-refund-tag {
  padding: 2px 7px;
  border-radius: 4px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 10px;
}

.refund-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.refund-row strong {
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 500;
}

.refund-row code {
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 10px;
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

  .order-top {
    gap: 8px;
  }

  .order-id {
    word-break: break-all;
  }

  .order-cancel-actions {
    justify-content: flex-end;
  }

  .after-sale-fields {
    flex-direction: column;
    align-items: stretch;
  }

  .after-sale-field select,
  .after-sale-field textarea {
    width: 100%;
  }

  .after-sale-reason {
    flex-basis: auto;
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
