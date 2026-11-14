import "./b-workbench.css";

/* ============================================================
 * 独立 B 端商家工作台（/v2/b.html）
 * 不依赖 Vue / vue-router，直接渲染四个视图：
 * 订单（状态操作）/ 售后（审批与验收）/ 商品（只读）/ Super-agent（事件与人工审批）
 * ========================================================== */

const root = document.getElementById("b-root");

const VIEWS = [
  { key: "overview", label: "工作首页", short: "首页", group: "工作台" },
  { key: "orders", label: "订单", short: "订单", group: "交易" },
  { key: "after-sales", label: "售后", short: "售后", group: "交易" },
  { key: "products", label: "商品与 SKU", short: "商品", group: "商品与库存" },
  { key: "chat-profiles", label: "用户画像", short: "画像", group: "客户" },
  { key: "superagent", label: "调查与审批", short: "协作", group: "经营协作" },
  { key: "policy", label: "动作策略", short: "策略", group: "管理" },
  { key: "audit", label: "执行审计", short: "审计", group: "管理" },
];
const NAV_GROUPS = ["工作台", "交易", "商品与库存", "客户", "经营协作", "管理"];

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

const SUPERAGENT_STATUS_LABELS = {
  PENDING: "待运行",
  RUNNING: "调查中",
  WAITING_APPROVAL: "待审批",
  EXECUTING: "执行中",
  DONE: "已完成",
  EXECUTION_FAILED: "执行失败",
  REJECTED: "已驳回",
  FAILED: "失败",
  STUCK: "卡住",
  CANCELLED: "已停止",
};

const APPROVAL_STATUS_LABELS = {
  NONE: "未触发",
  PENDING: "待审批",
  APPROVED: "已通过",
  REJECTED: "已驳回",
};

const ACTION_LABELS = {
  CANCEL_ORDER: "取消订单",
  CREATE_AFTER_SALE: "创建售后工单",
  SHIP_ORDER: "发货",
  COMPLETE_ORDER: "完成订单",
  REFUND_AFTER_SALE: "售后退款",
  RECEIVE_RETURN: "退货验收入库",
  REJECT_AFTER_SALE: "驳回售后",
  ISSUE_COMPENSATION: "发放补偿",
};

const ACTION_SALE_TYPE_LABELS = {
  REFUND_ONLY: "仅退款",
  RETURN_REFUND: "退货退款",
};

const EXECUTION_STATUS_LABELS = {
  NONE: "未执行",
  EXECUTED: "已执行",
  FAILED: "执行失败",
};

const SUPERAGENT_EVENT_EXAMPLE =
  "请查订单 order_xxx，买家反馈物流异常要售后，确认是否需要人工介入。";

const state = {
  view: "overview",
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
  orderQuery: "",
  orderDateFrom: "",
  orderDateTo: "",
  orderLimit: 20,
  orderOffset: 0,
  orderTotal: 0,
  afterSaleFilter: "",
  overview: null,
  overviewLoaded: false,
  overviewLoading: false,
  orders: [],
  ordersLoaded: false,
  afterSales: [],
  afterSalesLoaded: false,
  products: [],
  productsLoaded: false,
  chatProfiles: [],
  chatProfilesLoaded: false,
  productFilter: "all",
  productQuery: "",
  productView: "products",
  productSummary: null,
  inventoryDraft: null,
  inventoryAlerts: [],
  inventoryAlertsLoaded: false,
  inventoryScanning: false,
  inventoryDispatching: false,
  policy: null,
  policyLoaded: false,
  policySaving: false,
  auditActions: [],
  auditPolicy: [],
  auditChain: null,
  auditTotal: 0,
  auditPolicyTotal: 0,
  auditLoaded: false,
  auditFilters: {
    action_type: "",
    execution_status: "",
    q: "",
    date_from: "",
    date_to: "",
    limit: 50,
    offset: 0,
    policy_offset: 0,
    policy_limit: 10,
  },
  shipForm: null,
  cancelConfirmId: "",
  orderDetailId: "",
  statusConfirm: null,
  selectedOrderIds: new Set(),
  mobileMoreOpen: false,
  /* Super-agent */
  workItems: [],
  workItemsLoaded: false,
  workItemsLoading: false,
  eventDraft: "",
  eventSubmitting: false,
  eventNotice: null,
  busyWorkItem: "",
  workItemDetailId: "",
  workItemDetail: null,
  watchdogBusy: false,
  approveConfirm: null,
  actionParams: {},
  executionCache: {},
};

let toastTimer = null;
let workPollTimer = null;
const executionPollTimers = new Map();

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
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
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
    role: text(data?.merchant?.role ?? source.role, ""),
    permissions: Array.isArray(data?.permissions) ? data.permissions : [],
  };
}

function can(permission) {
  return state.me?.permissions?.includes(permission) ?? true;
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
    const query = new URLSearchParams({
      limit: String(state.orderLimit),
      offset: String(state.orderOffset),
    });
    if (state.orderFilter) query.set("status", state.orderFilter);
    if (state.orderQuery) query.set("q", state.orderQuery);
    if (state.orderDateFrom) query.set("date_from", state.orderDateFrom);
    if (state.orderDateTo) query.set("date_to", state.orderDateTo);
    const data = await api(`/api/b/workbench/orders?${query.toString()}`);
    state.orders = collectionFrom(data, ["orders"]);
    state.orderTotal = Number(data?.total ?? state.orders.length);
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

async function uploadProductImages(productId, files) {
  const selected = Array.from(files || []);
  if (!productId || !selected.length) return;
  for (const file of selected) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      showToast("只支持 PNG / JPEG / WebP", "error");
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      showToast("单张图片不能超过 2MB", "error");
      return;
    }
  }
  const form = new FormData();
  for (const file of selected) form.append("files", file);
  try {
    const data = await api(`/api/b/workbench/products/${encodeURIComponent(productId)}/images`, {
      method: "POST",
      body: form,
    });
    showToast(`已添加 ${selected.length} 张图片`, "success");
    await loadProducts();
    return data;
  } catch (error) {
    if (handleAuthFailure(error)) return;
    showToast(errorMessage(error), "error");
  }
}

async function deleteProductImage(productId, imageUrl) {
  if (!productId || !imageUrl) return;
  if (!window.confirm("删除这张商品图片？")) return;
  try {
    await api(
      `/api/b/workbench/products/${encodeURIComponent(productId)}/images?url=${encodeURIComponent(imageUrl)}`,
      { method: "DELETE" },
    );
    showToast("商品图片已删除", "success");
    await loadProducts();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    showToast(errorMessage(error), "error");
  }
}

async function loadProducts() {
  state.loading = true;
  state.error = "";
  render();
  try {
    const data = await api("/api/b/workbench/products");
    state.products = collectionFrom(data, ["products"]);
    state.productSummary = data?.summary || null;
    state.productsLoaded = true;
    await loadInventoryAlerts();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.loading = false;
    render();
  }
}

async function loadInventoryAlerts() {
  try {
    const data = await api("/api/b/workbench/inventory/alerts?status=PENDING&limit=100");
    state.inventoryAlerts = collectionFrom(data, ["alerts"]);
    state.inventoryAlertsLoaded = true;
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.inventoryAlerts = [];
    state.inventoryAlertsLoaded = false;
  }
}

async function scanInventoryAlerts() {
  if (state.inventoryScanning) return;
  state.inventoryScanning = true;
  render();
  try {
    const data = await api("/api/b/workbench/inventory/alerts/scan", {
      method: "POST",
      body: JSON.stringify({}),
    });
    state.inventoryAlerts = collectionFrom(data, ["alerts"]);
    state.inventoryAlertsLoaded = true;
    state.productSummary = state.productSummary || null;
    const created = Number(data?.created || 0);
    const resolved = Number(data?.resolved || 0);
    showToast(`扫描完成：新增 ${created} 条，恢复 ${resolved} 条，待发送 ${Number(data?.pending || 0)} 条。`);
    await loadProducts();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    showToast(errorMessage(error), "error");
  } finally {
    state.inventoryScanning = false;
    render();
  }
}

