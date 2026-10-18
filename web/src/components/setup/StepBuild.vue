<script setup>
/**
 * 第 3 步：构建索引（第五轮：增量更新 / 覆盖重建）。
 *
 * 进入本步先 GET /api/wizard/plan?upload_id=：
 *   - 「追加更新」默认选中，只处理新增/变更文件，已有用户不受影响；
 *     can_incremental=false 时禁用并展示 incremental_block_reason；
 *   - 「覆盖重建」会清空全量重算，点开始先弹二次确认（明确代价 + 建议追加 + 可离开页面）。
 *
 * POST /api/wizard/build 只传 {upload_id, fields, mode}：数据集由登录账号推导（红线）。
 * 轮询固定 3000ms；总进度与五步进度条用 transform: scaleX + CSS transition（GPU），
 * 不再用 rAF 逐帧改 width / setState。
 *
 * 构建任务号写 localStorage：离开页面后回来，由 Setup 先查 /api/wizard/build/active
 * 把任务交回本组件继续轮询（initialTask）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { getJson, postJson } from "../../api";
import { toast } from "../../store";
import {
  clearBuildTaskId,
  freshnessText,
  humanizeStatusText,
  readBuildTaskId,
  writeBuildTaskId,
} from "../../lib/wizardCache";

const POLL_INTERVAL_MS = 3000;

const props = defineProps({
  uploadId: { type: String, required: true },
  fields: { type: Object, required: true },
  summary: { type: Object, default: () => ({}) },
  // 本次会话里上一次已完成构建的结果（重新进入第 3 步时展示，不重复构建）
  previousResult: { type: Object, default: null },
  // 从 /api/wizard/build/active 恢复的进行中任务（由 Setup 传入）
  initialTask: { type: Object, default: null },
});

const emit = defineEmits(["back", "done", "running", "ask"]);

/* ---------- 构建计划 / 模式 ---------- */
const plan = ref(null);
const planLoading = ref(false);
const planError = ref("");
const mode = ref("incremental"); // incremental | full
const confirmOpen = ref(false);
const confirmBtn = ref(null);

const planStats = computed(() => {
  const p = plan.value;
  if (!p) return null;
  return {
    newCsv: Number(p.new_csv_count) || 0,
    newMd: Number(p.new_md_count) || 0,
    changedMd: Number(p.changed_md_count) || 0,
    skippedChangedCsv: p.skipped_changed_csv || [],
    existing: p.existing || {},
    seededFrom: (p.manifest && p.manifest.seeded_from) || null,
  };
});
const hasNewFiles = computed(() => {
  const s = planStats.value;
  return !!s && s.newCsv + s.newMd + s.changedMd > 0;
});
// can_incremental 是后端给的「有基线、可增量」；前端还要叠加「本批确实有新增文件」，
// 否则点下去必然 400（后端不让空转），不如在入口就禁用并说清楚。
const canIncremental = computed(
  () => !!(plan.value && plan.value.can_incremental) && hasNewFiles.value
);
const incrementalReason = computed(() => {
  if (planError.value) return "暂时读不到构建计划，本次只能选择「覆盖重建」。";
  if (plan.value && !plan.value.can_incremental) {
    return plan.value.incremental_block_reason || "当前批次无法追加更新，请选择覆盖重建。";
  }
  if (plan.value && !hasNewFiles.value) {
    return "本批次没有新增文件可追加；要重算全部数据请选「覆盖重建」。";
  }
  return "";
});
const planHint = computed(() => {
  if (plan.value && plan.value.hint) return plan.value.hint;
  if (!planStats.value) return "";
  const s = planStats.value;
  const users = Number(s.existing.profiles);
  const base = `本次新增 ${s.newCsv} 个 CSV、${s.newMd} 篇文档`;
  return Number.isFinite(users) && users > 0
    ? `${base}；已有 ${users.toLocaleString()} 个用户不受影响`
    : base;
});

