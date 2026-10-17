/**
 * 统一 HTTP 出口。
 *
 * 约定（与既有 static/app.js 的 apiFetch 保持一致）：
 * - 所有请求带 credentials: "same-origin"（会话是 HttpOnly Cookie）；
 * - 401 = 未登录/会话过期 → 直接回 /login（每个调用点自己判断必然漏）；
 * - 其它非 2xx 抛 ApiError，detail 是后端给的中文提示，由页面 toast 出来。
 *
 * ⚠ 只接受接口地址，例如 "/qa/stream"：绝对以 / 开头。
 *   不要用相对路径 —— 页面部署在 /v2/ 子路径下，相对路径会拼成 /v2/qa/stream。
 */

const LOGIN_PATH = "/login";

export class ApiError extends Error {
  constructor(status, detail, payload = null) {
    super(detail || `请求失败（HTTP ${status}）`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail || `请求失败（HTTP ${status}）`;
    this.payload = payload;
  }
}

function redirectToLogin() {
  if (!window.location.pathname.startsWith(LOGIN_PATH)) {
    window.location.href = LOGIN_PATH;
  }
}

/** 发请求：只处理 401 跳登录，其它状态交给调用方。 */
export async function apiFetch(url, options = {}) {
  let res;
  try {
    res = await fetch(url, {
      credentials: "same-origin",
      ...options,
      headers: { ...(options.headers || {}) },
    });
  } catch (e) {
    if (e && e.name === "AbortError") throw e;
    throw new ApiError(0, "网络异常，无法连接服务器，请检查后端是否在运行");
  }
  if (res.status === 401) {
    redirectToLogin();
    throw new ApiError(401, "登录已失效，正在跳转登录页…");
  }
  return res;
}

/** 读响应体：JSON 解析失败时退回 { detail: 文本 }，避免抛 SyntaxError。 */
export async function readBody(res) {
  let text = "";
  try {
    text = await res.text();
  } catch {
    return null;
  }
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text.slice(0, 300) };
  }
}

export function detailMessage(data, status) {
  if (data && typeof data.detail === "string") return data.detail;
  if (data && Array.isArray(data.detail)) return "请求参数不合法";
  if (data && typeof data.error === "string") return data.error;
  return `请求失败（HTTP ${status}）`;
}

/** 请求 JSON 接口；非 2xx 抛 ApiError。 */
export async function apiJson(url, options = {}) {
  const res = await apiFetch(url, options);
  const data = await readBody(res);
  if (!res.ok) throw new ApiError(res.status, detailMessage(data, res.status), data);
  return data;
}

export function getJson(url) {
  return apiJson(url, { method: "GET" });
}

export function postJson(url, body) {
  return apiJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body == null ? {} : body),
  });
}

export function putJson(url, body) {
  return apiJson(url, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body == null ? {} : body),
  });
}

export function del(url) {
  return apiJson(url, { method: "DELETE" });
}
