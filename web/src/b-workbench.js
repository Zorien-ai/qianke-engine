import "./b-workbench.css";

/* ============================================================
 * 独立 B 端商家工作台（/v2/b.html）
 * 不依赖 Vue / vue-router，直接渲染三个视图：
 * 订单（状态操作）/ 售后（审批与验收）/ 商品（只读）
 * ========================================================== */

const root = document.getElementById("b-root");

const VIEWS = [
  { key: "orders", label: "订单" },
  { key: "after-sales", label: "售后" },
  { key: "products", label: "商品" },
];

const ORDER_STATUS_LABELS = {
  CREATED: "待支付",
  PAID: "已支付",
  SHIPPED: "已发货",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
  REFUNDED: "已退款",
};

const ORDER_FILTERS = ["", "CREATED", "PAID", "SHIPPED", "COMPLETED", "CANCELLED", "REFUNDED"];
const AFTER_SALE_FILTERS = ["", "OPEN", "RETURN_PENDING", "RETURN_SHIPPED", "APPROVED", "REJECTED"];

const AFTER_SALE_STATUS_LABELS = {
  OPEN: "待处理",
  RETURN_PENDING: "待寄回",
  RETURN_SHIPPED: "退货运输中",
  APPROVED: "已通过",
  REJECTED: "已拒绝",
};

const AFTER_SALE_TYPE_LABELS = {
  REFUND_ONLY: "仅退款",
  RETURN_REFUND: "退货退款",
};

const state = {
  view: "orders",
  me: null,
  meLoaded: false,
  loginRequired: false,
  fatalError: "",
  initialLoading: true,
  loading: false,
  busy: "",
  error: "",
  toast: { message: "", type: "" },
  orderFilter: "",
  afterSaleFilter: "",
  orders: [],
  ordersLoaded: false,
  afterSales: [],
  afterSalesLoaded: false,
  products: [],
  productsLoaded: false,
  shipForm: null,
  cancelConfirmId: "",
};

let toastTimer = null;

/* ---------------- 基础工具 ---------------- */

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function text(value, fallback = "—") {
  const normalized = String(value ?? "").trim();
  return normalized || fallback;
}

function money(value) {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  return Number.isFinite(amount) ? `¥${amount.toFixed(2)}` : `¥${escapeHtml(value)}`;
}

function timeText(value) {
  if (!value) return "—";
  return String(value).replace("T", " ").slice(0, 19);
}

function statusLabel(status) {
  const key = String(status || "").toUpperCase();
  return ORDER_STATUS_LABELS[key] || key || "—";
}

function afterSaleStatusLabel(status) {
  const key = String(status || "").toUpperCase();
  return AFTER_SALE_STATUS_LABELS[key] || key || "—";
}

function afterSaleTypeLabel(type) {
  const key = String(type || "").toUpperCase();
  return AFTER_SALE_TYPE_LABELS[key] || key || "—";
}

function statusTone(status) {
  const key = String(status || "").toUpperCase();
  if (key === "PAID" || key === "SHIPPED" || key === "RETURN_SHIPPED" || key === "RETURN_PENDING") return "is-info";
  if (key === "COMPLETED" || key === "APPROVED") return "is-success";
  if (key === "CANCELLED" || key === "REFUNDED" || key === "REJECTED") return "is-muted";
  return "is-warn";
}

function detailMessage(payload) {
  if (payload === null || payload === undefined) return "";
  if (typeof payload === "string") return payload;
  if (typeof payload !== "object") return "";
  const detail = payload.detail !== undefined ? payload.detail : payload.error;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    return String(detail.message || detail.code || "").trim();
  }
  if (typeof payload.message === "string") return payload.message;
  return "";
}

class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers,
    });
  } catch (cause) {
    throw new ApiError("网络异常，无法连接商家服务", 0, null);
  }
  let payload = null;
  const raw = await response.text();
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = raw;
    }
  }
  if (!response.ok) {
    const message = detailMessage(payload) || `请求失败（HTTP ${response.status}）`;
    throw new ApiError(message, response.status, payload);
  }
  return payload;
}