function fmtDuration(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n <= 0) return "";
  if (n < 60) return `${Math.round(n)} 秒`;
  if (n < 3600) return `${Math.round(n / 60)} 分钟`;
  const hours = Math.floor(n / 3600);
  const minutes = Math.round((n % 3600) / 60);
  return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
}

function fmtNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString() : "—";
}

const existingSummary = computed(() => {
  const e = (plan.value && plan.value.existing) || {};
  return {
    profiles: Number(e.profiles) || 0,
    docs: Number(e.docs) || 0,
    chunks: Number(e.chunks) || 0,
    builtAt: e.built_at || "",
    lastMode: e.last_mode || "",
    lastElapsed: e.last_elapsed_s,
    lastRows: e.last_rows,
    lastFullElapsed: e.last_full_elapsed_s,
    hasData: Number(e.profiles) > 0 || Number(e.docs) > 0 || Number(e.chunks) > 0,
  };
});

const fullTimeText = computed(() => {
  const e = existingSummary.value;
  if (!e.lastFullElapsed) return "";
  const rows = e.lastRows ? `，${fmtNumber(e.lastRows)} 行` : "";
  return `上次全量构建用时 ${fmtDuration(e.lastFullElapsed)}${rows}`;
});

const lastModeLabel = computed(() => {
  const m = existingSummary.value.lastMode;
  if (m === "incremental") return "追加更新";
  if (m === "full") return "覆盖重建";
  return "";
});

/* ---------- 任务状态 ---------- */
const starting = ref(false);
const taskId = ref("");
const status = ref(props.previousResult ? "done" : "idle"); // idle|running|done|failed|expired
const task = ref(null);
const percent = ref(props.previousResult ? 100 : 0);
const steps = ref([]);
const note = ref((props.previousResult && props.previousResult.note) || "");
const errorText = ref("");
const startedAt = ref(0);
const elapsedSec = ref(0);

let pollTimer = null;
let tickTimer = null;

const isRunning = computed(() => status.value === "running");
const isDone = computed(() => status.value === "done");
const isFailed = computed(() => status.value === "failed");

const currentMode = computed(() => (task.value && task.value.mode) || mode.value);
const currentModeLabel = computed(() =>
  currentMode.value === "incremental" ? "追加更新" : "覆盖重建"
);

const stepProgress = computed(() => {
  const list = steps.value || [];
  return {
    done: list.filter((s) => s.status === "done" || s.status === "skipped").length,
    total: list.length,
  };
});

const result = computed(() => {
  if (task.value && task.value.result) return task.value.result;
  if (props.previousResult && props.previousResult.result) return props.previousResult.result;
  return null;
});

const doneNote = computed(() => {
  const raw =
    note.value ||
    (props.previousResult && props.previousResult.note) ||
    "构建完成，可以开始提问了。";
  return humanizeStatusText(raw);
});

const resultMode = computed(() => {
  const r = result.value;
  return (r && r.mode) || currentMode.value;
});

const LEVEL_SOURCE_LABEL = {
  user: "你的会员等级列",
  derived: "按金额自动推导（旧版本行为）",
  none: "数据未提供（不推算）",
};