async function ackInventoryAlert(alertId) {
  if (!alertId || state.busy) return;
  state.busy = "inventory-alert-ack";
  render();
  try {
    await api(`/api/b/workbench/inventory/alerts/${encodeURIComponent(alertId)}/ack`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    await loadInventoryAlerts();
    showToast("库存告警已标记为已处理。");
  } catch (error) {
    if (handleAuthFailure(error)) return;
    showToast(errorMessage(error), "error");
  } finally {
    state.busy = "";
    render();
  }
}

async function dispatchInventoryAlerts() {
  if (state.inventoryDispatching) return;
  state.inventoryDispatching = true;
  render();
  try {
    const data = await api("/api/b/workbench/inventory/alerts/dispatch", {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (data?.sent) {
      showToast(`已推送 ${Number(data.dispatched || 0)} 条库存告警到企业微信。`);
    } else if (data?.reason === "NO_RECIPIENT") {
      showToast("未配置企业微信接收人：请设置 QIANKE_INVENTORY_ALERT_WECOM_TOUSER。", "error");
    } else if (data?.reason === "NOT_CONFIGURED") {
      showToast("企业微信应用消息未配置 Secret/AgentId。", "error");
    } else {
      showToast(`告警未发送：${data?.reason || "UNKNOWN"}`, "error");
    }
    await loadInventoryAlerts();
    await loadProducts();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    showToast(errorMessage(error), "error");
  } finally {
    state.inventoryDispatching = false;
    render();
  }
}

async function loadChatProfiles() {
  state.loading = true;
  state.error = "";
  render();
  try {
    const data = await api("/api/b/workbench/chat-profiles?limit=100");
    state.chatProfiles = collectionFrom(data, ["profiles"]);
    state.chatProfilesLoaded = true;
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.loading = false;
    render();
  }
}

async function loadPolicy() {
  state.loading = true;
  state.error = "";
  render();
  try {
    const data = await api("/api/superagent/policy");
    state.policy = data.policy || null;
    state.policyLoaded = true;
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.loading = false;
    render();
  }
}

async function savePolicy() {
  if (state.policySaving) return;
  const allowed = [...root.querySelectorAll("[data-policy-action]:checked")].map((input) => input.value);
  const compensation = Number(document.getElementById("b-policy-compensation")?.value || 0);
  const refund = Number(document.getElementById("b-policy-refund")?.value || 0);
  const requireNote = Boolean(document.getElementById("b-policy-note")?.checked);
  state.policySaving = true;
  state.error = "";
  render();
  try {
    const data = await api("/api/superagent/policy", {
      method: "PUT",
      body: JSON.stringify({
        allowed_actions: allowed,
        compensation_max_amount: compensation,
        refund_max_amount: refund,
        require_note: requireNote,
      }),
    });
    state.policy = data.policy || state.policy;
    state.policyLoaded = true;
    showToast("动作策略已保存");
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.policySaving = false;
    render();
  }
}

async function loadAudit() {
  state.loading = true;
  state.error = "";
  render();
  try {
    const f = state.auditFilters;
    const params = new URLSearchParams({
      limit: String(f.limit),
      offset: String(f.offset),
    });
    if (f.action_type) params.set("action_type", f.action_type);
    if (f.execution_status) params.set("execution_status", f.execution_status);
    if (f.q) params.set("q", f.q);
    if (f.date_from) params.set("date_from", f.date_from);
    if (f.date_to) params.set("date_to", f.date_to);
    const policyParams = new URLSearchParams({
      limit: String(f.policy_limit),
      offset: String(f.policy_offset),
    });
    if (f.date_from) policyParams.set("date_from", f.date_from);
    if (f.date_to) policyParams.set("date_to", f.date_to);
    const [actions, policy, chain] = await Promise.all([
      api(`/api/superagent/audit/actions?${params.toString()}`),
      api(`/api/superagent/audit/policy?${policyParams.toString()}`),
      api("/api/superagent/audit/policy/verify"),
    ]);
    state.auditActions = actions.items || [];
    state.auditTotal = Number(actions.total || 0);
    state.auditPolicy = policy.items || [];
    state.auditPolicyTotal = Number(policy.total || 0);
    state.auditChain = chain || null;
    state.auditLoaded = true;
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    showToast(state.error, "error");
  } finally {
    state.loading = false;
    render();
  }
}

function auditExportUrl() {
  const f = state.auditFilters;
  const params = new URLSearchParams();
  if (f.action_type) params.set("action_type", f.action_type);
  if (f.execution_status) params.set("execution_status", f.execution_status);
  if (f.q) params.set("q", f.q);
  if (f.date_from) params.set("date_from", f.date_from);
  if (f.date_to) params.set("date_to", f.date_to);
  return `/api/superagent/audit/actions.csv?${params.toString()}`;
}

function auditPolicyExportUrl() {
  const f = state.auditFilters;
  const params = new URLSearchParams();
  if (f.date_from) params.set("date_from", f.date_from);
  if (f.date_to) params.set("date_to", f.date_to);
  return `/api/superagent/audit/policy.csv?${params.toString()}`;
}

async function ensureViewData(view = state.view) {
  if (view === "overview") {
    if (!state.overviewLoaded) await loadOverview();
    return;
  }
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
    return;
  }
  if (view === "superagent") {
    if (!state.workItemsLoaded) await loadWorkItems();
    else syncWorkPolling();
    return;
  }
  if (view === "policy") {
    if (!state.policyLoaded) await loadPolicy();
    return;
  }
  if (view === "audit") {
    if (!state.auditLoaded) await loadAudit();
  }
  if (view === "chat-profiles") {
    if (!state.chatProfilesLoaded) await loadChatProfiles();
  }
}

async function switchView(view) {
  if (!VIEWS.some((item) => item.key === view) || state.view === view) return;
  if (state.view === "superagent" && view !== "superagent") {
    stopWorkPolling();
    stopAllExecutionPolling();
  }
  state.view = view;
  state.error = "";
  state.shipForm = null;
  state.cancelConfirmId = "";
  state.orderDetailId = "";
  state.statusConfirm = null;
  state.selectedOrderIds.clear();
  state.workItemDetailId = "";
  state.workItemDetail = null;
  state.approveConfirm = null;
  render();
  await ensureViewData(view);
}

async function refreshCurrent() {
  state.error = "";
  if (state.view === "overview") await loadOverview();
  else if (state.view === "orders") await loadOrders();
  else if (state.view === "after-sales") await loadAfterSales();
  else if (state.view === "superagent") await loadWorkItems();
  else if (state.view === "policy") await loadPolicy();
  else if (state.view === "audit") await loadAudit();
  else if (state.view === "chat-profiles") await loadChatProfiles();
  else await loadProducts();
}

/* ================= Super-agent：事件 / 工作项 / 人工审批 ================= */

function superAgentStatusLabel(status) {
  const key = String(status || "").toUpperCase();
  return SUPERAGENT_STATUS_LABELS[key] || key || "—";
}

function approvalStatusLabel(status) {
  const key = String(status || "").toUpperCase();
  return APPROVAL_STATUS_LABELS[key] || key || "—";
}

function superAgentTone(status) {
  const key = String(status || "").toUpperCase();
  if (key === "RUNNING" || key === "EXECUTING") return "is-info";
  if (key === "DONE") return "is-success";
  if (key === "FAILED" || key === "STUCK" || key === "EXECUTION_FAILED") return "is-danger";
  if (key === "REJECTED" || key === "CANCELLED") return "is-muted";
  return "is-warn";
}

/* ---------- 审批动作 / 受控执行 ---------- */

function workItemAction(item) {
  const candidates = [item?.approval?.action, item?.result?.action];
  for (const candidate of candidates) {
    if (candidate && typeof candidate === "object" && Object.keys(candidate).length) {
      return candidate;
    }
  }
  return null;
}

function actionLabel(action) {
  const key = String(action?.action_type || "").toUpperCase();
  return ACTION_LABELS[key] || key || "受控动作";
}

function actionParams(action) {
  const rows = [];
  if (action?.order_id) rows.push(["订单号", String(action.order_id)]);
  if (action?.sale_type) {
    const key = String(action.sale_type).toUpperCase();
    rows.push(["售后类型", ACTION_SALE_TYPE_LABELS[key] || action.sale_type]);
  }
  if (action?.tracking_no) rows.push(["物流单号", String(action.tracking_no)]);
  if (action?.carrier) rows.push(["承运商", String(action.carrier)]);
  if (action?.reason) rows.push(["原因", String(action.reason)]);
  return rows;
}

function actionExtraText(action) {
  const parts = [];
  if (action?.sale_type) {
    const key = String(action.sale_type).toUpperCase();
    parts.push(`售后类型：${ACTION_SALE_TYPE_LABELS[key] || action.sale_type}`);
  }
  if (action?.tracking_no) parts.push(`物流单号：${action.tracking_no}`);
  if (action?.carrier) parts.push(`承运商：${action.carrier}`);
  return parts.join(" · ");
}

function actionParamsText(action) {
  return actionExtraText(action) || "无额外参数";
}

/** 每个工作项的人工补充参数；SHIP_ORDER 预填动作已有值，CREATE_AFTER_SALE 必须由人选择 */
function getActionParamsState(item) {
  const id = String(item?.work_item_id || "");
  if (!id) return { sale_type: "", tracking_no: "", carrier: "", amount: "", reason: "" };
  if (!state.actionParams[id]) {
    const action = workItemAction(item);
    const type = String(action?.action_type || "").toUpperCase();
    const isShip = type === "SHIP_ORDER";
    const isCompensation = type === "ISSUE_COMPENSATION";
    state.actionParams[id] = {
      sale_type: "",
      tracking_no: isShip ? String(action?.tracking_no || "") : "",
      carrier: isShip ? String(action?.carrier || "") : "",
      amount: isCompensation && Number(action?.amount) > 0 ? String(action.amount) : "",
      reason: isCompensation ? String(action?.reason || "") : "",
    };
  }
  return state.actionParams[id];
}

function actionParamsValid(action, params) {
  const type = String(action?.action_type || "").toUpperCase();
  if (type === "CREATE_AFTER_SALE") {
    return ["REFUND_ONLY", "RETURN_REFUND"].includes(String(params?.sale_type || "").toUpperCase());
  }
  if (type === "SHIP_ORDER") {
    return String(params?.tracking_no || "").trim().length > 0;
  }
  if (type === "ISSUE_COMPENSATION") {
    return Number(params?.amount) > 0;
  }
  return true;
}

function actionParamsForPost(action, params) {
  const type = String(action?.action_type || "").toUpperCase();
  if (type === "CREATE_AFTER_SALE") {
    return { sale_type: String(params?.sale_type || "").toUpperCase() };
  }
  if (type === "SHIP_ORDER") {
    const post = { tracking_no: String(params?.tracking_no || "").trim() };
    const carrier = String(params?.carrier || "").trim();
    if (carrier) post.carrier = carrier;
    return post;
  }
  if (type === "ISSUE_COMPENSATION") {
    return {
      amount: Number(params?.amount || 0),
      reason: String(params?.reason || "").trim(),
    };
  }
  return {};
}

function actionParamsMarkup(item, action) {
  const type = String(action?.action_type || "").toUpperCase();
  if (type !== "CREATE_AFTER_SALE" && type !== "SHIP_ORDER" && type !== "ISSUE_COMPENSATION") return "";
  const id = String(item?.work_item_id || "");
  const params = getActionParamsState(item);
  const valid = actionParamsValid(action, params);

  if (type === "ISSUE_COMPENSATION") {
    return `<div class="b-param-card">
      <p class="b-param-title">审批参数</p>
      <div class="b-param-fields">
        <label class="b-param-field">补偿金额（元）
          <input id="b-param-amount-${escapeHtml(id)}" data-param-amount="${escapeHtml(id)}" value="${escapeHtml(params.amount)}" placeholder="如 20" inputmode="decimal" autocomplete="off" />
        </label>
        <label class="b-param-field">补偿原因
          <input id="b-param-reason-${escapeHtml(id)}" data-param-reason="${escapeHtml(id)}" value="${escapeHtml(params.reason)}" placeholder="如 物流延迟补偿" autocomplete="off" />
        </label>
      </div>
      ${valid ? "" : `<p class="b-param-hint">请填写大于 0 的补偿金额后再通过并执行</p>`}
    </div>`;
  }
  if (type === "CREATE_AFTER_SALE") {
    const saleType = String(params.sale_type || "").toUpperCase();
    return `<div class="b-param-card">
      <p class="b-param-title">审批参数</p>
      <p class="b-param-label">售后类型（必选）</p>
      <div class="b-param-options">
        ${Object.entries(ACTION_SALE_TYPE_LABELS)
          .map(
            ([value, label]) =>
              `<label class="b-param-radio"><input type="radio" name="b-sale-type-${escapeHtml(id)}" value="${value}" data-param-sale-type="${escapeHtml(id)}" ${saleType === value ? "checked" : ""} /><span>${escapeHtml(label)}</span></label>`
          )
          .join("")}
      </div>
      ${
        valid
          ? `<p class="b-param-current">已选：${escapeHtml(ACTION_SALE_TYPE_LABELS[saleType] || saleType)}</p>`
          : `<p class="b-param-hint">请选择售后类型后再通过并执行</p>`
      }
    </div>`;
  }

  return `<div class="b-param-card">
    <p class="b-param-title">审批参数</p>
    <div class="b-param-fields">
      <label class="b-param-field">物流单号（必填）
        <input id="b-param-tracking-${escapeHtml(id)}" data-param-tracking="${escapeHtml(id)}" value="${escapeHtml(params.tracking_no)}" placeholder="如 SF1234567890" autocomplete="off" />
      </label>
      <label class="b-param-field">承运商（可选）
        <input id="b-param-carrier-${escapeHtml(id)}" data-param-carrier="${escapeHtml(id)}" value="${escapeHtml(params.carrier)}" placeholder="如 顺丰速运" autocomplete="off" />
      </label>
    </div>
    ${valid ? "" : `<p class="b-param-hint">请填写物流单号后再通过并执行</p>`}
  </div>`;
}

function executionStatusLabel(status) {
  const key = String(status || "").toUpperCase();
  return EXECUTION_STATUS_LABELS[key] || key || "未执行";
}

/** 兼容读取 approval.execution_status / execution_result 与 result.execution */
function executionInfo(item) {
  const approval = item?.approval && typeof item.approval === "object" ? item.approval : null;
  const rawExecution = item?.result?.execution;
  const execution =
    rawExecution && typeof rawExecution === "object"
      ? rawExecution
      : approval?.execution_result && typeof approval.execution_result === "object"
        ? approval.execution_result
        : null;
  const executionStatus = String(approval?.execution_status || "").toUpperCase();
  const status = String(item?.status || "").toUpperCase();
  const hasExecution =
    (execution && Object.keys(execution).length > 0) ||
    (executionStatus && executionStatus !== "NONE") ||
    status === "EXECUTION_FAILED";
  if (!hasExecution) return null;

  const action =
    approval?.action ||
    item?.result?.action ||
    execution?.action ||
    (execution?.action_type ? execution : null) ||
    null;
  const failed =
    status === "EXECUTION_FAILED" ||
    executionStatus === "FAILED" ||
    execution?.success === false;
  const executed = execution?.executed === true;
  const error = String(item?.error || execution?.error || "").trim();
  const orderId = String(execution?.order_id || action?.order_id || "").trim();
  const label = actionLabel(action);

  if (failed) {
    return {
      failed: true,
      executed,
      title: "执行失败",
      detail: error || "受控动作执行失败，请人工核查",
      orderId,
      action,
    };
  }
  if (executed) {
    const extra = actionExtraText(action);
    return {
      failed: false,
      executed,
      title: "已执行",
      detail: `${label}${orderId ? `（订单 ${orderId}）` : ""}${extra ? ` · ${extra}` : ""}`,
      orderId,
      action,
    };
  }
  const message =
    typeof execution?.message === "string" && execution.message.trim()
      ? execution.message
      : execution?.reason === "NO_ACTION"
        ? "仅记录人工审批，无执行动作"
        : "仅记录人工审批，未执行动作";
  return {
    failed: false,
    executed: false,
    title: "未执行动作",
    detail: message,
    orderId,
    action,
  };
}

function actionCardMarkup(action) {
  const params = actionParams(action);
  return `<div class="b-action-card">
    <div class="b-action-head">
      <span class="b-tag">建议动作</span>
      <strong>${escapeHtml(actionLabel(action))}</strong>
    </div>
    ${
      params.length
        ? `<dl class="b-meta b-meta-inline">${params
            .map(
              ([label, value]) =>
                `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`
            )
            .join("")}</dl>`
        : ""
    }
    <p class="b-action-warning">通过后会调用受控接口执行，不只是记录审批；执行结果会写入工作项。</p>
    <p class="b-muted">驳回只记录审批结果，不会执行动作。</p>
  </div>`;
}

function executionBlockMarkup(execution) {
  return `<div class="b-exec ${execution.failed ? "is-error" : "is-success"}">
    <strong>${escapeHtml(execution.title)}</strong>
    <span>${escapeHtml(execution.detail)}</span>
  </div>`;
}

function approveConfirmMarkup(item, action, busy, params) {
  const id = String(item?.work_item_id || "");
  const hasAction = Boolean(action);
  const label = hasAction ? actionLabel(action) : "";
  const orderId = hasAction ? String(action?.order_id || "").trim() : "";
  const finalAction = hasAction
    ? { ...action, ...actionParamsForPost(action, params || getActionParamsState(item)) }
    : null;
  const paramsText = hasAction ? actionParamsText(finalAction) : "";
  return `<div class="b-confirm b-approve-confirm">
    <p>${hasAction ? "确认通过并执行该受控动作？" : "确认通过本次审批？"}</p>
    ${
      hasAction
        ? `<p class="b-confirm-detail">动作：<strong>${escapeHtml(label)}</strong>${orderId ? ` · 订单 <code>${escapeHtml(orderId)}</code>` : ""}</p>
           <p class="b-confirm-detail">参数：<strong>${escapeHtml(paramsText)}</strong></p>
           <p class="b-confirm-note">通过后会调用受控接口执行，不只是记录审批；执行失败会记录在工作项中。</p>`
        : `<p class="b-confirm-detail">本次审批只记录结论，无可执行动作。</p>`
    }
    <div class="b-actions">
      <button type="button" class="b-btn b-btn-primary" data-confirm-approve="${escapeHtml(id)}" ${busy ? "disabled" : ""}>${hasAction ? "确认通过并执行" : "确认通过"}</button>
      <button type="button" class="b-btn b-btn-ghost" data-cancel-approve="${escapeHtml(id)}" ${busy ? "disabled" : ""}>取消</button>
    </div>
  </div>`;
}

function isSuperAgentAuthError(error) {
  return error instanceof ApiError && error.status === 401;
}

function handleSuperAgentError(error) {
  if (isSuperAgentAuthError(error)) return handleAuthFailure(error);
  state.error = errorMessage(error);
  showToast(state.error, "error");
  return false;
}

function workItemSummary(item) {
  const result = item?.result;
  if (result === null || result === undefined || result === "") return "";
  if (typeof result === "string") return result.trim();
  if (typeof result === "object") {
    if (!Object.keys(result).length) return "";
    for (const key of ["summary", "conclusion", "answer", "text", "report"]) {
      const value = result[key];
      if (typeof value === "string" && value.trim()) return value;
    }
    return JSON.stringify(result, null, 2);
  }
  return String(result);
}

/** 安全渲染 Markdown 风格结论：先整体转义 HTML，再按行还原换行/简单列表，不注入原文 HTML */
function renderSafeText(value) {
  const escapedLines = escapeHtml(value).split(/\r?\n/);
  const blocks = [];
  for (const line of escapedLines) {
    const trimmed = line.trim();
    if (!trimmed) {
      blocks.push('<p class="b-md-gap"></p>');
      continue;
    }
    if (/^[-*]\s+/.test(trimmed)) {
      blocks.push(`<p class="b-md-li">• ${trimmed.replace(/^[-*]\s+/, "")}</p>`);
      continue;
    }
    if (/^\d+\.\s+/.test(trimmed)) {
      blocks.push(`<p class="b-md-li">${trimmed}</p>`);
      continue;
    }
    if (/^#{1,6}\s+/.test(trimmed)) {
      blocks.push(`<p class="b-md-h">${trimmed.replace(/^#{1,6}\s+/, "")}</p>`);
      continue;
    }
    blocks.push(`<p class="b-md-p">${trimmed}</p>`);
  }
  return blocks.join("");
}

function stopWorkPolling() {
  if (workPollTimer) {
    clearInterval(workPollTimer);
    workPollTimer = null;
  }
}

function syncWorkPolling() {
  const hasActive = state.workItems.some((item) => {
    const status = String(item.status || "").toUpperCase();
    return status === "RUNNING" || status === "EXECUTING";
  });
  if (state.view === "superagent" && hasActive) {
    if (!workPollTimer) {
      workPollTimer = window.setInterval(() => {
        loadWorkItems({ silent: true });
      }, 2000);
    }
    syncExecutionPolling();
    return;
  }
  stopWorkPolling();
  syncExecutionPolling();
}

/* ---------- 异步执行单条轮询（approve → EXECUTING → 终态） ---------- */

function isExecutionActiveStatus(status) {
  return String(status || "").toUpperCase() === "EXECUTING";
}

function isExecutionTerminalStatus(status) {
  return ["DONE", "EXECUTION_FAILED", "REJECTED", "CANCELLED", "FAILED", "STUCK"].includes(
    String(status || "").toUpperCase()
  );
}

function stopExecutionPolling(workItemId) {
  const timer = executionPollTimers.get(workItemId);
  if (timer) {
    clearInterval(timer);
    executionPollTimers.delete(workItemId);
  }
}

function stopAllExecutionPolling() {
  for (const workItemId of [...executionPollTimers.keys()]) {
    stopExecutionPolling(workItemId);
  }
}

function upsertWorkItem(updated) {
  if (!updated?.work_item_id) return;
  const id = String(updated.work_item_id);
  const index = state.workItems.findIndex((item) => item.work_item_id === id);
  if (index >= 0) {
    state.workItems[index] = { ...state.workItems[index], ...updated };
  } else {
    state.workItems.unshift(updated);
  }
  if (updated.approval) state.executionCache[id] = updated;
}

function handleExecutionSettled(item) {
  const status = String(item?.status || "").toUpperCase();
  const execution = executionInfo(item);
  if (status === "EXECUTION_FAILED" || execution?.failed) {
    showToast(
      `执行失败：${execution?.detail || errorMessage(item?.error || "受控动作执行失败")}`,
      "error"
    );
    return;
  }
  if (execution?.executed) {
    showToast(`执行完成：${execution.detail}`, "success");
    return;
  }
  if (status === "CANCELLED") {
    showToast("执行已取消", "success");
    return;
  }
  showToast("审批已完成", "success");
}

function startExecutionPolling(workItemId) {
  if (!workItemId || executionPollTimers.has(workItemId) || state.view !== "superagent") return;
  const timer = window.setInterval(async () => {
    try {
      const updated = await api(
        `/api/superagent/work-items/${encodeURIComponent(workItemId)}`
      );
      if (!updated?.work_item_id) return;
      upsertWorkItem(updated);
      if (isExecutionTerminalStatus(updated.status)) {
        stopExecutionPolling(workItemId);
        handleExecutionSettled(updated);
        render();
        loadWorkItems({ silent: true });
        return;
      }
      render();
    } catch (error) {
      stopExecutionPolling(workItemId);
      if (isSuperAgentAuthError(error)) {
        handleAuthFailure(error);
        return;
      }
      state.error = errorMessage(error);
      showToast(state.error, "error");
      render();
    }
  }, 2000);
  executionPollTimers.set(workItemId, timer);
}

function syncExecutionPolling() {
  if (state.view !== "superagent") {
    stopAllExecutionPolling();
    return;
  }
  const activeIds = new Set(
    state.workItems
      .filter((item) => isExecutionActiveStatus(item.status))
      .map((item) => String(item.work_item_id))
  );
  for (const workItemId of [...executionPollTimers.keys()]) {
    if (!activeIds.has(workItemId)) stopExecutionPolling(workItemId);
  }
  for (const workItemId of activeIds) {
    if (!executionPollTimers.has(workItemId)) startExecutionPolling(workItemId);
  }
}

async function loadWorkItems(options = {}) {
  const silent = Boolean(options.silent);
  if (silent && state.workItemsLoading) return;
  state.workItemsLoading = true;
  if (!silent) {
    state.error = "";
    render();
  }
  try {
    const data = await api("/api/superagent/work-items?limit=50");
    state.workItems = collectionFrom(data, ["work_items", "workItems"]);
    state.workItemsLoaded = true;
  } catch (error) {
    if (isSuperAgentAuthError(error)) {
      handleAuthFailure(error);
      return;
    }
    if (!silent) {
      state.error = errorMessage(error);
      showToast(state.error, "error");
    }
  } finally {
    state.workItemsLoading = false;
    syncWorkPolling();
    render();
  }
}

async function submitSuperAgentEvent() {
  if (state.eventSubmitting) return;
  const content = String(state.eventDraft || "").trim();
  if (!content) {
    state.error = "请先填写业务事件内容";
    showToast(state.error, "error");
    render();
    return;
  }
  state.eventSubmitting = true;
  state.error = "";
  render();
  try {
    const data = await api("/api/superagent/events", {
      method: "POST",
      body: JSON.stringify({
        source: "manual",
        channel: "b-workbench",
        content,
        auto_run: false,
      }),
    });
    const item = data?.work_item || {};
    if (data?.accepted === false) {
      state.eventNotice = {
        accepted: false,
        message: String(data?.reason || "事件未被 Super-agent 受理"),
      };
      showToast(state.eventNotice.message, "error");
    } else {
      state.eventDraft = "";
      state.eventNotice = {
        accepted: true,
        work_item_id: item.work_item_id || "",
        status: item.status || "PENDING",
        message: String(data?.reason || "已受理"),
      };
      showToast(`已提交给 Super-agent：${item.work_item_id || "已创建"}`, "success");
      await loadWorkItems();
    }
  } catch (error) {
    handleSuperAgentError(error);
  } finally {
    state.eventSubmitting = false;
    render();
  }
}

async function runWorkItem(workItemId) {
  if (!workItemId || state.busyWorkItem) return;
  state.busyWorkItem = workItemId;
  state.error = "";
  render();
  try {
    await api(`/api/superagent/work-items/${encodeURIComponent(workItemId)}/run`, {
      method: "POST",
    });
    showToast("调查已启动，页面会每 2 秒自动刷新状态", "success");
    await loadWorkItems();
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      state.error = errorMessage(error);
      showToast(state.error, "error");
    } else {
      handleSuperAgentError(error);
    }
  } finally {
    state.busyWorkItem = "";
    syncWorkPolling();
    render();
  }
}

async function stopWorkItem(workItemId) {
  if (!workItemId || state.busyWorkItem) return;
  state.busyWorkItem = workItemId;
  state.error = "";
  render();
  try {
    const data = await api(`/api/superagent/work-items/${encodeURIComponent(workItemId)}/stop`, {
      method: "POST",
    });
    const stoppedStatus = String(data?.status || "CANCELLED").toUpperCase();
    showToast(
      stoppedStatus === "CANCELLED"
        ? `已停止工作项 ${workItemId} 的调查`
        : `工作项状态已更新为「${superAgentStatusLabel(stoppedStatus)}」`,
      "success"
    );
    await loadWorkItems();
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      state.error = errorMessage(error);
      showToast(state.error, "error");
    } else {
      handleSuperAgentError(error);
    }
  } finally {
    state.busyWorkItem = "";
    syncWorkPolling();
    render();
  }
}

