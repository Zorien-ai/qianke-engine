<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { hasCap, isDemo, isManager, logout, store, toast } from "./store";
import ToastHost from "./components/ToastHost.vue";
import LanguageToggle from "./components/LanguageToggle.vue";
import ThemeToggle from "./components/ThemeToggle.vue";
import Logo from "./components/Logo.vue";

const route = useRoute();
const drawerOpen = ref(false);
const collapsed = ref(false);
const demoMode = computed(() => isDemo());

function demoSetupBlocked() {
  toast("演示模式无法导入数据", "warn");
}

const ICONS = {
  dashboard:
    '<rect x="3" y="3" width="7" height="9" rx="2"/><rect x="14" y="3" width="7" height="5" rx="2"/><rect x="14" y="12" width="7" height="9" rx="2"/><rect x="3" y="16" width="7" height="5" rx="2"/>',
  chat: '<path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.9 8.9 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z"/><path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01"/>',
  agent: '<path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3z"/><path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14z"/><path d="M5 15l.6 1.7L7.3 17.3l-1.7.6L5 19.6l-.6-1.7-1.7-.6 1.7-.6L5 15z"/>',
  shop: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
  social: '<path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.9 8.9 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z"/><path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01"/>',
  orders: '<path d="M6 2h12v20l-3-2-3 2-3-2-3 2z"/><path d="M9 7h6M9 11h6M9 15h4"/>',
  kb: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
  eval:
    '<path d="M9 3h6v4H9z"/><path d="M9 5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-3"/><path d="M8 13l2.2 2.2L16 9.5"/>',
  staff:
    '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  settings:
    '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
  monitor:
    '<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/><circle cx="12" cy="12" r="9"/>',
  billing:
    '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/><path d="M6 15h4"/>',
  wizard:
    '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  menu: '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>',
  collapse: '<polyline points="11 17 6 12 11 7"/><polyline points="18 17 13 12 18 7"/>',
  logout:
    '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
};

const navItems = computed(() => {
  const items = [
    { to: "/", key: "dashboard", label: "工作台", icon: ICONS.dashboard },
    { to: "/chat", key: "chat", label: "对话", icon: ICONS.chat },
    { to: "/agent", key: "agent", label: "Agent 智能助理", icon: ICONS.agent },
    { to: "/c", key: "shop", label: "C 端商城", icon: ICONS.shop },
    { to: "/c/app", key: "capp", label: "C 端 App", icon: ICONS.social },
    { to: "/c/social", key: "social", label: "社交消息", icon: ICONS.social },
    { to: "/c/orders", key: "orders", label: "我的订单", icon: ICONS.orders },
    { to: "/kb", key: "kb", label: "知识库", icon: ICONS.kb },
  ];
  if (isManager()) items.push({ to: "/staff", key: "staff", label: "员工管理", icon: ICONS.staff });
  if (isManager() || demoMode.value) items.push({ to: "/eval", key: "eval", label: "离线评测", icon: ICONS.eval });
  if (isManager()) items.push({ to: "/monitor", key: "monitor", label: "实时监控", icon: ICONS.monitor });
  if (isManager()) items.push({ to: "/billing", key: "billing", label: "Token 账单", icon: ICONS.billing });
  if (store.account && store.account.is_system_admin)
    items.push({ to: "/admin/monitor", key: "adminMonitor", label: "平台监控", icon: ICONS.monitor });
  if (store.account && store.account.is_system_admin)
    items.push({ to: "/admin/c-end", key: "adminCEnd", label: "C 端审计", icon: ICONS.orders });
  if (hasCap("ops"))
    items.push({ to: "/settings", key: "settings", label: "权限配置", icon: ICONS.settings });
  return items;
});

const pageTitle = computed(() => (route.meta && route.meta.title) || "工作台");
// 登录后的工作台统一 Tab 标题；公开营销页 /home 由 Landing 自己设置更完整的标题
watch(
  () => route.path,
  () => {
    if (route.meta && route.meta.standalone) {
      document.title = route.meta.title || "千客";
    } else if (!(route.meta && route.meta.public)) {
      document.title = "千客引擎 · 新版工作台";
    }
  },
  { immediate: true },
);
// 公开营销页（/home）不套应用外壳：它自带极简导航与暖白底色
const isPublicRoute = computed(() => !!(route.meta && route.meta.public));
const isStandaloneRoute = computed(() => !!(route.meta && route.meta.standalone));
const accountName = computed(() => {
  const a = store.account;
  if (!a) return "未登录";
  return a.display_name || a.username || "未知账号";
});
const avatarChar = computed(() => {
  const n = accountName.value;
  return n ? n.slice(0, 1).toUpperCase() : "?";
});
const enterpriseName = computed(() => {
  const ent = store.account && store.account.enterprise;
  return ent ? ent.name : store.account && store.account.is_system_admin ? "平台方" : "—";
});
const roleLine = computed(() => {
  const a = store.account;
  if (!a) return "";
  return [a.account_type_label, store.roleLabel].filter(Boolean).join(" · ");
});

function onResize() {
  if (window.innerWidth > 900) drawerOpen.value = false;
}

onMounted(() => {
  try {
    collapsed.value = localStorage.getItem("rag-v2-sidebar") === "1";
  } catch {
    /* 忽略 */
  }
  window.addEventListener("resize", onResize);
});

