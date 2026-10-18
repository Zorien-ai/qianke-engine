import { createRouter, createWebHashHistory } from "vue-router";
import { boot, hasCap, isManager, store, toast } from "./store";

import Landing from "./views/Landing.vue";
import Dashboard from "./views/Dashboard.vue";
import Chat from "./views/Chat.vue";
import Kb from "./views/Kb.vue";
import Staff from "./views/Staff.vue";
import Settings from "./views/Settings.vue";
import Setup from "./views/Setup.vue";

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
  { path: "/kb", name: "kb", component: Kb, meta: { title: "知识库" } },
  { path: "/staff", name: "staff", component: Staff, meta: { title: "员工管理" } },
  { path: "/settings", name: "settings", component: Settings, meta: { title: "权限配置" } },
  // 四步导入向导（替代老 /wizard 页面；老路径由后端 302 到 /v2/#/setup）
  { path: "/setup", name: "setup", component: Setup, meta: { title: "数据导入" } },
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

  // 无能力的页面手动敲 hash 也进不去：送回工作台并说明原因
  if (to.name === "staff" && !isManager()) {
    toast("当前账号不是管理员，无法访问员工管理", "error");
    return { name: "dashboard" };
  }
  if (to.name === "settings" && !hasCap("ops")) {
    toast("当前账号没有权限配置能力（仅系统管理员可用）", "error");
    return { name: "dashboard" };
  }
  // 导入向导会构建数据（写库），仅管理员可进；后端还会再拦截一次
  if (to.name === "setup" && !isManager()) {
    toast("只有企业管理员可以导入或重建数据", "error");
    return { name: "dashboard" };
  }
  return true;
});

export default router;