async function approveWorkItem(workItemId, approved, actionParams = {}) {
  if (!workItemId || state.busyWorkItem) return;
  state.busyWorkItem = workItemId;
  state.error = "";
  state.approveConfirm = null;
  render();
  const body = approved
    ? { approved: true, note: "", action_params: actionParams || {} }
    : { approved: false, note: "" };
  try {
    const response = await api(
      `/api/superagent/work-items/${encodeURIComponent(workItemId)}/approve`,
      {
        method: "POST",
        body: JSON.stringify(body),
      }
    );
    if (approved) {
      if (response?.work_item_id) {
        state.executionCache[workItemId] = response;
        upsertWorkItem(response);
      }
      const asyncExecution =
        String(response?.status || "").toUpperCase() === "EXECUTING" ||
        response?.execution_pending === true;
      if (asyncExecution) {
        showToast("已通过，正在执行…", "success");
        startExecutionPolling(workItemId);
        render();
        await loadWorkItems({ silent: true });
        return;
      }
      const execution = executionInfo(response);
      if (response?.status === "EXECUTION_FAILED" || execution?.failed) {
        showToast(`执行失败：${execution?.detail || errorMessage(response?.error || "")}`, "error");
      } else if (execution?.executed) {
        showToast(`已通过并执行：${execution.detail}`, "success");
      } else if (workItemAction(response)) {
        showToast("已通过并执行受控动作", "success");
      } else {
        showToast("已通过审批（无执行动作）", "success");
      }
    } else {
      showToast("已驳回工作项，未执行任何动作", "success");
    }
    await loadWorkItems();
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      state.error = errorMessage(error);
      showToast(state.error, "error");
    } else {
      handleSuperAgentError(error);
    }
  } finally {
    state.busyWorkItem = "";
    render();
  }
}

async function runWatchdog() {
  if (state.watchdogBusy) return;
  state.watchdogBusy = true;
  state.error = "";
  render();
  try {
    const data = await api("/api/superagent/watchdog", {
      method: "POST",
      body: JSON.stringify({ timeout_seconds: 180 }),
    });
    const stuckCount = Number(data?.stuck_count || 0);
    showToast(
      stuckCount
        ? `Watchdog 扫描完成：${stuckCount} 个工作项被标记为卡住`
        : "Watchdog 扫描完成：没有发现卡住的工作项",
      "success"
    );
    await loadWorkItems();
  } catch (error) {
    handleSuperAgentError(error);
  } finally {
    state.watchdogBusy = false;
    render();
  }
}

