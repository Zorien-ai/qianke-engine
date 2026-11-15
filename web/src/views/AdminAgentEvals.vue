<script setup>
/**
 * A 端 Agent 数据集与评测实验（Phase C MVP）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { getJson, postJson } from "../api";

const loading = ref(true);
const error = ref("");
const datasets = ref([]);
const traces = ref([]);
const experiments = ref([]);
const selectedTraceIds = ref([]);
const datasetName = ref("");
const datasetDescription = ref("");
const creatingDataset = ref(false);
const activeDataset = ref(null);
const datasetLoading = ref(false);
const experimentDatasetId = ref("");
const experimentName = ref("");
const creatingExperiment = ref(false);
const activeExperiment = ref(null);
const experimentLoading = ref(false);
const activeTab = ref("datasets");
let pollTimer = null;

function num(value) { return Number(value || 0).toLocaleString(); }
function ms(value) { const n = Number(value || 0); return n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`; }
function date(value) { return value ? String(value).replace("T", " ").slice(0, 19) : "—"; }
function pct(value) { return `${(Number(value || 0) * 100).toFixed(1)}%`; }
function statusText(status) {
  const map = { QUEUED: "排队中", RUNNING: "运行中", COMPLETED: "已完成", FAILED: "失败", success: "成功", error: "失败" };
  return map[status] || status || "—";
}
function statusClass(status) {
  if (status === "COMPLETED" || status === "success") return "is-ok";
  if (status === "FAILED" || status === "error") return "is-error";
  return "is-running";
}
function toggleTrace(id) {
  const current = selectedTraceIds.value;
  if (current.includes(id)) selectedTraceIds.value = current.filter((x) => x !== id);
  else selectedTraceIds.value = [...current, id];
}
function isTraceSelected(id) { return selectedTraceIds.value.includes(id); }
function toggleAllTraces() {
  if (selectedTraceIds.value.length === traces.value.length) selectedTraceIds.value = [];
  else selectedTraceIds.value = traces.value.map((item) => item.trace_id);
}

async function loadAll() {
  loading.value = true;
  error.value = "";
  try {
    const [ds, tr, ex] = await Promise.all([
      getJson("/api/admin/agent-datasets"),
      getJson("/api/admin/agent-traces?range=7d&limit=30"),
      getJson("/api/admin/agent-experiments"),
    ]);
    datasets.value = ds.items || [];
    traces.value = tr.items || [];
    experiments.value = ex.items || [];
    if (!experimentDatasetId.value && datasets.value.length) {
      experimentDatasetId.value = datasets.value[0].dataset_id;
    }
    maybePoll();
  } catch (e) {
    error.value = e?.detail || e?.message || "Agent 评测数据加载失败";
  } finally {
    loading.value = false;
  }
}

async function refreshExperiments() {
  try {
    const ex = await getJson("/api/admin/agent-experiments");
    experiments.value = ex.items || [];
    if (activeExperiment.value) {
      const current = experiments.value.find((x) => x.experiment_id === activeExperiment.value.experiment_id);
      if (current && current.status !== activeExperiment.value.status) await openExperiment(current.experiment_id);
    }
    maybePoll();
  } catch { /* 保留当前页面 */ }
}

function maybePoll() {
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  if (experiments.value.some((item) => ["QUEUED", "RUNNING"].includes(item.status))) {
    pollTimer = setTimeout(refreshExperiments, 2000);
  }
}

async function createDataset() {
  if (!datasetName.value.trim()) { error.value = "请填写数据集名称"; return; }
  if (!selectedTraceIds.value.length) { error.value = "至少选择一条 Trace"; return; }
  creatingDataset.value = true;
  error.value = "";
  try {
    const data = await postJson("/api/admin/agent-datasets", {
      name: datasetName.value.trim(),
      description: datasetDescription.value.trim(),
      trace_ids: selectedTraceIds.value,
    });
    datasets.value = [data, ...datasets.value];
    datasetName.value = "";
    datasetDescription.value = "";
    selectedTraceIds.value = [];
    if (!experimentDatasetId.value) experimentDatasetId.value = data.dataset_id;
    activeTab.value = "datasets";
  } catch (e) {
    error.value = e?.detail || e?.message || "数据集创建失败";
  } finally {
    creatingDataset.value = false;
  }
}

async function openDataset(datasetId) {
  datasetLoading.value = true;
  activeDataset.value = { dataset_id: datasetId, cases: [] };
  try {
    activeDataset.value = await getJson(`/api/admin/agent-datasets/${encodeURIComponent(datasetId)}`);
  } catch (e) {
    error.value = e?.detail || e?.message || "数据集加载失败";
  } finally {
    datasetLoading.value = false;
  }
}

