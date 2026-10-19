<script setup>
/**
 * 构建历史子页面：读取当前数据空间的 build_history。
 * 没有历史表的旧库，后端会从 last_build 降级返回一条并带 note。
 */
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api";

const items = ref([]);
const loading = ref(true);
const error = ref("");

const total = computed(() => items.value.length);
const hasFallback = computed(() => items.value.some((x) => x.note));

function modeLabel(mode) {
  if (mode === "incremental") return "增量";
  if (mode === "full") return "全量";
  return mode || "—";
}
function statusLabel(status) {
  if (status === "failed") return "失败";
  if (status === "success") return "成功";
  return status || "未知";
}
function statusClass(status) {
  if (status === "failed") return "is-error";
  if (status === "success") return "is-success";
  return "is-muted";
}
function duration(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n >= 60) return `${Math.floor(n / 60)} 分 ${Math.round(n % 60)} 秒`;
  return `${n.toFixed(n < 10 ? 1 : 0)} 秒`;
}
function count(value) {
  if (value === null || value === undefined || value === "") return "—";
  return Number(value || 0).toLocaleString();
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await getJson("/api/kb/history");
    items.value = data.items || [];
  } catch (e) {
    error.value = e.detail || e.message || "构建历史加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="page kb-subpage">
    <div class="kb-subhead">
      <div>
        <RouterLink to="/kb" class="kb-back">← 知识库概况</RouterLink>
        <h2>构建历史</h2>
        <p class="card-sub">
          当前数据空间的构建流水：每次全量/增量构建的时间、耗时和写入规模。只显示本账号数据空间。
        </p>
      </div>
      <div class="row-actions">
        <RouterLink class="btn btn-ghost" to="/setup">数据导入 / 重建</RouterLink>
        <button type="button" class="btn btn-ghost" :disabled="loading" @click="load">
          {{ loading ? "加载中…" : "刷新" }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="card">
      <div v-for="i in 5" :key="i" class="skeleton" style="height: 42px; margin-top: 8px"></div>
    </div>

    <div v-else-if="error" class="card">
      <div class="empty-state">
        <div class="empty-emoji">🧱</div>
        <div class="empty-title">构建历史加载失败</div>
        <div class="empty-desc">{{ error }}</div>
        <button type="button" class="btn btn-primary" @click="load">重试</button>
      </div>
    </div>

    <div v-else class="card">
      <div class="history-head">
        <div class="visual-kicker">BUILD PIPELINE</div>
        <span class="badge">{{ total }} 条记录</span>
        <span v-if="hasFallback" class="badge is-warn">旧库兼容视图</span>
        <span class="spacer"></span>
        <span class="field-hint">最新在前 · 最多 50 条</span>
      </div>

      <div v-if="!items.length" class="empty-state" style="padding: 34px 10px">
        <div class="empty-emoji">🏗️</div>
        <div class="empty-title">还没有构建记录</div>
        <div class="empty-desc">完成一次数据构建后，这里会出现构建流水。</div>
      </div>

      <div v-else class="table-wrap">
        <table class="table history-table">
          <thead>
            <tr>
              <th>构建时间</th>
              <th>类型</th>
              <th>耗时</th>
              <th>涉及行数</th>
              <th>用户画像</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in items" :key="`${row.built_at}-${i}`">
              <td class="history-time">{{ row.built_at || "—" }}</td>
              <td><span class="tag">{{ modeLabel(row.mode) }}</span></td>
              <td>{{ duration(row.elapsed_s) }}</td>
              <td>{{ count(row.rows) }}</td>
              <td>{{ count(row.profiles) }}</td>
              <td>
                <span class="badge" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
                <div v-if="row.error" class="history-error" :title="row.error">{{ row.error }}</div>
                <div v-if="row.note" class="history-note">{{ row.note }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kb-subpage { max-width: 1200px; }
.kb-subhead {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.kb-back {
  display: inline-block;
  margin-bottom: 8px;
  color: var(--primary);
  text-decoration: none;
  font-size: 12px;
}
.kb-back:hover { text-decoration: underline; }
.kb-subhead h2 { margin: 0; font-size: 22px; }
.kb-subhead .card-sub { margin: 7px 0 0; max-width: 760px; }
.history-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.visual-kicker {
  font-family: var(--font-mono, monospace);
  font-size: 10px;
  letter-spacing: 0.15em;
  color: var(--primary);
  font-weight: 700;
}
.history-table .history-time { font-family: var(--font-mono, monospace); font-size: 12px; white-space: nowrap; }
.history-error {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--danger);
  font-size: 10.5px;
  margin-top: 4px;
}
.history-note { color: var(--muted); font-size: 10.5px; margin-top: 3px; }
@media (max-width: 700px) {
  .history-table { min-width: 620px; }
}
</style>
