<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { apiFetch, ApiError, detailMessage, getJson, patchJson, postJson, readBody } from "../api";
import { toast, toastError } from "../store";

const PAGE_SIZE = 20;

const orders = ref([]);
const quotes = ref([]);
const summary = ref({});
const ordersTotal = ref(0);
const quotesTotal = ref(0);
const offset = ref(0);
const loading = ref(true);
const exporting = ref(false);
const error = ref("");
const buyerId = ref("");
const quoteStatus = ref("");
const dateFrom = ref("");
const dateTo = ref("");

/* ---------- 运营台视图切换（交易审计 / 商家订单 / 售后工单） ---------- */
const VIEWS = [
  { key: "audit", label: "交易审计" },
  { key: "merchant", label: "商家订单" },
  { key: "after-sales", label: "售后工单" },
];
const activeView = ref("audit");

/* ---------- 商家订单运营 ---------- */
const MERCHANT_STATUS_LABELS = {
  CREATED: "待支付",
  PAID: "已支付",
  SHIPPED: "已发货",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  REFUNDED: "已退款",
};
const MERCHANT_STATUS_OPTIONS = ["CREATED", "PAID", "SHIPPED", "COMPLETED", "CANCELLED", "REFUNDED"];

const merchantOrders = ref([]);
const merchantLoading = ref(false);
const merchantError = ref("");
const merchantStatus = ref("");
const merchantBusy = ref("");
const shipFormId = ref("");
const shipTracking = ref("");
const shipCarrier = ref("");
const shipError = ref("");

/* ---------- 售后工单审批 ---------- */
const AFTER_SALE_STATUS_LABELS = {
  OPEN: "待处理",
  RETURN_PENDING: "待寄回",
  RETURN_SHIPPED: "退货运输中",
  APPROVED: "已通过",
  REJECTED: "已拒绝",
};
const AFTER_SALE_TYPE_LABELS = { REFUND_ONLY: "仅退款", RETURN_REFUND: "退货退款" };

const afterSales = ref([]);
const afterSaleLoading = ref(false);
const afterSaleError = ref("");
const afterSaleStatus = ref("");
const afterSaleBusy = ref("");

const activeLoading = computed(() => {
  if (activeView.value === "merchant") return merchantLoading.value;
  if (activeView.value === "after-sales") return afterSaleLoading.value;
  return loading.value;
});

function money(value) {
  return `¥${Number(value || 0).toFixed(2)}`;
}
function date(value) {
  return value ? String(value).replace("T", " ").slice(0, 19) : "—";
}
function policyLabel(policy) {
  return policy.title || policy.policy_id || "政策";
}
function productLabel(product) {
  return product.title || product.product_id || "商品";
}

const pendingQuotes = computed(() => summary.value.pending_quotes || 0);
const quoteStatusCounts = computed(() => summary.value.quote_status || {});
const maxTotal = computed(() => Math.max(ordersTotal.value, quotesTotal.value));
const totalPages = computed(() => Math.max(1, Math.ceil(maxTotal.value / PAGE_SIZE)));
const currentPage = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1);
const hasPrev = computed(() => offset.value > 0);
const hasNext = computed(() => offset.value + PAGE_SIZE < maxTotal.value);

// 列表、分页与 CSV 导出共用同一套筛选参数拼装，避免两处逻辑分叉导致参数不一致。
function filterParams() {
  const params = new URLSearchParams();
  if (buyerId.value.trim()) params.set("buyer_id", buyerId.value.trim());
  if (quoteStatus.value) params.set("status", quoteStatus.value);
  if (dateFrom.value) params.set("date_from", dateFrom.value);
  if (dateTo.value) params.set("date_to", dateTo.value);
  return params;
}

function pageParams() {
  const params = filterParams();
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String(offset.value));
  return params;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await getJson(`/api/c/admin/audit?${pageParams().toString()}`);
    orders.value = data?.orders || [];
    quotes.value = data?.quotes || [];
    summary.value = data?.summary || {};
    ordersTotal.value = Number(data?.orders_total || 0);
    quotesTotal.value = Number(data?.quotes_total || 0);
    // 后端会钳制 offset；若当前页因数据变少越界，回到最后一页重新拉取。
    const lastPageOffset = Math.max(0, Math.ceil(maxTotal.value / PAGE_SIZE) - 1) * PAGE_SIZE;
    if (maxTotal.value > 0 && offset.value > lastPageOffset) {
      offset.value = lastPageOffset;
      await load();
      return;
    }
    offset.value = Math.max(0, Number(data?.offset ?? offset.value));
  } catch (e) {
    error.value = e?.detail || e?.message || "审计数据加载失败";
    toastError?.(e);
  } finally {
    loading.value = false;
  }
}