const resultRows = computed(() => {
  const r = result.value;
  if (!r) return [];
  const rows = [];
  const incremental = resultMode.value === "incremental";

  rows.push({
    label: "构建模式",
    value: incremental ? "追加更新" : "覆盖重建",
  });

  if (incremental) {
    rows.push({
      label: "本次更新用户",
      value: `新增 ${fmtNumber(r.profiles_new || 0)} · 更新 ${fmtNumber(r.profiles_updated ?? r.profiles ?? 0)}`,
    });
    rows.push({ label: "新增数据行", value: `${fmtNumber(r.rows_incremental ?? 0)} 行` });
    const docsChanged = Number(r.docs_new || 0) + Number(r.docs_updated || 0);
    if (docsChanged) rows.push({ label: "文档新增/更新", value: `${fmtNumber(docsChanged)} 篇` });
  } else {
    rows.push({
      label: "用户画像",
      value:
        r.profiles == null
          ? "本次未重建（保留上一批）"
          : `${fmtNumber(r.profiles)} 个用户`,
    });
    rows.push({ label: "交易行数", value: `${fmtNumber(r.rows || 0)} 行` });
  }

  rows.push({ label: "索引条数", value: `${fmtNumber(r.index_total || 0)} 条` });

  if (r.freshness) {
    rows.push({
      label: "数据状态",
      value: freshnessText(r.freshness),
      title: `技术值：${r.freshness}`,
    });
  }
  if (r.elapsed_s != null) rows.push({ label: "构建用时", value: fmtDuration(r.elapsed_s) || `${r.elapsed_s}s` });
  if (r.member_level_source) {
    rows.push({
      label: "会员等级来源",
      value: LEVEL_SOURCE_LABEL[r.member_level_source] || r.member_level_source,
    });
  }
  if (r.skipped_changed_csv && r.skipped_changed_csv.length) {
    rows.push({
      label: "跳过的同名 CSV",
      value: r.skipped_changed_csv.join("、"),
      title: "同名 CSV 内容已变化，追加会重复累加，已跳过；请改名或改用覆盖重建",
    });
  }
  return rows;
});

const startDisabled = computed(
  () =>
    starting.value ||
    isRunning.value ||
    !props.uploadId ||
    planLoading.value ||
    (mode.value === "incremental" && !canIncremental.value)
);
const startHint = computed(() => {
  if (planLoading.value) return "正在读取构建计划…";
  if (mode.value === "incremental") {
    return canIncremental.value
      ? "只处理新增/变更文件，已有用户不受影响"
      : incrementalReason.value;
  }
  return fullTimeText.value || "会清空现有数据并全量重算";
});

/* ---------- 计划加载 ---------- */
async function loadPlan() {
  if (!props.uploadId) return;
  planLoading.value = true;
  planError.value = "";
  try {
    const data = await getJson(`/api/wizard/plan?upload_id=${encodeURIComponent(props.uploadId)}`);
    plan.value = data;
    mode.value = data && data.can_incremental ? "incremental" : "full";
  } catch (e) {
    plan.value = null;
    planError.value = (e && (e.detail || e.message)) || "读取构建计划失败";
    // 读不到计划时不允许"猜"增量，只能走覆盖重建
    mode.value = "full";
  } finally {
    planLoading.value = false;
  }
}

function selectMode(next) {
  if (status.value !== "idle") return;
  if (next === "incremental" && !canIncremental.value) return;
  mode.value = next;
}

/* ---------- 计时 / 轮询 ---------- */
function stopTimers() {
  clearTimeout(pollTimer);
  pollTimer = null;
  clearInterval(tickTimer);
  tickTimer = null;
}

function startTicker(keepStart = false) {
  if (!keepStart || !startedAt.value) startedAt.value = Date.now();
  elapsedSec.value = Math.max(0, (Date.now() - startedAt.value) / 1000);
  clearInterval(tickTimer);
  tickTimer = setInterval(() => {
    elapsedSec.value = Math.max(0, (Date.now() - startedAt.value) / 1000);
  }, 1000);
}

function schedulePoll(delay = POLL_INTERVAL_MS) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, delay);
}

function applyTask(t) {
  task.value = t;
  percent.value = Math.min(100, Math.max(0, Number(t.percent) || 0));
  steps.value = t.steps || [];
  note.value = t.note || "";
  if (t.error) errorText.value = t.error;
}

