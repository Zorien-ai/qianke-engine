<script setup>
import { computed, onMounted, ref } from "vue";
import { getJson, postJson } from "../api";

const actions = ref([]);
const loading = ref(true);
const error = ref("");
const statusFilter = ref("");
const busy = ref("");
const hint = ref("");

const STATUS_LABELS = {
  DRAFT: "待确认",
  CONFIRMED: "已确认",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
};

const STATUS_ORDER = ["DRAFT", "CONFIRMED", "COMPLETED", "CANCELLED"];

const counts = computed(() => {
  const result = { DRAFT: 0, CONFIRMED: 0, COMPLETED: 0, CANCELLED: 0 };
  for (const action of actions.value) {
    if (result[action.status] !== undefined) result[action.status] += 1;
  }
  return result;
});

function statusLabel(status) {
  return STATUS_LABELS[status] || status || "未知";
}

function statusClass(status) {
  return `is-${String(status || "").toLowerCase()}`;
}

function date(value) {
  return value ? String(value).replace("T", " ").slice(0, 16) : "—";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const query = new URLSearchParams({ limit: "100" });
    if (statusFilter.value) query.set("status", statusFilter.value);
    const data = await getJson(`/api/agent/actions?${query.toString()}`);
    actions.value = data?.actions || [];
  } catch (e) {
    error.value = e?.detail?.message || e?.detail || e?.message || "任务加载失败";
  } finally {
    loading.value = false;
  }
}

async function runAction(action, operation) {
  if (!action?.action_id || busy.value) return;
  busy.value = action.action_id;
  error.value = "";
  hint.value = "";
  try {
    await postJson(`/api/agent/actions/${encodeURIComponent(action.action_id)}/${operation}`, {});
    hint.value = operation === "complete" ? "任务已完成" : operation === "confirm" ? "任务已确认" : "任务已取消";
    await load();
  } catch (e) {
    error.value = e?.detail?.message || e?.detail || e?.message || "操作失败";
  } finally {
    busy.value = "";
  }
}

function setStatus(status) {
  statusFilter.value = status;
  load();
}

onMounted(load);
</script>

<template>
  <div class="tasks-page">
    <header class="tasks-hero">
      <div>
        <div class="hero-kicker">AGENT · 受控写入</div>
        <h2>运营任务看板</h2>
        <p>Agent 只生成待确认草稿；确认后才进入任务队列，完成由你手动推进。</p>
      </div>
      <button type="button" class="tasks-refresh" :disabled="loading" @click="load">
        {{ loading ? "加载中…" : "刷新" }}
      </button>
    </header>

    <section class="tasks-stats" aria-label="任务统计">
      <button
        v-for="status in STATUS_ORDER"
        :key="status"
        type="button"
        class="tasks-stat"
        :class="{ active: statusFilter === status }"
        @click="setStatus(statusFilter === status ? '' : status)"
      >
        <span>{{ statusLabel(status) }}</span>
        <strong>{{ counts[status] || 0 }}</strong>
      </button>
      <button
        type="button"
        class="tasks-stat tasks-stat-all"
        :class="{ active: !statusFilter }"
        @click="setStatus('')"
      >
        <span>全部</span>
        <strong>{{ actions.length }}</strong>
      </button>
    </section>

    <p v-if="error" class="tasks-error" role="alert">{{ error }}</p>
    <p v-else-if="hint" class="tasks-hint" role="status">{{ hint }}</p>

    <section class="tasks-panel">
      <div v-if="loading" class="tasks-empty">正在加载任务…</div>
      <div v-else-if="!actions.length" class="tasks-empty">
        <strong>没有任务</strong>
        <p>在「经营分析 Agent」中明确要求创建跟进任务，会先生成待确认草稿。</p>
      </div>
      <div v-else class="tasks-list">
        <article v-for="action in actions" :key="action.action_id" class="task-card">
          <div class="task-main">
            <div class="task-title-row">
              <h3>{{ action.title }}</h3>
              <span class="task-status" :class="statusClass(action.status)">
                {{ statusLabel(action.status) }}
              </span>
            </div>
            <p v-if="action.description" class="task-desc">{{ action.description }}</p>
            <div class="task-meta">
              <span>{{ action.owner || "未指定负责人" }}</span>
              <span>优先级 {{ action.priority || "normal" }}</span>
              <span>截止 {{ action.due_date || "未设置" }}</span>
              <span>创建 {{ date(action.created_at) }}</span>
            </div>
          </div>
          <div class="task-actions">
            <button
              v-if="action.status === 'DRAFT'"
              type="button"
              class="task-btn primary"
              :disabled="busy === action.action_id"
              @click="runAction(action, 'confirm')"
            >
              确认
            </button>
            <button
              v-if="action.status === 'DRAFT'"
              type="button"
              class="task-btn"
              :disabled="busy === action.action_id"
              @click="runAction(action, 'cancel')"
            >
              取消
            </button>
            <button
              v-if="action.status === 'CONFIRMED'"
              type="button"
              class="task-btn primary"
              :disabled="busy === action.action_id"
              @click="runAction(action, 'complete')"
            >
              标记完成
            </button>
            <span v-if="action.status === 'COMPLETED'" class="task-done">
              {{ date(action.completed_at) }} 完成
            </span>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.tasks-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 24px 56px;
}

.tasks-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 24px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}

.hero-kicker {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.08em;
}

.tasks-hero h2 {
  margin-top: 6px;
  font-size: 24px;
}

.tasks-hero p {
  max-width: 680px;
  margin-top: 8px;
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.7;
}

.tasks-refresh {
  flex-shrink: 0;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--text-2);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.tasks-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-top: 16px;
}

.tasks-stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface);
  color: var(--muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.tasks-stat strong {
  color: var(--text);
  font-family: var(--mono);
  font-size: 18px;
}

.tasks-stat.active {
  border-color: var(--primary);
  color: var(--primary);
}

.tasks-error,
.tasks-hint {
  margin-top: 12px;
  font-size: 11px;
}

.tasks-error {
  color: var(--danger);
}

.tasks-hint {
  color: var(--success);
}

.tasks-panel {
  margin-top: 16px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}

.tasks-empty {
  padding: 42px 20px;
  color: var(--muted);
  text-align: center;
  font-size: 12px;
}

.tasks-empty strong {
  color: var(--text);
  font-size: 14px;
}

.tasks-empty p {
  margin-top: 6px;
}

.tasks-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.task-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 14px 16px;
  border-radius: var(--radius-xs);
  background: var(--surface-2);
}

.task-main {
  min-width: 0;
  flex: 1;
}

.task-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.task-title-row h3 {
  font-size: 13px;
}

.task-status {
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 9px;
}

.task-status.is-draft {
  color: var(--warn);
  background: var(--warn-soft);
}

.task-status.is-confirmed {
  color: var(--primary);
  background: var(--primary-soft);
}

.task-status.is-completed {
  color: var(--success);
  background: var(--success-soft);
}

.task-status.is-cancelled {
  color: var(--muted);
  background: var(--surface);
}

.task-desc {
  margin-top: 5px;
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.6;
}

.task-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  color: var(--muted);
  font-size: 10px;
}

.task-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
}

.task-btn {
  padding: 5px 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--text-2);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.task-btn.primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.task-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.task-done {
  color: var(--muted);
  font-size: 10px;
}

@media (max-width: 760px) {
  .tasks-page {
    padding: 16px 12px 32px;
  }

  .tasks-hero {
    flex-direction: column;
  }

  .tasks-stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .task-card {
    flex-direction: column;
  }

  .task-actions {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
