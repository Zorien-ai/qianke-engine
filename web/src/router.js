import { createRouter, createWebHashHistory } from "vue-router";
import { boot, hasCap, isManager, toast } from "./store";

import Dashboard from "./views/Dashboard.vue";
import Chat from "./views/Chat.vue";
import Kb from "./views/Kb.vue";
import Staff from "./views/Staff.vue";
import Settings from "./views/Settings.vue";

/**
 * 用 hash 路由：后端把 web/dist 静态挂到 /v2/，没有服务端 fallback，
 * history 模式刷新 /v2/chat 会 404；hash 模式下服务端只认 /v2/index.html。
 */
const routes = [
  { path: "/", name: "dashboard", component: Dashboard, meta: { title: "工作台" } },
  { path: "/chat", name: "chat", component: Chat, meta: { title: "对话" } },
  { path: "/kb", name: "kb", component: Kb, meta: { title: "知识库" } },
  { path: "/staff", name: "staff", component: Staff, meta: { title: "员工管理" } },
  { path: "/settings", name: "settings", component: Settings, meta: { title: "权限配置" } },
  { path: "/:pathMatch(.*)*", redirect: "/" },
];

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 };
  },
});

router.beforeEach(async (to) => {
  const ok = await boot();
  if (!ok) return false;
  // 无能力的页面手动敲 hash 也进不去：送回工作台并说明原因
  if (to.name === "staff" && !isManager()) {
    toast("当前账号不是管理员，无法访问员工管理", "error");
    return { name: "dashboard" };
  }
  if (to.name === "settings" && !hasCap("ops")) {
    toast("当前账号没有权限配置能力（仅系统管理员可用）", "error");
    return { name: "dashboard" };
  }
  return true;
});

export default router;