function changePage(delta) {
  const nextOffset = offset.value + delta * PAGE_SIZE;
  if (nextOffset < 0) return;
  if (nextOffset >= maxTotal.value && delta > 0) return;
  offset.value = nextOffset;
  load();
}

// 筛选条件一变就回到第一页，避免用旧 offset 命中另一套筛选结果。
watch([buyerId, quoteStatus, dateFrom, dateTo], () => {
  offset.value = 0;
});

function attachmentFilename(disposition) {
  const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(disposition || "");
  if (!match) return "";
  const raw = match[1] ? decodeURIComponent(match[1]) : match[2];
  return (raw || "").trim();
}

// 下载必须带会话 Cookie：apiFetch 内部固定 credentials: "same-origin"（HttpOnly Cookie 会话）。
async function exportCsv() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    const params = filterParams();
    // CSV 导出当前筛选下最近 50 条（不跟随列表分页 offset）。
    params.set("limit", "50");
    const res = await apiFetch(`/api/c/admin/audit/export?${params.toString()}`);
    if (!res.ok) {
      const data = await readBody(res);
      throw new ApiError(res.status, detailMessage(data, res.status), data);
    }
    const blob = await res.blob();
    const filename = attachmentFilename(res.headers.get("Content-Disposition")) || "c_end_audit.csv";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast("已导出当前筛选条件下的订单 CSV", "success");
  } catch (e) {
    // 导出失败只提示，不覆盖页面已有的审计数据。
    toast(e?.detail || e?.message || "CSV 导出失败，请稍后重试", "error", 5000);
  } finally {
    exporting.value = false;
  }
}

function resetFilters() {
  buyerId.value = "";
  quoteStatus.value = "";
  dateFrom.value = "";
  dateTo.value = "";
  offset.value = 0;
  load();
}

/* ================= 商家订单 ================= */
function merchantStatusLabel(status) {
  return MERCHANT_STATUS_LABELS[String(status || "").toUpperCase()] || status || "—";
}

function merchantStatusBadge(status) {
  const key = String(status || "").toUpperCase();
  if (key === "PAID" || key === "SHIPPED") return "is-primary";
  if (key === "COMPLETED") return "is-success";
  if (key === "CANCELLED") return "is-danger";
  if (key === "REFUNDED") return "is-warn";
  return "";
}

function merchantItemSummary(order) {
  const items = Array.isArray(order?.items) ? order.items : [];
  return items.map((item) => `${item.title || item.product_id} ×${item.quantity}`).join("、") || "—";
}

function canMarkPaid(order) {
  return String(order?.status || "").toUpperCase() === "CREATED";
}
function canShip(order) {
  return String(order?.status || "").toUpperCase() === "PAID";
}
function canComplete(order) {
  return String(order?.status || "").toUpperCase() === "SHIPPED";
}
function canCancelOrder(order) {
  return ["CREATED", "PAID"].includes(String(order?.status || "").toUpperCase());
}
function hasMerchantActions(order) {
  return canMarkPaid(order) || canShip(order) || canComplete(order) || canCancelOrder(order);
}

/** 后端 detail 可能是字符串，也可能是 {code,message}（MerchantError / HTTPException）。 */
function errorMessage(e) {
  const detail = e?.payload?.detail;
  if (detail && typeof detail === "object") {
    return detail.message || detail.code || "操作失败";
  }
  return e?.detail || e?.message || "操作失败";
}

async function loadMerchantOrders() {
  merchantLoading.value = true;
  merchantError.value = "";
  try {
    const params = new URLSearchParams({ limit: "100" });
    if (merchantStatus.value) params.set("status", merchantStatus.value);
    const data = await getJson(`/api/c/admin/merchant/orders?${params.toString()}`);
    merchantOrders.value = data?.orders || [];
  } catch (e) {
    merchantError.value = errorMessage(e);
    toast(merchantError.value, "error", 5000);
  } finally {
    merchantLoading.value = false;
  }
}

function openShipForm(order) {
  if (!canShip(order) || merchantBusy.value) return;
  shipFormId.value = order.order_id;
  shipTracking.value = order.tracking_no || "";
  shipCarrier.value = order.carrier || "";
  shipError.value = "";
}