function errorMessage(error) {
  if (!error) return "未知错误";
  return String(error.message || error).trim() || "请求失败";
}

function isAuthError(error) {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

function showToast(message, type = "success") {
  const value = String(message || "").trim();
  if (!value) return;
  state.toast = { message: value, type };
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    state.toast = { message: "", type: "" };
    toastTimer = null;
    render();
  }, 3600);
}

function clearToast() {
  if (toastTimer) {
    clearTimeout(toastTimer);
    toastTimer = null;
  }
  state.toast = { message: "", type: "" };
}

/* ---------------- 数据加载 ---------------- */

function merchantFrom(data) {
  const source = data?.merchant || data?.data?.merchant || data?.data || data || {};
  const account = data?.account || source?.account || {};
  return {
    name: text(
      source.merchant_name ?? source.merchantName ?? source.name ?? source.display_name ?? account.display_name,
      "商家"
    ),
    id: text(source.merchant_id ?? source.merchantId ?? source.id ?? account.merchant_id, ""),
  };
}

async function loadMe() {
  const data = await api("/api/b/workbench/me");
  state.me = merchantFrom(data);
  state.meLoaded = true;
  state.loginRequired = false;
  state.fatalError = "";
  document.title = `${state.me.name} · 商家工作台`;
}

function collectionFrom(data, keys) {
  if (Array.isArray(data)) return data;
  for (const key of keys) {
    const value = data?.[key];
    if (Array.isArray(value)) return value;
  }
  const nested = data?.data;
  if (nested && typeof nested === "object") {
    for (const key of keys) {
      const value = nested[key];
      if (Array.isArray(value)) return value;
    }
  }
  return [];
}

function handleAuthFailure(error) {
  if (!isAuthError(error)) return false;
  if (error.status === 401) {
    state.loginRequired = true;
    state.fatalError = "";
  } else {
    state.fatalError = errorMessage(error) || "当前账号没有商家工作台的访问权限（HTTP 403）。";
  }
  state.initialLoading = false;
  state.loading = false;
  state.busy = "";
  state.me = null;
  state.meLoaded = false;
  render();
  return true;
}

async function loadOrders(force = true) {
  if (state.loading && !force) return;
  state.loading = true;
  state.error = "";
  render();
  try {
    const query = new URLSearchParams({ limit: "100" });
    if (state.orderFilter) query.set("status", state.orderFilter);
    const data = await api(`/api/b/workbench/orders?${query.toString()}`);
    state.orders = collectionFrom(data, ["orders"]);
    state.ordersLoaded = true;
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.loading = false;
    render();
  }
}

async function loadAfterSales(force = true) {
  if (state.loading && !force) return;
  state.loading = true;
  state.error = "";
  render();
  try {
    const query = new URLSearchParams({ limit: "100" });
    if (state.afterSaleFilter) query.set("status", state.afterSaleFilter);
    const data = await api(`/api/b/workbench/after-sales?${query.toString()}`);
    state.afterSales = collectionFrom(data, ["tickets", "after_sales", "afterSales", "aftersales"]);
    state.afterSalesLoaded = true;
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.loading = false;
    render();
  }
}

async function loadProducts() {
  state.loading = true;
  state.error = "";
  render();
  try {
    const data = await api("/api/b/workbench/products");
    state.products = collectionFrom(data, ["products"]);
    state.productsLoaded = true;
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.loading = false;
    render();
  }
}

async function ensureViewData(view = state.view) {
  if (view === "orders") {
    if (!state.ordersLoaded) await loadOrders();
    return;
  }
  if (view === "after-sales") {
    if (!state.afterSalesLoaded) await loadAfterSales();
    return;
  }
  if (view === "products") {
    if (!state.productsLoaded) await loadProducts();
  }
}