async function createExperiment() {
  if (!experimentDatasetId.value) { error.value = "请选择数据集"; return; }
  creatingExperiment.value = true;
  error.value = "";
  try {
    const data = await postJson("/api/admin/agent-experiments", {
      dataset_id: experimentDatasetId.value,
      name: experimentName.value.trim(),
    });
    experiments.value = [data, ...experiments.value];
    experimentName.value = "";
    activeTab.value = "experiments";
    maybePoll();
  } catch (e) {
    error.value = e?.detail || e?.message || "实验创建失败";
  } finally {
    creatingExperiment.value = false;
  }
}

async function openExperiment(experimentId) {
  experimentLoading.value = true;
  try {
    activeExperiment.value = await getJson(`/api/admin/agent-experiments/${encodeURIComponent(experimentId)}`);
  } catch (e) {
    error.value = e?.detail || e?.message || "实验详情加载失败";
  } finally {
    experimentLoading.value = false;
  }
}

function closeDataset() { activeDataset.value = null; }
function closeExperiment() { activeExperiment.value = null; }

onMounted(loadAll);
onBeforeUnmount(() => { if (pollTimer) clearTimeout(pollTimer); });
</script>

<template>
  <div class="page agent-evals">
    <header class="admin-hero">
      <div>
        <div class="monitor-kicker">LOCAL LANGSMITH · DATASETS & EXPERIMENTS</div>
        <div class="admin-title-line">
          <h2>Agent 数据集与评测</h2>
          <span class="badge is-primary">Phase C</span>
          <span class="badge is-warn">系统管理员</span>
        </div>
        <p class="card-sub">从真实 Trace 建数据集，运行 Agent 实验并查看逐条结果。评测结果进入本地控制面。</p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="loadAll">刷新</button>
    </header>

    <div class="obs-tabs eval-tabs">
      <button type="button" :class="{ 'is-active': activeTab === 'datasets' }" @click="activeTab = 'datasets'">数据集</button>
      <button type="button" :class="{ 'is-active': activeTab === 'experiments' }" @click="activeTab = 'experiments'">评测实验</button>
    </div>

    <div v-if="error" class="card eval-error"><span>{{ error }}</span><button type="button" class="btn btn-ghost btn-sm" @click="error = ''">关闭</button></div>
    <div v-if="loading" class="card"><div class="skeleton" style="height:120px"></div></div>

    <template v-else-if="activeTab === 'datasets'">
      <section class="card eval-create">
        <div class="admin-section-head"><strong>从 Trace 创建数据集</strong><span class="field-hint">勾选最近 7 天 Agent Trace</span></div>
        <div class="eval-create-grid">
          <label class="eval-field"><span>数据集名称</span><input v-model="datasetName" maxlength="100" placeholder="例如：B 端回归集" /></label>
          <label class="eval-field"><span>描述</span><input v-model="datasetDescription" maxlength="500" placeholder="可选" /></label>
          <button type="button" class="btn btn-primary" :disabled="creatingDataset || !selectedTraceIds.length" @click="createDataset">{{ creatingDataset ? "创建中…" : `创建数据集（${selectedTraceIds.length} 条）` }}</button>
        </div>
        <div class="table-wrap eval-trace-wrap">
          <table class="table eval-trace-table">
            <thead><tr><th class="eval-check"><input type="checkbox" :checked="traces.length && selectedTraceIds.length === traces.length" aria-label="全选 Trace" @change="toggleAllTraces" /></th><th>时间</th><th>问题</th><th>状态</th><th>耗时</th><th>Tools</th></tr></thead>
            <tbody>
              <tr v-for="item in traces" :key="item.trace_id">
                <td class="eval-check"><input type="checkbox" :checked="isTraceSelected(item.trace_id)" @change="toggleTrace(item.trace_id)" /></td>
                <td class="obs-nowrap">{{ date(item.started_at) }}</td>
                <td class="obs-question">{{ item.question || "—" }}</td>
                <td><span class="obs-status" :class="statusClass(item.status)">{{ statusText(item.status) }}</span></td>
                <td class="obs-nowrap">{{ ms(item.total_ms) }}</td>
                <td>{{ num(item.tool_call_count) }}</td>
              </tr>
              <tr v-if="!traces.length"><td colspan="6" class="field-hint">最近没有 Agent Trace</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card eval-list-card">
        <div class="admin-section-head"><strong>数据集</strong><span class="field-hint">共 {{ datasets.length }} 个</span></div>
        <div v-if="!datasets.length" class="empty-state"><div class="empty-title">还没有数据集</div><div class="empty-desc">从上方选择 Trace 创建第一个数据集。</div></div>
        <div v-else class="eval-dataset-grid">
          <button v-for="ds in datasets" :key="ds.dataset_id" type="button" class="eval-dataset-card" @click="openDataset(ds.dataset_id)">
            <strong>{{ ds.name }}</strong>
            <span>{{ ds.description || "无描述" }}</span>
            <small>{{ num(ds.case_count) }} 个用例 · {{ ds.created_by || "—" }} · {{ date(ds.created_at) }}</small>
          </button>
        </div>
      </section>
    </template>

    <template v-else>
      <section class="card eval-create">
        <div class="admin-section-head"><strong>运行评测实验</strong><span class="field-hint">对数据集逐条运行 Agent，按状态/关键词/工具判定通过</span></div>
        <div class="eval-create-grid">
          <label class="eval-field"><span>数据集</span>
            <select v-model="experimentDatasetId">
              <option value="">选择数据集</option>
              <option v-for="ds in datasets" :key="ds.dataset_id" :value="ds.dataset_id">{{ ds.name }}（{{ num(ds.case_count) }} 条）</option>
            </select>
          </label>
          <label class="eval-field"><span>实验名称</span><input v-model="experimentName" maxlength="100" placeholder="可选" /></label>
          <button type="button" class="btn btn-primary" :disabled="creatingExperiment || !experimentDatasetId" @click="createExperiment">{{ creatingExperiment ? "创建中…" : "开始评测" }}</button>
        </div>
        <p class="field-hint">实验会调用真实 Agent，耗时取决于用例数量；结果逐条落库。</p>
      </section>

      <section class="card eval-list-card">
        <div class="admin-section-head"><strong>实验记录</strong><span class="field-hint">运行中的实验每 2 秒刷新</span></div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>实验</th><th>数据集</th><th>状态</th><th>通过</th><th>成功率</th><th>创建时间</th></tr></thead>
            <tbody>
              <tr v-for="exp in experiments" :key="exp.experiment_id" class="eval-row" @click="openExperiment(exp.experiment_id)">
                <td><strong>{{ exp.name }}</strong><br /><small class="field-hint">{{ exp.experiment_id }}</small></td>
                <td class="field-hint">{{ exp.dataset_id }}</td>
                <td><span class="obs-status" :class="statusClass(exp.status)">{{ statusText(exp.status) }}</span></td>
                <td>{{ num(exp.passed_cases) }} / {{ num(exp.total_cases) }}</td>
                <td>{{ exp.total_cases ? pct(exp.passed_cases / exp.total_cases) : "—" }}</td>
                <td class="obs-nowrap">{{ date(exp.created_at) }}</td>
              </tr>
              <tr v-if="!experiments.length"><td colspan="6" class="field-hint">还没有实验</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <div v-if="activeDataset" class="obs-detail-mask" @click.self="closeDataset">
      <aside class="obs-detail" role="dialog" aria-modal="true" aria-labelledby="dataset-detail-title">
        <header class="obs-detail-head">
          <div><div class="monitor-kicker">DATASET</div><h3 id="dataset-detail-title">{{ activeDataset.name }}</h3></div>
          <button type="button" class="obs-close" aria-label="关闭数据集" @click="closeDataset">×</button>
        </header>
        <p class="card-sub">{{ activeDataset.description || "无描述" }} · {{ activeDataset.case_count || 0 }} 个用例</p>
        <div v-if="datasetLoading" class="skeleton" style="height:120px"></div>
        <ol v-else class="eval-case-list">
          <li v-for="(c, idx) in activeDataset.cases || []" :key="c.case_id">
            <b>{{ idx + 1 }}. {{ c.question }}</b>
            <p v-if="c.expected_answer" class="field-hint">期望：{{ c.expected_answer }}</p>
            <p v-else class="field-hint">未设置期望答案（按 Agent 完成状态判定）</p>
          </li>
        </ol>
      </aside>
    </div>

    <div v-if="activeExperiment" class="obs-detail-mask" @click.self="closeExperiment">
      <aside class="obs-detail obs-experiment" role="dialog" aria-modal="true" aria-labelledby="experiment-title">
        <header class="obs-detail-head">
          <div><div class="monitor-kicker">EXPERIMENT</div><h3 id="experiment-title">{{ activeExperiment.name }}</h3></div>
          <button type="button" class="obs-close" aria-label="关闭实验" @click="closeExperiment">×</button>
        </header>
        <div v-if="experimentLoading" class="skeleton" style="height:120px"></div>
        <template v-else>
          <div class="obs-detail-meta">
            <div><span>状态</span><b class="obs-status" :class="statusClass(activeExperiment.status)">{{ statusText(activeExperiment.status) }}</b></div>
            <div><span>用例</span><b>{{ num(activeExperiment.total_cases) }}</b></div>
            <div><span>通过</span><b>{{ num(activeExperiment.passed_cases) }}</b></div>
            <div><span>成功率</span><b>{{ pct((activeExperiment.metrics || {}).success_rate || 0) }}</b></div>
            <div><span>平均耗时</span><b>{{ ms((activeExperiment.metrics || {}).avg_latency_ms) }}</b></div>
          </div>
          <p v-if="activeExperiment.error" class="field-hint">{{ activeExperiment.error }}</p>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>用例</th><th>状态</th><th>通过</th><th>耗时</th><th>Tokens</th><th>回答</th></tr></thead>
              <tbody>
                <tr v-for="r in activeExperiment.results || []" :key="r.result_id">
                  <td class="obs-question">{{ r.question || r.case_id }}</td>
                  <td>{{ statusText(r.status) }}</td>
                  <td><span class="obs-status" :class="r.passed ? 'is-ok' : 'is-error'">{{ r.passed ? "通过" : "失败" }}</span></td>
                  <td class="obs-nowrap">{{ ms(r.latency_ms) }}</td>
                  <td>{{ num(r.total_tokens) }}</td>
                  <td class="eval-answer">{{ r.answer || r.error || "—" }}</td>
                </tr>
                <tr v-if="!(activeExperiment.results || []).length"><td colspan="6" class="field-hint">暂无结果</td></tr>
              </tbody>
            </table>
          </div>
        </template>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.obs-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); }