function closeShipForm() {
  if (merchantBusy.value) return;
  shipFormId.value = "";
  shipError.value = "";
}

async function patchOrderStatus(order, status, extra = {}) {
  if (!order || merchantBusy.value) return;
  merchantBusy.value = order.order_id;
  shipError.value = "";
  try {
    await patchJson(`/api/c/admin/merchant/orders/${encodeURIComponent(order.order_id)}/status`, {
      status,
      ...extra,
    });
    toast(`订单 ${order.order_id} 已更新为 ${merchantStatusLabel(status)}`, "success");
    shipFormId.value = "";
    await loadMerchantOrders();
  } catch (e) {
    const message = errorMessage(e);
    if (shipFormId.value === order.order_id) shipError.value = message;
    toast(message, "error", 5000);
  } finally {
    merchantBusy.value = "";
  }
}

function markOrderPaid(order) {
  return patchOrderStatus(order, "PAID");
}

function completeMerchantOrder(order) {
  return patchOrderStatus(order, "COMPLETED");
}

function cancelMerchantOrder(order) {
  return patchOrderStatus(order, "CANCELLED");
}

function submitShip(order) {
  const tracking = shipTracking.value.trim();
  if (!tracking) {
    shipError.value = "请填写物流单号";
    return;
  }
  if (tracking.length < 4) {
    shipError.value = "物流单号至少 4 位";
    return;
  }
  return patchOrderStatus(order, "SHIPPED", {
    tracking_no: tracking,
    carrier: shipCarrier.value.trim() || null,
  });
}

/** 发货表单在表格外：按当前展开的订单号找回订单再提交 */
function submitShipForPending() {
  const order = merchantOrders.value.find((item) => item.order_id === shipFormId.value);
  if (!order) {
    shipFormId.value = "";
    return;
  }
  return submitShip(order);
}

/* ================= 售后工单 ================= */
function afterSaleStatusLabel(status) {
  return AFTER_SALE_STATUS_LABELS[String(status || "").toUpperCase()] || status || "—";
}

function afterSaleStatusBadge(status) {
  const key = String(status || "").toUpperCase();
  if (key === "APPROVED") return "is-success";
  if (key === "REJECTED") return "is-danger";
  if (key === "RETURN_SHIPPED") return "is-primary";
  return "is-warn";
}

function afterSaleTypeLabel(type) {
  return AFTER_SALE_TYPE_LABELS[String(type || "").toUpperCase()] || type || "—";
}

function afterSaleRefundText(ticket) {
  return ticket?.refund_amount === null || ticket?.refund_amount === undefined
    ? "—"
    : money(ticket.refund_amount);
}

function afterSaleStatusKey(ticket) {
  return String(ticket?.status || "").toUpperCase();
}

/** 退货退款：OPEN 时是「同意退货」，寄回后进入验收 */
function isReturnTicket(ticket) {
  return String(ticket?.type || "").toUpperCase() === "RETURN_REFUND";
}

function canReceiveTicket(ticket) {
  // 只有用户已寄回（RETURN_SHIPPED）才能验收；待寄回阶段不能替用户确认物流。
  return afterSaleStatusKey(ticket) === "RETURN_SHIPPED";
}

function afterSaleReturnText(ticket) {
  const tracking = String(ticket?.return_tracking_no || "").trim();
  if (!tracking) return "—";
  const carrier = String(ticket?.return_carrier || "").trim();
  return carrier ? `${carrier} · ${tracking}` : tracking;
}

async function loadAfterSales() {
  afterSaleLoading.value = true;
  afterSaleError.value = "";
  try {
    const params = new URLSearchParams();
    if (afterSaleStatus.value) params.set("status", afterSaleStatus.value);
    const query = params.toString();
    const data = await getJson(`/api/c/admin/after-sales${query ? `?${query}` : ""}`);
    afterSales.value = data?.tickets || [];
  } catch (e) {
    afterSaleError.value = errorMessage(e);
    toast(afterSaleError.value, "error", 5000);
  } finally {
    afterSaleLoading.value = false;
  }
}

async function resolveAfterSale(ticket, approved) {
  if (!ticket || afterSaleBusy.value) return;
  afterSaleBusy.value = ticket.ticket_id;
  try {
    await patchJson(`/api/c/admin/after-sales/${encodeURIComponent(ticket.ticket_id)}`, { approved });
    toast(
      approved
        ? isReturnTicket(ticket)
          ? `已同意退货工单 ${ticket.ticket_id}，等待用户寄回`
          : `已通过工单 ${ticket.ticket_id}，退款已写入订单`
        : `已拒绝工单 ${ticket.ticket_id}`,
      "success"
    );
    await loadAfterSales();
  } catch (e) {
    toast(errorMessage(e), "error", 5000);
  } finally {
    afterSaleBusy.value = "";
  }
}

