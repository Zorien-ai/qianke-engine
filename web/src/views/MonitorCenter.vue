<script setup>
/**
 * 监控中心：业务请求 / Agent 调用 / 租户与计费 三个子页面共用一个入口。
 * 子页面保留各自原有的权限、筛选和操作；中心只负责 tab 与角色可见性。
 */
import { computed, defineAsyncComponent } from "vue";
import { useRoute, useRouter } from "vue-router";
import { isManager, store, toast } from "../store";

const route = useRoute();
const router = useRouter();
const RequestMonitor = defineAsyncComponent(() => import("./Monitor.vue"));
const AgentMonitor = defineAsyncComponent(() => import("./AdminAgentMonitor.vue"));
const PlatformMonitor = defineAsyncComponent(() => import("./MonitorAdmin.vue"));

const isSystemAdmin = computed(() => !!(store.account && store.account.is_system_admin));
const allTabs = [
  { key: "request", label: "业务请求", component: RequestMonitor, enabled: () => isManager() || isSystemAdmin.value },
  { key: "agent", label: "Agent 调用", component: AgentMonitor, enabled: () => isSystemAdmin.value },
  { key: "platform", label: "租户与计费", component: PlatformMonitor, enabled: () => isSystemAdmin.value },
];
const visibleTabs = computed(() => allTabs.filter((tab) => tab.enabled()));
const activeKey = computed(() => {
  const requested = String(route.query.tab || "request");
  return visibleTabs.value.some((tab) => tab.key === requested) ? requested : "request";
});
const activeComponent = computed(() => (allTabs.find((tab) => tab.key === activeKey.value) || allTabs[0]).component);

function switchTab(key) {
  const tab = allTabs.find((item) => item.key === key);
  if (!tab || !tab.enabled()) {
    toast("当前账号没有该监控权限", "error");
    return;
  }
  router.replace({ name: "monitor-center", query: { tab: key } });
}
</script>

<template>
  <div class="page center-shell">
    <nav class="center-tabs" aria-label="监控分区">
      <button
        v-for="tab in visibleTabs"
        :key="tab.key"
        type="button"
        class="center-tab"
        :class="{ 'is-active': activeKey === tab.key }"
        @click="switchTab(tab.key)"
      >{{ tab.label }}</button>
      <span class="center-hint">统一入口 · 原有权限与筛选保留</span>
    </nav>
    <component :is="activeComponent" :key="activeKey" />
  </div>
</template>

<style scoped>
.center-shell { padding-top: 8px; }
.center-tabs { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-bottom: 12px; padding: 4px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); }
.center-tab { padding: 7px 12px; border: 0; border-radius: 7px; background: transparent; color: var(--muted); font-size: 12px; cursor: pointer; }
.center-tab:hover { color: var(--text); background: var(--surface); }
.center-tab.is-active { background: var(--surface); color: var(--text); box-shadow: var(--shadow-sm); font-weight: 600; }
.center-hint { margin-left: auto; padding-right: 7px; color: var(--muted); font-size: 10px; }
.center-shell :deep(.page) { padding: 0; max-width: none; }
@media (max-width: 700px) {
  .center-hint { display: none; }
  .center-tab { flex: 1; text-align: center; }
}
</style>