async function switchView(view) {
  if (!VIEWS.some((item) => item.key === view) || state.view === view) return;
  state.view = view;
  state.error = "";
  state.shipForm = null;
  state.cancelConfirmId = "";
  render();
  await ensureViewData(view);
}

async function refreshCurrent() {
  state.error = "";
  if (state.view === "orders") await loadOrders();
  else if (state.view === "after-sales") await loadAfterSales();
  else await loadProducts();
}

/* ---------------- 订单操作 ---------------- */

function findOrder(orderId) {
  return state.orders.find((order) => String(order.order_id) === String(orderId)) || null;
}

async function patchOrderStatus(orderId, status, extra = {}) {
  const order = findOrder(orderId);
  if (!order || state.busy) return;
  state.busy = `order:${orderId}`;
  state.error = "";
  render();
  try {
    await api(`/api/b/workbench/orders/${encodeURIComponent(orderId)}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, ...extra }),
    });
    state.shipForm = null;
    state.cancelConfirmId = "";
    showToast(`订单 ${orderId} 已更新为「${statusLabel(status)}」`, "success");
    await loadOrders();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    if (state.shipForm && String(state.shipForm.orderId) === String(orderId)) {
      state.shipForm = { ...state.shipForm, error: state.error };
    }
    showToast(state.error, "error");
  } finally {
    state.busy = "";
    render();
  }
}

function openShipForm(orderId) {
  state.shipForm = { orderId, tracking: "", carrier: "", error: "" };
  state.cancelConfirmId = "";
  render();
  const input = document.getElementById("b-ship-tracking");
  if (input) input.focus();
}

function closeShipForm() {
  state.shipForm = null;
  render();
}

function submitShipment() {
  const form = state.shipForm;
  if (!form || state.busy) return;
  const trackingInput = document.getElementById("b-ship-tracking");
  const carrierInput = document.getElementById("b-ship-carrier");
  const tracking = String(trackingInput?.value || form.tracking || "").trim();
  const carrier = String(carrierInput?.value || form.carrier || "").trim();
  state.shipForm = { ...form, tracking, carrier, error: "" };
  if (!tracking) {
    state.shipForm.error = "请填写物流单号（至少 4 位）";
    render();
    return;
  }
  if (tracking.length < 4) {
    state.shipForm.error = "物流单号至少 4 位";
    render();
    return;
  }
  patchOrderStatus(form.orderId, "SHIPPED", {
    tracking_no: tracking,
    carrier: carrier || undefined,
  });
}

async function onOrderAction(action, orderId) {
  if (state.busy) return;
  const order = findOrder(orderId);
  if (!order) return;
  if (action === "paid") {
    await patchOrderStatus(orderId, "PAID");
  } else if (action === "complete") {
    await patchOrderStatus(orderId, "COMPLETED");
  } else if (action === "ship") {
    openShipForm(orderId);
  } else if (action === "ship-submit") {
    submitShipment();
  } else if (action === "ship-cancel") {
    closeShipForm();
  } else if (action === "cancel") {
    state.cancelConfirmId = orderId;
    state.shipForm = null;
    render();
  } else if (action === "cancel-dismiss") {
    state.cancelConfirmId = "";
    render();
  } else if (action === "cancel-confirm") {
    await patchOrderStatus(orderId, "CANCELLED");
  }
}

/* ---------------- 售后操作 ---------------- */

function findTicket(ticketId) {
  return state.afterSales.find((ticket) => String(ticket.ticket_id) === String(ticketId)) || null;
}

async function resolveAfterSale(ticket, approved) {
  if (!ticket || state.busy) return;
  state.busy = `ticket:${ticket.ticket_id}`;
  state.error = "";
  render();
  try {
    await api(`/api/b/workbench/after-sales/${encodeURIComponent(ticket.ticket_id)}`, {
      method: "PATCH",
      body: JSON.stringify({ approved }),
    });
    const isReturn = String(ticket.type || "").toUpperCase() === "RETURN_REFUND";
    showToast(
      approved
        ? isReturn
          ? `已同意退货工单 ${ticket.ticket_id}，等待买家寄回`
          : `已通过工单 ${ticket.ticket_id}，退款将写入订单`
        : `已拒绝工单 ${ticket.ticket_id}`,
      "success"
    );
    await loadAfterSales();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.busy = "";
    render();
  }
}

async function receiveAfterSale(ticket, accepted) {
  if (!ticket || state.busy) return;
  state.busy = `ticket:${ticket.ticket_id}`;
  state.error = "";
  render();
  try {
    await api(`/api/b/workbench/after-sales/${encodeURIComponent(ticket.ticket_id)}/receive`, {
      method: "POST",
      body: JSON.stringify({ accepted }),
    });
    showToast(
      accepted
        ? `工单 ${ticket.ticket_id} 验收通过，退款与库存已恢复`
        : `工单 ${ticket.ticket_id} 已拒收`,
      "success"
    );
    await loadAfterSales();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.busy = "";
    render();
  }
}

async function onTicketAction(action, ticketId) {
  if (state.busy) return;
  const ticket = findTicket(ticketId);
  if (!ticket) return;
  if (action === "approve") await resolveAfterSale(ticket, true);
  else if (action === "reject") await resolveAfterSale(ticket, false);
  else if (action === "receive") await receiveAfterSale(ticket, true);
  else if (action === "reject-receive") await receiveAfterSale(ticket, false);
}

/* ---------------- 渲染 ---------------- */

function badge(status, label) {
  return `<span class="b-badge ${statusTone(status)}">${escapeHtml(label)}</span>`;
}

function toastMarkup() {
  if (!state.toast.message) return "";
  return `<div class="b-toast ${state.toast.type === "error" ? "is-error" : "is-success"}" role="status">
    <span>${escapeHtml(state.toast.message)}</span>
    <button type="button" class="b-toast-close" data-dismiss-toast aria-label="关闭提示">×</button>
  </div>`;
}

function authViewMarkup() {
  return `<div class="b-fullscreen">
    <section class="b-card b-auth-card">
      <div class="b-brand b-brand-center"><span class="b-brand-mark">千客</span><span class="b-brand-sub">商家工作台</span></div>
      <h1>请先登录</h1>
      <p>商家工作台需要登录商家账号后使用，未登录不会展示任何经营数据。</p>
      <div class="b-auth-actions">
        <a class="b-btn b-btn-primary" href="/v2/">去登录</a>
        <button type="button" class="b-btn b-btn-ghost" data-retry>重新检查</button>
      </div>
    </section>
  </div>`;
}

function fatalViewMarkup(message) {
  return `<div class="b-fullscreen">
    <section class="b-card b-auth-card">
      <div class="b-brand b-brand-center"><span class="b-brand-mark">千客</span><span class="b-brand-sub">商家工作台</span></div>
      <h1>无法加载商家工作台</h1>
      <p class="b-error-text">${escapeHtml(message || "商家服务暂时不可用，请稍后重试。")}</p>
      <div class="b-auth-actions">
        <button type="button" class="b-btn b-btn-primary" data-retry>重试</button>
        <a class="b-btn b-btn-ghost" href="/v2/">去登录</a>
      </div>
    </section>
  </div>`;
}

function orderCard(order) {
  const id = String(order.order_id || "");
  const status = String(order.status || "").toUpperCase();
  const busy = state.busy === `order:${id}`;
  const attrs = `data-order-id="${escapeHtml(id)}" ${busy ? "disabled" : ""}`;
  const showShipForm = state.shipForm && String(state.shipForm.orderId) === id;
  const showCancelConfirm = state.cancelConfirmId === id;
  const items = Array.isArray(order.items) ? order.items : [];
  const itemsText = items.length
    ? items
        .map((item) => `${text(item.title || item.product_id, "商品")} × ${Number(item.quantity || 1)}`)
        .join("、")
    : text(order.item_count, "—");
  const logistics =
    order.carrier || order.tracking_no
      ? [order.carrier, order.tracking_no].filter(Boolean).join(" · ")
      : "—";

  const buttons = [];
  if (status === "CREATED") {
    buttons.push(`<button type="button" class="b-btn b-btn-primary" data-order-action="paid" ${attrs}>标记已支付</button>`);
    buttons.push(`<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-order-action="cancel" ${attrs}>取消订单</button>`);
  } else if (status === "PAID") {
    buttons.push(`<button type="button" class="b-btn b-btn-primary" data-order-action="ship" ${attrs}>发货</button>`);
    buttons.push(`<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-order-action="cancel" ${attrs}>取消订单</button>`);
  } else if (status === "SHIPPED") {
    buttons.push(`<button type="button" class="b-btn b-btn-primary" data-order-action="complete" ${attrs}>完成订单</button>`);
  } else {
    buttons.push(`<span class="b-muted">当前状态无可用操作</span>`);
  }

  const shipForm = showShipForm
    ? `<div class="b-ship-form">
        <p class="b-form-title">填写物流信息后发货</p>
        <div class="b-ship-fields">
          <label>物流单号（必填）
            <input id="b-ship-tracking" type="text" maxlength="64" value="${escapeHtml(state.shipForm.tracking)}" placeholder="如 SF1234567890" autocomplete="off" />
          </label>
          <label>承运商（可选）
            <input id="b-ship-carrier" type="text" maxlength="64" value="${escapeHtml(state.shipForm.carrier)}" placeholder="如 顺丰速运" autocomplete="off" />
          </label>
        </div>
        ${state.shipForm.error ? `<p class="b-field-error" role="alert">${escapeHtml(state.shipForm.error)}</p>` : ""}
        <div class="b-actions">
          <button type="button" class="b-btn b-btn-primary" data-order-action="ship-submit" ${attrs}>${busy ? "提交中…" : "确认发货"}</button>
          <button type="button" class="b-btn b-btn-ghost" data-order-action="ship-cancel" ${busy ? "disabled" : ""}>取消</button>
        </div>
      </div>`
    : "";

  const cancelConfirm = showCancelConfirm
    ? `<div class="b-confirm">
        <p>确认取消订单 <code>${escapeHtml(id)}</code>？取消后不可恢复。</p>
        <div class="b-actions">
          <button type="button" class="b-btn b-btn-danger" data-order-action="cancel-confirm" ${attrs}>确认取消</button>
          <button type="button" class="b-btn b-btn-ghost" data-order-action="cancel-dismiss" ${busy ? "disabled" : ""}>放弃</button>
        </div>
      </div>`
    : "";

  return `<article class="b-card b-order-card">
    <div class="b-card-head">
      <div class="b-card-title">
        <code class="b-mono">${escapeHtml(text(id))}</code>
        ${badge(status, statusLabel(status))}
      </div>
      <time>${escapeHtml(timeText(order.created_at))}</time>
    </div>
    <dl class="b-meta">
      <div><dt>买家</dt><dd>${escapeHtml(text(order.buyer_id))}</dd></div>
      <div><dt>金额</dt><dd class="b-amount">${money(order.total_amount)}</dd></div>
      <div><dt>商品</dt><dd>${escapeHtml(itemsText)}</dd></div>
      <div><dt>物流</dt><dd>${escapeHtml(logistics)}</dd></div>
    </dl>
    <div class="b-actions">${buttons.join("")}</div>
    ${cancelConfirm}
    ${shipForm}
  </article>`;
}

function afterSaleCard(ticket) {
  const id = String(ticket.ticket_id || "");
  const status = String(ticket.status || "").toUpperCase();
  const type = String(ticket.type || "").toUpperCase();
  const busy = state.busy === `ticket:${id}`;
  const attrs = `data-ticket-id="${escapeHtml(id)}" ${busy ? "disabled" : ""}`;
  const isReturn = type === "RETURN_REFUND";
  const buttons = [];
  if (status === "OPEN") {
    buttons.push(
      `<button type="button" class="b-btn b-btn-primary" data-ticket-action="approve" ${attrs}>${isReturn ? "同意退货" : "通过"}</button>`
    );
    buttons.push(
      `<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-ticket-action="reject" ${attrs}>拒绝</button>`
    );
  } else if (status === "RETURN_SHIPPED") {
    buttons.push(
      `<button type="button" class="b-btn b-btn-primary" data-ticket-action="receive" ${attrs}>验收通过</button>`
    );
    buttons.push(
      `<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-ticket-action="reject-receive" ${attrs}>拒收</button>`
    );
  } else if (status === "RETURN_PENDING") {
    buttons.push(`<span class="b-muted">等待买家寄回</span>`);
  } else {
    buttons.push(`<span class="b-muted">当前状态无可用操作</span>`);
  }

  const returnInfo = [
    ticket.return_tracking_no
      ? `退回运单 ${[ticket.return_carrier, ticket.return_tracking_no].filter(Boolean).join(" · ")}`
      : "",
    ticket.return_shipped_at ? `寄回 ${timeText(ticket.return_shipped_at)}` : "",
    ticket.received_at ? `入库 ${timeText(ticket.received_at)}` : "",
  ]
    .filter(Boolean)
    .join("　");

  return `<article class="b-card b-ticket-card">
    <div class="b-card-head">
      <div class="b-card-title">
        <code class="b-mono">${escapeHtml(text(id))}</code>
        ${badge(status, afterSaleStatusLabel(status))}
        <span class="b-tag">${escapeHtml(afterSaleTypeLabel(type))}</span>
      </div>
      <time>${escapeHtml(timeText(ticket.created_at))}</time>
    </div>
    <dl class="b-meta">
      <div><dt>订单</dt><dd><code class="b-mono">${escapeHtml(text(ticket.order_id))}</code></dd></div>
      <div><dt>退款金额</dt><dd class="b-amount">${money(ticket.refund_amount)}</dd></div>
      <div class="b-meta-wide"><dt>原因</dt><dd>${escapeHtml(text(ticket.reason))}</dd></div>
    </dl>
    ${returnInfo ? `<p class="b-return-info">${escapeHtml(returnInfo)}</p>` : ""}
    <div class="b-actions">${buttons.join("")}</div>
  </article>`;
}

function productCard(product) {
  const status = String(product.status || "").toUpperCase();
  const skuPrice = Array.isArray(product.skus) && product.skus.length ? product.skus[0].price : "";
  const price = product.price ?? product.unit_price ?? skuPrice;
  const stock = product.stock ?? product.available_stock ?? product.inventory?.available;
  const category = [product.category, product.brand].filter(Boolean).join(" · ");
  return `<article class="b-card b-product-card">
    <div class="b-card-head">
      <div class="b-card-title">
        <strong>${escapeHtml(text(product.title || product.name, "商品"))}</strong>
        <code class="b-mono">${escapeHtml(text(product.product_id))}</code>
      </div>
      ${status ? `<span class="b-badge ${status === "ACTIVE" ? "is-success" : "is-muted"}">${escapeHtml(status === "ACTIVE" ? "在售" : status)}</span>` : ""}
    </div>
    <dl class="b-meta">
      <div><dt>价格</dt><dd class="b-amount">${price === "" || price === null || price === undefined ? "—" : money(price)}</dd></div>
      <div><dt>库存</dt><dd>${stock === null || stock === undefined ? "—" : escapeHtml(stock)}</dd></div>
      <div><dt>分类</dt><dd>${escapeHtml(text(category))}</dd></div>
      <div><dt>更新时间</dt><dd>${escapeHtml(timeText(product.updated_at || product.created_at))}</dd></div>
    </dl>
  </article>`;
}

function skeletonMarkup(count = 3) {
  return `<div class="b-skeletons">${Array.from({ length: count }, () => `<div class="b-skeleton"></div>`).join("")}</div>`;
}

function emptyMarkup(message) {
  return `<div class="b-empty">${escapeHtml(message)}</div>`;
}

function ordersView() {
  const body = state.loading && !state.orders.length
    ? skeletonMarkup()
    : state.orders.length
      ? `<div class="b-list">${state.orders.map(orderCard).join("")}</div>`
      : emptyMarkup("暂无订单");
  return `<section class="b-view" aria-label="订单">
    <div class="b-view-head">
      <div>
        <h1>订单</h1>
        <p class="b-muted">共 ${state.orders.length} 单${state.loading ? " · 刷新中…" : ""}</p>
      </div>
      <div class="b-view-tools">
        <label class="b-filter">状态
          <select data-order-filter ${state.loading ? "disabled" : ""}>
            ${ORDER_FILTERS.map((value) => `<option value="${value}" ${state.orderFilter === value ? "selected" : ""}>${value ? statusLabel(value) : "全部状态"}</option>`).join("")}
          </select>
        </label>
        <button type="button" class="b-btn b-btn-ghost" data-refresh ${state.loading || state.busy ? "disabled" : ""}>刷新</button>
      </div>
    </div>
    ${body}
  </section>`;
}

function afterSalesView() {
  const body = state.loading && !state.afterSales.length
    ? skeletonMarkup()
    : state.afterSales.length
      ? `<div class="b-list">${state.afterSales.map(afterSaleCard).join("")}</div>`
      : emptyMarkup("暂无售后工单");
  return `<section class="b-view" aria-label="售后">
    <div class="b-view-head">
      <div>
        <h1>售后</h1>
        <p class="b-muted">共 ${state.afterSales.length} 单${state.loading ? " · 刷新中…" : ""}</p>
      </div>
      <div class="b-view-tools">
        <label class="b-filter">状态
          <select data-after-sale-filter ${state.loading ? "disabled" : ""}>
            ${AFTER_SALE_FILTERS.map((value) => `<option value="${value}" ${state.afterSaleFilter === value ? "selected" : ""}>${value ? afterSaleStatusLabel(value) : "全部状态"}</option>`).join("")}
          </select>
        </label>
        <button type="button" class="b-btn b-btn-ghost" data-refresh ${state.loading || state.busy ? "disabled" : ""}>刷新</button>
      </div>
    </div>
    ${body}
  </section>`;
}

function productsView() {
  const body = state.loading && !state.products.length
    ? skeletonMarkup(2)
    : state.products.length
      ? `<div class="b-product-grid">${state.products.map(productCard).join("")}</div>`
      : emptyMarkup("暂无商品");
  return `<section class="b-view" aria-label="商品">
    <div class="b-view-head">
      <div>
        <h1>商品</h1>
        <p class="b-muted">只读 · 共 ${state.products.length} 个商品${state.loading ? " · 刷新中…" : ""}</p>
      </div>
      <div class="b-view-tools">
        <button type="button" class="b-btn b-btn-ghost" data-refresh ${state.loading || state.busy ? "disabled" : ""}>刷新</button>
      </div>
    </div>
    ${body}
  </section>`;
}

function shellMarkup() {
  const activeView = VIEWS.find((view) => view.key === state.view) || VIEWS[0];
  const viewMarkup =
    activeView.key === "orders"
      ? ordersView()
      : activeView.key === "after-sales"
        ? afterSalesView()
        : productsView();
  const merchantName = state.me?.name || "商家";
  const merchantId = state.me?.id || "";
  return `<div class="b-shell">
    <header class="b-header">
      <div class="b-brand"><span class="b-brand-mark">千客</span><span class="b-brand-sub">商家工作台</span></div>
      <div class="b-merchant">
        <strong>${escapeHtml(merchantName)}</strong>
        ${merchantId ? `<code class="b-mono">${escapeHtml(merchantId)}</code>` : ""}
      </div>
      <div class="b-header-actions">
        <a class="b-text-link" href="/v2/">返回 C 端</a>
      </div>
    </header>
    <nav class="b-nav" aria-label="商家工作台视图">
      ${VIEWS.map((view) => `<button type="button" class="b-nav-btn ${state.view === view.key ? "active" : ""}" data-view="${view.key}" ${state.loading || state.busy ? 'aria-disabled="true"' : ""}>${view.label}</button>`).join("")}
    </nav>
    ${state.error ? `<p class="b-inline-error" role="alert"><span>${escapeHtml(state.error)}</span><button type="button" class="b-inline-close" data-clear-error aria-label="关闭错误提示">×</button></p>` : ""}
    <main class="b-main">${viewMarkup}</main>
    ${toastMarkup()}
  </div>`;
}

function render() {
  if (state.loginRequired) {
    root.innerHTML = authViewMarkup() + toastMarkup();
    bindEvents();
    return;
  }
  if (state.fatalError && !state.me) {
    root.innerHTML = fatalViewMarkup(state.fatalError) + toastMarkup();
    bindEvents();
    return;
  }
  if (state.initialLoading && !state.me) {
    root.innerHTML = `<div class="b-boot"><span class="b-spinner" aria-hidden="true"></span>正在加载商家工作台…</div>`;
    return;
  }
  root.innerHTML = shellMarkup();
  bindEvents();
}

/* ---------------- 事件绑定 ---------------- */

let eventsBound = false;

function bindEvents() {
  if (eventsBound) return;
  eventsBound = true;

  root.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    if (target.closest("[data-retry]")) {
      boot();
      return;
    }
    if (target.closest("[data-clear-error]")) {
      state.error = "";
      render();
      return;
    }
    if (target.closest("[data-dismiss-toast]")) {
      clearToast();
      render();
      return;
    }
    const viewButton = target.closest("[data-view]");
    if (viewButton) {
      await switchView(viewButton.dataset.view);
      return;
    }
    if (target.closest("[data-refresh]")) {
      if (state.loading || state.busy) return;
      await refreshCurrent();
      return;
    }
    const orderButton = target.closest("[data-order-action]");
    if (orderButton) {
      await onOrderAction(orderButton.dataset.orderAction, orderButton.dataset.orderId);
      return;
    }
    const ticketButton = target.closest("[data-ticket-action]");
    if (ticketButton) {
      await onTicketAction(ticketButton.dataset.ticketAction, ticketButton.dataset.ticketId);
    }
  });

  root.addEventListener("change", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLSelectElement)) return;
    if (target.matches("[data-order-filter]")) {
      state.orderFilter = target.value;
      await loadOrders();
      return;
    }
    if (target.matches("[data-after-sale-filter]")) {
      state.afterSaleFilter = target.value;
      await loadAfterSales();
    }
  });

  root.addEventListener("keydown", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (event.key === "Escape" && (state.shipForm || state.cancelConfirmId)) {
      state.shipForm = null;
      state.cancelConfirmId = "";
      render();
    }
  });
}

/* ---------------- 启动 ---------------- */

async function boot() {
  clearToast();
  state.initialLoading = true;
  state.loginRequired = false;
  state.fatalError = "";
  state.me = null;
  state.meLoaded = false;
  state.ordersLoaded = false;
  state.afterSalesLoaded = false;
  state.productsLoaded = false;
  state.orders = [];
  state.afterSales = [];
  state.products = [];
  state.error = "";
  state.shipForm = null;
  state.cancelConfirmId = "";
  render();
  try {
    await loadMe();
    await loadOrders();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.fatalError = errorMessage(error);
  } finally {
    state.initialLoading = false;
    render();
  }
}

boot();
