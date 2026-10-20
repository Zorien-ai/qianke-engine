/**
 * 全局会话 / 能力 / 轻提示状态。
 *
 * 唯一真源是 GET /whoami：角色、等级、`can` 能力清单全部由后端给，
 * 前端**不硬编码权限表**（否则改一处漏一处）。隐藏入口只是"不设计入口"，
 * 真正的拦截在后端——前端藏起来不代表安全。
 */
import { reactive } from "vue";
import { getJson } from "./api";

export const store = reactive({
  booted: false,
  bootError: "",
  authenticated: false,
  whoami: null,
  account: null,
  can: {},
  notes: "",
  level: "",
  levelLabel: "",
  role: "",
  roleLabel: "",
  topkRange: { min: 1, max: 30 },
  theme: "light",
  themeMode: "system",
  toasts: [],
});

let bootPromise = null;

/**
 * 读取 /whoami 并写入 store。
 *
 * 这里只负责"我是谁/登录了没有"，**不负责跳转**：
 * 未登录要不要送去登录页、还是先看官网，由路由守卫按 meta.public 决定。
 * 之前在这里直接 window.location.href="/login"，导致官网 Landing Page 无法匿名访问。
 */
async function doBoot() {
  store.bootError = "";
  try {
    const mine = await getJson("/whoami");
    store.whoami = mine;
    store.authenticated = !!mine.authenticated;
    if (mine.authenticated) applyWhoami(mine);
    else {
      // 匿名：清掉可能残留的旧账号信息，模板里按"未登录"渲染
      store.account = null;
      store.can = {};
      store.level = "";
      store.levelLabel = "";
      store.role = "";
      store.roleLabel = "";
    }
    store.booted = true;
    return true;
  } catch (e) {
    store.bootError = e && e.message ? e.message : "初始化失败";
    bootPromise = null;
    return false;
  }
}

export function boot() {
  if (!bootPromise) bootPromise = doBoot();
  return bootPromise;
}

export async function refreshWhoami() {
  const mine = await getJson("/whoami");
  store.whoami = mine;
  store.authenticated = !!mine.authenticated;
  if (mine.authenticated) applyWhoami(mine);
  else {
    store.account = null;
    store.can = {};
  }
  return mine;
}

function applyWhoami(mine) {
  store.account = mine.account || null;
  store.can = mine.can || {};
  store.level = mine.level || "";
  store.levelLabel = mine.level_label || mine.level || "";
  store.role = mine.role || "";
  store.roleLabel = mine.role_label || mine.role || "";
  store.topkRange = mine.topk_range || { min: 1, max: 30 };
  store.notes = mine.note || "";
}

/** 能力判断：所有显隐都走这里，参数就是 /whoami.can 的键名。 */
export function hasCap(name) {
  return !!(store.can && store.can[name]);
}

/** 能进员工管理的人：系统管理员 / 企业管理员（由账号标记决定，不是等级）。 */
export function isManager() {
  const a = store.account;
  return !!(a && (a.is_system_admin || a.is_enterprise_admin));
}

/* ---------- 轻提示（toast） ---------- */
let toastSeq = 0;

export function toast(message, type = "info", ttl = 3600) {
  if (!message) return;
  const id = ++toastSeq;
  store.toasts.push({ id, message, type });
  setTimeout(() => {
    const i = store.toasts.findIndex((t) => t.id === id);
    if (i >= 0) store.toasts.splice(i, 1);
  }, ttl);
}

export function toastError(e) {
  const msg = e && (e.detail || e.message) ? e.detail || e.message : "操作失败";
  toast(msg, "error", 5200);
}

export async function logout() {
  try {
    await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch {
    /* 退出失败也照样回登录页：本地已是不可用状态 */
  }
  window.location.href = "/login";
}
