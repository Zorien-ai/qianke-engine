<script setup>
/**
 * AI 实时监控：请求、Token、成本、延迟、错误、缓存与 Trace 下钻。
 */
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api";

const RANGES = [
  { key: "1h", label: "近 1 小时" },
  { key: "24h", label: "近 24 小时" },
  { key: "7d", label: "近 7 天" },
];
const range = ref("24h");
const overview = ref(null);
const series = ref([]);
const traces = ref([]);
const loading = ref(true);
const error = ref("");
const activeTrace = ref(null);
const traceOpen = ref(false);
const traceLoading = ref(false);

const maxTokens = computed(() => Math.max(1, ...series.value.map((x) => x.tokens || 0)));
const maxRequests = computed(() => Math.max(1, ...series.value.map((x) => x.requests || 0)));

function num(value) {
  return Number(value || 0).toLocaleString();
}
function money(value) {
  const n = Number(value || 0);
  return `¥${n.toFixed(Math.abs(n) > 0 && Math.abs(n) < 0.01 ? 4 : 2)}`;
}
function pct(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}
function shortTime(value) {
  if (!value) return "—";
  return String(value).replace("T", " ").slice(0, 19);
}
function dots(values, max, width = 680, height = 110) {
  if (!values.length) return [];
  return values.map((value, i) => {
    const x = values.length === 1 ? width / 2 : (i / (values.length - 1)) * width;
    const y = height - (Number(value || 0) / max) * (height - 10) - 5;
    return { x: Number(x.toFixed(1)), y: Number(y.toFixed(1)) };
  });
}
function points(values, max, width = 680, height = 110) {
  return dots(values, max, width, height).map((p) => `${p.x},${p.y}`).join(" ");
}
function sparkDots() {
  return dots(series.value.map((x) => x.tokens || 0), maxTokens.value);
}
function spark() {
  return points(series.value.map((x) => x.tokens || 0), maxTokens.value);
}
function requestSpark() {
  return points(series.value.map((x) => x.requests || 0), maxRequests.value);
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [ov, ts, tr] = await Promise.all([
      getJson(`/api/monitor/overview?range=${range.value}`),
      getJson(`/api/monitor/timeseries?range=${range.value}`),
      getJson("/api/monitor/traces?limit=30"),
    ]);
    overview.value = ov;
    series.value = ts.items || [];
    traces.value = tr.items || [];
  } catch (e) {
    error.value = e.detail || e.message || "监控数据加载失败";
  } finally {
    loading.value = false;
  }
}

function changeRange(key) {
  range.value = key;
  load();
}

