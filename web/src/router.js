import { createRouter, createWebHashHistory } from "vue-router";
import { boot, hasCap, isDemo, isManager, store, toast } from "./store";

// 路由级懒加载：首屏只下载当前页面需要的 chunk，避免把 B/C/A 全部视图
// 打进 1.2MB 的 main bundle（C 端冷启动首屏传输 1.59MB 的主要来源）。
const Landing = () => import("./views/Landing.vue");
const Dashboard = () => import("./views/Dashboard.vue");
const Chat = () => import("./views/Chat.vue");
const Kb = () => import("./views/Kb.vue");
const KbProfiles = () => import("./views/KbProfiles.vue");
const KbDocs = () => import("./views/KbDocs.vue");
const KbHistory = () => import("./views/KbHistory.vue");
const Staff = () => import("./views/Staff.vue");
const Settings = () => import("./views/Settings.vue");
const Setup = () => import("./views/Setup.vue");
const Eval = () => import("./views/Eval.vue");
const Monitor = () => import("./views/Monitor.vue");
const Billing = () => import("./views/Billing.vue");
const MonitorAdmin = () => import("./views/MonitorAdmin.vue");
const AdminAgentMonitor = () => import("./views/AdminAgentMonitor.vue");
const AgentDemo = () => import("./views/AgentDemo.vue");
const AgentActions = () => import("./views/AgentActions.vue");
const MyAgent = () => import("./views/MyAgent.vue");
const CHome = () => import("./views/CHome.vue");
const CShop = () => import("./views/CShop.vue");
const CSocial = () => import("./views/CSocial.vue");
const COrders = () => import("./views/COrders.vue");
const CApp = () => import("./views/CApp.vue");
const CMe = () => import("./views/CMe.vue");
const CAdminAudit = () => import("./views/CAdminAudit.vue");
const ChatProfiles = () => import("./views/ChatProfiles.vue");
const MerchantStoreFriends = () => import("./views/MerchantStoreFriends.vue");

/**
 * 用 hash 路由：后端把 web/dist 静态挂到 /v2/，没有服务端 fallback，
 * history 模式刷新 /v2/chat 会 404；hash 模式下服务端只认 /v2/index.html。
 *
 * 匿名访问策略（task-8 起）：
 *   - `/home` 是公开营销页（meta.public=true），未登录可直接看；
 *   - 未登录访问其它页面 → 统一回 /home（先看官网，而不是粗暴跳登录）；
 *   - 已登录访问 /home 正常展示，主按钮变「进入工作台」。
 */
const routes = [
  {
    path: "/home",
    name: "home",
    component: Landing,
    meta: { title: "官网首页", public: true },
  },
  { path: "/", name: "dashboard", component: Dashboard, meta: { title: "工作台" } },
  { path: "/chat", name: "chat", component: Chat, meta: { title: "对话" } },
  { path: "/agent", name: "agent", component: AgentDemo, meta: { title: "Agent 智能助理" } },
  { path: "/agent/actions", name: "agent-actions", component: AgentActions, meta: { title: "运营任务看板" } },
  { path: "/my-agent", name: "my-agent", component: MyAgent, meta: { title: "我的 AI" } },
  { path: "/c/home", name: "c-home", component: CHome, meta: { title: "首页", cShell: true } },
  { path: "/c", name: "c-shop", component: CShop, meta: { title: "市集", cShell: true } },
  { path: "/c/social", name: "c-social", component: CSocial, meta: { title: "消息", cShell: true } },
  { path: "/c/orders", name: "c-orders", component: COrders, meta: { title: "订单", cShell: true } },
  { path: "/c/app", name: "c-app", component: CApp, meta: { title: "千客 · C 端", standalone: true } },
  { path: "/c/me", name: "c-me", component: CMe, meta: { title: "我的", cShell: true } },
  { path: "/admin/c-end", name: "admin-c-end", component: CAdminAudit, meta: { title: "C 端交易审计" } },
  { path: "/admin/chat-profiles", name: "admin-chat-profiles", component: ChatProfiles, meta: { title: "会话用户画像" } },
  { path: "/admin/merchant-store-friends", name: "admin-merchant-store-friends", component: MerchantStoreFriends, meta: { title: "店宠映射" } },
  { path: "/kb", name: "kb", component: Kb, meta: { title: "知识库" } },
  { path: "/kb/profiles", name: "kb-profiles", component: KbProfiles, meta: { title: "用户画像" } },
  { path: "/kb/docs", name: "kb-docs", component: KbDocs, meta: { title: "文档管理" } },
  { path: "/kb/history", name: "kb-history", component: KbHistory, meta: { title: "构建历史" } },
  { path: "/staff", name: "staff", component: Staff, meta: { title: "员工管理" } },
  { path: "/settings", name: "settings", component: Settings, meta: { title: "权限配置" } },
  // 四步导入向导（替代老 /wizard 页面；老路径由后端 302 到 /v2/#/setup）
  { path: "/setup", name: "setup", component: Setup, meta: { title: "数据导入" } },
  { path: "/eval", name: "eval", component: Eval, meta: { title: "离线评测" } },
  { path: "/monitor", name: "monitor", component: Monitor, meta: { title: "实时监控" } },
  { path: "/billing", name: "billing", component: Billing, meta: { title: "Token 账单" } },
  { path: "/admin/monitor", name: "monitor-admin", component: MonitorAdmin, meta: { title: "平台监控" } },
  { path: "/admin/agent-monitor", name: "admin-agent-monitor", component: AdminAgentMonitor, meta: { title: "Agent 调用监控" } },
  // 未知路径 → 工作台；未登录时守卫会再把人送回 /home
  { path: "/:pathMatch(.*)*", redirect: "/" },
];

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior(to) {
    // 落地页内部锚点（#contact 等）交给浏览器平滑滚动
    if (to.hash) return { el: to.hash, behavior: "smooth", top: 0 };
    return { top: 0 };
  },
});

