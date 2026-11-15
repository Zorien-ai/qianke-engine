<script setup>
/**
 * 评测中心：RAG 离线评测 / Agent 数据集实验共用一个入口。
 * 两套后端 API 分开，前端只合并入口和 tab。
 */
import { computed, defineAsyncComponent } from "vue";
import { useRoute, useRouter } from "vue-router";
import { isDemo, isManager, store, toast } from "../store";

const route = useRoute();
const router = useRouter();
const RagEval = defineAsyncComponent(() => import("./Eval.vue"));
const AgentEval = defineAsyncComponent(() => import("./AdminAgentEvals.vue"));

const isSystemAdmin = computed(() => !!(store.account && store.account.is_system_admin));
const allTabs = [
  { key: "rag", label: "RAG 离线评测", component: RagEval, enabled: () => isManager() || isDemo() || isSystemAdmin.value },
  { key: "agent", label: "Agent 实验", component: AgentEval, enabled: () => isSystemAdmin.value },
];
const visibleTabs = computed(() => allTabs.filter((tab) => tab.enabled()));
const activeKey = computed(() => {
  const requested = String(route.query.tab || "rag");
  return visibleTabs.value.some((tab) => tab.key === requested) ? requested : "rag";
});
const activeComponent = computed(() => (allTabs.find((tab) => tab.key === activeKey.value) || allTabs[0]).component);

function switchTab(key) {
  const tab = allTabs.find((item) => item.key === key);
  if (!tab || !tab.enabled()) {
    toast("当前账号没有该评测权限", "error");
    return;
  }
  router.replace({ name: "eval-center", query: { tab: key } });
}
</script>

<template>
  <div class="page center-shell">
    <nav class="center-tabs" aria-label="评测分区">
      <button
        v-for="tab in visibleTabs"
        :key="tab.key"
        type="button"
        class="center-tab"
        :class="{ 'is-active': activeKey === tab.key }"
        @click="switchTab(tab.key)"
      >{{ tab.label }}</button>
      <span class="center-hint">题库评测与 Agent 实验统一入口</span>
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
