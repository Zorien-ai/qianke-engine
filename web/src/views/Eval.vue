<script setup>
/**
 * 企业侧离线评测：
 * 1) 上传 QA 题库（当前数据空间）
 * 2) 后台运行 RAG 链路 + LLM-as-a-Judge
 * 3) 展示通过率 / 分模块 / 失败题
 *
 * dataset 不从前端传：后端由登录账号推导，企业只能评自己的 ent_* 空间，
 * 系统管理员走 demo 基线。页面只负责当前数据空间。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { getJson, postJson } from "../api";
import { toast, toastError } from "../store";

const loading = ref(true);
const loadError = ref("");
const setsInfo = ref({ sets: [], dataset: "", scope: "enterprise", judge_model: "deepseek-chat" });
const latest = ref(null);
const selectedSet = ref("");
const uploading = ref(false);
const starting = ref(false);
const fileInput = ref(null);
let pollTimer = null;

const sets = computed(() => setsInfo.value.sets || []);
const run = computed(() => (latest.value && latest.value.run) || null);
const summary = computed(() => (latest.value && latest.value.summary) || null);
const modules = computed(() => (latest.value && latest.value.modules) || []);
const failures = computed(() => (latest.value && latest.value.failures) || []);
const isRunning = computed(() => run.value && ["running", "queued"].includes(run.value.status));
const canStart = computed(() => !isRunning.value && !!selectedSet.value && !starting.value);

const boundary = computed(() => {
  const row = modules.value.find((m) => m.module && m.module.includes("边界"));
  return row ? `${row.passed}/${row.judged}` : "—";
});
const scopeLabel = computed(() => (setsInfo.value.scope === "platform" ? "平台基线" : "企业数据空间"));

function pct(value) {
  if (value === null || value === undefined) return "—";
  return `${(Number(value) * 100).toFixed(1)}%`;
}
function num(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString();
}
function setLabel(set) {
  return `${set.name} · ${set.count} 题`;
}
function statusLabel(status) {
  return {
    running: "评测中",
    queued: "排队中",
    completed: "已完成",
    failed: "失败",
    interrupted: "已中断",
  }[status] || status || "—";
}
function statusClass(status) {
  if (status === "completed") return "is-success";
  if (status === "running" || status === "queued") return "is-primary";
  if (status === "failed") return "is-danger";
  return "is-warn";
}

async function loadAll() {
  loadError.value = "";
  try {
    const [setsData, latestData] = await Promise.all([
      getJson("/api/eval/question-sets"),
      getJson("/api/eval/runs/latest"),
    ]);
    setsInfo.value = setsData;
    latest.value = latestData;
    if (!selectedSet.value && sets.value.length) selectedSet.value = sets.value[0].id;
    schedulePoll();
  } catch (e) {
    loadError.value = e && (e.detail || e.message) ? e.detail || e.message : "评测数据加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadLatest(silent = true) {
  try {
    latest.value = await getJson("/api/eval/runs/latest");
    schedulePoll();
  } catch (e) {
    if (!silent) toastError(e);
  }
}

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = null;
  if (isRunning.value) {
    pollTimer = setTimeout(() => loadLatest(true), 2000);
  }
}

function pickFile() {
  if (fileInput.value) fileInput.value.click();
}

async function onFile(event) {
  const file = event.target.files && event.target.files[0];
  event.target.value = "";
  if (!file) return;
  uploading.value = true;
  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    const questions = Array.isArray(parsed) ? parsed : parsed && parsed.questions;
    if (!Array.isArray(questions) || !questions.length) {
      throw new Error("JSON 必须是非空数组，或包含 questions 数组");
    }
    const resp = await postJson("/api/eval/question-sets", {
      name: file.name.replace(/\.json$/i, "").slice(0, 80),
      questions,
    });
    setsInfo.value.sets = [resp.set, ...sets.value];
    selectedSet.value = resp.set.id;
    toast(`题库已上传：${resp.set.count} 题`, "success");
  } catch (e) {
    toast(e && e.detail ? e.detail : e.message || "题库上传失败", "error", 5200);
  } finally {
    uploading.value = false;
  }
}

async function startRun() {
  if (!selectedSet.value || starting.value) return;
  starting.value = true;
  try {
    const resp = await postJson("/api/eval/runs", { set_id: selectedSet.value });
    latest.value = { ...(latest.value || {}), run: resp.run, summary: null, modules: [], failures: [] };
    toast("评测已启动，正在后台运行", "info");
    schedulePoll();
  } catch (e) {
    toastError(e);
  } finally {
    starting.value = false;
  }
}

function downloadTemplate() {
  const template = [
    {
      id: "BIZ-001",
      module: "运营/市场",
      question: "高客单、喜欢美妆的女性用户有哪些？",
      acceptance: "引用高客单定义，并列出符合条件的用户与客单价",
      expect_sources: ["user_profile", "tag_definitions.md"],
    },
  ];
  const blob = new Blob([JSON.stringify(template, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "qianke-eval-template.json";
  a.click();
  URL.revokeObjectURL(url);
}

onMounted(loadAll);
onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer);
});
</script>

<template>
  <div class="page eval-page">
    <div v-if="loading" class="card">
      <div class="skeleton" style="height: 26px; width: 30%"></div>
      <div class="skeleton" style="height: 90px; margin-top: 16px"></div>
    </div>

    <div v-else-if="loadError" class="card">
      <div class="empty-state">
        <div class="empty-emoji">🧪</div>
        <div class="empty-title">离线评测加载失败</div>
        <div class="empty-desc">{{ loadError }}</div>
        <button type="button" class="btn btn-primary" @click="loadAll">重试</button>
      </div>
    </div>

    <template v-else>
      <div class="eval-hero">
        <div>
          <div class="eval-kicker">EVAL-DRIVEN DEVELOPMENT</div>
          <div class="eval-title-line">
            <h2>离线评测</h2>
            <span class="badge is-primary">{{ setsInfo.dataset }}</span>
            <span class="badge" :class="setsInfo.scope === 'platform' ? 'is-warn' : 'is-success'">
              {{ scopeLabel }}
            </span>
          </div>
          <p class="card-sub eval-sub">
            上传 QA 题库，在<strong>当前数据空间</strong>跑真实 RAG/SQL 链路，再由 LLM-as-a-Judge
            按 acceptance 判分。题库和结果按数据空间隔离，不跨企业复用。
          </p>
        </div>
        <div class="row-actions">
          <button type="button" class="btn btn-ghost" :disabled="uploading" @click="downloadTemplate">
            下载题库模板
          </button>
          <button type="button" class="btn btn-primary" :disabled="uploading" @click="pickFile">
            <span v-if="uploading" class="spinner spinner-sm" />
            {{ uploading ? "上传中…" : "上传 QA 题库" }}
          </button>
          <button type="button" class="btn btn-ghost" @click="loadAll">刷新</button>
        </div>
      </div>

      <input
        id="eval-file"
        ref="fileInput"
        name="eval-file"
        type="file"
        accept=".json,application/json"
        aria-label="上传 QA 题库文件"
        hidden
        @change="onFile"
      />

      <!-- 题库 + 发起评测 -->
      <section class="card eval-start-card">
        <div class="card-title">
          <span class="dot"></span>评测任务
          <span class="badge">{{ sets.length }} 个题库</span>
          <span class="spacer"></span>
          <span class="card-sub">裁判：{{ setsInfo.judge_model }}</span>
        </div>

        <div v-if="!sets.length" class="empty-state eval-empty">
          <div class="empty-emoji">📋</div>
          <div class="empty-title">还没有这个数据空间的评测题库</div>
          <div class="empty-desc">
            上传一个 QA JSON 开始。每个企业 / 数据空间单独维护题库和结果，不使用 demo 的 33 题。
          </div>
          <div class="row-actions" style="justify-content: center">
            <button type="button" class="btn btn-primary" @click="pickFile">上传 QA 题库</button>
            <button type="button" class="btn btn-ghost" @click="downloadTemplate">下载模板</button>
          </div>
          <pre class="eval-template">[
  {
    "id": "BIZ-001",
    "module": "运营/市场",
    "question": "高客单、喜欢美妆的女性用户有哪些？",
    "acceptance": "引用高客单定义，并列出符合条件的用户与客单价",
    "expect_sources": ["user_profile", "tag_definitions.md"]
  }
]</pre>
        </div>

        <template v-else>
          <div class="eval-start-row">
            <label class="eval-field">
              <span>选择题库</span>
              <select id="eval-set" name="eval-set" v-model="selectedSet" class="select" :disabled="isRunning">
                <option v-for="set in sets" :key="set.id" :value="set.id">{{ setLabel(set) }}</option>
              </select>
            </label>
            <button type="button" class="btn btn-primary" :disabled="!canStart" @click="startRun">
              <span v-if="starting" class="spinner spinner-sm" />
              {{ starting ? "启动中…" : isRunning ? "评测运行中…" : "开始评测" }}
            </button>
            <span class="field-hint">单次最多 50 题；结果保存到当前数据空间</span>
          </div>

          <div v-if="run && isRunning" class="eval-running">
            <div class="eval-running-head">
              <span class="status-dot is-running"></span>
              <strong>{{ statusLabel(run.status) }}</strong>
              <span class="field-hint">{{ run.phase }}</span>
              <span class="spacer"></span>
              <span class="eval-progress-text">{{ Math.round((run.progress || 0) * 100) }}%</span>
            </div>
            <div class="progress progress-lg">
              <div class="progress-fill" :style="{ width: `${Math.max(2, (run.progress || 0) * 100)}%` }"></div>
            </div>
            <p class="field-hint" style="margin-top: 8px">
              {{ run.current || 0 }} / {{ run.total || 0 }} 题 · 可以离开页面，回来会继续显示进度
            </p>
          </div>

          <div v-else-if="run && run.status === 'failed'" class="alert is-error" style="margin-top: 14px">
            <strong>评测失败：</strong>{{ run.error || "未知错误" }}
          </div>
          <div v-else-if="run && run.status === 'interrupted'" class="alert is-warn" style="margin-top: 14px">
            <strong>任务已中断：</strong>{{ run.error || "服务重启后任务未完成，请重新发起评测" }}
          </div>
        </template>
      </section>

      <!-- 结果 -->
      <template v-if="run && run.status === 'completed'">
        <div class="stat-grid">
          <div class="stat-card">
            <div class="stat-value eval-accent">{{ pct(summary && summary.pass_rate) }}</div>
            <div class="stat-label">通过率</div>
            <div class="stat-extra">{{ num(summary && summary.passed) }} / {{ num(summary && summary.judged) }} 题成功判定</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ pct(summary && summary.coverage) }}</div>
            <div class="stat-label">判定覆盖率</div>
            <div class="stat-extra">{{ num(run.total) }} 题 · 裁判异常 {{ num(summary && summary.judge_errors) }}</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ boundary }}</div>
            <div class="stat-label">边界题</div>
            <div class="stat-extra">安全边界通过 / 已判定</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ pct(summary && summary.source_recall_avg) }}</div>
            <div class="stat-label">来源召回</div>
            <div class="stat-extra">{{ summary && summary.source_cases ? `${summary.source_cases} 题有期望来源` : "无期望来源" }}</div>
          </div>
        </div>

        <section class="card">
          <div class="card-title">
            <span class="dot"></span>分模块通过率
            <span class="spacer"></span>
            <span class="card-sub">题库：{{ run.set_name }} · 耗时 {{ run.elapsed_s ?? "—" }}s</span>
          </div>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>模块</th>
                  <th class="num">题数</th>
                  <th class="num">已判定</th>
                  <th class="num">通过</th>
                  <th class="num">通过率</th>
                  <th class="num">来源召回</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in modules" :key="row.module">
                  <td>{{ row.module }}</td>
                  <td class="num">{{ row.total }}</td>
                  <td class="num">{{ row.judged }}</td>
                  <td class="num">{{ row.passed }}</td>
                  <td class="num">
                    <span class="badge" :class="row.pass_rate >= 0.85 ? 'is-success' : row.pass_rate >= 0.6 ? 'is-warn' : 'is-danger'">
                      {{ pct(row.pass_rate) }}
                    </span>
                  </td>
                  <td class="num">{{ pct(row.recall) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="card">
          <div class="card-title">
            <span class="dot"></span>失败与异常题目
            <span class="badge" :class="failures.length ? 'is-warn' : 'is-success'">{{ failures.length }} 题</span>
            <span class="spacer"></span>
            <span class="card-sub">包含 0 分、裁判异常、回答异常</span>
          </div>
          <div v-if="!failures.length" class="empty-state" style="padding: 28px 10px">
            <div class="empty-emoji">✅</div>
            <div class="empty-desc">这次没有失败或异常题目。</div>
          </div>
          <div v-else class="eval-failures">
            <article v-for="item in failures" :key="item.id" class="eval-failure">
              <div class="eval-failure-head">
                <span class="badge is-primary">{{ item.id }}</span>
                <span class="badge">{{ item.module || "未分类" }}</span>
                <span class="spacer"></span>
                <span class="badge" :class="item.answer_error ? 'is-danger' : item.judge_error ? 'is-warn' : 'is-danger'">
                  {{ item.answer_error ? "回答异常" : item.judge_error ? "裁判异常" : "未通过" }}
                </span>
              </div>
              <div class="eval-question">{{ item.question }}</div>
              <div class="eval-acceptance">验收：{{ item.acceptance }}</div>
              <div v-if="item.judge_reason" class="eval-reason">裁判：{{ item.judge_reason }}</div>
              <div v-if="item.answer_error" class="eval-reason">回答异常：{{ item.answer_error }}</div>
              <div v-if="item.judge_error" class="eval-reason">裁判异常：{{ item.judge_error }}</div>
              <details class="eval-detail">
                <summary>查看回答与来源</summary>
                <pre>{{ item.answer_excerpt || "（无回答）" }}</pre>
                <div class="eval-sources">
                  <span>期望来源：{{ (item.expect_sources || []).join("、") || "—" }}</span>
                  <span>实际来源：{{ (item.actual_sources || []).join("、") || "—" }}</span>
                  <span>来源召回：{{ pct(item.source_recall && item.source_recall.recall) }}</span>
                </div>
              </details>
            </article>
          </div>
        </section>

        <section class="eval-meta card">
          <div>
            <strong>{{ run.set_name }}</strong>
            <span class="field-hint">
              {{ run.started_at }} → {{ run.finished_at }} ·
              裁判 {{ run.judge_model }} · 数据集 {{ run.dataset }}
            </span>
          </div>
          <span class="badge is-success">已完成</span>
        </section>
      </template>

      <section v-else-if="!isRunning && sets.length" class="card">
        <div class="empty-state" style="padding: 28px 10px">
          <div class="empty-emoji">🌱</div>
          <div class="empty-title">还没有评测结果</div>
          <div class="empty-desc">选择题库并点击「开始评测」，结果会保存到当前数据空间。</div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.eval-page { display: flex; flex-direction: column; gap: 16px; }
.eval-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; flex-wrap: wrap; }
.eval-kicker { font-family: var(--of-mono, monospace); font-size: 11px; letter-spacing: 0.16em; color: var(--primary); font-weight: 650; }
.eval-title-line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 6px; }
.eval-title-line h2 { font-size: 22px; }
.eval-sub { margin-top: 8px; max-width: 820px; line-height: 1.65; }
.eval-start-card { padding-bottom: 18px; }
.eval-start-row { display: flex; align-items: flex-end; gap: 14px; flex-wrap: wrap; margin-top: 6px; }
.eval-field { display: flex; flex-direction: column; gap: 6px; min-width: 280px; max-width: 440px; flex: 1; }
.eval-field > span { font-size: 12px; color: var(--muted); font-weight: 600; }
.eval-running { margin-top: 16px; padding: 14px 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface-2); }
.eval-running-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.eval-progress-text { font-variant-numeric: tabular-nums; font-weight: 700; color: var(--primary); }
.eval-accent { color: var(--primary); }
.eval-empty { padding: 30px 10px; }
.eval-template { max-width: 680px; margin: 16px auto 0; padding: 14px 16px; text-align: left; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--line); font-size: 12px; line-height: 1.6; overflow: auto; color: var(--text-2); }
.eval-failures { display: flex; flex-direction: column; gap: 12px; }
.eval-failure { padding: 14px 16px; border: 1px solid var(--line); border-radius: 12px; background: var(--surface-2); }
.eval-failure-head { display: flex; align-items: center; gap: 8px; }
.eval-question { margin-top: 10px; font-size: 14px; font-weight: 600; line-height: 1.5; }
.eval-acceptance { margin-top: 6px; font-size: 12.5px; color: var(--muted); line-height: 1.6; }
.eval-reason { margin-top: 8px; font-size: 12.5px; color: var(--danger); line-height: 1.6; }
.eval-detail { margin-top: 10px; font-size: 12.5px; color: var(--text-2); }
.eval-detail summary { cursor: pointer; color: var(--primary); font-weight: 600; }
.eval-detail pre { margin-top: 8px; padding: 10px 12px; border-radius: 8px; background: var(--surface); border: 1px solid var(--line); white-space: pre-wrap; word-break: break-word; max-height: 240px; overflow: auto; font-family: inherit; font-size: 12px; line-height: 1.55; }
.eval-sources { display: flex; flex-direction: column; gap: 3px; margin-top: 8px; color: var(--muted); }
.eval-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.eval-meta .field-hint { display: block; margin-top: 4px; }
@media (max-width: 720px) {
  .eval-hero { flex-direction: column; }
  .eval-start-row { align-items: stretch; }
  .eval-field { min-width: 0; }
}
</style>