router.beforeEach(async (to) => {
  const ok = await boot();
  if (!ok) return false;

  // 公开页面：匿名可看；已登录也正常展示
  if (to.meta && to.meta.public) return true;

  // 未登录访问受保护页面：先看官网（登录入口在官网顶部/按钮里）
  if (!store.authenticated) return { name: "home" };

  // B 端单入口：已绑定商户、且不是管理员的账号，只进 /v2/b.html。
  // 管理员（系统管理员/企业管理员）仍保留工作台；商家手动改 hash 也进不来。
  const merchant = store.account && store.account.merchant;
  if (merchant && !isManager() && !(store.account && store.account.is_system_admin)) {
    window.location.replace("/v2/b.html");
    return false;
  }

  // 无能力的页面手动敲 hash 也进不去：送回工作台并说明原因
  if (to.name === "staff" && !isManager()) {
    toast("当前账号不是管理员，无法访问员工管理", "error");
    return { name: "dashboard" };
  }
  if (to.name === "settings" && !hasCap("ops")) {
    toast("当前账号没有权限配置能力（仅系统管理员可用）", "error");
    return { name: "dashboard" };
  }
  // 导入向导会构建数据（写库），仅管理员可进；演示账号明确禁用
  if (to.name === "setup" && isDemo()) {
    toast("演示模式无法导入数据", "warn");
    return { name: "dashboard" };
  }
  if (to.name === "setup" && !isManager()) {
    toast("只有企业管理员可以导入或重建数据", "error");
    return { name: "dashboard" };
  }
  // 离线评测只读看板对演示账号开放；写接口由后端只读中间件拦截
  if (to.name === "eval" && !isManager() && !isDemo()) {
    toast("只有管理员可以访问离线评测", "error");
    return { name: "dashboard" };
  }
  if ((to.name === "monitor" || to.name === "billing") && !isManager()) {
    toast("只有管理员可以访问监控与 Token 账单", "error");
    return { name: "dashboard" };
  }
  if (to.name === "monitor-admin" && !(store.account && store.account.is_system_admin)) {
    toast("只有系统管理员可以访问平台监控", "error");
    return { name: "dashboard" };
  }
  if (to.name === "admin-agent-monitor" && !(store.account && store.account.is_system_admin)) {
    toast("只有系统管理员可以访问 Agent 调用监控", "error");
    return { name: "dashboard" };
  }
  if (to.name === "admin-chat-profiles" && !(store.account && store.account.is_system_admin)) {
    toast("只有系统管理员可以查看全部会话画像", "error");
    return { name: "dashboard" };
  }
  if (to.name === "admin-merchant-store-friends" && !(store.account && store.account.is_system_admin)) {
    toast("只有系统管理员可以维护店宠映射", "error");
    return { name: "dashboard" };
  }
  return true;
});

export default router;