async function poll() {
  if (!taskId.value) return;
  try {
    const t = await getJson(`/api/wizard/build/${encodeURIComponent(taskId.value)}`);
    applyTask(t);
    if (t.status === "running") {
      schedulePoll(POLL_INTERVAL_MS);
    } else if (t.status === "done") {
      finishDone(t);
    } else {
      finishFailed(t);
    }
  } catch (e) {
    stopTimers();
    emit("running", false);
    if (e && e.status === 404) {
      clearBuildTaskId();
      status.value = "expired";
      errorText.value = "构建任务不存在或已过期（后端可能重启过），请重新点击「开始构建」。";
    } else {
      status.value = "failed";
      errorText.value = (e && (e.detail || e.message)) || "读取构建进度失败";
    }
  }
}

function finishDone(t, options = {}) {
  stopTimers();
  status.value = "done";
  percent.value = 100;
  task.value = t;
  note.value = t.note || "构建完成";
  emit("running", false);
  emit("done", {
    note: t.note || "",
    result: t.result || null,
    mode: (t.result && t.result.mode) || t.mode || currentMode.value,
  });
  if (!options.quiet) {
    const label = ((t.result && t.result.mode) || t.mode) === "incremental" ? "增量更新完成" : "构建完成";
    toast(`${label}，可以开始提问了`, "success", 4200);
  }
}

function finishFailed(t) {
  stopTimers();
  status.value = "failed";
  errorText.value = t.error || t.note || "构建失败";
  note.value = t.note || "";
  emit("running", false);
}

/* ---------- 开始构建（覆盖重建先二次确认） ---------- */
async function startBuild() {
  if (!props.uploadId || starting.value || isRunning.value) return;
  if (mode.value === "full") {
    confirmOpen.value = true;
    await nextTick();
    if (confirmBtn.value && confirmBtn.value.focus) confirmBtn.value.focus();
    return;
  }
  await doStart("incremental");
}

function cancelConfirm() {
  confirmOpen.value = false;
}

function switchToIncremental() {
  confirmOpen.value = false;
  if (canIncremental.value) mode.value = "incremental";
}

async function confirmFull() {
  confirmOpen.value = false;
  await doStart("full");
}

async function doStart(selectedMode) {
  if (!props.uploadId || starting.value || isRunning.value) return;
  starting.value = true;
  status.value = "idle";
  errorText.value = "";
  note.value = "正在提交构建任务…";
  percent.value = 0;
  steps.value = [];
  taskId.value = "";
  task.value = null;
  errorText.value = "";
  emit("running", true);
  try {
    // 只传上传批次 + 字段映射 + 模式；dataset 由后端按登录账号推导（红线）
    const res = await postJson("/api/wizard/build", {
      upload_id: props.uploadId,
      fields: props.fields,
      mode: selectedMode,
    });
    taskId.value = (res && res.task_id) || "";
    if (!taskId.value) throw new Error("服务端没有返回任务号，请重试");
    writeBuildTaskId(taskId.value);
    status.value = "running";
    note.value = "构建任务已启动，正在准备…";
    startTicker();
    schedulePoll(POLL_INTERVAL_MS);
  } catch (e) {
    status.value = "failed";
    errorText.value = (e && (e.detail || e.message)) || "启动构建失败";
    emit("running", false);
  } finally {
    starting.value = false;
  }
}

function retry() {
  startBuild();
}

/* ---------- 从 active 任务恢复 ---------- */
function applyInitialTask(t) {
  if (!t) return;
  task.value = t;
  taskId.value = t.task_id || taskId.value;
  if (taskId.value) writeBuildTaskId(taskId.value);
  percent.value = Math.min(100, Math.max(0, Number(t.percent) || 0));
  steps.value = t.steps || [];
  note.value = t.note || "";
  errorText.value = t.error || "";
  const startedAtSec = Number(t.started_at) || 0;
  if (startedAtSec) startedAt.value = startedAtSec * 1000;
  if (t.status === "running") {
    status.value = "running";
    startTicker(true);
    emit("running", true);
    schedulePoll(POLL_INTERVAL_MS);
  } else if (t.status === "done") {
    finishDone(t, { quiet: true });
  } else {
    finishFailed(t);
  }
}