async function openTrace(trace) {
  activeTrace.value = trace;
  traceOpen.value = true;
  traceLoading.value = true;
  try {
    activeTrace.value = await getJson(`/api/monitor/traces/${encodeURIComponent(trace.trace_id)}`);
  } catch (e) {
    activeTrace.value = { ...trace, spans: [], error: e.detail || e.message };
  } finally {
    traceLoading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="page monitor-page">
    <div class="monitor-hero">
      <div>
        <div class="monitor-kicker">AI OBSERVABILITY · TOKEN LEDGER</div>
        <div class="monitor-title-line">
          <h2>AI 实时监控</h2>
          <span class="badge is-primary">全链路</span>
          <span class="badge">内部成本价</span>
        </div>
        <p class="card-sub">
          请求、检索、SQL、LLM、安全审查与 Token 成本集中查看；数据来自当前账号的数据空间。
        </p>
      </div>
      <div class="row-actions">
        <div class="monitor-ranges">
          <button
            v-for="r in RANGES"
            :key="r.key"
            type="button"
            class="btn btn-sm"
            :class="range === r.key ? 'btn-primary' : 'btn-ghost'"
            @click="changeRange(r.key)"
          >{{ r.label }}</button>
        </div>
        <button type="button" class="btn btn-ghost" :disabled="loading" @click="load">刷新</button>
      </div>
    </div>

    <div v-if="loading" class="card">
      <div class="skeleton" style="height: 28px; width: 30%"></div>
      <div class="skeleton" style="height: 110px; margin-top: 16px"></div>
    </div>

    <div v-else-if="error" class="card">
      <div class="empty-state">
        <div class="empty-emoji">📡</div>
        <div class="empty-title">监控数据加载失败</div>
        <div class="empty-desc">{{ error }}</div>
        <button type="button" class="btn btn-primary" @click="load">重试</button>
      </div>
    </div>

    <template v-else-if="overview">
      <div class="monitor-stats">
        <div class="monitor-stat">
          <span class="monitor-label">请求</span>
          <b>{{ num(overview.requests) }}</b>
          <span class="monitor-sub">错误 {{ num(overview.errors) }} · {{ pct(overview.error_rate) }}</span>
        </div>
        <div class="monitor-stat">
          <span class="monitor-label">Token</span>
          <b>{{ num(overview.tokens) }}</b>
          <span class="monitor-sub">输入 + 输出</span>
        </div>
        <div class="monitor-stat">
          <span class="monitor-label">内部成本</span>
          <b>{{ money(overview.cost) }}</b>
          <span class="monitor-sub">销售金额 {{ money(overview.sales) }}</span>
        </div>
        <div class="monitor-stat">
          <span class="monitor-label">P95 延迟</span>
          <b>{{ num(overview.p95_latency_ms) }}<small>ms</small></b>
          <span class="monitor-sub">平均 {{ num(overview.avg_latency_ms) }} ms</span>
        </div>
        <div class="monitor-stat">
          <span class="monitor-label">缓存命中</span>
          <b>{{ pct(overview.cache_hit_rate) }}</b>
          <span class="monitor-sub">安全拦截 {{ num(overview.guard_hits) }}</span>
        </div>
      </div>

      <div class="monitor-grid">
        <section class="card monitor-chart-card">
          <div class="monitor-card-head">
            <span>Token / 请求趋势</span>
            <span class="field-hint">{{ range === "1h" ? "按分钟" : "按小时" }}</span>
          </div>
          <div v-if="!series.length" class="empty-desc" style="padding: 24px 0">暂无调用数据</div>
          <div v-else class="spark-wrap">
            <svg viewBox="0 0 680 120" preserveAspectRatio="none" class="spark">
              <defs>
                <linearGradient id="tokenFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="var(--primary)" stop-opacity="0.28" />
                  <stop offset="100%" stop-color="var(--primary)" stop-opacity="0" />
                </linearGradient>
              </defs>
              <polyline :points="spark()" fill="none" stroke="var(--primary)" stroke-width="2.5" />
              <polyline :points="requestSpark()" fill="none" stroke="#94a3b8" stroke-width="1.4" stroke-dasharray="4 4" />
              <circle v-for="(dot, i) in sparkDots()" :key="i" :cx="dot.x" :cy="dot.y" r="3" fill="var(--primary)" />
            </svg>
            <div class="spark-legend">
              <span><i class="legend-dot is-token"></i>Token</span>
              <span><i class="legend-dot is-request"></i>请求</span>
            </div>
          </div>
        </section>

        <section class="card monitor-chart-card">
          <div class="monitor-card-head"><span>最近 Trace</span><span class="field-hint">点击下钻</span></div>
          <div v-if="!traces.length" class="empty-desc" style="padding: 24px 0">暂无 Trace</div>
          <div v-else class="trace-list">
            <button
              v-for="item in traces.slice(0, 8)"
              :key="item.trace_id"
              type="button"
              class="trace-row"
              @click="openTrace(item)"
            >
              <span class="trace-entry">{{ item.entrypoint }}</span>
              <span class="trace-time">{{ shortTime(item.started_at) }}</span>
              <span class="trace-tokens">{{ num(item.total_tokens) }} tok</span>
              <span class="badge" :class="item.status === 'error' ? 'is-error' : item.cache_hit ? 'is-warn' : 'is-success'">
                {{ item.status === "error" ? "失败" : item.cache_hit ? "缓存" : "成功" }}
              </span>
            </button>
          </div>
        </section>
      </div>

      <section class="card" style="margin-top: 16px">
        <div class="monitor-card-head">
          <span>链路 Trace 列表</span>
          <span class="field-hint">最近 30 条</span>
        </div>
        <div class="table-wrap">
          <table class="table monitor-table">
            <thead>
              <tr><th>时间</th><th>入口</th><th>状态</th><th>Token</th><th>成本</th><th>耗时</th><th>Trace</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in traces" :key="item.trace_id">
                <td>{{ shortTime(item.started_at) }}</td>
                <td>{{ item.entrypoint }}</td>
                <td><span class="badge" :class="item.status === 'error' ? 'is-error' : 'is-success'">{{ item.status }}</span></td>
                <td>{{ num(item.total_tokens) }}</td>
                <td>{{ money(item.cost_amount) }}</td>
                <td>{{ item.total_ms ? `${num(item.total_ms)} ms` : "—" }}</td>
                <td><button type="button" class="btn btn-sm btn-ghost" @click="openTrace(item)">查看</button></td>
              </tr>
              <tr v-if="!traces.length"><td colspan="7" class="field-hint">暂无数据，先发起一次问答</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <Teleport to="body">
      <div v-if="traceOpen" class="trace-overlay" @click.self="traceOpen = false">
        <aside class="trace-drawer" role="dialog" aria-modal="true" aria-label="Trace 详情">
          <header class="trace-drawer-head">
            <div>
              <div class="monitor-kicker">TRACE DETAIL</div>
              <h3>{{ activeTrace?.entrypoint || "Trace" }}</h3>
              <p class="field-hint">{{ activeTrace?.trace_id }} · {{ shortTime(activeTrace?.started_at) }}</p>
            </div>
            <button type="button" class="icon-btn" @click="traceOpen = false">×</button>
          </header>
          <div v-if="traceLoading" class="doc-state"><span class="spinner" /><p>加载链路…</p></div>
          <template v-else-if="activeTrace">
            <div class="trace-summary">
              <span class="badge" :class="activeTrace.status === 'error' ? 'is-error' : 'is-success'">{{ activeTrace.status }}</span>
              <span>{{ num(activeTrace.total_tokens) }} tokens</span>
              <span>{{ money(activeTrace.cost_amount) }}</span>
              <span>{{ activeTrace.total_ms || "—" }} ms</span>
            </div>
            <div class="trace-spans">
              <div v-for="(span, i) in (activeTrace.spans || [])" :key="span.span_id" class="trace-span">
                <span class="trace-span-index">{{ String(i + 1).padStart(2, "0") }}</span>
                <div>
                  <strong>{{ span.kind }} · {{ span.name }}</strong>
                  <p>{{ span.latency_ms || 0 }} ms · {{ num(span.total_tokens) }} tokens · {{ span.status }}</p>
                </div>
              </div>
              <p v-if="!(activeTrace.spans || []).length" class="field-hint">没有 span 明细。</p>
            </div>
          </template>
        </aside>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.monitor-page { max-width: 1320px; }
.monitor-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; flex-wrap: wrap; margin-bottom: 18px; }
.monitor-kicker { font-family: var(--font-mono, monospace); font-size: 10px; letter-spacing: .14em; color: var(--primary); font-weight: 700; }
.monitor-title-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.monitor-title-line h2 { margin: 0; font-size: 22px; }
.monitor-ranges { display: inline-flex; gap: 3px; padding: 3px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface-2); }
.monitor-stats { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.monitor-stat { padding: 13px 15px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); }
.monitor-label { display: block; font-size: 11px; color: var(--muted); }
.monitor-stat b { display: block; margin-top: 7px; font-size: 22px; letter-spacing: -.02em; }
.monitor-stat b small { font-size: 11px; color: var(--muted); font-weight: 500; }
.monitor-sub { display: block; margin-top: 4px; font-size: 10.5px; color: var(--muted); }
.monitor-grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 16px; margin-top: 16px; }
.monitor-chart-card { min-height: 210px; }
.monitor-card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 13px; font-weight: 650; margin-bottom: 8px; }
.spark { width: 100%; height: 150px; overflow: visible; }
.spark-legend { display: flex; gap: 14px; color: var(--muted); font-size: 10.5px; align-items: center; }
.legend-dot { display: inline-block; width: 7px; height: 7px; border-radius: 99px; margin-right: 5px; }
.legend-dot.is-token { background: var(--primary); }
.legend-dot.is-request { background: #94a3b8; }
.trace-list { display: flex; flex-direction: column; gap: 4px; }
.trace-row { display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 8px; border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--text-2); text-align: left; cursor: pointer; font-size: 11px; }
.trace-row:hover { border-color: var(--border); background: var(--surface-2); }
.trace-entry { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-time { color: var(--muted); white-space: nowrap; }
.trace-tokens { color: var(--muted); white-space: nowrap; }
.monitor-table td { font-size: 12px; }
.trace-overlay { position: fixed; inset: 0; z-index: 2100; display: flex; justify-content: flex-end; background: rgba(8,8,12,.42); backdrop-filter: blur(3px); }
.trace-drawer { width: min(620px, 95vw); height: 100%; overflow: auto; padding: 24px; background: var(--surface); border-left: 1px solid var(--border); }
.trace-drawer-head { display: flex; justify-content: space-between; gap: 14px; padding-bottom: 14px; border-bottom: 1px solid var(--border); }
.trace-drawer-head h3 { margin: 5px 0 4px; font-size: 20px; }
.trace-summary { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 16px; font-size: 12px; color: var(--muted); }
.trace-spans { display: flex; flex-direction: column; gap: 8px; margin-top: 18px; }
.trace-span { display: flex; gap: 12px; padding: 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); }
.trace-span-index { font-family: var(--font-mono, monospace); color: var(--primary); font-size: 11px; font-weight: 700; }
.trace-span strong { font-size: 12.5px; }
.trace-span p { margin: 4px 0 0; color: var(--muted); font-size: 11px; }
.doc-state { min-height: 240px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: var(--muted); font-size: 12px; }
@media (max-width: 980px) {
  .monitor-stats { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .monitor-grid { grid-template-columns: 1fr; }
}
@media (max-width: 600px) {
  .monitor-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