async function toggleWorkItemDetail(workItemId) {
  if (state.workItemDetailId === workItemId) {
    state.workItemDetailId = "";
    state.workItemDetail = null;
    render();
    return;
  }
  state.workItemDetailId = workItemId;
  state.workItemDetail = null;
  render();
  try {
    const data = await api(`/api/superagent/work-items/${encodeURIComponent(workItemId)}`);
    if (state.workItemDetailId === workItemId) {
      state.workItemDetail = data || null;
      render();
    }
  } catch (error) {
    handleSuperAgentError(error);
  }
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

async function simulateOrderAction(orderId, action, requestId) {
  const order = findOrder(orderId);
  if (!order || state.busy) return;
  const isComplete = action === "complete";
  state.busy = `order:${orderId}`;
  state.error = "";
  render();
  try {
    const result = await api(`/api/b/workbench/orders/${encodeURIComponent(orderId)}/simulation-actions`, {
      method: "POST",
      body: JSON.stringify({
        client_request_id: requestId,
        action: isComplete ? "SIMULATE_COMPLETION" : "SIMULATE_PAYMENT",
        expected_status: isComplete ? "SHIPPED" : "CREATED",
        expected_amount: String(order.total_amount ?? ""),
        expected_currency: String(order.currency || "CNY"),
        reason: "B端模拟状态推进",
      }),
    });
    const eventId = result?.action?.action_id || "";
    showToast(`${isComplete ? "模拟完成" : "模拟支付"}已写入审计${eventId ? ` · ${eventId.slice(-8)}` : ""}`, "success");
    await loadOrders();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.error = errorMessage(error);
    // 保留同一个 request_id，超时/断网重试不会生成第二个模拟动作。
    state.statusConfirm = { orderId, action, requestId };
    showToast(`${state.error} · 可重试同一请求`, "error");
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
  if (action === "paid" || action === "complete") {
    state.statusConfirm = {
      orderId,
      action,
      requestId: `b_sim_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
    };
    render();
    return;
  } else if (action === "status-confirm") {
    const confirm = state.statusConfirm;
    const statusAction = confirm?.action;
    if (!["paid", "complete"].includes(statusAction) || confirm?.orderId !== orderId || !confirm?.requestId) return;
    state.statusConfirm = null;
    await simulateOrderAction(orderId, statusAction, confirm.requestId);
    return;
  } else if (action === "status-dismiss") {
    state.statusConfirm = null;
    render();
    return;
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
  const logistics = order.carrier || order.tracking_no
    ? [order.carrier, order.tracking_no].filter(Boolean).join(" · ")
    : "—";
  return `<article class="b-card b-order-card">
    <div class="b-card-head">
      <div class="b-card-title"><input type="checkbox" data-order-select="${escapeHtml(id)}" ${state.selectedOrderIds.has(id) ? "checked" : ""} aria-label="选择订单 ${escapeHtml(id)}" /><code class="b-mono">${escapeHtml(text(id))}</code>${badge(status, statusLabel(status))}</div>
      <time>${escapeHtml(timeText(order.created_at))}</time>
    </div>
    <dl class="b-meta">
      <div><dt>买家</dt><dd>${escapeHtml(text(order.buyer_id))}</dd></div>
      <div><dt>金额</dt><dd class="b-amount">${money(order.total_amount)}</dd></div>
      <div><dt>商品</dt><dd>${escapeHtml(orderItemsText(order))}</dd></div>
      <div><dt>物流</dt><dd>${escapeHtml(logistics)}</dd></div>
    </dl>
    <div class="b-actions"><button type="button" class="b-btn b-btn-ghost" data-order-detail="${escapeHtml(id)}">查看详情${status === "CREATED" || status === "PAID" || status === "SHIPPED" ? " / 处理" : ""}</button></div>
  </article>`;
}

function afterSaleCard(ticket) {
  const id = String(ticket.ticket_id || "");
  const status = String(ticket.status || "").toUpperCase();
  const type = String(ticket.type || "").toUpperCase();
  const busy = state.busy === `ticket:${id}`;
  const attrs = `data-ticket-id="${escapeHtml(id)}" ${busy ? "disabled" : ""}`;
  const canResolve = can("resolve_after_sale");
  const canReceive = can("receive_return");
  const isReturn = type === "RETURN_REFUND";
  const buttons = [];
  if (status === "OPEN") {
    buttons.push(
      `<button type="button" class="b-btn b-btn-primary" data-ticket-action="approve" ${attrs} ${canResolve ? "" : "disabled"}>${isReturn ? "同意退货" : "通过"}</button>`
    );
    buttons.push(
      `<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-ticket-action="reject" ${attrs} ${canResolve ? "" : "disabled"}>拒绝</button>`
    );
  } else if (status === "RETURN_SHIPPED") {
    buttons.push(
      `<button type="button" class="b-btn b-btn-primary" data-ticket-action="receive" ${attrs} ${canReceive ? "" : "disabled"}>验收通过</button>`
    );
    buttons.push(
      `<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-ticket-action="reject-receive" ${attrs} ${canReceive ? "" : "disabled"}>拒收</button>`
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
  const skus = Array.isArray(product.skus) ? product.skus : [];
  const lowStock = Boolean(product.low_stock);
  const reorderQty = Number(product.reorder_qty || 0);
  const skuRows = skus.map((sku) => {
    const available = sku.available_qty;
    const reserved = sku.reserved_qty;
    const isLow = Boolean(sku.low_stock);
    const skuReorder = Number(sku.reorder_qty || 0);
    return `<div class="b-sku-row${isLow ? " is-low" : ""}">
      <span class="b-sku-name">${escapeHtml(text(sku.spec || sku.sku))}</span>
      <span class="b-sku-qty">可售 ${available === null || available === undefined ? "—" : escapeHtml(available)} · 锁定 ${reserved === null || reserved === undefined ? "—" : escapeHtml(reserved)}</span>
      ${isLow ? `<span class="b-sku-low">低库存</span>` : ""}
      ${skuReorder > 0 ? `<span class="b-sku-reorder">建议补货 +${skuReorder}</span>` : ""}
    </div>`;
  }).join("");
  const category = [product.category, product.brand].filter(Boolean).join(" · ");
  const imageUrl = String(product.image_url || "");
  const images = (Array.isArray(product.images) ? product.images : [])
    .filter((item) => item && item.url)
    .map((item) => ({ url: String(item.url), thumb_url: String(item.thumb_url || item.url) }));
  const coverImage = imageUrl || images[0]?.url || "";
  const imageIndex = new Map(images.map((item, index) => [item.url, index]));
  const imageRows = images.length
    ? `<div class="b-product-thumbs">${images.map((item) => {
        const index = imageIndex.get(item.url) || 0;
        return `<span class="b-product-thumb" title="第 ${index + 1} 张">
          <img src="${escapeHtml(item.thumb_url)}" alt="" loading="lazy" />
          ${index === 0 ? `<em>封面</em>` : ""}
          ${can("operate_inventory") ? `<button type="button" data-product-image-delete="${escapeHtml(item.url)}" data-product-id="${escapeHtml(product.product_id)}" aria-label="删除图片">×</button>` : ""}
        </span>`;
      }).join("")}</div>`
    : "";
  return `<article class="b-card b-product-card">
    <div class="b-product-cover">
      ${coverImage ? `<img src="${escapeHtml(coverImage)}" alt="${escapeHtml(text(product.title))}" loading="lazy" />` : `<span class="b-product-cover-empty">暂无图片</span>`}
      ${can("operate_inventory") ? `<label class="b-product-image-btn">
        添加图片
        <input type="file" name="product-images" multiple accept="image/png,image/jpeg,image/webp" data-product-image-add="${escapeHtml(product.product_id)}" hidden />
      </label>` : ""}
    </div>
    ${imageRows}
    <div class="b-card-head">
      <div class="b-card-title">
        <strong>${escapeHtml(text(product.title || product.name, "商品"))}</strong>
        <code class="b-mono">${escapeHtml(text(product.product_id))}</code>
      </div>
      <span class="b-badge ${status === "ACTIVE" ? "is-success" : "is-muted"}">${escapeHtml(status === "ACTIVE" ? "在售" : status || "—")}</span>
    </div>
    <dl class="b-meta">
      <div><dt>价格</dt><dd class="b-amount">${price === "" || price === null || price === undefined ? "—" : money(price)}</dd></div>
      <div><dt>库存</dt><dd class="${lowStock ? "b-stock-low" : ""}">${stock === null || stock === undefined ? "—" : escapeHtml(stock)}${lowStock ? ` <span class="b-badge is-warn">低库存</span>` : ""}${reorderQty > 0 ? ` <span class="b-sku-reorder">建议补货 +${reorderQty}</span>` : ""}</dd></div>
      <div><dt>安全库存</dt><dd>${product.safety_stock === null || product.safety_stock === undefined ? "—" : escapeHtml(product.safety_stock)}</dd></div>
      <div><dt>分类</dt><dd>${escapeHtml(text(category))}</dd></div>
      <div><dt>更新时间</dt><dd>${escapeHtml(timeText(product.updated_at || product.created_at))}</dd></div>
    </dl>
    ${skuRows ? `<details class="b-sku-details"><summary>SKU 明细 · ${skus.length}</summary><div class="b-sku-list">${skuRows}</div></details>` : ""}
  </article>`;
}

function skeletonMarkup(count = 3) {
  return `<div class="b-skeletons">${Array.from({ length: count }, () => `<div class="b-skeleton"></div>`).join("")}</div>`;
}

function emptyMarkup(message) {
  return `<div class="b-empty">${escapeHtml(message)}</div>`;
}

/* ---------------- B 2.0 P0：角色工作首页 ---------------- */

function workspaceRole() {
  const role = String(state.me?.role || "").toLowerCase();
  const permissions = state.me?.permissions || [];
  if (role === "owner" || role === "admin") return "owner";
  if (permissions.includes("operate_inventory") && !permissions.includes("view_after_sales")) {
    return "warehouse";
  }
  if (permissions.includes("view_after_sales") || permissions.includes("view_orders")) {
    return "support";
  }
  return "owner";
}

function workspaceRoleLabel(role) {
  return role === "warehouse" ? "仓库" : role === "support" ? "客服" : "店主";
}

async function overviewRequest(path, permission) {
  if (permission && !can(permission)) {
    return { ok: false, error: "当前角色无此数据权限" };
  }
  try {
    return { ok: true, data: await api(path) };
  } catch (error) {
    if (handleAuthFailure(error)) throw error;
    return { ok: false, error: errorMessage(error) };
  }
}

async function loadOverview() {
  if (state.overviewLoading) return;
  state.overviewLoading = true;
  state.error = "";
  render();
  const [orders, afterSales, products, alerts, workItems] = await Promise.all([
    overviewRequest("/api/b/workbench/orders?limit=100", "view_orders"),
    overviewRequest("/api/b/workbench/after-sales?limit=100", "view_after_sales"),
    overviewRequest("/api/b/workbench/products", "view_products"),
    overviewRequest("/api/b/workbench/inventory/alerts?status=PENDING&limit=100", "operate_inventory"),
    overviewRequest("/api/superagent/work-items?limit=50", "view_superagent"),
  ]);
  const productPayload = products.ok ? products.data : null;
  const productList = productPayload ? collectionFrom(productPayload, ["products"]) : [];
  state.overview = {
    orders: orders.ok ? collectionFrom(orders.data, ["orders"]) : [],
    afterSales: afterSales.ok ? collectionFrom(afterSales.data, ["tickets", "after_sales", "afterSales", "aftersales"]) : [],
    products: productList,
    productSummary: productPayload?.summary || null,
    alerts: alerts.ok ? collectionFrom(alerts.data, ["alerts"]) : [],
    workItems: workItems.ok ? collectionFrom(workItems.data, ["work_items", "workItems"]) : [],
    errors: {
      orders: orders.ok ? "" : orders.error,
      afterSales: afterSales.ok ? "" : afterSales.error,
      products: products.ok ? "" : products.error,
      alerts: alerts.ok ? "" : alerts.error,
      workItems: workItems.ok ? "" : workItems.error,
    },
  };
  state.overviewLoaded = true;
  state.overviewLoading = false;
  render();
}

function overviewMetric(label, value, note, tone = "") {
  return `<article class="b-metric ${tone ? `is-${tone}` : ""}">
    <span>${escapeHtml(label)}</span>
    <strong>${escapeHtml(value)}</strong>
    <small>${escapeHtml(note)}</small>
  </article>`;
}

function overviewTaskRow(label, detail, count, view) {
  return `<button type="button" class="b-overview-task" data-view="${escapeHtml(view)}">
    <span class="b-overview-task-copy"><strong>${escapeHtml(label)}</strong><small>${escapeHtml(detail)}</small></span>
    <span class="b-overview-task-count">${escapeHtml(String(count))}</span>
    <span class="b-overview-task-arrow" aria-hidden="true">查看</span>
  </button>`;
}

function overviewView() {
  const role = workspaceRole();
  if (state.overviewLoading && !state.overview) {
    return `<section class="b-view b-overview" aria-label="工作首页">
      <div class="b-overview-head"><div><p class="b-eyebrow">WORKSPACE / ${workspaceRoleLabel(role)}</p><h1>工作首页</h1><p class="b-muted">正在加载当前工作范围…</p></div></div>
      ${skeletonMarkup(3)}
    </section>`;
  }
  const data = state.overview || { orders: [], afterSales: [], products: [], productSummary: null, alerts: [], workItems: [], errors: {} };
  const orders = data.orders || [];
  const afterSales = data.afterSales || [];
  const products = data.products || [];
  const alerts = data.alerts || [];
  const workItems = data.workItems || [];
  const completed = orders.filter((order) => String(order.status || "").toUpperCase() === "COMPLETED");
  const completedRevenue = completed.reduce((sum, order) => sum + Number(order.total_amount || 0), 0);
  const pendingShipment = orders.filter((order) => String(order.status || "").toUpperCase() === "PAID");
  const openAfterSales = afterSales.filter((ticket) => ["OPEN", "RETURN_SHIPPED", "RETURN_PENDING"].includes(String(ticket.status || "").toUpperCase()));
  const lowStockSkus = products.reduce((sum, product) => {
    const skus = Array.isArray(product.skus) ? product.skus : [];
    return sum + skus.filter((sku) => {
      const available = Number(sku.available_qty ?? sku.stock ?? 0);
      const safety = Number(sku.safety_stock ?? 0);
      return safety > 0 && available <= safety;
    }).length;
  }, 0);
  const pendingApproval = workItems.filter((item) => ["WAITING_APPROVAL", "EXECUTION_FAILED"].includes(String(item.status || "").toUpperCase()));
  const lockedSkus = products.reduce((sum, product) => {
    const skus = Array.isArray(product.skus) ? product.skus : [];
    return sum + skus.filter((sku) => Number(sku.locked_qty || 0) > 0).length;
  }, 0);
  const errorNotes = Object.entries(data.errors || {}).filter(([, value]) => value);
  const partialNote = errorNotes.length ? `部分数据未加载：${errorNotes.map(([key]) => key).join("、")}。` : "";
  const scopeNote = `当前加载范围：${orders.length} 笔订单、${afterSales.length} 笔售后。`;
  const lowStockSummary = data.productSummary || {};
  const lowStockCount = Number(lowStockSummary.low_stock_skus || lowStockSkus);
  const roleTitle = role === "warehouse" ? "今天先看库存和发货" : role === "support" ? "今天先看售后和顾客" : "今天经营，一眼有数";
  const roleSubtitle = role === "warehouse"
    ? "优先处理缺货、锁定库存和待发货商品。"
    : role === "support"
      ? "优先处理售后工单；客服会话能力待接入，不展示假会话。"
      : "先看完成口径的模拟流水，再处理待发货和库存提醒。";

  const metrics = role === "warehouse"
    ? [
        overviewMetric("低库存 SKU", String(lowStockCount), "当前加载范围 · 可用 ≤ 安全库存", "warn"),
        overviewMetric("待发货订单", String(pendingShipment.length), "当前加载范围 · 模拟交易"),
        overviewMetric("商品数", String(products.length), "当前加载范围"),
        overviewMetric("有锁定库存 SKU", String(lockedSkus), "锁定库存不可当可售库存"),
      ]
    : role === "support"
      ? [
          overviewMetric("待处理售后", String(openAfterSales.length), "当前加载范围 · OPEN / 退货中", "warn"),
          overviewMetric("待发货订单", String(pendingShipment.length), "用于核对顾客咨询", "info"),
          overviewMetric("客服会话", "待接入", "B 端坐席后端尚未接入"),
          overviewMetric("可查订单", String(orders.length), "当前加载范围"),
        ]
      : [
          overviewMetric("当前加载完成流水", money(completedRevenue), "当前加载范围 · 非真实收款", "accent"),
          overviewMetric("当前加载完成订单", `${completed.length} 笔`, "不是全店汇总"),
          overviewMetric("待发货样例", `${pendingShipment.length} 笔`, "与完成流水分开"),
          overviewMetric("低库存 SKU", String(lowStockCount), "当前加载范围 · 可用 ≤ 安全库存", "warn"),
        ];

  const priorityRows = role === "warehouse"
    ? [
        overviewTaskRow("低库存 SKU", "核对可用、锁定和安全库存差额", lowStockCount, "products"),
        overviewTaskRow("待发货订单", "先核对商品、数量和履约信息", pendingShipment.length, "orders"),
        overviewTaskRow("待处理告警", "通知处理不等于补货入库", alerts.length, "products"),
      ]
    : role === "support"
      ? [
          overviewTaskRow("待处理售后", "核对申请、订单商品与金额", openAfterSales.length, "after-sales"),
          overviewTaskRow("待发货订单", "用于回答顾客物流/发货咨询", pendingShipment.length, "orders"),
          overviewTaskRow("客服会话", "能力待接入，当前不展示假会话", 0, "after-sales"),
        ]
      : [
          overviewTaskRow("待发货订单", "先核对商品、数量和履约信息", pendingShipment.length, "orders"),
          overviewTaskRow("待处理售后", "退款、退货和验收影响需分别确认", openAfterSales.length, "after-sales"),
          overviewTaskRow("待人工审批", "调查与审批工作项", pendingApproval.length, "superagent"),
          overviewTaskRow("低库存 SKU", "查看可用量与安全库存差额", lowStockCount, "products"),
        ];

  return `<section class="b-view b-overview" aria-label="工作首页">
    <div class="b-overview-head">
      <div>
        <p class="b-eyebrow">WORKSPACE / ${workspaceRoleLabel(role)}</p>
        <h1>${roleTitle}</h1>
        <p class="b-muted">${roleSubtitle}</p>
      </div>
      <div class="b-overview-date">${escapeHtml(timeText(new Date().toISOString()).slice(0, 10))}<small>当前会话 · 模拟交易</small></div>
    </div>
    ${partialNote ? `<p class="b-overview-notice" role="status">${escapeHtml(partialNote)}</p>` : ""}
    <div class="b-overview-scope">${escapeHtml(scopeNote)} 数字只代表已加载范围，不是全店汇总。</div>
    <div class="b-metrics">${metrics.join("")}</div>
    <div class="b-overview-columns">
      <section class="b-card b-overview-panel">
        <div class="b-panel-head"><div><h2>优先处理</h2><p>把注意力放在明确的待办上</p></div><span class="b-chip">当前范围</span></div>
        <div class="b-overview-tasks">${priorityRows.join("")}</div>
      </section>
      <section class="b-card b-overview-panel">
        <div class="b-panel-head"><div><h2>${role === "support" ? "客服能力" : role === "warehouse" ? "库存口径" : "经营报告"}</h2><p>${role === "support" ? "明确当前能力边界" : role === "warehouse" ? "先对齐字段含义" : "先把统计口径说清楚"}</p></div><span class="b-chip">${role === "support" ? "待接入" : "待接入"}</span></div>
        ${role === "support"
          ? `<div class="b-overview-placeholder"><strong>客服会话待接入</strong><p>当前 B 端有用户画像和售后数据，但没有完整的客服坐席收件箱。正式接入前不展示假会话、假在线状态。</p><button type="button" class="b-btn b-btn-ghost" disabled>进入客服会话</button></div>`
          : role === "warehouse"
            ? `<div class="b-overview-placeholder"><strong>库存字段待后端确认</strong><p>可用、锁定、安全库存目前来自商品快照；批量保存、并发版本和部分失败契约尚未接入。</p><button type="button" class="b-btn b-btn-ghost" data-view="products">查看商品与 SKU</button></div>`
            : `<div class="b-overview-placeholder"><strong>暂不绘制经营趋势</strong><p>当前是模拟交易；按完成时间统计的口径已确认，但退款冲减、跨月归属和真实支付尚未接入。</p><button type="button" class="b-btn b-btn-ghost" disabled>查看经营报告</button></div>`}
      </section>
    </div>
  </section>`;
}

function orderItemsText(order) {
  const items = Array.isArray(order.items) ? order.items : [];
  if (!items.length) return text(order.item_count, "—");
  return items.map((item) => `${text(item.title || item.product_id, "商品")} × ${Number(item.quantity || 1)}`).join("、");
}

function orderTableRow(order) {
  const id = String(order.order_id || "");
  const status = String(order.status || "").toUpperCase();
  const itemsText = orderItemsText(order);
  const logistics = order.carrier || order.tracking_no
    ? [order.carrier, order.tracking_no].filter(Boolean).join(" · ")
    : "—";
  const selected = state.selectedOrderIds.has(id) ? "checked" : "";
  return `<tr>
    <td class="b-select-cell"><input type="checkbox" data-order-select="${escapeHtml(id)}" ${selected} aria-label="选择订单 ${escapeHtml(id)}" /></td>
    <td><button type="button" class="b-table-link" data-order-detail="${escapeHtml(id)}"><code class="b-mono">${escapeHtml(text(id))}</code></button><br /><small>${escapeHtml(timeText(order.created_at))}</small></td>
    <td>${escapeHtml(text(order.buyer_id))}</td>
    <td class="b-order-items-cell">${escapeHtml(itemsText)}</td>
    <td class="b-num">${escapeHtml(money(order.total_amount))}</td>
    <td>${badge(status, statusLabel(status))}</td>
    <td>${escapeHtml(logistics)}</td>
    <td><button type="button" class="b-btn b-btn-ghost b-btn-small" data-order-detail="${escapeHtml(id)}">详情</button></td>
  </tr>`;
}

function orderDrawerMarkup() {
  const order = state.orders.find((item) => String(item.order_id || "") === state.orderDetailId);
  if (!order) return "";
  const id = String(order.order_id || "");
  const status = String(order.status || "").toUpperCase();
  const items = Array.isArray(order.items) ? order.items : [];
  const attrs = `data-order-id="${escapeHtml(id)}" ${state.busy === `order:${id}` || !can("operate_orders") ? "disabled" : ""}`;
  const actionButtons = [];
  if (status === "CREATED") {
    actionButtons.push(`<button type="button" class="b-btn b-btn-primary" data-order-action="paid" ${attrs} title="演示动作：不产生真实收款">模拟支付（演示）</button>`);
    actionButtons.push(`<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-order-action="cancel" ${attrs}>取消订单</button>`);
  } else if (status === "PAID") {
    actionButtons.push(`<button type="button" class="b-btn b-btn-primary" data-order-action="ship" ${attrs}>发货</button>`);
    actionButtons.push(`<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-order-action="cancel" ${attrs}>取消订单</button>`);
  } else if (status === "SHIPPED") {
    actionButtons.push(`<button type="button" class="b-btn b-btn-primary" data-order-action="complete" ${attrs} title="演示动作：不代表真实交易完成">模拟完成（演示）</button>`);
  }
  const shipForm = state.shipForm && String(state.shipForm.orderId) === id
    ? `<div class="b-ship-form"><p class="b-form-title">填写物流信息后发货</p><div class="b-ship-fields"><label>物流单号（必填）<input id="b-ship-tracking" type="text" maxlength="64" value="${escapeHtml(state.shipForm.tracking)}" placeholder="如 SF1234567890" autocomplete="off" /></label><label>承运商（可选）<input id="b-ship-carrier" type="text" maxlength="64" value="${escapeHtml(state.shipForm.carrier)}" placeholder="如 顺丰速运" autocomplete="off" /></label></div>${state.shipForm.error ? `<p class="b-field-error" role="alert">${escapeHtml(state.shipForm.error)}</p>` : ""}<div class="b-actions"><button type="button" class="b-btn b-btn-primary" data-order-action="ship-submit" ${attrs}>确认发货</button><button type="button" class="b-btn b-btn-ghost" data-order-action="ship-cancel">取消</button></div></div>`
    : "";
  const cancelConfirm = state.cancelConfirmId === id
    ? `<div class="b-confirm"><p>确认取消订单 <code>${escapeHtml(id)}</code>？取消后不可恢复。</p><div class="b-actions"><button type="button" class="b-btn b-btn-danger" data-order-action="cancel-confirm" ${attrs}>确认取消</button><button type="button" class="b-btn b-btn-ghost" data-order-action="cancel-dismiss">放弃</button></div></div>`
    : "";
  const statusConfirm = state.statusConfirm?.orderId === id
    ? `<div class="b-confirm"><p>${state.statusConfirm.action === "paid" ? "确认标记为“模拟支付”？会写入当前商家订单状态和 paid_at，但不会产生真实收款。" : "确认标记为“模拟完成”？会写入当前商家订单状态和 completed_at，不会改变外部支付或结算。"}<br /><code>${escapeHtml(id)}</code> · ${escapeHtml(money(order.total_amount))}</p><div class="b-actions"><button type="button" class="b-btn b-btn-primary" data-order-action="status-confirm" ${attrs}>确认写入模拟状态</button><button type="button" class="b-btn b-btn-ghost" data-order-action="status-dismiss">返回</button></div></div>`
    : "";
  return `<div class="b-drawer-backdrop" data-order-detail-close></div>
    <aside class="b-order-drawer" role="dialog" aria-modal="true" aria-label="订单详情">
      <header class="b-drawer-head"><div><p class="b-eyebrow">订单详情 · 模拟交易</p><h2><code class="b-mono">${escapeHtml(text(id))}</code></h2></div><button type="button" class="b-btn b-btn-ghost" data-order-detail-close aria-label="关闭订单详情">关闭</button></header>
      <div class="b-drawer-body">
        <div class="b-drawer-summary"><span>${badge(status, statusLabel(status))}</span><strong>${escapeHtml(money(order.total_amount))}</strong><small>金额为模拟交易金额，非真实收款</small></div>
        <dl class="b-detail-list"><div><dt>下单时间</dt><dd>${escapeHtml(timeText(order.created_at))}</dd></div><div><dt>买家</dt><dd>${escapeHtml(text(order.buyer_id))}</dd></div><div><dt>物流</dt><dd>${escapeHtml([order.carrier, order.tracking_no].filter(Boolean).join(" · ") || "—")}</dd></div></dl>
        <h3>商品明细</h3>
        <div class="b-drawer-items">${items.length ? items.map((item) => `<div><span>${escapeHtml(text(item.title || item.product_id, "商品"))}</span><small>${escapeHtml(text(item.sku || item.spec, "未提供规格"))} · ×${Number(item.quantity || 1)}</small></div>`).join("") : `<p class="b-muted">订单未返回商品明细。</p>`}</div>
        ${actionButtons.length ? `<div class="b-drawer-actions">${actionButtons.join("")}</div>` : ""}
        ${statusConfirm}
        ${cancelConfirm}
        ${shipForm}
        <p class="b-drawer-note">演示操作会写入当前商家订单状态/时间，并写入模拟动作审计（is_simulated、操作者、前后状态）；不会创建真实支付、结算、物流或库存变更。</p>
      </div>
    </aside>`;
}

function selectedOrders() {
  return state.orders.filter((order) => state.selectedOrderIds.has(String(order.order_id || "")));
}

function batchBarMarkup() {
  const selected = selectedOrders();
  if (!selected.length) return "";
  const eligible = selected.filter((order) => String(order.status || "").toUpperCase() === "PAID");
  return `<div class="b-batch-bar" role="status">
    <div><strong>已选择 ${selected.length} 笔订单</strong><small>当前加载范围 · 其中 ${eligible.length} 笔待发货可进入预览</small></div>
    <button type="button" class="b-btn b-btn-ghost" data-order-export>导出选中 CSV</button>
    <button type="button" class="b-btn b-btn-primary" disabled title="批量发货接口尚未接入">预览批量发货</button>
    <button type="button" class="b-btn b-btn-ghost" data-order-clear-selection>清除选择</button>
  </div>`;
}

function exportSelectedOrders() {
  const selected = selectedOrders();
  if (!selected.length) return;
  const escapeCsv = (value) => {
    let cell = String(value ?? "");
    if (/^[=+\-@]/.test(cell.trimStart())) cell = "'" + cell;
    return `"${cell.replace(/"/g, '""')}"`;
  };
  const rows = [["订单号", "创建时间", "买家", "商品", "金额", "状态", "物流", "模拟数据"]];
  for (const order of selected) {
    rows.push([
      order.order_id || "", order.created_at || "", order.buyer_id || "",
      orderItemsText(order), order.total_amount ?? "", order.status || "",
      [order.carrier, order.tracking_no].filter(Boolean).join(" · "), "1",
    ]);
  }
  const csv = rows.map((row) => row.map(escapeCsv).join(",")).join("\r\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `qianke-b-orders-selected-${Date.now()}.csv`;
  link.click();
  URL.revokeObjectURL(url);
  showToast(`已导出 ${selected.length} 笔订单`, "success");
}

function ordersView() {
  const body = state.loading && !state.orders.length
    ? skeletonMarkup()
    : state.orders.length
      ? `<div class="b-order-table-wrap"><table class="b-order-table"><thead><tr><th class="b-select-cell"><input type="checkbox" data-order-select-all ${state.orders.length && state.orders.every((order) => state.selectedOrderIds.has(String(order.order_id || ""))) ? "checked" : ""} aria-label="选择当前页面全部订单" /></th><th>订单</th><th>买家</th><th>商品</th><th class="b-num">金额</th><th>状态</th><th>物流</th><th></th></tr></thead><tbody>${state.orders.map(orderTableRow).join("")}</tbody></table></div>
         <div class="b-order-cards">${state.orders.map(orderCard).join("")}</div>`
      : emptyMarkup("暂无订单");
  return `<section class="b-view" aria-label="订单">
    <div class="b-view-head">
      <div>
        <h1>订单</h1>
        <p class="b-muted">共 ${state.orderTotal} 单（当前筛选）${state.loading ? " · 刷新中…" : ""}</p>
      </div>
      <div class="b-view-tools">
        <label class="b-filter">状态
          <select data-order-filter ${state.loading ? "disabled" : ""}>
            ${ORDER_FILTERS.map((value) => `<option value="${value}" ${state.orderFilter === value ? "selected" : ""}>${value ? statusLabel(value) : "全部状态"}</option>`).join("")}
          </select>
        </label>
        <label class="b-filter">每页
          <select data-order-limit ${state.loading ? "disabled" : ""}>
            ${[10, 20, 50, 100].map((value) => `<option value="${value}" ${state.orderLimit === value ? "selected" : ""}>${value} 条</option>`).join("")}
          </select>
        </label>
        <button type="button" class="b-btn b-btn-ghost" data-refresh ${state.loading || state.busy ? "disabled" : ""}>刷新</button>
      </div>
    </div>
    <div class="b-order-filters">
      <label>搜索<input type="search" data-order-query value="${escapeHtml(state.orderQuery)}" placeholder="订单号 / 买家 / 商品" maxlength="80" /></label>
      <label>从<input type="date" data-order-date-from value="${escapeHtml(state.orderDateFrom)}" /></label>
      <label>到<input type="date" data-order-date-to value="${escapeHtml(state.orderDateTo)}" /></label>
      <button type="button" class="b-btn b-btn-primary" data-order-search ${state.loading ? "disabled" : ""}>查找</button>
    </div>
    ${body}
    <div class="b-order-pager"><span>第 ${Math.floor(state.orderOffset / state.orderLimit) + 1} / ${Math.max(1, Math.ceil(state.orderTotal / state.orderLimit))} 页 · 共 ${state.orderTotal} 条（当前筛选）</span><button type="button" class="b-btn b-btn-ghost" data-order-prev ${state.orderOffset <= 0 || state.loading ? "disabled" : ""}>上一页</button><button type="button" class="b-btn b-btn-ghost" data-order-next ${state.orderOffset + state.orderLimit >= state.orderTotal || state.loading ? "disabled" : ""}>下一页</button></div>
    ${batchBarMarkup()}
    ${orderDrawerMarkup()}
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

function chatProfilesView() {
  const body = state.loading && !state.chatProfiles.length
    ? skeletonMarkup()
    : state.chatProfiles.length
      ? `<div class="b-list">${state.chatProfiles.map((profile) => {
          const summary = profile.profile_text || "暂无摘要";
          const json = JSON.stringify(profile.profile || {}, null, 2);
          return `<article class="b-card b-chat-profile-card">
            <div class="b-card-head">
              <div class="b-card-title">
                <strong>${escapeHtml(text(profile.buyer_id, "买家"))}</strong>
                <code class="b-mono">${escapeHtml(text(profile.merchant_id))}</code>
              </div>
              <span class="b-badge is-info">置信度 ${Math.round(Number(profile.confidence || 0) * 100)}%</span>
            </div>
            <p class="b-chat-profile-summary">${escapeHtml(summary)}</p>
            <dl class="b-meta">
              <div><dt>版本</dt><dd>${escapeHtml(profile.version)}</dd></div>
              <div><dt>来源消息</dt><dd>${escapeHtml(profile.source_message_count)}</dd></div>
              <div><dt>更新时间</dt><dd>${escapeHtml(timeText(profile.extracted_at))}</dd></div>
            </dl>
            <details class="b-chat-profile-json">
              <summary>展开 JSON</summary>
              <pre>${escapeHtml(json)}</pre>
            </details>
          </article>`;
        }).join("")}</div>`
      : emptyMarkup("还没有会话画像。用户在店宠会话中聊过，且 30 分钟无新消息后会自动生成。");
  return `<section class="b-view" aria-label="用户画像">
    <div class="b-view-head">
      <div>
        <h1>用户画像</h1>
        <p class="b-muted">只读 · 当前商家 ${state.chatProfiles.length} 个会话画像 · 摘要与 JSON 均来自明确对话</p>
      </div>
      <div class="b-view-tools">
        <button type="button" class="b-btn b-btn-ghost" data-refresh ${state.loading || state.busy ? "disabled" : ""}>刷新</button>
      </div>
    </div>
    ${body}
  </section>`;
}

function productTableRow(product) {
  const skus = Array.isArray(product.skus) ? product.skus : [];
  const prices = skus.map((sku) => Number(sku.price)).filter((value) => Number.isFinite(value));
  const priceText = prices.length
    ? (Math.min(...prices) === Math.max(...prices) ? money(Math.min(...prices)) : `${money(Math.min(...prices))}–${money(Math.max(...prices))}`)
    : "—";
  const available = skus.reduce((sum, sku) => sum + Number(sku.available_qty ?? 0), 0);
  const locked = skus.reduce((sum, sku) => sum + Number(sku.locked_qty ?? 0), 0);
  const lowCount = skus.filter((sku) => {
    const safety = Number(sku.safety_stock ?? 0);
    return safety > 0 && Number(sku.available_qty ?? 0) <= safety;
  }).length;
  const status = String(product.status || "").toUpperCase();
  return `<tr>
    <td><strong>${escapeHtml(text(product.title || product.name, "商品"))}</strong><br /><small><code class="b-mono">${escapeHtml(text(product.product_id))}</code> · ${escapeHtml(text(product.category))}</small></td>
    <td>${status === "ACTIVE" ? "在售" : escapeHtml(status || "—")}</td>
    <td class="b-num">${skus.length}</td>
    <td class="b-num">${escapeHtml(priceText)}</td>
    <td class="b-num">${available}</td>
    <td class="b-num">${locked}</td>
    <td>${lowCount ? `<span class="b-badge is-warn">${lowCount} 个低库存</span>` : "—"}</td>
  </tr>`;
}

function filteredProducts() {
  let list = [...state.products];
  if (state.productFilter === "low") {
    list = list.filter((product) => product.low_stock || (Array.isArray(product.skus) && product.skus.some((sku) => sku.low_stock)));
  }
  const query = String(state.productQuery || "").trim().toLowerCase();
  if (!query) return list;
  return list.filter((product) => {
    const text = [
      product.title, product.name, product.product_id, product.category, product.brand,
      ...(Array.isArray(product.skus) ? product.skus.flatMap((sku) => [sku.sku, sku.spec]) : []),
    ].map((value) => String(value || "").toLowerCase()).join(" ");
    return text.includes(query);
  });
}

function skuTableRows(products) {
  return products.flatMap((product) => {
    const skus = Array.isArray(product.skus) ? product.skus : [];
    return skus.map((sku) => {
      const safety = Number(sku.safety_stock ?? 0);
      const available = Number(sku.available_qty ?? 0);
      const low = safety > 0 && available <= safety;
      return `<tr>
        <td><strong>${escapeHtml(text(product.title || product.name, "商品"))}</strong><br /><small>${escapeHtml(text(product.product_id))}</small></td>
        <td><code class="b-mono">${escapeHtml(text(sku.sku))}</code><br /><small>${escapeHtml(text(sku.spec))}</small></td>
        <td class="b-num">${escapeHtml(money(sku.price))}</td>
        <td class="b-num">${escapeHtml(String(available))}</td>
        <td class="b-num">${escapeHtml(String(Number(sku.locked_qty ?? 0)))}</td>
        <td class="b-num">${escapeHtml(String(safety))}</td>
        <td>${low ? `<span class="b-badge is-warn">低库存</span>` : "—"}</td>
      </tr>`;
    });
  }).join("");
}

const INVENTORY_ERROR_LABELS = {
  NOT_FOUND: "库存记录不存在",
  VERSION_CONFLICT: "库存已变化，请重新预检",
};

function openInventoryBatch() {
  const products = filteredProducts();
  const rows = products.flatMap((product) => (Array.isArray(product.skus) ? product.skus : []).map((sku) => ({
    item_id: `inv_${product.product_id}_${sku.sku}`,
    product_id: product.product_id,
    title: product.title || product.name || "商品",
    sku: sku.sku,
    spec: sku.spec || "",
    available_qty: Number(sku.available_qty ?? 0),
    reserved_qty: Number(sku.reserved_qty ?? 0),
    target_available: "",
    warehouse_id: "",
    selected: false,
    status: "",
    error: "",
  })));
  const warehouseIds = [...new Set(products.flatMap((product) => (Array.isArray(product.skus) ? product.skus : []).flatMap((sku) => (Array.isArray(sku.warehouses) ? sku.warehouses.map((warehouse) => warehouse.warehouse_id) : []))))].sort();
  state.inventoryDraft = {
    rows,
    warehouse_id: warehouseIds[0] || "",
    warehouses: warehouseIds,
    previewed: false,
    busy: false,
    error: "",
    result: null,
    request_id: `b_inv_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`,
  };
  render();
  requestAnimationFrame(() => {
    root.querySelector(".b-inventory-modal [data-inv-select]")?.focus();
  });
}

function syncInventoryDraftFromDom(root) {
  if (!state.inventoryDraft) return;
  for (const row of state.inventoryDraft.rows) {
    const checked = root.querySelector(`[data-inv-select="${CSS.escape(row.item_id)}"]`);
    const target = root.querySelector(`[data-inv-target="${CSS.escape(row.item_id)}"]`);
    if (checked) row.selected = Boolean(checked.checked);
    if (target) {
      const raw = String(target.value || "").trim();
      row.target_available = raw === "" ? "" : Math.max(0, Number(raw));
    }
  }
  state.inventoryDraft.previewed = false;
}

function inventoryModalMarkup() {
  const draft = state.inventoryDraft;
  if (!draft) return "";
  const selectedRows = draft.rows.filter((row) => row.selected);
  return `<div class="b-modal-backdrop" role="dialog" aria-modal="true" aria-label="批量改库存">
    <section class="b-inventory-modal">
      <div class="b-inventory-head">
        <div><strong>批量改库存</strong><p>仅调整可售量；预占/安全库存不变，提交会写入当前商家库存与审计。</p></div>
        <button type="button" class="b-btn b-btn-ghost" data-inventory-close>关闭</button>
      </div>
      <label class="b-inventory-warehouse">仓库
        <select data-inv-warehouse ${draft.busy ? "disabled" : ""}>${draft.warehouses.map((warehouse) => `<option value="${escapeHtml(warehouse)}" ${draft.warehouse_id === warehouse ? "selected" : ""}>${escapeHtml(warehouse)}</option>`).join("")}</select>
      </label>
      <div class="b-inventory-table-wrap">
        <table class="b-inventory-table">
          <thead><tr><th></th><th>商品 / SKU</th><th>当前可售</th><th>目标可售</th><th>预占</th><th>预览</th></tr></thead>
          <tbody>${draft.rows.map((row) => `<tr>
            <td><input type="checkbox" data-inv-select="${escapeHtml(row.item_id)}" ${row.selected ? "checked" : ""} aria-label="选择 ${escapeHtml(row.sku)}" /></td>
            <td><strong>${escapeHtml(row.title)}</strong><br /><small>${escapeHtml(row.sku)} · ${escapeHtml(row.spec)}</small></td>
            <td class="b-num">${escapeHtml(String(row.available_qty))}</td>
            <td><input type="number" min="0" step="1" inputmode="numeric" data-inv-target="${escapeHtml(row.item_id)}" value="${escapeHtml(row.target_available === "" || row.target_available === null ? "" : String(row.target_available))}" placeholder="目标" ${row.selected ? "" : "disabled"} /></td>
            <td class="b-num">${escapeHtml(String(row.reserved_qty))}</td>
            <td>${row.status ? `<span class="b-badge ${row.status === "READY" ? "is-ok" : row.status === "INVALID" || row.status === "FAILED" ? "is-warn" : ""}">${escapeHtml(row.status)}</span>${row.error ? `<br /><small>${escapeHtml(row.error)}</small>` : ""}` : "—"}</td>
          </tr>`).join("")}</tbody>
        </table>
      </div>
      ${draft.error ? `<p class="b-inline-error">${escapeHtml(draft.error)}</p>` : ""}
      ${draft.result ? `<div class="b-inventory-result"><strong>${escapeHtml(draft.result.status)}</strong> · 成功 ${draft.result.succeeded} / 失败 ${draft.result.failed} / 未变 ${draft.result.unchanged}</div>` : ""}
      <div class="b-inventory-actions">
        <span>已选 ${selectedRows.length} 个 SKU · 最多 50 个</span>
        <button type="button" class="b-btn b-btn-ghost" data-inventory-preview ${draft.busy || !selectedRows.length ? "disabled" : ""}>预检</button>
        <button type="button" class="b-btn b-btn-primary" data-inventory-submit ${draft.busy || !draft.previewed ? "disabled" : ""}>确认提交</button>
      </div>
    </section>
  </div>`;
}

async function previewInventoryDraft() {
  const draft = state.inventoryDraft;
  if (!draft) return;
  syncInventoryDraftFromDom(document);
  const selected = draft.rows.filter((row) => row.selected);
  if (!selected.length) {
    draft.error = "请至少选择一个 SKU";
    render();
    return;
  }
  if (!draft.warehouse_id) {
    draft.error = "请选择仓库";
    render();
    return;
  }
  if (selected.length > 50) {
    draft.error = "单次最多 50 个 SKU，请分批提交";
    render();
    return;
  }
  if (selected.some((row) => row.target_available === "" || row.target_available === null || !Number.isFinite(Number(row.target_available)))) {
    draft.error = "请给所有已选 SKU 填写目标可售量";
    render();
    return;
  }
  draft.busy = true;
  draft.error = "";
  render();
  try {
    const result = await api("/api/b/workbench/inventory/preview", {
      method: "POST",
      body: JSON.stringify({
        warehouse_id: draft.warehouse_id,
        reason_code: "MANUAL_RECONCILIATION",
        reason: "B 端批量可售量调整",
        items: selected.map((row) => ({ item_id: row.item_id, sku: row.sku, target_available: row.target_available })),
      }),
    });
    const byId = new Map((result.items || []).map((item) => [item.item_id, item]));
    for (const row of draft.rows) {
      const item = byId.get(row.item_id);
      if (!item) continue;
      row.status = item.status || "";
      row.warehouse_id = item.warehouse_id || "";
      row.expected_available = item.expected_available;
      row.expected_reserved = item.expected_reserved;
      row.available_qty = item.expected_available ?? row.available_qty;
      row.error = item.error?.code ? (INVENTORY_ERROR_LABELS[item.error.code] || item.error.message || item.error.code) : "";
    }
    draft.previewed = draft.rows.some((row) => row.selected && ["READY", "UNCHANGED"].includes(row.status));
    if (!draft.previewed) draft.error = "没有可提交的有效行";
  } catch (error) {
    draft.error = error.message || "预检失败";
  } finally {
    draft.busy = false;
    render();
  }
}

async function submitInventoryDraft() {
  const draft = state.inventoryDraft;
  if (!draft || !draft.previewed) return;
  syncInventoryDraftFromDom(document);
  const selected = draft.rows.filter((row) => row.selected && ["READY", "UNCHANGED"].includes(row.status) && row.warehouse_id && row.target_available !== "" && row.target_available !== null);
  if (!selected.length) {
    draft.error = "没有可提交的有效行";
    render();
    return;
  }
  draft.busy = true;
  draft.error = "";
  render();
  try {
    const result = await api("/api/b/workbench/inventory/batch", {
      method: "POST",
      body: JSON.stringify({
        client_request_id: draft.request_id,
        reason_code: "MANUAL_RECONCILIATION",
        reason: "B 端批量可售量调整",
        items: selected.map((row) => ({
          item_id: row.item_id,
          sku: row.sku,
          warehouse_id: row.warehouse_id,
          target_available: row.target_available,
          expected_available: Number(row.expected_available ?? row.available_qty ?? 0),
          expected_reserved: Number(row.expected_reserved ?? row.reserved_qty ?? 0),
        })),
      }),
    });
    draft.result = result;
    draft.previewed = false;
    for (const row of draft.rows) {
      const item = (result.items || []).find((entry) => entry.item_id === row.item_id);
      if (!item) continue;
      row.status = item.status;
      row.error = item.error_code ? (INVENTORY_ERROR_LABELS[item.error_code] || item.error_code) : "";
      row.available_qty = item.after_available ?? row.available_qty;
    }
    await loadProducts();
  } catch (error) {
    draft.error = error.message || "提交失败";
  } finally {
    draft.busy = false;
    render();
  }
}

function productsView() {
  const summary = state.productSummary || {};
  const lowProducts = state.products.filter((product) => product.low_stock);
  const visibleProducts = filteredProducts();
  const body = state.loading && !state.products.length
    ? skeletonMarkup(2)
    : visibleProducts.length
      ? state.productView === "skus"
        ? `<div class="b-product-table-wrap"><table class="b-product-table"><thead><tr><th>商品</th><th>SKU / 规格</th><th class="b-num">价格</th><th class="b-num">可售</th><th class="b-num">锁定</th><th class="b-num">安全库存</th><th>库存</th></tr></thead><tbody>${skuTableRows(visibleProducts)}</tbody></table></div>
           <div class="b-product-grid">${visibleProducts.map(productCard).join("")}</div>`
        : `<div class="b-product-table-wrap"><table class="b-product-table"><thead><tr><th>商品</th><th>状态</th><th class="b-num">SKU</th><th class="b-num">价格</th><th class="b-num">可售</th><th class="b-num">锁定</th><th>库存</th></tr></thead><tbody>${visibleProducts.map(productTableRow).join("")}</tbody></table></div>
           <div class="b-product-grid">${visibleProducts.map(productCard).join("")}</div>`
      : emptyMarkup(state.productQuery ? "没有匹配的商品或 SKU" : state.productFilter === "low" ? "当前没有低库存商品" : "暂无商品");
  const alert = Number(summary.low_stock_products || 0) > 0
    ? `<div class="b-stock-alert" role="status">
        <div>
          <strong>库存提醒</strong>
          <span>${Number(summary.low_stock_products || 0)} 个商品 · ${Number(summary.low_stock_skus || 0)} 个 SKU 低于安全库存，建议补货 ${Number(summary.suggested_reorder_qty || 0)} 件。</span>
        </div>
        <button type="button" class="b-btn b-btn-ghost" data-low-stock-filter>只看低库存</button>
      </div>`
    : "";
  const queued = state.inventoryAlerts || [];
  const queue = queued.length
    ? `<div class="b-alert-queue">
        <div class="b-alert-queue-head">
          <strong>待发送库存告警 · ${queued.length} 条</strong>
          <span>企业微信应用消息 · 接收人由服务端配置</span>
          ${can("operate_inventory") ? `<button type="button" class="b-btn b-btn-primary" data-dispatch-inventory ${state.inventoryDispatching ? "disabled" : ""}>${state.inventoryDispatching ? "推送中…" : "推送告警"}</button>` : ""}
        </div>
        ${queued.map((item) => `<div class="b-alert-row">
          <div>
            <strong>${escapeHtml(text(item.product_id))}${item.sku_spec ? ` · ${escapeHtml(text(item.sku_spec))}` : ""}</strong>
            <span>${escapeHtml(text(item.message))}</span>
          </div>
          <button type="button" class="b-btn b-btn-ghost" data-ack-inventory="${escapeHtml(item.alert_id)}" ${can("operate_inventory") ? "" : "disabled"}>标记已处理</button>
        </div>`).join("")}
      </div>`
    : "";
  return `<section class="b-view" aria-label="商品">
    <div class="b-view-head">
      <div>
        <h1>商品</h1>
        <p class="b-muted">商品图片可由 owner/admin 更换 · 当前 ${visibleProducts.length} 个商品 · ${Number(summary.low_stock_products || lowProducts.length)} 个低库存 · ${Number(summary.low_stock_skus || 0)} 个 SKU 低于安全库存${state.loading ? " · 刷新中…" : ""}</p>
      </div>
      <div class="b-view-tools">
        <label class="b-filter b-product-search">搜索
          <input type="search" data-product-query value="${escapeHtml(state.productQuery)}" placeholder="商品名 / ID / SKU / 规格" maxlength="80" />
        </label>
        <button type="button" class="b-btn b-btn-ghost" data-product-search>查找</button>
        <label class="b-filter">视图
          <select data-product-view>
            <option value="products" ${state.productView === "products" ? "selected" : ""}>商品</option>
            <option value="skus" ${state.productView === "skus" ? "selected" : ""}>SKU</option>
          </select>
        </label>
        ${can("operate_inventory") ? `<button type="button" class="b-btn b-btn-ghost" data-inventory-open>批量改库存</button>` : ""}
        <label class="b-filter">库存
          <select data-product-filter ${state.loading ? "disabled" : ""}>
            <option value="all" ${state.productFilter === "all" ? "selected" : ""}>全部商品</option>
            <option value="low" ${state.productFilter === "low" ? "selected" : ""}>仅低库存（${Number(summary.low_stock_products || lowProducts.length)}）</option>
          </select>
        </label>
        ${can("operate_inventory") ? `<button type="button" class="b-btn b-btn-ghost" data-scan-inventory ${state.inventoryScanning ? "disabled" : ""}>${state.inventoryScanning ? "扫描中…" : "扫描低库存"}</button>` : ""}
        <button type="button" class="b-btn b-btn-ghost" data-refresh ${state.loading || state.busy ? "disabled" : ""}>刷新</button>
      </div>
    </div>
    ${alert}
    ${queue}
    ${body}
    ${inventoryModalMarkup()}
  </section>`;
}

function auditTime(value) {
  const text = String(value || "");
  return text ? text.replace("T", " ").slice(0, 19) : "—";
}

function auditView() {
  const actionRows = state.auditActions.length
    ? state.auditActions.map((row) => {
        const actionType = row.action_type || "—";
        const exec = String(row.execution_status || "NONE").toUpperCase();
        const result = row.execution_result || {};
        const detail =
          result.ticket?.ticket_id ||
          result.compensation?.compensation_id ||
          row.error ||
          "—";
        return `<tr>
          <td><code>${escapeHtml(String(row.work_item_id || "").slice(-10))}</code></td>
          <td>${escapeHtml(ACTION_LABELS[actionType] || actionType)}</td>
          <td><code>${escapeHtml(row.order_id || "—")}</code></td>
          <td>${escapeHtml(superAgentStatusLabel(row.work_status))}</td>
          <td><span class="b-status ${exec === "EXECUTED" ? "is-success" : exec === "FAILED" ? "is-danger" : ""}">${escapeHtml(EXECUTION_STATUS_LABELS[exec] || exec)}</span></td>
          <td title="${escapeHtml(JSON.stringify(result).slice(0, 500))}">${escapeHtml(String(detail))}</td>
          <td>${escapeHtml(auditTime(row.executed_at || row.decided_at || row.created_at))}</td>
        </tr>`;
      }).join("")
    : `<tr><td colspan="7" class="b-empty">暂无动作执行记录</td></tr>`;
  const policyRows = state.auditPolicy.length
    ? state.auditPolicy.map((change) => {
        const before = change.before || {};
        const after = change.after || {};
        const summary = `补偿 ${Number(before.compensation_max_amount || 0)}→${Number(after.compensation_max_amount || 0)} 元 · 退款 ${Number(before.refund_max_amount || 0)}→${Number(after.refund_max_amount || 0)} 元 · 动作 ${(before.allowed_actions || []).length}→${(after.allowed_actions || []).length} 个`;
        return `<li class="b-audit-policy-row">
          <div><strong>${escapeHtml(change.changed_by || "—")}</strong> <span class="b-muted">${escapeHtml(auditTime(change.changed_at))}</span></div>
          <div class="b-muted">${escapeHtml(summary)}</div>
        </li>`;
      }).join("")
    : `<li class="b-empty">暂无策略变更</li>`;
  return `<section class="b-view" aria-label="执行审计">
    <div class="b-view-head">
      <div>
        <h1>执行审计</h1>
        <p class="b-muted">动作执行结果与商家策略变更 · 只读</p>
      </div>
      <div class="b-view-tools">
        <select data-audit-action-filter ${state.loading ? "disabled" : ""}>
          <option value="">全部动作</option>
          ${Object.entries(ACTION_LABELS).map(([action, label]) => `<option value="${action}" ${state.auditFilters.action_type === action ? "selected" : ""}>${label}</option>`).join("")}
        </select>
        <select data-audit-status-filter ${state.loading ? "disabled" : ""}>
          <option value="">全部执行状态</option>
          ${Object.entries(EXECUTION_STATUS_LABELS).map(([status, label]) => `<option value="${status}" ${state.auditFilters.execution_status === status ? "selected" : ""}>${label}</option>`).join("")}
        </select>
        <input data-audit-search type="search" placeholder="搜索工作项/订单" value="${escapeHtml(state.auditFilters.q || "")}" ${state.loading ? "disabled" : ""} />
        <input data-audit-date-from type="datetime-local" step="60" value="${escapeHtml(state.auditFilters.date_from || "")}" ${state.loading ? "disabled" : ""} title="开始时间" />
        <input data-audit-date-to type="datetime-local" step="60" value="${escapeHtml(state.auditFilters.date_to || "")}" ${state.loading ? "disabled" : ""} title="结束时间" />
        <a class="b-btn b-btn-ghost" href="${escapeHtml(auditExportUrl())}" download>导出 CSV</a>
        <button type="button" class="b-btn b-btn-ghost" data-refresh ${state.loading || state.busy ? "disabled" : ""}>刷新</button>
      </div>
    </div>
    <div class="b-card b-audit-card">
      <h2 class="b-card-title">动作执行</h2>
      <div class="b-table-wrap">
        <table class="b-audit-table">
          <thead><tr><th>工作项</th><th>动作</th><th>订单</th><th>工作项状态</th><th>执行</th><th>结果</th><th>时间</th></tr></thead>
          <tbody>${actionRows}</tbody>
        </table>
      </div>
      <div class="b-audit-pager">
        <span class="b-muted">共 ${state.auditTotal} 条 · 第 ${Math.floor(state.auditFilters.offset / state.auditFilters.limit) + 1} 页</span>
        <button type="button" class="b-btn b-btn-ghost" data-audit-prev ${state.auditFilters.offset <= 0 ? "disabled" : ""}>上一页</button>
        <button type="button" class="b-btn b-btn-ghost" data-audit-next ${state.auditFilters.offset + state.auditFilters.limit >= state.auditTotal ? "disabled" : ""}>下一页</button>
      </div>
    </div>
    <div class="b-card b-audit-card">
      <h2 class="b-card-title">策略变更</h2>
      <div class="b-audit-policy-tools">
        <span class="b-muted">审计链：${state.auditChain?.ok && state.auditChain?.anchor?.ok ? "正常" : "异常"} · ${Number(state.auditChain?.checked || 0)} 条 · 锚点 ${Number(state.auditChain?.anchor?.anchors || 0)}</span>
        <a class="b-btn b-btn-ghost" href="${escapeHtml(auditPolicyExportUrl())}" download>导出策略 CSV</a>
      </div>
      <ul class="b-audit-policy">${policyRows}</ul>
      <div class="b-audit-pager">
        <span class="b-muted">共 ${state.auditPolicyTotal} 条 · 第 ${Math.floor(state.auditFilters.policy_offset / state.auditFilters.policy_limit) + 1} 页</span>
        <button type="button" class="b-btn b-btn-ghost" data-audit-policy-prev ${state.auditFilters.policy_offset <= 0 ? "disabled" : ""}>上一页</button>
        <button type="button" class="b-btn b-btn-ghost" data-audit-policy-next ${state.auditFilters.policy_offset + state.auditFilters.policy_limit >= state.auditPolicyTotal ? "disabled" : ""}>下一页</button>
      </div>
    </div>
  </section>`;
}

function policyView() {
  const policy = state.policy || {
    allowed_actions: Object.keys(ACTION_LABELS),
    compensation_max_amount: 50,
    refund_max_amount: 1000,
    require_note: false,
  };
  const allowed = new Set(policy.allowed_actions || []);
  const canEdit = can("approve_superagent") && !state.policySaving;
  const disabled = canEdit ? "" : "disabled";
  return `<section class="b-view" aria-label="动作策略">
    <div class="b-view-head">
      <div>
        <h1>动作策略</h1>
        <p class="b-muted">控制本商家允许的 Super-agent 动作与金额上限${canEdit ? "" : " · 只读"}</p>
      </div>
      <div class="b-view-tools">
        <button type="button" class="b-btn b-btn-primary" data-save-policy ${canEdit ? "" : "disabled"}>${state.policySaving ? "保存中…" : "保存策略"}</button>
      </div>
    </div>
    <div class="b-card b-policy-card">
      <h2 class="b-card-title">允许的动作</h2>
      <div class="b-policy-actions">
        ${Object.entries(ACTION_LABELS).map(([action, label]) => `<label class="b-policy-check"><input type="checkbox" data-policy-action value="${action}" ${allowed.has(action) ? "checked" : ""} ${disabled} /> ${label}</label>`).join("")}
      </div>
      <div class="b-policy-grid">
        <label>补偿上限（元/单）
          <input id="b-policy-compensation" type="number" min="0" max="100000" step="1" value="${Number(policy.compensation_max_amount || 0)}" ${disabled} />
        </label>
        <label>退款上限（元/单）
          <input id="b-policy-refund" type="number" min="0" max="100000" step="1" value="${Number(policy.refund_max_amount || 0)}" ${disabled} />
        </label>
        <label class="b-policy-check"><input id="b-policy-note" type="checkbox" ${policy.require_note ? "checked" : ""} ${disabled} /> 动作必须填写原因</label>
      </div>
      <p class="b-muted">执行前会再次校验；超过上限或未开放的动作会直接拒绝，审批参数无法绕过。</p>
    </div>
  </section>`;
}

function workItemCard(item) {
  const id = String(item?.work_item_id || "");
  const status = String(item?.status || "").toUpperCase();
  const approval = String(item?.approval_status || "").toUpperCase();
  const busy = state.busyWorkItem === id;
  const cached = state.executionCache[id] || null;
  const effective = cached
    ? {
        ...item,
        approval: item?.approval || cached.approval,
        result:
          item?.result && Object.keys(item.result).length ? item.result : cached.result,
        error: item?.error || cached.error,
      }
    : item;
  const summary = workItemSummary(effective);
  const errorText = String(item?.error || "").trim();
  const showDetail = state.workItemDetailId === id;
  const detail = state.workItemDetail;
  const action = workItemAction(effective);
  const execution = executionInfo(effective);
  const params = action ? getActionParamsState(item) : null;
  const paramsValid = !action || actionParamsValid(action, params);
  const confirming = state.approveConfirm?.workItemId === id && status === "WAITING_APPROVAL";

  const buttons = [];
  if (status === "PENDING") {
    buttons.push(
      `<button type="button" class="b-btn b-btn-primary" data-run-work-item="${escapeHtml(id)}" ${busy ? "disabled" : ""}>${busy ? "启动中…" : "运行调查"}</button>`
    );
    buttons.push(
      `<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-stop-work-item="${escapeHtml(id)}" ${busy || !can("approve_superagent") ? "disabled" : ""}>停止调查</button>`
    );
  } else if (status === "RUNNING") {
    buttons.push(
      `<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-stop-work-item="${escapeHtml(id)}" ${busy || !can("approve_superagent") ? "disabled" : ""}>${busy ? "停止中…" : "停止调查"}</button>`
    );
  } else if (status === "EXECUTING") {
    buttons.push(
      `<button type="button" class="b-btn b-btn-primary" disabled>执行中…</button>`
    );
  } else if (status === "WAITING_APPROVAL") {
    buttons.push(
      `<button type="button" class="b-btn b-btn-primary" data-approve-work-item="${escapeHtml(id)}" ${busy || !paramsValid || !can("approve_superagent") ? "disabled" : ""} ${action && !paramsValid ? 'title="请先填写/选择审批参数"' : ""}>${action ? "通过并执行" : "通过"}</button>`
    );
    buttons.push(
      `<button type="button" class="b-btn b-btn-ghost b-btn-danger" data-reject-work-item="${escapeHtml(id)}" ${busy ? "disabled" : ""}>驳回</button>`
    );
  }
  buttons.push(
    `<button type="button" class="b-btn b-btn-ghost" data-detail-work-item="${escapeHtml(id)}">${showDetail ? "收起详情" : "查看详情"}</button>`
  );

  let body = "";
  if (status === "RUNNING") {
    body = `<p class="b-muted b-running-line"><span class="b-spinner" aria-hidden="true"></span>调查中，页面每 2 秒自动刷新状态…</p>`;
  } else if (status === "EXECUTING") {
    body = `<p class="b-muted b-running-line"><span class="b-spinner" aria-hidden="true"></span>执行中，页面每 2 秒自动刷新执行结果…</p>
      ${summary ? `<div class="b-md">${renderSafeText(summary)}</div>` : ""}`;
  } else if (status === "WAITING_APPROVAL") {
    body = `${action ? actionCardMarkup(action) : `<p class="b-approval-tip">本次结论没有可执行动作，通过仅记录人工审批。</p>`}
      ${action ? actionParamsMarkup(item, action) : ""}
      <div class="b-md">${renderSafeText(summary || "（本次调查没有返回结论摘要）")}</div>
      ${action ? "" : `<p class="b-approval-tip">驳回同样只记录审批结果，不会执行动作。</p>`}
      ${confirming ? approveConfirmMarkup(item, action, busy, params) : ""}`;
  } else if (status === "EXECUTION_FAILED") {
    body = `${execution ? executionBlockMarkup(execution) : `<div class="b-md b-md-error">${renderSafeText(errorText || "受控动作执行失败")}</div>`}
      ${summary ? `<div class="b-md">${renderSafeText(summary)}</div>` : ""}`;
  } else if (status === "FAILED" || status === "STUCK") {
    body = `<div class="b-md b-md-error">${renderSafeText(errorText || "执行失败，未返回错误详情")}</div>
      ${summary ? `<div class="b-md">${renderSafeText(summary)}</div>` : ""}`;
  } else if (status === "REJECTED") {
    body = `<p class="b-muted">已驳回，仅记录审批结果，未执行任何动作。</p>
      ${summary ? `<div class="b-md">${renderSafeText(summary)}</div>` : ""}`;
  } else if (status === "DONE") {
    body = `${execution ? executionBlockMarkup(execution) : ""}
      <div class="b-md">${renderSafeText(summary || "调查完成，本次未返回结论摘要。")}</div>`;
  } else if (status === "CANCELLED") {
    body = `<p class="b-muted">已手动停止本次调查，不会继续产生结论或执行任何操作。</p>`;
  } else if (status === "PENDING") {
    body = `<p class="b-muted">工作项已受理，点击「运行调查」后由 Super-agent 执行只读调查。</p>`;
  }

  const detailMarkup = showDetail
    ? detail
      ? `<div class="b-detail">
          <p class="b-muted">线程 <code>${escapeHtml(text(detail.thread_id))}</code> · 更新 ${escapeHtml(timeText(detail.updated_at))} · 触发 ${(detail.triggers || []).length} 条</p>
          ${
            detail.approval
              ? `<p class="b-muted">审批：${escapeHtml(approvalStatusLabel(detail.approval.status))} · 执行：${escapeHtml(executionStatusLabel(detail.approval.execution_status))}</p>`
              : ""
          }
          ${(detail.triggers || [])
            .map(
              (trigger) =>
                `<p class="b-detail-trigger"><span class="b-muted">[${escapeHtml(text(trigger.source))}/${escapeHtml(text(trigger.channel))}]</span> ${escapeHtml(text(trigger.content))}</p>`
            )
            .join("")}
        </div>`
      : `<p class="b-muted">详情加载中…</p>`
    : "";

  return `<article class="b-card b-work-item">
    <div class="b-card-head">
      <div class="b-card-title">
        <strong>${escapeHtml(text(item?.title, "未命名工作项"))}</strong>
        <span class="b-badge ${superAgentTone(status)}">${escapeHtml(superAgentStatusLabel(status))}</span>
        ${approval && approval !== "NONE" ? `<span class="b-tag">审批 · ${escapeHtml(approvalStatusLabel(approval))}</span>` : ""}
        ${status === "EXECUTING" ? `<span class="b-tag">执行 · 执行中</span>` : ""}
        ${execution ? `<span class="b-tag ${execution.failed ? "is-error" : "is-success"}">执行 · ${escapeHtml(execution.title)}</span>` : ""}
      </div>
      <time>${escapeHtml(timeText(item?.created_at))}</time>
    </div>
    <dl class="b-meta b-meta-inline">
      <div><dt>工作项</dt><dd><code class="b-mono">${escapeHtml(id)}</code></dd></div>
      <div><dt>更新</dt><dd>${escapeHtml(timeText(item?.updated_at))}</dd></div>
    </dl>
    ${body}
    ${detailMarkup}
    <div class="b-actions">${buttons.join("")}</div>
  </article>`;
}

function superAgentNoticeMarkup() {
  const notice = state.eventNotice;
  if (!notice) return "";
  if (notice.accepted === false) {
    return `<p class="b-event-notice is-error" role="alert">未受理：${escapeHtml(notice.message)}</p>`;
  }
  return `<p class="b-event-notice" role="status">已受理：工作项 <code>${escapeHtml(notice.work_item_id || "—")}</code> · 状态 ${escapeHtml(superAgentStatusLabel(notice.status))}</p>`;
}

function superAgentView() {
  const body = state.workItemsLoading && !state.workItems.length
    ? skeletonMarkup()
    : state.workItems.length
      ? `<div class="b-list">${state.workItems.map(workItemCard).join("")}</div>`
      : emptyMarkup("暂无工作项，提交一条业务事件开始调查");
  return `<section class="b-view" aria-label="Super-agent">
    <div class="b-view-head">
      <div>
        <h1>Super-agent</h1>
        <p class="b-muted">只读调查 + 人工审批，不会自动改订单/退款。</p>
      </div>
      <div class="b-view-tools">
        <button type="button" class="b-btn b-btn-ghost" data-watchdog ${state.watchdogBusy ? "disabled" : ""}>${state.watchdogBusy ? "扫描中…" : "扫描卡死"}</button>
        <button type="button" class="b-btn b-btn-ghost" data-refresh ${state.workItemsLoading ? "disabled" : ""}>刷新</button>
      </div>
    </div>
    <div class="b-card b-event-card">
      <label class="b-event-label" for="b-event-content">业务事件</label>
      <textarea id="b-event-content" data-event-input rows="3" maxlength="4000" placeholder="${escapeHtml(SUPERAGENT_EVENT_EXAMPLE)}">${escapeHtml(state.eventDraft)}</textarea>
      <div class="b-event-actions">
        <span class="b-muted">提交后生成待运行工作项；核查结论需人工审批。</span>
        <button type="button" class="b-btn b-btn-primary" data-submit-event ${state.eventSubmitting ? "disabled" : ""}>${state.eventSubmitting ? "提交中…" : "提交给 Super-agent"}</button>
      </div>
      ${superAgentNoticeMarkup()}
    </div>
    <div class="b-section-head">
      <strong>工作项</strong>
      <span class="b-muted">共 ${state.workItems.length} 项${state.workItems.some((item) => String(item.status || "").toUpperCase() === "RUNNING") ? " · 有调查进行中（2s 轮询）" : ""}</span>
    </div>
    ${body}
  </section>`;
}

function shellMarkup() {
  const activeView = VIEWS.find((view) => view.key === state.view) || VIEWS[0];
  const viewMarkup =
    activeView.key === "overview"
      ? overviewView()
      : activeView.key === "orders"
      ? ordersView()
      : activeView.key === "after-sales"
        ? afterSalesView()
        : activeView.key === "superagent"
          ? superAgentView()
          : activeView.key === "policy"
            ? policyView()
            : activeView.key === "audit"
              ? auditView()
              : activeView.key === "chat-profiles"
                ? chatProfilesView()
                : productsView();
  const merchantName = state.me?.name || "商家";
  const merchantId = state.me?.id || "";
  const role = String(state.me?.role || "").toLowerCase();
  const roleText = workspaceRoleLabel(workspaceRole());
  const navMarkup = NAV_GROUPS.map((group) => {
    const views = VIEWS.filter((view) => view.group === group);
    if (!views.length) return "";
    return `<div class="b-nav-group">
      <p class="b-nav-group-label">${group}</p>
      ${views.map((view) => `<button type="button" class="b-nav-btn ${state.view === view.key ? "active" : ""}" data-view="${view.key}" ${state.loading || state.busy ? 'aria-disabled="true"' : ""}><span class="b-nav-full">${view.label}</span><span class="b-nav-short">${view.short || view.label}</span></button>`).join("")}
    </div>`;
  }).join("");
  return `<div class="b-shell">
    <header class="b-topbar">
      <div class="b-brand"><span class="b-brand-mark">千客</span><span class="b-brand-sub">商家工作台</span></div>
      <div class="b-context">
        <div class="b-merchant">
          <strong>${escapeHtml(merchantName)}</strong>
          ${merchantId ? `<code class="b-mono">${escapeHtml(merchantId)}</code>` : ""}
        </div>
        <span class="b-role">${escapeHtml(roleText)}</span>
        <button type="button" class="b-store-switch" disabled title="多店成员关系接口尚未接入">切换店铺</button>
        <span class="b-env" title="当前订单与收款均为演示数据">模拟交易</span>
      </div>
      <div class="b-header-actions">
        <a class="b-text-link" href="/v2/#/home">返回入口</a>
      </div>
    </header>
    <div class="b-body">
      <aside class="b-sidebar" aria-label="商家工作台导航">
        ${navMarkup}
      </aside>
      <main class="b-main">
        ${state.error ? `<p class="b-inline-error" role="alert"><span>${escapeHtml(state.error)}</span><button type="button" class="b-inline-close" data-clear-error aria-label="关闭错误提示">×</button></p>` : ""}
        ${viewMarkup}
      </main>
    </div>
    <nav class="b-bottom-nav" aria-label="移动端快捷导航">
      <button type="button" class="${state.view === "overview" ? "active" : ""}" data-view="overview" ${state.view === "overview" ? 'aria-current="page"' : ""}>首页</button>
      <button type="button" class="${state.view === "orders" ? "active" : ""}" data-view="orders" ${state.view === "orders" ? 'aria-current="page"' : ""}>订单</button>
      <button type="button" class="${state.view === "products" ? "active" : ""}" data-view="products" ${state.view === "products" ? 'aria-current="page"' : ""}>商品</button>
      <button type="button" class="${state.view === "after-sales" ? "active" : ""}" data-view="after-sales" ${state.view === "after-sales" ? 'aria-current="page"' : ""}>售后</button>
      <button type="button" class="${state.mobileMoreOpen ? "active" : ""}" data-mobile-more aria-expanded="${state.mobileMoreOpen ? "true" : "false"}">更多</button>
    </nav>
    ${state.mobileMoreOpen ? `<div class="b-mobile-sheet"><div class="b-mobile-sheet-head"><strong>全部功能</strong><button type="button" class="b-btn b-btn-ghost" data-mobile-more>关闭</button></div>${navMarkup}</div>` : ""}
    ${toastMarkup()}
  </div>`;
}

function paint(html) {
  // 轮询/浮层刷新时保留业务事件输入框的焦点与光标，避免打断输入
  const active = document.activeElement;
  const focusState =
    active && active.id && root.contains(active)
      ? { id: active.id, start: active.selectionStart, end: active.selectionEnd }
      : null;
  root.innerHTML = html;
  if (focusState) {
    const element = document.getElementById(focusState.id);
    if (element) {
      element.focus({ preventScroll: true });
      if (typeof focusState.start === "number" && typeof element.setSelectionRange === "function") {
        try {
          element.setSelectionRange(focusState.start, focusState.end);
        } catch {
          /* ignore */
        }
      }
    }
  }
  bindEvents();
}

function syncMobileNav() {
  const nav = root.querySelector(".b-nav");
  const active = nav?.querySelector(".b-nav-btn.active");
  if (!nav || !active) return;
  if (nav.scrollWidth <= nav.clientWidth + 2) {
    nav.scrollLeft = 0;
    return;
  }
  nav.scrollLeft = Math.max(
    0,
    active.offsetLeft - nav.clientWidth / 2 + active.clientWidth / 2
  );
}

function render() {
  if (state.loginRequired) {
    paint(authViewMarkup() + toastMarkup());
    return;
  }
  if (state.fatalError && !state.me) {
    paint(fatalViewMarkup(state.fatalError) + toastMarkup());
    return;
  }
  if (state.initialLoading && !state.me) {
    root.innerHTML = `<div class="b-boot"><span class="b-spinner" aria-hidden="true"></span>正在加载商家工作台…</div>`;
    return;
  }
  paint(shellMarkup());
  syncMobileNav();
}

/* ---------------- 事件绑定 ---------------- */

let eventsBound = false;

function bindEvents() {
  if (eventsBound) return;
  eventsBound = true;

  root.addEventListener("change", async (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    if (target.matches("[data-order-select]")) {
      const id = target.dataset.orderSelect || "";
      if (target.checked) state.selectedOrderIds.add(id);
      else state.selectedOrderIds.delete(id);
      render();
      return;
    }
    if (target.matches("[data-order-select-all]")) {
      const visible = state.orders.map((order) => String(order.order_id || "")).filter(Boolean);
      if (target.checked) visible.forEach((id) => state.selectedOrderIds.add(id));
      else visible.forEach((id) => state.selectedOrderIds.delete(id));
      render();
      return;
    }
    if (target.matches("[data-inv-select]")) {
      const row = state.inventoryDraft?.rows.find((item) => item.item_id === target.dataset.invSelect);
      if (row) row.selected = target.checked;
      state.inventoryDraft && (state.inventoryDraft.previewed = false);
      render();
      return;
    }
    if (target.matches("[data-inv-target]")) {
      const row = state.inventoryDraft?.rows.find((item) => item.item_id === target.dataset.invTarget);
      if (row) {
        const raw = String(target.value || "").trim();
        row.target_available = raw === "" ? "" : Math.max(0, Number(raw));
      }
      state.inventoryDraft && (state.inventoryDraft.previewed = false);
      return;
    }
    if (target.matches("[data-inv-warehouse]")) {
      if (state.inventoryDraft) {
        state.inventoryDraft.warehouse_id = target.value;
        state.inventoryDraft.previewed = false;
        for (const row of state.inventoryDraft.rows) {
          row.status = "";
          row.error = "";
          row.warehouse_id = "";
        }
      }
      return;
    }
    if (target.matches("[data-product-view]")) {
      state.productView = target.value === "skus" ? "skus" : "products";
      render();
      return;
    }
    if (target.matches("[data-product-filter]")) {
      state.productFilter = target.value === "low" ? "low" : "all";
      render();
      return;
    }
    if (target.matches("[data-product-image-add]")) {
      const files = target.files;
      target.value = "";
      await uploadProductImages(target.dataset.productImageAdd, files);
      return;
    }
    if (target.matches("[data-audit-action-filter]")) {
      state.auditFilters.action_type = target.value;
      state.auditFilters.offset = 0;
      await loadAudit();
      return;
    }
    if (target.matches("[data-audit-status-filter]")) {
      state.auditFilters.execution_status = target.value;
      state.auditFilters.offset = 0;
      await loadAudit();
      return;
    }
    if (target.matches("[data-audit-search]")) {
      state.auditFilters.q = target.value.trim();
      state.auditFilters.offset = 0;
      await loadAudit();
      return;
    }
    if (target.matches("[data-audit-date-from]")) {
      state.auditFilters.date_from = target.value;
      state.auditFilters.offset = 0;
      state.auditFilters.policy_offset = 0;
      await loadAudit();
      return;
    }
    if (target.matches("[data-audit-date-to]")) {
      state.auditFilters.date_to = target.value;
      state.auditFilters.offset = 0;
      state.auditFilters.policy_offset = 0;
      await loadAudit();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (state.inventoryDraft) {
      state.inventoryDraft = null;
      render();
      requestAnimationFrame(() => root.querySelector("[data-inventory-open]")?.focus());
      return;
    }
    if (state.orderDetailId || state.statusConfirm) {
      state.orderDetailId = "";
      state.statusConfirm = null;
      render();
      return;
    }
    if (state.mobileMoreOpen) {
      state.mobileMoreOpen = false;
      render();
    }
  });

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
    if (target.closest("[data-scan-inventory]")) {
      await scanInventoryAlerts();
      return;
    }
    if (target.closest("[data-dispatch-inventory]")) {
      await dispatchInventoryAlerts();
      return;
    }
    const ackInventoryButton = target.closest("[data-ack-inventory]");
    if (ackInventoryButton) {
      await ackInventoryAlert(ackInventoryButton.dataset.ackInventory);
      return;
    }
    if (target.closest("[data-low-stock-filter]")) {
      state.productFilter = "low";
      render();
      return;
    }
    const imageDeleteButton = target.closest("[data-product-image-delete]");
    if (imageDeleteButton) {
      await deleteProductImage(imageDeleteButton.dataset.productId, imageDeleteButton.dataset.productImageDelete);
      return;
    }
    if (target.closest("[data-inventory-open]")) {
      openInventoryBatch();
      return;
    }
    if (target.closest("[data-inventory-close]")) {
      state.inventoryDraft = null;
      render();
      requestAnimationFrame(() => root.querySelector("[data-inventory-open]")?.focus());
      return;
    }
    if (target.closest("[data-inventory-preview]")) {
      await previewInventoryDraft();
      return;
    }
    if (target.closest("[data-inventory-submit]")) {
      await submitInventoryDraft();
      return;
    }
    if (target.closest("[data-product-search]")) {
      const input = root.querySelector("[data-product-query]");
      state.productQuery = String(input?.value || "").trim();
      render();
      return;
    }
    if (target.closest("[data-order-search]")) {
      const query = root.querySelector("[data-order-query]");
      const dateFrom = root.querySelector("[data-order-date-from]");
      const dateTo = root.querySelector("[data-order-date-to]");
      state.orderQuery = String(query?.value || "").trim();
      state.orderDateFrom = String(dateFrom?.value || "");
      state.orderDateTo = String(dateTo?.value || "");
      state.orderOffset = 0;
      state.selectedOrderIds.clear();
      state.ordersLoaded = false;
      await loadOrders();
      return;
    }
    if (target.closest("[data-order-prev]")) {
      state.orderOffset = Math.max(0, state.orderOffset - state.orderLimit);
      state.selectedOrderIds.clear();
      state.ordersLoaded = false;
      await loadOrders();
      return;
    }
    if (target.closest("[data-order-next]")) {
      state.orderOffset += state.orderLimit;
      state.selectedOrderIds.clear();
      state.ordersLoaded = false;
      await loadOrders();
      return;
    }
    if (target.closest("[data-order-export]")) {
      exportSelectedOrders();
      return;
    }
    if (target.closest("[data-order-clear-selection]")) {
      state.selectedOrderIds.clear();
      render();
      return;
    }
    const detailButton = target.closest("[data-order-detail]");
    if (detailButton) {
      state.orderDetailId = detailButton.dataset.orderDetail || "";
      render();
      requestAnimationFrame(() => {
        root.querySelector(".b-order-drawer [data-order-detail-close]")?.focus();
      });
      return;
    }
    if (target.closest("[data-order-detail-close]")) {
      state.orderDetailId = "";
      state.statusConfirm = null;
      render();
      return;
    }
    if (target.closest("[data-mobile-more]")) {
      state.mobileMoreOpen = !state.mobileMoreOpen;
      render();
      return;
    }
    const viewButton = target.closest("[data-view]");
    if (viewButton) {
      state.mobileMoreOpen = false;
      await switchView(viewButton.dataset.view);
      return;
    }
    if (target.closest("[data-refresh]")) {
      if (state.loading || state.busy || state.workItemsLoading) return;
      await refreshCurrent();
      return;
    }
    if (target.closest("[data-submit-event]")) {
      await submitSuperAgentEvent();
      return;
    }
    if (target.closest("[data-save-policy]")) {
      await savePolicy();
      return;
    }
    if (target.closest("[data-audit-prev]")) {
      state.auditFilters.offset = Math.max(0, state.auditFilters.offset - state.auditFilters.limit);
      await loadAudit();
      return;
    }
    if (target.closest("[data-audit-next]")) {
      state.auditFilters.offset += state.auditFilters.limit;
      await loadAudit();
      return;
    }
    if (target.closest("[data-audit-policy-prev]")) {
      state.auditFilters.policy_offset = Math.max(
        0,
        state.auditFilters.policy_offset - state.auditFilters.policy_limit,
      );
      await loadAudit();
      return;
    }
    if (target.closest("[data-audit-policy-next]")) {
      state.auditFilters.policy_offset += state.auditFilters.policy_limit;
      await loadAudit();
      return;
    }
    if (target.closest("[data-watchdog]")) {
      await runWatchdog();
      return;
    }
    const runItemButton = target.closest("[data-run-work-item]");
    if (runItemButton) {
      await runWorkItem(runItemButton.dataset.runWorkItem);
      return;
    }
    const stopItemButton = target.closest("[data-stop-work-item]");
    if (stopItemButton) {
      await stopWorkItem(stopItemButton.dataset.stopWorkItem);
      return;
    }
    const approveItemButton = target.closest("[data-approve-work-item]");
    if (approveItemButton) {
      const workItemId = approveItemButton.dataset.approveWorkItem;
      const item = state.workItems.find((candidate) => candidate.work_item_id === workItemId);
      const action = item ? workItemAction(item) : null;
      if (action && !actionParamsValid(action, getActionParamsState(item))) {
        state.error = "请先填写/选择审批参数";
        showToast(state.error, "error");
        render();
        return;
      }
      // 通过前二次确认；仅展开确认区，不发请求
      state.approveConfirm = { workItemId };
      render();
      return;
    }
    const confirmApproveButton = target.closest("[data-confirm-approve]");
    if (confirmApproveButton) {
      const workItemId = confirmApproveButton.dataset.confirmApprove;
      const item = state.workItems.find((candidate) => candidate.work_item_id === workItemId);
      const action = item ? workItemAction(item) : null;
      const params = item ? getActionParamsState(item) : null;
      if (action && !actionParamsValid(action, params)) {
        state.error = "请先填写/选择审批参数";
        showToast(state.error, "error");
        render();
        return;
      }
      const actionParams = action ? actionParamsForPost(action, params) : {};
      state.approveConfirm = null;
      await approveWorkItem(workItemId, true, actionParams);
      return;
    }
    const cancelApproveButton = target.closest("[data-cancel-approve]");
    if (cancelApproveButton) {
      state.approveConfirm = null;
      render();
      return;
    }
    const rejectItemButton = target.closest("[data-reject-work-item]");
    if (rejectItemButton) {
      state.approveConfirm = null;
      await approveWorkItem(rejectItemButton.dataset.rejectWorkItem, false);
      return;
    }
    const detailItemButton = target.closest("[data-detail-work-item]");
    if (detailItemButton) {
      await toggleWorkItemDetail(detailItemButton.dataset.detailWorkItem);
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
    if (target instanceof HTMLInputElement && target.matches("[data-param-sale-type]")) {
      const workItemId = target.dataset.paramSaleType;
      const item = state.workItems.find((candidate) => candidate.work_item_id === workItemId);
      if (item) {
        const params = getActionParamsState(item);
        params.sale_type = target.value;
      }
      render();
      return;
    }
    if (!(target instanceof HTMLSelectElement)) return;
    if (target.matches("[data-order-limit]")) {
      const nextLimit = Number(target.value || 20);
      state.orderLimit = [10, 20, 50, 100].includes(nextLimit) ? nextLimit : 20;
      state.orderOffset = 0;
      state.selectedOrderIds.clear();
      state.ordersLoaded = false;
      await loadOrders();
      return;
    }
    if (target.matches("[data-order-filter]")) {
      state.orderFilter = target.value;
      state.orderOffset = 0;
      state.selectedOrderIds.clear();
      state.ordersLoaded = false;
      render();
      await loadOrders();
      return;
    }
    if (target.matches("[data-after-sale-filter]")) {
      state.afterSaleFilter = target.value;
      await loadAfterSales();
    }
  });

  root.addEventListener("input", (event) => {
    const target = event.target;
    if (target instanceof HTMLTextAreaElement && target.matches("[data-event-input]")) {
      state.eventDraft = target.value;
      return;
    }
    if (
      target instanceof HTMLInputElement &&
      (target.matches("[data-param-tracking]") ||
        target.matches("[data-param-carrier]") ||
        target.matches("[data-param-amount]") ||
        target.matches("[data-param-reason]"))
    ) {
      const workItemId =
        target.dataset.paramTracking ||
        target.dataset.paramCarrier ||
        target.dataset.paramAmount ||
        target.dataset.paramReason;
      const item = state.workItems.find((candidate) => candidate.work_item_id === workItemId);
      const params = item
        ? getActionParamsState(item)
        : (state.actionParams[workItemId] =
            state.actionParams[workItemId] || {
              sale_type: "",
              tracking_no: "",
              carrier: "",
              amount: "",
              reason: "",
            });
      if (target.matches("[data-param-tracking]")) params.tracking_no = target.value;
      else if (target.matches("[data-param-carrier]")) params.carrier = target.value;
      else if (target.matches("[data-param-amount]")) params.amount = target.value;
      else params.reason = target.value;
      render();
    }
  });

  root.addEventListener("keydown", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (event.key === "Escape" && (state.shipForm || state.cancelConfirmId || state.approveConfirm)) {
      state.shipForm = null;
      state.cancelConfirmId = "";
      state.approveConfirm = null;
      render();
    }
  });
}

/* ---------------- 启动 ---------------- */

async function boot() {
  clearToast();
  stopWorkPolling();
  stopAllExecutionPolling();
  state.initialLoading = true;
  state.loginRequired = false;
  state.fatalError = "";
  state.me = null;
  state.meLoaded = false;
  state.ordersLoaded = false;
  state.afterSalesLoaded = false;
  state.productsLoaded = false;
  state.workItemsLoaded = false;
  state.overview = null;
  state.overviewLoaded = false;
  state.overviewLoading = false;
  state.orders = [];
  state.afterSales = [];
  state.products = [];
  state.workItems = [];
  state.workItemsLoading = false;
  state.eventDraft = "";
  state.eventSubmitting = false;
  state.eventNotice = null;
  state.busyWorkItem = "";
  state.workItemDetailId = "";
  state.workItemDetail = null;
  state.watchdogBusy = false;
  state.approveConfirm = null;
  state.actionParams = {};
  state.executionCache = {};
  state.error = "";
  state.shipForm = null;
  state.cancelConfirmId = "";
  state.orderDetailId = "";
  state.statusConfirm = null;
  render();
  try {
    await loadMe();
    state.view = "overview";
    await loadOverview();
  } catch (error) {
    if (handleAuthFailure(error)) return;
    state.fatalError = errorMessage(error);
  } finally {
    state.initialLoading = false;
    render();
  }
}

boot();