function onKeydown(event) {
  if (event.key === "Escape" && confirmOpen.value) {
    confirmOpen.value = false;
  }
}

function stepMark(s) {
  if (s.status === "done") return "✓";
  if (s.status === "failed") return "✕";
  if (s.status === "skipped") return "–";
  if (s.status === "running") return "•";
  return "";
}

function stepPct(s) {
  if (s.status === "done") return "完成";
  if (s.status === "skipped") return "已跳过";
  if (s.status === "failed") return "失败";
  return `${s.percent || 0}%`;
}

/** 五步进度条：0~1 的 scaleX（GPU 动画，避免改 width 触发重排） */
function stepScale(s) {
  if (s.status === "done" || s.status === "skipped") return 1;
  const n = Number(s.percent) || 0;
  return Math.min(1, Math.max(0, n / 100));
}

const totalScale = computed(() => Math.min(1, Math.max(0, percent.value / 100)));

onMounted(() => {
  loadPlan();
  applyInitialTask(props.initialTask);
  window.addEventListener("keydown", onKeydown);
});

onBeforeUnmount(() => {
  stopTimers();
  window.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <section class="step-card">
    <div class="step-head">
      <div>
        <div class="step-kicker">第 3 步 · 构建索引</div>
        <h3 class="step-title">把这次上传的内容写进数据空间</h3>
        <p class="step-desc">
          「追加更新」只处理本次新增 / 变更的文件，已有用户与文档不受影响；「覆盖重建」会先清空再全量重算。
          目标数据空间由登录账号推导，页面不、也无法指定数据集。
        </p>
      </div>
      <div v-if="isRunning" class="step-head-badge is-running">
        <span class="status-dot is-running" />
        {{ currentModeLabel }} · 进行中 {{ elapsedSec.toFixed(0) }}s
      </div>
    </div>

    <div class="summary-row">
      <span class="summary-chip"><b>{{ summary.csv_count || 0 }}</b> 个数据文件</span>
      <span class="summary-chip"><b>{{ summary.md_count || 0 }}</b> 篇规则文档</span>
      <span class="summary-chip"><b>{{ Number(summary.total_rows || 0).toLocaleString() }}</b> 行交易记录</span>
      <span class="summary-chip"><b>{{ summary.total_chunks || 0 }}</b> 个预计分块</span>
    </div>

    <!-- ================= 待开始：选模式 ================= -->
    <template v-if="status === 'idle'">
      <div v-if="planLoading" class="plan-loading">
        <div class="skeleton" style="height: 22px; width: 36%"></div>
        <div class="skeleton" style="height: 118px; margin-top: 12px"></div>
      </div>

      <template v-else>
        <div v-if="planError" class="alert is-warn" style="margin-top: 14px">
          无法读取构建计划：{{ planError }}。本次只能选择「覆盖重建」。
        </div>

        <div class="mode-grid">
          <!-- 追加更新（默认） -->
          <button
            type="button"
            class="mode-card"
            :class="{ 'is-selected': mode === 'incremental', 'is-disabled': !canIncremental }"
            :disabled="!canIncremental"
            :aria-pressed="mode === 'incremental'"
            @click="selectMode('incremental')"
          >
            <span class="mode-radio" aria-hidden="true" />
            <span class="mode-title">
              追加更新
              <span v-if="canIncremental" class="badge is-success">推荐</span>
              <span v-else class="badge is-warn">不可用</span>
            </span>
            <p class="mode-desc" :class="{ 'is-warn': !canIncremental }">
              {{ canIncremental ? planHint : incrementalReason }}
            </p>
            <div v-if="canIncremental && planStats" class="mode-meta">
              <span>新增 CSV {{ planStats.newCsv }} 个</span>
              <span>新增文档 {{ planStats.newMd }} 篇</span>
              <span v-if="planStats.changedMd">内容有变文档 {{ planStats.changedMd }} 篇</span>
              <span v-if="Number(planStats.existing.profiles) > 0">
                已有 {{ fmtNumber(planStats.existing.profiles) }} 个用户不受影响
              </span>
            </div>
            <p v-if="canIncremental && planStats && planStats.skippedChangedCsv.length" class="mode-warn-line">
              同名 CSV 内容已变化，追加会跳过（避免重复累加）：{{ planStats.skippedChangedCsv.join("、") }}
            </p>
            <p
              v-if="canIncremental && planStats && planStats.seededFrom === 'last_build_mtime'"
              class="mode-hint-line"
            >
              增量清单按上次构建时间推断（旧数据空间自动引导）。
            </p>
          </button>

          <!-- 覆盖重建 -->
          <button
            type="button"
            class="mode-card"
            :class="{ 'is-selected': mode === 'full', 'is-danger': mode === 'full' }"
            :aria-pressed="mode === 'full'"
            @click="selectMode('full')"
          >
            <span class="mode-radio" aria-hidden="true" />
            <span class="mode-title">
              覆盖重建
              <span class="badge">清空重算</span>
            </span>
            <p class="mode-desc">清空当前数据空间里的画像 / 文档 / 检索索引，再全量重算。</p>
            <div class="mode-meta">
              <span v-if="existingSummary.hasData">
                现有 {{ fmtNumber(existingSummary.profiles) }} 个用户 /
                {{ fmtNumber(existingSummary.docs) }} 篇文档 / {{ fmtNumber(existingSummary.chunks) }} 个切片
              </span>
              <span v-else>当前还没有构建数据</span>
              <span v-if="lastModeLabel">上次构建：{{ lastModeLabel }}</span>
            </div>
            <p v-if="fullTimeText" class="mode-hint-line">{{ fullTimeText }}</p>
          </button>
        </div>

        <div class="build-intro">
          <div class="build-intro-icon">⚡</div>
          <div>
            <div class="build-intro-title">
              {{ mode === "incremental" ? "只处理本次新增内容，通常比全量快很多" : "覆盖重建会清空后全量重算，耗时较长" }}
            </div>
            <p class="build-intro-text">
              构建在服务端进行，<b>期间可以离开本页面</b>；回到本页会自动恢复进度。
              构建过程中同一数据空间不接受提问。
            </p>
          </div>
        </div>
      </template>
    </template>

    <!-- ================= 进行中 ================= -->
    <div v-if="isRunning" class="build-panel">
      <div class="build-percent-line">
        <span class="build-percent">{{ Math.round(percent) }}<small>%</small></span>
        <span class="build-mode-tag">{{ currentModeLabel }}</span>
        <span class="build-step-count" v-if="stepProgress.total">
          步骤 {{ stepProgress.done }}/{{ stepProgress.total }} · 已用 {{ elapsedSec.toFixed(0) }}s
        </span>
      </div>
      <div class="build-bar">
        <div class="build-bar-fill" :style="{ transform: `scaleX(${totalScale})` }" />
      </div>
      <p class="build-note">{{ humanizeStatusText(note) || "处理中…" }}</p>

      <div class="build-steps">
        <div v-for="s in steps" :key="s.key" class="build-step" :class="`is-${s.status}`">
          <span class="build-step-mark">{{ stepMark(s) }}</span>
          <span class="build-step-label">{{ s.label }}</span>
          <span class="build-step-bar">
            <i :style="{ transform: `scaleX(${stepScale(s)})` }" />
          </span>
          <span class="build-step-pct">
            <template v-if="s.status === 'running' && s.total">
              {{ Number(s.processed || 0).toLocaleString() }}/{{ Number(s.total).toLocaleString() }}
            </template>
            <template v-else>{{ stepPct(s) }}</template>
          </span>
        </div>
        <div v-if="!steps.length" class="build-step-skeleton">
          <span class="spinner spinner-sm" /> 正在获取构建步骤…
        </div>
      </div>
      <p class="field-hint" style="margin-top: 10px">
        可以离开本页面：任务在服务端继续，回到本页会自动恢复进度。
      </p>
    </div>

    <!-- ================= 完成 ================= -->
    <div v-if="isDone" class="build-success">
      <div class="build-success-head">
        <span class="build-success-icon">✓</span>
        <div>
          <div class="build-success-title">{{ resultMode === "incremental" ? "增量更新完成" : "构建完成" }}</div>
          <p class="build-success-note">{{ doneNote }}</p>
        </div>
      </div>
      <div v-if="resultRows.length" class="build-result-grid">
        <div v-for="row in resultRows" :key="row.label" class="build-result-item" :title="row.title || ''">
          <div class="build-result-label">{{ row.label }}</div>
          <div class="build-result-value">{{ row.value }}</div>
        </div>
      </div>
      <p v-if="previousResult && !taskId" class="field-hint">
        这是本次会话上一次构建的结果；如需重跑，点下面的「重新构建」。
      </p>
    </div>

    <!-- ================= 失败 / 过期 ================= -->
    <div v-if="isFailed || status === 'expired'" class="alert is-error">
      <div>
        <strong>{{ status === "expired" ? "任务已过期" : "构建失败" }}</strong>
        <p style="margin-top: 6px">{{ errorText }}</p>
        <p v-if="note" class="field-hint" style="margin-top: 6px">{{ humanizeStatusText(note) }}</p>
      </div>
    </div>

    <div class="step-footer">
      <button type="button" class="btn btn-ghost" :disabled="isRunning || starting" @click="$emit('back')">
        ← 上一步
      </button>
      <span class="spacer" />
      <template v-if="isDone">
        <button type="button" class="btn btn-ghost" :disabled="starting" @click="startBuild">重新构建</button>
        <button type="button" class="btn btn-primary" @click="$emit('ask')">下一步：提问验证 →</button>
      </template>
      <template v-else-if="isRunning">
        <span class="field-hint">构建进行中，完成后会展示结果并解锁第 4 步</span>
      </template>
      <template v-else>
        <span class="field-hint" :class="{ 'is-error-text': startDisabled }">{{ startHint }}</span>
        <button
          type="button"
          class="btn"
          :class="mode === 'full' ? 'btn-danger' : 'btn-primary'"
          :disabled="startDisabled"
          @click="startBuild"
        >
          <span v-if="starting" class="spinner spinner-sm" />
          {{ starting ? "启动中…" : status === "failed" || status === "expired" ? "重新开始构建" : "开始构建" }}
        </button>
      </template>
    </div>

    <!-- 覆盖重建二次确认 -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="confirmOpen" class="modal-backdrop" @click.self="cancelConfirm">
          <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
            <div class="modal-icon is-danger">!</div>
            <h3 id="confirm-title" class="modal-title">覆盖重建会清空现有数据</h3>
            <div class="modal-body">
              <p>
                当前数据空间已有
                <b>{{ fmtNumber(existingSummary.profiles) }}</b> 个用户画像、
                <b>{{ fmtNumber(existingSummary.docs) }}</b> 篇文档
                （{{ fmtNumber(existingSummary.chunks) }} 个切片）。
                覆盖重建会先清空这些内容，再按本次上传全量重算。
              </p>
              <ul class="modal-list">
                <li v-if="fullTimeText">{{ fullTimeText }}。</li>
                <li>如果这次只是新增了文件，用「追加更新」更快，已有用户不受影响。</li>
                <li>构建期间可以离开此页面，回到本页时会自动恢复进度。</li>
              </ul>
            </div>
            <div class="modal-actions">
              <button type="button" class="btn btn-ghost" @click="cancelConfirm">取消</button>
              <button
                v-if="canIncremental"
                type="button"
                class="btn btn-ghost"
                @click="switchToIncremental"
              >
                改用追加更新
              </button>
              <button ref="confirmBtn" type="button" class="btn btn-danger" @click="confirmFull">
                确认覆盖重建
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>