.obs-tabs button { padding: 7px 11px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); font-size: 12px; cursor: pointer; }
.obs-tabs button.is-active { border-bottom-color: var(--primary); color: var(--text); }
.obs-status { display: inline-flex; align-items: center; padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.obs-status.is-ok { color: #166534; background: #e8f5ec; }
.obs-status.is-error { color: #991b1b; background: #fdeaea; }
.obs-status.is-running { color: #92400e; background: #fef3c7; }
.obs-nowrap { white-space: nowrap; }
.obs-question { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.obs-detail-mask { position: fixed; inset: 0; z-index: 80; display: flex; justify-content: flex-end; overflow: hidden; background: rgba(15, 23, 42, .34); }
.obs-detail { width: min(620px, 94vw); height: 100vh; overflow-y: auto; padding: 22px; border-left: 1px solid var(--border); background: var(--surface); box-shadow: -12px 0 36px rgba(15, 23, 42, .14); }
.obs-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.obs-detail-head h3 { margin: 5px 0 0; font-size: 18px; line-height: 1.4; }
.obs-close { flex: 0 0 auto; width: 32px; height: 32px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); color: var(--text); font-size: 20px; line-height: 1; cursor: pointer; }
.obs-detail-meta { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin-top: 16px; }
.obs-detail-meta > div { padding: 10px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); }
.obs-detail-meta span { display: block; color: var(--muted); font-size: 10.5px; }
.obs-detail-meta b { display: block; margin-top: 4px; font-size: 14px; }
.obs-experiment { width: min(900px, 96vw); }
.eval-tabs { margin: 14px 0 0; }
.eval-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; color: #991b1b; background: #fff7f7; border-color: #fecaca; }
.eval-create, .eval-list-card { margin-top: 14px; }
.eval-create-grid { display: flex; align-items: flex-end; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
.eval-field { display: flex; flex-direction: column; gap: 4px; min-width: 180px; flex: 1; }
.eval-field span { color: var(--muted); font-size: 11px; }
.eval-field input, .eval-field select { height: 34px; padding: 0 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); font-size: 13px; }
.eval-trace-wrap { max-height: 320px; overflow: auto; margin-top: 12px; }
.eval-trace-table { min-width: 760px; }
.eval-check { width: 28px; text-align: center; }
.eval-check input { width: 14px; height: 14px; accent-color: var(--primary); }
.eval-dataset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; margin-top: 12px; }
.eval-dataset-card { display: flex; flex-direction: column; gap: 5px; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); text-align: left; cursor: pointer; }
.eval-dataset-card strong { font-size: 13px; }
.eval-dataset-card span { color: var(--text-2); font-size: 12px; }
.eval-dataset-card small { color: var(--muted); font-size: 10.5px; }
.eval-row { cursor: pointer; }
.eval-row:hover td { background: var(--surface-2); }
.eval-case-list { margin: 0; padding: 0; list-style: none; display: grid; gap: 10px; }
.eval-case-list li { padding: 10px 12px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface-2); }
.eval-case-list b { font-size: 12.5px; }
.eval-case-list p { margin: 4px 0 0; font-size: 11px; }
.obs-experiment { width: min(900px, 96vw); }
.eval-answer { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 900px) {
  .obs-detail-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  .obs-detail { width: 100vw; padding: 16px; }
  .eval-create-grid { align-items: stretch; }
  .eval-field { min-width: 100%; }
  .eval-field input, .eval-field select, .eval-create-grid .btn { width: 100%; }
  .eval-answer { max-width: 160px; }
}
</style>