/** 退货验收入库：accepted=true 退款并恢复库存；false = 拒收 */
async function receiveAfterSale(ticket, accepted) {
  if (!ticket || afterSaleBusy.value) return;
  afterSaleBusy.value = ticket.ticket_id;
  try {
    await postJson(
      `/api/c/admin/after-sales/${encodeURIComponent(ticket.ticket_id)}/receive`,
      { accepted }
    );
    toast(
      accepted
        ? `工单 ${ticket.ticket_id} 验收通过，退款与库存已恢复`
        : `工单 ${ticket.ticket_id} 已拒收`,
      "success"
    );
    await loadAfterSales();
  } catch (e) {
    toast(errorMessage(e), "error", 5000);
  } finally {
    afterSaleBusy.value = "";
  }
}

/* ================= 视图切换 ================= */
function switchView(view) {
  if (activeView.value === view) return;
  activeView.value = view;
  if (view === "merchant") loadMerchantOrders();
  else if (view === "after-sales") loadAfterSales();
}

function refreshActive() {
  if (activeView.value === "merchant") loadMerchantOrders();
  else if (activeView.value === "after-sales") loadAfterSales();
  else load();
}

onMounted(load);
</script>

<template>
  <div class="page admin-page">
    <div class="admin-hero">
      <div>
        <div class="monitor-kicker">C-END OPS</div>
        <div class="admin-title-line">
          <h2>商家运营台</h2>
          <span class="badge is-warn">系统管理员</span>
        </div>
        <p class="card-sub">
          交易审计只读；商家订单与售后工单为平台管理员的受控操作入口，操作后立即刷新列表。
        </p>
      </div>
      <div class="audit-hero-actions">
        <button type="button" class="btn btn-ghost" :disabled="activeLoading" @click="refreshActive">
          刷新
        </button>
        <button
          v-if="activeView === 'audit'"
          type="button"
          class="btn btn-primary"
          :disabled="exporting || loading"
          @click="exportCsv"
        >{{ exporting ? "导出中…" : "导出 CSV" }}</button>
      </div>
    </div>

    <div class="op-tabs" role="tablist" aria-label="运营台视图">
      <button
        v-for="view in VIEWS"
        :key="view.key"
        type="button"
        role="tab"
        class="op-tab"
        :class="{ 'is-active': activeView === view.key }"
        :aria-selected="activeView === view.key"
        @click="switchView(view.key)"
      >{{ view.label }}</button>
    </div>

    <!-- ========== 视图一：交易审计（原有功能全部保留） ========== -->
    <template v-if="activeView === 'audit'">
    <section class="audit-filters" aria-label="审计筛选">
      <label>
        <span>买家</span>
        <input v-model="buyerId" type="text" placeholder="buyer_1" />
      </label>
      <label>
        <span>报价状态</span>
        <select v-model="quoteStatus">
          <option value="">全部</option>
          <option value="PENDING">PENDING</option>
          <option value="CONSUMED">CONSUMED</option>
          <option value="CANCELLED">CANCELLED</option>
        </select>
      </label>
      <label>
        <span>开始日期</span>
        <input v-model="dateFrom" type="date" />
      </label>
      <label>
        <span>结束日期</span>
        <input v-model="dateTo" type="date" />
      </label>
      <div class="audit-filter-actions">
        <button type="button" class="btn btn-primary" :disabled="loading" @click="load">应用</button>
        <button type="button" class="btn btn-ghost" :disabled="loading" @click="resetFilters">重置</button>
      </div>
    </section>

    <div v-if="loading" class="card"><div class="skeleton" style="height:100px"></div></div>
    <div v-else-if="error" class="card">
      <div class="empty-state">
        <div class="empty-title">加载失败</div>
        <div class="empty-desc">{{ error }}</div>
      </div>
    </div>

    <template v-else>
      <section class="audit-stats">
        <div class="audit-stat">
          <span>已确认订单</span>
          <strong>{{ summary.order_count || 0 }}</strong>
          <small>{{ quoteStatus ? `仅 ${quoteStatus} 关联订单` : "本页" }} · 共 {{ ordersTotal }} 条</small>
        </div>
        <div class="audit-stat">
          <span>成交金额</span>
          <strong>{{ money(summary.gmv || 0) }}</strong>
          <small>按本页订单应付合计</small>
        </div>
        <div class="audit-stat">
          <span>报价记录</span>
          <strong>{{ summary.quote_count || 0 }}</strong>
          <small>本页 · 共 {{ quotesTotal }} 条</small>
        </div>
        <div class="audit-stat">
          <span>待确认报价</span>
          <strong>{{ pendingQuotes }}</strong>
          <small>本页 PENDING</small>
        </div>
      </section>

      <section class="card">
        <div class="admin-section-head">
          <strong>订单与报价绑定</strong>
          <span class="field-hint">{{ quoteStatus ? `按报价状态 ${quoteStatus} 关联订单 · ` : "" }}quote_id / policy_ids / 原价 / 优惠</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>订单</th>
                <th>买家</th>
                <th>报价</th>
                <th>政策</th>
                <th>原价</th>
                <th>优惠</th>
                <th>应付</th>
                <th>确认时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="order in orders" :key="order.order_id">
                <td class="mono">{{ order.order_id }}</td>
                <td>{{ order.buyer_id }}</td>
                <td class="mono">{{ order.quote_id || "—" }}</td>
                <td>
                  <span v-for="policy in order.policy_ids" :key="policy" class="audit-chip">{{ policy }}</span>
                  <span v-if="!order.policy_ids?.length" class="field-hint">—</span>
                </td>
                <td>{{ money(order.original_amount) }}</td>
                <td>{{ money(order.discount_amount) }}</td>
                <td><strong>{{ money(order.total_amount) }}</strong></td>
                <td class="field-hint">{{ date(order.confirmed_at) }}</td>
              </tr>
              <tr v-if="!orders.length">
                <td colspan="8" class="field-hint">{{ quoteStatus ? `暂无关联 ${quoteStatus} 报价的已确认订单` : "暂无已确认订单" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card" style="margin-top:16px">
        <div class="admin-section-head">
          <strong>结构化报价</strong>
          <span class="field-hint">
            {{ quoteStatusCounts.PENDING || 0 }} pending · {{ quoteStatusCounts.CONSUMED || 0 }} consumed · {{ quoteStatusCounts.CANCELLED || 0 }} cancelled
          </span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>报价</th>
                <th>买家</th>
                <th>状态</th>
                <th>商品</th>
                <th>政策</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="quote in quotes" :key="quote.quote_id">
                <td class="mono">{{ quote.quote_id }}</td>
                <td>{{ quote.buyer_id }}</td>
                <td><span class="badge" :class="{ 'is-ok': quote.status === 'CONSUMED', 'is-warn': quote.status === 'PENDING' }">{{ quote.status }}</span></td>
                <td>
                  <span v-for="product in quote.product_refs" :key="product.product_id" class="audit-chip">
                    {{ productLabel(product) }} × {{ product.quantity || 1 }}
                  </span>
                  <span v-if="!quote.product_refs?.length" class="field-hint">—</span>
                </td>
                <td>
                  <span v-for="policy in quote.policy_refs" :key="policy.policy_id" class="audit-chip">
                    {{ policyLabel(policy) }}
                  </span>
                  <span v-if="!quote.policy_refs?.length" class="field-hint">—</span>
                </td>
                <td class="field-hint">{{ date(quote.created_at) }}</td>
              </tr>
              <tr v-if="!quotes.length">
                <td colspan="6" class="field-hint">暂无报价记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="audit-pagination" aria-label="订单与报价分页">
        <button
          type="button"
          class="btn btn-ghost"
          :disabled="!hasPrev || loading"
          @click="changePage(-1)"
        >上一页</button>
        <span class="field-hint">
          第 {{ currentPage }} / {{ totalPages }} 页 · 订单共 {{ ordersTotal }} 条 · 报价共 {{ quotesTotal }} 条
        </span>
        <button
          type="button"
          class="btn btn-ghost"
          :disabled="!hasNext || loading"
          @click="changePage(1)"
        >下一页</button>
      </section>
    </template>
    </template><!-- /视图一：交易审计 -->

    <!-- ========== 视图二：商家订单 ========== -->
    <template v-else-if="activeView === 'merchant'">
      <section class="audit-filters" aria-label="商家订单筛选">
        <label>
          <span>订单状态</span>
          <select v-model="merchantStatus" :disabled="merchantLoading" @change="loadMerchantOrders">
            <option value="">全部</option>
            <option v-for="status in MERCHANT_STATUS_OPTIONS" :key="status" :value="status">
              {{ merchantStatusLabel(status) }}（{{ status }}）
            </option>
          </select>
        </label>
        <div class="audit-filter-actions">
          <button type="button" class="btn btn-primary" :disabled="merchantLoading" @click="loadMerchantOrders">
            {{ merchantLoading ? "刷新中…" : "刷新" }}
          </button>
        </div>
      </section>

      <div v-if="merchantLoading && !merchantOrders.length" class="card">
        <div class="skeleton" style="height:100px"></div>
      </div>
      <div v-else-if="merchantError" class="card">
        <div class="empty-state">
          <div class="empty-title">商家订单加载失败</div>
          <div class="empty-desc">{{ merchantError }}</div>
        </div>
      </div>

      <section v-else class="card">
        <div class="admin-section-head">
          <strong>商家订单</strong>
          <span class="field-hint">
            共 {{ merchantOrders.length }} 条 · 当前筛选 {{ merchantStatus ? merchantStatusLabel(merchantStatus) : "全部" }} · 每次操作后自动刷新
          </span>
        </div>
        <div class="table-wrap op-table-wrap">
          <table class="table op-table">
            <thead>
              <tr>
                <th>订单</th>
                <th>买家</th>
                <th>状态</th>
                <th>商品</th>
                <th>金额</th>
                <th>物流</th>
                <th>时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="order in merchantOrders" :key="order.order_id">
                <tr>
                  <td class="mono">{{ order.order_id }}</td>
                  <td>{{ order.buyer_id }}</td>
                  <td>
                    <span class="badge" :class="merchantStatusBadge(order.status)">
                      {{ merchantStatusLabel(order.status) }}
                    </span>
                  </td>
                  <td class="op-cell-wrap">{{ merchantItemSummary(order) }}</td>
                  <td>{{ money(order.total_amount) }}</td>
                  <td>
                    <template v-if="order.tracking_no">
                      <span class="mono">{{ order.tracking_no }}</span>
                      <br />
                      <span class="field-hint">{{ order.carrier || "—" }}</span>
                    </template>
                    <span v-else class="field-hint">—</span>
                  </td>
                  <td class="field-hint">
                    {{ date(order.shipped_at || order.paid_at || order.created_at) }}
                  </td>
                  <td>
                    <div class="op-actions">
                      <button
                        v-if="canMarkPaid(order)"
                        type="button"
                        class="btn btn-primary op-btn"
                        :disabled="!!merchantBusy"
                        @click="markOrderPaid(order)"
                      >标记已支付</button>
                      <button
                        v-if="canShip(order)"
                        type="button"
                        class="btn btn-ghost op-btn"
                        :disabled="!!merchantBusy"
                        @click="openShipForm(order)"
                      >发货</button>
                      <button
                        v-if="canComplete(order)"
                        type="button"
                        class="btn btn-ghost op-btn"
                        :disabled="!!merchantBusy"
                        @click="completeMerchantOrder(order)"
                      >标记完成</button>
                      <button
                        v-if="canCancelOrder(order)"
                        type="button"
                        class="btn btn-ghost op-btn is-danger"
                        :disabled="!!merchantBusy"
                        @click="cancelMerchantOrder(order)"
                      >取消</button>
                      <span v-if="!hasMerchantActions(order)" class="field-hint">—</span>
                    </div>
                  </td>
                </tr>
              </template>
              <tr v-if="!merchantOrders.length">
                <td colspan="8" class="field-hint">暂无商家订单</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 发货表单不放在表格里：移动端跟随页面宽度，而不是被宽表横向撑开 -->
        <div v-if="shipFormId" class="ship-form-panel">
          <p class="ship-form-title">
            发货 · <span class="mono">{{ shipFormId }}</span>
          </p>
          <div class="ship-form">
            <label>
              <span>物流单号（必填）</span>
              <input v-model="shipTracking" type="text" maxlength="64" placeholder="如 SF1234567890" />
            </label>
            <label>
              <span>承运商（可选）</span>
              <input v-model="shipCarrier" type="text" maxlength="64" placeholder="如 顺丰速运" />
            </label>
            <p v-if="shipError" class="op-error">{{ shipError }}</p>
            <div class="op-actions">
              <button type="button" class="btn btn-ghost" :disabled="!!merchantBusy" @click="closeShipForm">
                取消
              </button>
              <button
                type="button"
                class="btn btn-primary"
                :disabled="!!merchantBusy"
                @click="submitShipForPending"
              >{{ merchantBusy === shipFormId ? "提交中…" : "确认发货" }}</button>
            </div>
          </div>
        </div>
      </section>
    </template><!-- /视图二：商家订单 -->

    <!-- ========== 视图三：售后工单 ========== -->
    <template v-else>
      <section class="audit-filters" aria-label="售后工单筛选">
        <label>
          <span>工单状态</span>
          <select v-model="afterSaleStatus" :disabled="afterSaleLoading" @change="loadAfterSales">
            <option value="">全部</option>
            <option value="OPEN">待处理（OPEN）</option>
            <option value="RETURN_PENDING">待寄回（RETURN_PENDING）</option>
            <option value="RETURN_SHIPPED">退货运输中（RETURN_SHIPPED）</option>
            <option value="APPROVED">已通过（APPROVED）</option>
            <option value="REJECTED">已拒绝（REJECTED）</option>
          </select>
        </label>
        <div class="audit-filter-actions">
          <button type="button" class="btn btn-primary" :disabled="afterSaleLoading" @click="loadAfterSales">
            {{ afterSaleLoading ? "刷新中…" : "刷新" }}
          </button>
        </div>
      </section>

      <div v-if="afterSaleLoading && !afterSales.length" class="card">
        <div class="skeleton" style="height:100px"></div>
      </div>
      <div v-else-if="afterSaleError" class="card">
        <div class="empty-state">
          <div class="empty-title">售后工单加载失败</div>
          <div class="empty-desc">{{ afterSaleError }}</div>
        </div>
      </div>

      <section v-else class="card">
        <div class="admin-section-head">
          <strong>售后工单</strong>
          <span class="field-hint">
            共 {{ afterSales.length }} 条 · 当前筛选 {{ afterSaleStatus ? afterSaleStatusLabel(afterSaleStatus) : "全部" }} · 退货工单需用户寄回后验收
          </span>
        </div>
        <div class="table-wrap op-table-wrap">
          <table class="table op-table">
            <thead>
              <tr>
                <th>工单</th>
                <th>订单</th>
                <th>买家</th>
                <th>类型</th>
                <th>状态</th>
                <th>退款金额</th>
                <th>原因</th>
                <th>创建 / 处理时间</th>
                <th>退回运单 / 入库</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ticket in afterSales" :key="ticket.ticket_id">
                <td class="mono">{{ ticket.ticket_id }}</td>
                <td class="mono">{{ ticket.order_id }}</td>
                <td>{{ ticket.buyer_id }}</td>
                <td>{{ afterSaleTypeLabel(ticket.type) }}</td>
                <td>
                  <span class="badge" :class="afterSaleStatusBadge(ticket.status)">
                    {{ afterSaleStatusLabel(ticket.status) }}
                  </span>
                </td>
                <td>{{ afterSaleRefundText(ticket) }}</td>
                <td class="op-cell-wrap">{{ ticket.reason || "—" }}</td>
                <td class="field-hint">
                  {{ date(ticket.created_at) }}
                  <template v-if="ticket.resolved_at"> · {{ date(ticket.resolved_at) }}</template>
                </td>
                <td class="field-hint">
                  <template v-if="ticket.return_tracking_no">
                    <span class="mono">{{ ticket.return_carrier || "物流" }}</span>
                    <br />{{ ticket.return_tracking_no }}
                  </template>
                  <template v-else>—</template>
                  <template v-if="ticket.received_at">
                    <br />入库 {{ date(ticket.received_at) }}
                  </template>
                </td>
                <td>
                  <div class="op-actions">
                    <template v-if="afterSaleStatusKey(ticket) === 'OPEN'">
                      <template v-if="isReturnTicket(ticket)">
                        <button
                          type="button"
                          class="btn btn-primary op-btn"
                          :disabled="!!afterSaleBusy"
                          @click="resolveAfterSale(ticket, true)"
                        >同意退货</button>
                        <button
                          type="button"
                          class="btn btn-ghost op-btn is-danger"
                          :disabled="!!afterSaleBusy"
                          @click="resolveAfterSale(ticket, false)"
                        >拒绝</button>
                      </template>
                      <template v-else>
                        <button
                          type="button"
                          class="btn btn-primary op-btn"
                          :disabled="!!afterSaleBusy"
                          @click="resolveAfterSale(ticket, true)"
                        >通过</button>
                        <button
                          type="button"
                          class="btn btn-ghost op-btn is-danger"
                          :disabled="!!afterSaleBusy"
                          @click="resolveAfterSale(ticket, false)"
                        >拒绝</button>
                      </template>
                    </template>
                    <template v-else-if="canReceiveTicket(ticket)">
                      <button
                        type="button"
                        class="btn btn-primary op-btn"
                        :disabled="!!afterSaleBusy"
                        @click="receiveAfterSale(ticket, true)"
                      >验收通过</button>
                      <button
                        type="button"
                        class="btn btn-ghost op-btn is-danger"
                        :disabled="!!afterSaleBusy"
                        @click="receiveAfterSale(ticket, false)"
                      >拒收</button>
                    </template>
                    <span v-else class="field-hint">—</span>
                  </div>
                </td>
              </tr>
              <tr v-if="!afterSales.length">
                <td colspan="10" class="field-hint">暂无售后工单</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template><!-- /视图三：售后工单 -->
  </div>
</template>

<style scoped>
.admin-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.monitor-kicker {
  color: var(--primary);
  font-family: var(--font-mono, monospace);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.admin-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 4px;
}

.admin-title-line h2 {
  margin: 0;
  font-size: 22px;
}

/* 视图切换：白底细边框胶囊 */
.op-tabs {
  display: flex;
  width: fit-content;
  max-width: 100%;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 16px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.op-tab {
  height: 30px;
  padding: 0 14px;
  border: none;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.op-tab:hover {
  color: var(--text);
}

.op-tab.is-active {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 600;
}

.audit-hero-actions {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
}

.audit-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.audit-filters {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.audit-filters label {
  display: flex;
  min-width: 140px;
  flex-direction: column;
  gap: 5px;
  color: var(--muted);
  font-size: 10px;
}

.audit-filters input,
.audit-filters select {
  height: 32px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface-2);
  color: var(--text);
  font: inherit;
  font-size: 11px;
}

.audit-filter-actions {
  display: flex;
  gap: 6px;
}

.audit-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 16px;
}

.audit-pagination .field-hint {
  font-size: 10px;
}

.audit-stat {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.audit-stat span {
  color: var(--muted);
  font-size: 11px;
}

.audit-stat strong {
  font-family: var(--mono);
  font-size: 22px;
  font-weight: 600;
}

.audit-stat small {
  color: var(--muted);
  font-size: 9px;
}

.audit-chip {
  display: inline-block;
  margin: 1px 3px 1px 0;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 10px;
}

.mono {
  font-family: var(--mono);
  font-size: 10px;
}

.admin-section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
}

/* ---------- 商家订单 / 售后工单操作 ---------- */
.op-table-wrap {
  margin-top: 12px;
}

.op-table td {
  vertical-align: middle;
}

.op-cell-wrap {
  max-width: 280px;
  white-space: normal;
  word-break: break-word;
  color: var(--text-2);
  font-size: 12px;
}

.op-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.op-btn {
  height: 26px;
  padding: 0 10px;
  font-size: 10px;
}

.btn.op-btn.is-danger,
.op-btn.is-danger {
  border-color: color-mix(in srgb, var(--danger) 35%, var(--border));
  color: var(--danger);
  background: var(--danger-soft);
}

.op-expand-row td {
  background: var(--surface-2);
}

.ship-form-panel {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--primary) 22%, var(--border));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--primary-soft) 24%, var(--surface));
}

.ship-form-title {
  margin: 0 0 8px;
  color: var(--text-2);
  font-size: 11px;
}

.ship-form {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 12px;
  padding: 4px 0;
}

.ship-form label {
  display: flex;
  min-width: 180px;
  flex-direction: column;
  gap: 4px;
  color: var(--muted);
  font-size: 10px;
}

.ship-form input {
  width: 220px;
  max-width: 100%;
  height: 30px;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 11px;
}

.op-error {
  margin: 0;
  color: var(--danger);
  font-size: 10px;
}

@media (max-width: 820px) {
  .audit-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .op-tabs {
    width: 100%;
  }

  .op-tabs .op-tab {
    flex: 1;
    padding: 0 8px;
  }

  .ship-form {
    flex-direction: column;
    align-items: stretch;
  }

  .ship-form label {
    min-width: 0;
  }

  .ship-form input {
    width: 100%;
  }

  .audit-hero-actions {
    width: 100%;
  }
}
</style>
