<script setup>
/**
 * 管理员端本地 LangSmith：Agent 调用 trace 列表 + 时间线。
 * 数据来自 ai_traces / ai_spans，不依赖外部 LangSmith。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { getJson } from "../api";

const ranges = [
  { value: "1h", label: "1 小时" },
  { value: "24h", label: "24 小时" },
  { value: "7d", label: "7 天" },
  { value: "30d", label: "30 天" },
];
const statuses = [
  { value: "", label: "全部状态" },
  { value: "success", label: "成功" },
  { value: "error", label: "失败" },
];
const range = ref("24h");
const status = ref("");
const q = ref("");
const items = ref([]);
const summary = ref(null);
const total = ref(0);
const loading = ref(true);
const error = ref("");
const detail = ref(null);
const detailLoading = ref(false);
const detailError = ref("");

function num(value) {
  return Number(value || 0).toLocaleString();
}
function ms(value) {
  const n = Number(value || 0);
  return n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`;
}
function date(value) {
  return value ? String(value).replace("T", " ").slice(0, 19) : "—";
}
function statusText(value) {
  const v = String(value || "").toLowerCase();
  if (v === "success" || v === "completed") return "成功";
  if (v === "error" || v === "failed") return "失败";
  if (v === "running") return "运行中";
  return value || "未知";
}
function statusClass(value) {
  const v = String(value || "").toLowerCase();
  if (v === "success" || v === "completed") return "is-ok";
  if (v === "error" || v === "failed" || v === "timeout" || v === "cancelled") return "is-error";
  return "is-running";
}

const traceMeta = computed(() => {
  const meta = detail.value?.meta;
  if (!meta) return {};
  if (typeof meta === "string") {
    try { return JSON.parse(meta); } catch { return {}; }
  }
  return meta;
});
const events = computed(() => {
  const list = traceMeta.value?.agent_events;
  return Array.isArray(list) ? list : [];
});

function eventLabel(event) {
  const name = String(event?.event || "");
  const map = {
    run_started: "运行开始",
    run_finished: "运行结束",
    run_failed: "运行失败",
    llm_started: "LLM 开始",
    llm_finished: "LLM 完成",
    llm_error: "LLM 错误",
    tool_started: "工具开始",
    tool_finished: "工具完成",
    tool_error: "工具错误",
  };
  return map[name] || name || "事件";
}
function eventClass(event) {
  const name = String(event?.event || "");
  if (name.includes("error") || name.includes("failed")) return "is-error";
  if (name.endsWith("_finished")) return "is-done";
  if (name.endsWith("_started")) return "is-start";
  return "";
}
function eventDuration(event) {
  if (event?.duration_ms != null) return ms(event.duration_ms);
  if (event?.latency_ms != null) return ms(event.latency_ms);
  return "";
}
function eventDetail(event) {
  const parts = [];
  if (event?.name) parts.push(event.name);
  if (event?.model) parts.push(event.model);
  const args = event?.args || event?.input_preview;
  if (args) parts.push(typeof args === "string" ? args : JSON.stringify(args));
  const output = event?.output_preview;
  if (output) parts.push(typeof output === "string" ? output : JSON.stringify(output));
  const errorText = event?.error;
  if (errorText) parts.push(String(errorText));
  return parts.filter(Boolean).join(" · ").slice(0, 500);
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({ range: range.value, limit: "100" });
    if (status.value) params.set("status", status.value);
    if (q.value.trim()) params.set("q", q.value.trim());
    const data = await getJson(`/api/admin/agent-traces?${params.toString()}`);
    items.value = data.items || [];
    summary.value = data.summary || null;
    total.value = data.total || 0;
  } catch (e) {
    error.value = e?.detail || e?.message || "Agent 调用数据加载失败";
  } finally {
    loading.value = false;
  }
}

async function openTrace(item) {
  const traceId = item?.trace_id;
  if (!traceId) return;
  detail.value = { ...item, meta: {} };
  detailError.value = "";
  detailLoading.value = true;
  try {
    detail.value = await getJson(`/api/admin/agent-traces/${encodeURIComponent(traceId)}`);
  } catch (e) {
    detailError.value = e?.detail || e?.message || "Trace 详情加载失败";
  } finally {
    detailLoading.value = false;
  }
}
function closeDetail() {
  detail.value = null;
  detailError.value = "";
}
function onKeydown(e) {
  if (e.key === "Escape" && detail.value) closeDetail();
}

onMounted(() => {
  window.addEventListener("keydown", onKeydown);
  load();
});
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <div class="page agent-observability">
    <header class="admin-hero">
      <div>
        <div class="monitor-kicker">LOCAL LANGSMITH · AGENT TRACES</div>
        <div class="admin-title-line">
          <h2>Agent 调用监控</h2>
          <span class="badge is-primary">本地中台</span>
          <span class="badge is-warn">系统管理员</span>
        </div>
        <p class="card-sub">记录 Agent 的 LLM / Tool / 最终状态、耗时与 Token，不依赖外部 LangSmith。</p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="load">刷新</button>
    </header>

    <section class="card obs-filter-card">
      <div class="obs-filters">
        <div class="obs-range" role="group" aria-label="时间范围">
          <button
            v-for="r in ranges"
            :key="r.value"
            type="button"
            class="obs-range-btn"
            :class="{ 'is-active': range === r.value }"
            @click="range = r.value; load()"
          >{{ r.label }}</button>
        </div>
        <label class="obs-field">
          <span>状态</span>
          <select v-model="status" @change="load">
            <option v-for="s in statuses" :key="s.value" :value="s.value">{{ s.label }}</option>
          </select>
        </label>
        <label class="obs-search">
          <span class="obs-search-icon" aria-hidden="true">⌕</span>
          <input v-model="q" type="search" placeholder="搜索问题 / request_id / trace_id" @keyup.enter="load" />
        </label>
        <button type="button" class="btn btn-primary" :disabled="loading" @click="load">查询</button>
      </div>
    </section>

    <div v-if="loading" class="card"><div class="skeleton" style="height:120px"></div></div>
    <div v-else-if="error" class="card"><div class="empty-state"><div class="empty-title">加载失败</div><div class="empty-desc">{{ error }}</div></div></div>
    <template v-else>
      <div class="obs-stats">
        <div class="obs-stat"><span>调用数</span><b>{{ num(summary?.requests) }}</b><small>当前筛选</small></div>
        <div class="obs-stat"><span>成功率</span><b>{{ summary ? (summary.success_rate * 100).toFixed(1) + "%" : "—" }}</b><small>成功 {{ num(summary?.success) }} / 失败 {{ num(summary?.errors) }}</small></div>
        <div class="obs-stat"><span>P95 耗时</span><b>{{ ms(summary?.p95_latency_ms) }}</b><small>Agent 端到端</small></div>
        <div class="obs-stat"><span>Token</span><b>{{ num(summary?.total_tokens) }}</b><small>当前筛选合计</small></div>
        <div class="obs-stat"><span>工具调用</span><b>{{ num(summary?.tool_calls) }}</b><small>当前筛选合计</small></div>
      </div>

      <section class="card obs-table-card">
        <div class="admin-section-head">
          <strong>最近调用</strong>
          <span class="field-hint">共 {{ num(total) }} 条 · 点击行查看 Trace</span>
        </div>
        <div class="table-wrap">
          <table class="table obs-table">
            <thead>
              <tr>
                <th>时间</th><th>入口</th><th>问题</th><th>状态</th>
                <th>耗时</th><th>Steps</th><th>Tools</th><th>Tokens</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.trace_id" class="obs-row" tabindex="0" @click="openTrace(item)" @keyup.enter="openTrace(item)">
                <td class="obs-nowrap">{{ date(item.started_at) }}</td>
                <td><span class="obs-entry">{{ item.entrypoint }}</span></td>
                <td class="obs-question">{{ item.question || "—" }}</td>
                <td><span class="obs-status" :class="statusClass(item.status)">{{ statusText(item.status) }}</span></td>
                <td class="obs-nowrap">{{ ms(item.total_ms) }}</td>
                <td>{{ num(item.steps) }}</td>
                <td>{{ num(item.tool_call_count) }}</td>
                <td>{{ num(item.total_tokens) }}</td>
              </tr>
              <tr v-if="!items.length"><td colspan="8" class="field-hint">暂无 Agent 调用</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <div v-if="detail" class="obs-detail-mask" @click.self="closeDetail">
      <aside class="obs-detail" role="dialog" aria-modal="true" aria-labelledby="agent-trace-title">
        <header class="obs-detail-head">
          <div>
            <div class="monitor-kicker">TRACE DETAIL</div>
            <h3 id="agent-trace-title">{{ traceMeta.question || detail.question || "Agent 调用" }}</h3>
          </div>
          <button type="button" class="obs-close" aria-label="关闭详情" @click="closeDetail">×</button>
        </header>

        <div v-if="detailLoading" class="skeleton" style="height:140px"></div>
        <div v-else-if="detailError" class="empty-state"><div class="empty-title">详情加载失败</div><div class="empty-desc">{{ detailError }}</div></div>
        <template v-else>
          <div class="obs-detail-meta">
            <div><span>状态</span><b class="obs-status" :class="statusClass(traceMeta.status || detail.status)">{{ statusText(traceMeta.status || detail.status) }}</b></div>
            <div><span>耗时</span><b>{{ ms(detail.total_ms) }}</b></div>
            <div><span>Steps</span><b>{{ num(traceMeta.steps) }}</b></div>
            <div><span>Tools</span><b>{{ num(traceMeta.tool_call_count) }}</b></div>
            <div><span>Tokens</span><b>{{ num(detail.total_tokens || traceMeta.total_tokens) }}</b></div>
          </div>
          <p class="obs-trace-id">trace_id：{{ detail.trace_id }}</p>
          <p v-if="traceMeta.request_id" class="obs-trace-id">request_id：{{ traceMeta.request_id }} · execution_id：{{ traceMeta.execution_id }}</p>

          <h4 class="obs-section-title">执行时间线</h4>
          <ol class="obs-timeline">
            <li v-for="(event, idx) in events" :key="idx" class="obs-timeline-item" :class="eventClass(event)">
              <span class="obs-dot" aria-hidden="true" />
              <div class="obs-event-body">
                <div class="obs-event-head">
                  <b>{{ eventLabel(event) }}</b>
                  <span v-if="eventDuration(event)" class="obs-event-duration">{{ eventDuration(event) }}</span>
                </div>
                <p v-if="eventDetail(event)" class="obs-event-detail">{{ eventDetail(event) }}</p>
              </div>
            </li>
            <li v-if="!events.length" class="field-hint">暂无事件记录（旧版本 trace 可能只有汇总）</li>
          </ol>

          <template v-if="traceMeta.error">
            <h4 class="obs-section-title">错误</h4>
            <pre class="obs-pre obs-error">{{ traceMeta.error }}</pre>
          </template>
          <template v-if="traceMeta.final_answer">
            <h4 class="obs-section-title">最终回答</h4>
            <pre class="obs-pre">{{ traceMeta.final_answer }}</pre>
          </template>
        </template>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.obs-filter-card { padding: 14px 16px; }
.obs-filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.obs-range { display: inline-flex; padding: 3px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); }
.obs-range-btn { padding: 6px 10px; border: 0; border-radius: 8px; background: transparent; color: var(--muted); font-size: 12px; cursor: pointer; }
.obs-range-btn.is-active { background: var(--surface); color: var(--text); box-shadow: var(--shadow-sm); }
.obs-field { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; }
.obs-field select { height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); color: var(--text); }
.obs-search { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 220px; height: 34px; padding: 0 10px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); }
.obs-search-icon { color: var(--muted); font-size: 17px; }
.obs-search input { flex: 1; min-width: 0; border: 0; outline: none; background: transparent; color: var(--text); font-size: 13px; }
.obs-stats { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.obs-stat { padding: 14px 16px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); }
.obs-stat span { display: block; color: var(--muted); font-size: 11.5px; }
.obs-stat b { display: block; margin-top: 5px; font-size: 24px; letter-spacing: -.03em; }
.obs-stat small { display: block; margin-top: 3px; color: var(--muted); font-size: 10.5px; }
.obs-table-card { margin-top: 14px; }
.obs-row { cursor: pointer; }
.obs-row:hover td { background: var(--surface-2); }
.obs-nowrap { white-space: nowrap; }
.obs-entry { color: var(--text-2); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 11px; }
.obs-question { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.obs-status { display: inline-flex; align-items: center; padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.obs-status.is-ok { color: #166534; background: #e8f5ec; }
.obs-status.is-error { color: #991b1b; background: #fdeaea; }
.obs-status.is-running { color: #92400e; background: #fef3c7; }
.obs-detail-mask { position: fixed; inset: 0; z-index: 80; display: flex; justify-content: flex-end; background: rgba(15, 23, 42, .34); }
.obs-detail { width: min(620px, 94vw); height: 100vh; overflow-y: auto; padding: 22px; border-left: 1px solid var(--border); background: var(--surface); box-shadow: -12px 0 36px rgba(15, 23, 42, .14); }
.obs-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.obs-detail-head h3 { margin: 5px 0 0; font-size: 18px; line-height: 1.4; }
.obs-close { flex: 0 0 auto; width: 32px; height: 32px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); color: var(--text); font-size: 20px; line-height: 1; cursor: pointer; }
.obs-detail-meta { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin-top: 16px; }
.obs-detail-meta > div { padding: 10px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); }
.obs-detail-meta span { display: block; color: var(--muted); font-size: 10.5px; }
.obs-detail-meta b { display: block; margin-top: 4px; font-size: 14px; }
.obs-trace-id { margin: 10px 0 0; color: var(--muted); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10.5px; word-break: break-all; }
.obs-section-title { margin: 20px 0 8px; font-size: 13px; }
.obs-timeline { margin: 0; padding: 0 0 0 4px; list-style: none; }
.obs-timeline-item { position: relative; display: flex; gap: 10px; padding: 0 0 14px 16px; border-left: 1px solid var(--border); }
.obs-timeline-item:last-child { border-left-color: transparent; }
.obs-dot { position: absolute; left: -4px; top: 4px; width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.obs-timeline-item.is-start .obs-dot { background: #6366f1; }
.obs-timeline-item.is-done .obs-dot { background: #22a06b; }
.obs-timeline-item.is-error .obs-dot { background: #dc2626; }
.obs-event-body { min-width: 0; flex: 1; }
.obs-event-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.obs-event-head b { font-size: 12.5px; }
.obs-event-duration { color: var(--muted); font-size: 10.5px; white-space: nowrap; }
.obs-event-detail { margin: 3px 0 0; color: var(--muted); font-size: 11px; line-height: 1.6; word-break: break-word; }
.obs-pre { margin: 0; padding: 12px; max-height: 260px; overflow: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); color: var(--text-2); font-size: 11.5px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.obs-error { border-color: #fecaca; background: #fff7f7; color: #991b1b; }
@media (max-width: 900px) {
  .obs-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .obs-detail-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  .obs-filters { align-items: stretch; }
  .obs-range { width: 100%; }
  .obs-range-btn { flex: 1; }
  .obs-field, .obs-search { width: 100%; }
  .obs-question { max-width: 220px; }
  .obs-detail { width: 100vw; padding: 16px; }
}
</style>