watch(collapsed, (v) => {
  try {
    localStorage.setItem("rag-v2-sidebar", v ? "1" : "0");
  } catch {
    /* 忽略 */
  }
});

function closeDrawer() {
  drawerOpen.value = false;
}
</script>

<template>
  <!-- 初始化中 / 初始化失败：两种外壳共用同一块提示 -->
  <div v-if="!store.booted" class="boot-screen">
    <div v-if="!store.bootError" class="boot-box">
      <span class="spinner" />
      <p>正在确认登录状态…</p>
    </div>
    <div v-else class="boot-box boot-error">
      <h2>无法完成初始化</h2>
      <p>{{ store.bootError }}</p>
      <div class="row-actions">
        <button class="btn btn-primary" @click="$router.go(0)">重试</button>
        <a class="btn btn-ghost" href="/login">去登录页</a>
      </div>
    </div>
  </div>

  <!-- 公开落地页：不渲染侧边栏 / topbar / 抽屉，页面自带营销页顶栏 -->
  <template v-else-if="isPublicRoute">
    <RouterView />
    <ToastHost />
  </template>

  <!-- 独立 C 端应用：不套企业工作台外壳 -->
  <template v-else-if="isStandaloneRoute">
    <RouterView />
    <ToastHost />
  </template>

  <!-- 应用外壳（登录后的工作台） -->
  <div v-else class="app-shell" :class="{ 'is-collapsed': collapsed, 'is-drawer-open': drawerOpen, 'is-chat-shell': route.name === 'chat' }">
      <div class="nav-backdrop" :class="{ show: drawerOpen }" @click="closeDrawer" />

      <aside class="sidebar">
        <div class="brand">
          <Logo :size="32" :show-text="false" class="brand-logo-slot" />
          <div class="brand-text">
            <strong>千客引擎</strong>
            <span>新版工作台</span>
          </div>
        </div>

        <nav class="nav-list">
          <RouterLink
            v-for="item in navItems"
            :key="item.key"
            :to="item.to"
            class="nav-item"
            active-class=""
            exact-active-class=""
            :class="{ 'is-active': route.path === item.to || (item.to === '/kb' && route.path.startsWith('/kb/')) }"
            :title="item.label"
            @click="closeDrawer"
          >
            <span class="nav-icon" v-html="`<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'>${item.icon}</svg>`" />
            <span class="nav-label">{{ item.label }}</span>
          </RouterLink>
        </nav>

        <div class="sidebar-foot">
          <button
            v-if="demoMode"
            type="button"
            class="nav-item is-disabled"
            title="演示模式无法导入数据"
            @click="demoSetupBlocked"
          >
            <span class="nav-icon" v-html="`<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'>${ICONS.wizard}</svg>`" />
            <span class="nav-label">数据导入</span>
            <span class="nav-lock">只读</span>
          </button>
          <RouterLink
            v-else-if="isManager()"
            to="/setup"
            class="nav-item"
            :class="{ 'is-active': route.path === '/setup' }"
            title="数据导入 · 四步向导"
            @click="closeDrawer"
          >
            <span class="nav-icon" v-html="`<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'>${ICONS.wizard}</svg>`" />
            <span class="nav-label">数据导入</span>
          </RouterLink>
          <button class="collapse-btn" type="button" @click="collapsed = !collapsed" :title="collapsed ? '展开侧边栏' : '折叠侧边栏'">
            <span class="nav-icon" v-html="`<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'>${ICONS.collapse}</svg>`" />
            <span class="nav-label">收起侧边栏</span>
          </button>
        </div>
      </aside>

      <div class="main-col">
        <header class="topbar">
          <button class="icon-btn menu-btn" type="button" @click="drawerOpen = true" aria-label="打开菜单">
            <span class="nav-icon" v-html="`<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round'>${ICONS.menu}</svg>`" />
          </button>
          <h1
            v-if="route.name === 'chat'"
            class="page-title chat-session-title"
            :title="store.chatTitle || '新对话'"
          >{{ store.chatTitle || "新对话" }}</h1>
          <h1 v-else class="page-title">{{ pageTitle }}</h1>

          <div class="topbar-right">
            <span v-if="store.level" class="level-badge" :title="`当前账号的有效等级：${store.levelLabel}`">
              {{ store.levelLabel }}
            </span>
            <ThemeToggle />
            <LanguageToggle />
            <div class="account-chip" :title="`${enterpriseName} · ${roleLine}`">
              <span class="avatar">{{ avatarChar }}</span>
              <span class="account-meta">
                <strong>{{ accountName }}</strong>
                <small>{{ enterpriseName }}</small>
              </span>
            </div>
            <button class="icon-btn" type="button" title="退出登录" @click="logout">
              <span class="nav-icon" v-html="`<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'>${ICONS.logout}</svg>`" />
            </button>
          </div>
        </header>

        <div v-if="demoMode" class="demo-banner" role="status">
          <span class="demo-banner-icon" aria-hidden="true">🎯</span>
          <span class="demo-banner-text">
            您当前处于演示体验模式。为保证系统稳定，演示库为只读，无法上传文件和构建。
          </span>
          <span class="demo-banner-tag">DEMO · READ ONLY</span>
        </div>

        <main class="content" :class="{ 'content-chat': route.name === 'chat' }">
          <RouterView v-slot="{ Component }">
            <transition name="page" mode="out-in">
              <component :is="Component" />
            </transition>
          </RouterView>
        </main>
      </div>

    <ToastHost />
  </div>
</template>
