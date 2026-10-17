<script setup>
/**
 * 第 3 步：构建索引。
 *
 * POST /api/wizard/build 只传 {upload_id, fields}：数据集由登录账号推导，
 * 前端绝不说"写哪个库"（红线）。随后 700ms 轮询 /api/wizard/build/{task_id}，
 * 任务状态、五步进度、note/result 全部按服务端返回渲染。
 *
 * 动效：总进度用渐变+光带，百分比数字用 rAF tween 平滑追上去；
 * 五步状态 running 脉冲 / done / skipped / failed 各自配色。
 */
import { computed, onBeforeUnmount, ref } from "vue";
import { getJson, postJson } from "../../api";
import { toast } from "../../store";

const props = defineProps({
  uploadId: { type: String, required: true },
  fields: { type: Object, required: true },
  summary: { type: Object, default: () => ({}) },
  // 上一次在本次会话里已构建完成的结果（重新进入第 3 步时展示，不重复构建）
  previousResult: { type: Object, default: null },
});

const emit = defineEmits(["back", "done", "running", "ask"]);

const starting = ref(false);
const taskId = ref("");
const status = ref(props.previousResult ? "done" : "idle"); // idle|running|done|failed|expired
const task = ref(null);
const percent = ref(props.previousResult ? 100 : 0);
const displayPercent = ref(percent.value);
const steps = ref([]);
const note = ref((props.previousResult && props.previousResult.note) || "");
const errorText = ref("");
const startedAt = ref(0);
const elapsedSec = ref(0);

let pollTimer = null;
let tickTimer = null;
let rafId = 0;

const isRunning = computed(() => status.value === "running");
const isDone = computed(() => status.value === "done");
const isFailed = computed(() => status.value === "failed");
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
  if (note.value) return note.value;
  if (props.previousResult && props.previousResult.note) return props.previousResult.note;
  return "构建完成，可以开始提问了。";
});

const LEVEL_SOURCE_LABEL = { user: "你的会员等级列", derived: "按金额自动推导", none: "不产出会员等级" };

const resultRows = computed(() => {
  const r = result.value;
  if (!r) return [];
  const rows = [];
  rows.push({
    label: "用户画像",
    value:
      r.profiles == null
        ? "本次未重建（保留上一批）"
        : `${Number(r.profiles).toLocaleString()} 个用户`,
  });
  rows.push({ label: "交易行数", value: `${Number(r.rows || 0).toLocaleString()} 行` });
  rows.push({ label: "索引条数", value: `${Number(r.index_total || 0).toLocaleString()} 条` });
  if (r.freshness) rows.push({ label: "索引新鲜度", value: String(r.freshness) });
  if (r.elapsed_s != null) rows.push({ label: "构建用时", value: `${r.elapsed_s}s` });
  if (r.member_level_source) {
    rows.push({
      label: "会员等级来源",
      value: LEVEL_SOURCE_LABEL[r.member_level_source] || r.member_level_source,
    });
  }
  return rows;
});

function stopTimers() {
  clearTimeout(pollTimer);
  pollTimer = null;
  clearInterval(tickTimer);
  tickTimer = null;
  cancelAnimationFrame(rafId);
  rafId = 0;
}

function tweenPercent(target) {
  cancelAnimationFrame(rafId);
  const from = displayPercent.value;
  const t0 = performance.now();
  const duration = 420;
  const tick = (now) => {
    const p = Math.min(1, (now - t0) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    displayPercent.value = from + (target - from) * eased;
    if (p < 1) {
      rafId = requestAnimationFrame(tick);
    } else {
      displayPercent.value = target;
      rafId = 0;
    }
  };
  rafId = requestAnimationFrame(tick);
}

function startTicker() {
  startedAt.value = Date.now();
  elapsedSec.value = 0;
  clearInterval(tickTimer);
  tickTimer = setInterval(() => {
    elapsedSec.value = (Date.now() - startedAt.value) / 1000;
  }, 1000);
}

function schedulePoll(delay = 700) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, delay);
}

async function poll() {
  if (!taskId.value) return;
  try {
    const t = await getJson(`/api/wizard/build/${encodeURIComponent(taskId.value)}`);
    task.value = t;
    percent.value = Number(t.percent) || 0;
    tweenPercent(percent.value);
    steps.value = t.steps || [];
    note.value = t.note || "";
    if (t.error) errorText.value = t.error;

    if (t.status === "running") {
      schedulePoll(700);
    } else if (t.status === "done") {
      finishDone(t);
    } else {
      finishFailed(t);
    }
  } catch (e) {
    stopTimers();
    emit("running", false);
    if (e && e.status === 404) {
      status.value = "expired";
      errorText.value = "构建任务不存在或已过期（后端可能重启过），请重新点击「开始构建」。";
    } else {
      status.value = "failed";
      errorText.value = (e && (e.detail || e.message)) || "读取构建进度失败";
    }
  }
}

function finishDone(t) {
  stopTimers();
  status.value = "done";
  percent.value = 100;
  tweenPercent(100);
  note.value = t.note || "构建完成";
  task.value = t;
  emit("running", false);
  emit("done", {
    note: t.note || "",
    result: t.result || null,
    missing_required: t.missing_required || [],
  });
  toast("构建完成，可以开始提问了", "success", 4200);
}

function finishFailed(t) {
  stopTimers();
  status.value = "failed";
  errorText.value = t.error || t.note || "构建失败";
  note.value = t.note || "";
  emit("running", false);
}

async function startBuild() {
  if (!props.uploadId || starting.value || isRunning.value) return;
  starting.value = true;
  status.value = "idle";
  errorText.value = "";
  note.value = "正在提交构建任务…";
  percent.value = 0;
  displayPercent.value = 0;
  steps.value = [];
  taskId.value = "";
  emit("running", true);
  try {
    // 只传上传批次 + 字段映射；dataset 由后端按登录账号推导（红线）
    const res = await postJson("/api/wizard/build", {
      upload_id: props.uploadId,
      fields: props.fields,
    });
    taskId.value = (res && res.task_id) || "";
    if (!taskId.value) throw new Error("服务端没有返回任务号，请重试");
    status.value = "running";
    note.value = "构建任务已启动，正在准备…";
    startTicker();
    schedulePoll(400);
  } catch (e) {
    status.value = "failed";
    errorText.value = (e && (e.detail || e.message)) || "启动构建失败";
    emit("running", false);
  } finally {
    starting.value = false;
  }
}

function retry() {
  status.value = "idle";
  errorText.value = "";
  startBuild();
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

onBeforeUnmount(stopTimers);
</script>

<template>
  <section class="step-card">
    <div class="step-head">
      <div>
        <div class="step-kicker">第 3 步 · 构建索引</div>
        <h3 class="step-title">写入当前账号的数据空间</h3>
        <p class="step-desc">
          构建会先清空当前账号数据空间中的画像 / 文档 / 检索索引，再按这次上传的内容全量重写。
          目标库由登录账号推导，页面不、也无法指定数据集。
        </p>
      </div>
      <div v-if="isRunning" class="step-head-badge is-running">
        <span class="status-dot is-running" />
        进行中 {{ elapsedSec.toFixed(0) }}s
      </div>
    </div>

    <div class="summary-row">
      <span class="summary-chip"><b>{{ summary.csv_count || 0 }}</b> 个数据文件</span>
      <span class="summary-chip"><b>{{ summary.md_count || 0 }}</b> 篇规则文档</span>
      <span class="summary-chip"><b>{{ Number(summary.total_rows || 0).toLocaleString() }}</b> 行交易记录</span>
      <span class="summary-chip"><b>{{ summary.total_chunks || 0 }}</b> 个预计分块</span>
    </div>

    <!-- 待开始 -->
    <template v-if="status === 'idle'">
      <div class="build-intro">
        <div class="build-intro-icon">⚡</div>
        <div>
          <div class="build-intro-title">准备好了就开始构建</div>
          <p class="build-intro-text">
            构建在服务端进行，通常需要 1~3 分钟（要跑向量化与索引）。期间请保持页面打开以查看进度；
            构建过程中同一数据空间不接受提问。
          </p>
        </div>
      </div>
    </template>

    <!-- 进行中 -->
    <div v-if="isRunning" class="build-panel">
      <div class="build-percent-line">
        <span class="build-percent">{{ Math.round(displayPercent) }}<small>%</small></span>
        <span class="build-step-count" v-if="stepProgress.total">
          步骤 {{ stepProgress.done }}/{{ stepProgress.total }} · 已用 {{ elapsedSec.toFixed(0) }}s
        </span>
      </div>
      <div class="build-bar">
        <div class="build-bar-fill" :style="{ width: `${displayPercent}%` }" />
      </div>
      <p class="build-note">{{ note || "处理中…" }}</p>

      <div class="build-steps">
        <div
          v-for="s in steps"
          :key="s.key"
          class="build-step"
          :class="`is-${s.status}`"
        >
          <span class="build-step-mark">{{ stepMark(s) }}</span>
          <span class="build-step-label">{{ s.label }}</span>
          <span class="build-step-bar">
            <i :style="{ width: `${s.status === 'done' || s.status === 'skipped' ? 100 : s.percent || 0}%` }" />
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
    </div>

    <!-- 完成 -->
    <div v-if="isDone" class="build-success">
      <div class="build-success-head">
        <span class="build-success-icon">✓</span>
        <div>
          <div class="build-success-title">构建完成</div>
          <p class="build-success-note">{{ doneNote }}</p>
        </div>
      </div>
      <div v-if="resultRows.length" class="build-result-grid">
        <div v-for="row in resultRows" :key="row.label" class="build-result-item">
          <div class="build-result-label">{{ row.label }}</div>
          <div class="build-result-value">{{ row.value }}</div>
        </div>
      </div>
      <p v-if="previousResult && !taskId" class="field-hint">
        这是本次会话上一次构建的结果；如需重跑，点下面的「重新构建」。
      </p>
    </div>

    <!-- 失败 / 过期 -->
    <div v-if="isFailed || status === 'expired'" class="alert is-error">
      <div>
        <strong>{{ status === "expired" ? "任务已过期" : "构建失败" }}</strong>
        <p style="margin-top: 6px">{{ errorText }}</p>
        <p v-if="note" class="field-hint" style="margin-top: 6px">{{ note }}</p>
      </div>
    </div>

    <div class="step-footer">
      <button type="button" class="btn btn-ghost" :disabled="isRunning || starting" @click="$emit('back')">
        ← 上一步
      </button>
      <span class="spacer" />
      <template v-if="isDone">
        <button type="button" class="btn btn-ghost" @click="startBuild">重新构建</button>
        <button type="button" class="btn btn-primary" @click="$emit('ask')">下一步：提问验证 →</button>
      </template>
      <template v-else-if="isRunning">
        <span class="field-hint">构建进行中，完成后会展示结果并解锁第 4 步</span>
      </template>
      <template v-else>
        <button type="button" class="btn btn-primary" :disabled="starting || !uploadId" @click="startBuild">
          <span v-if="starting" class="spinner spinner-sm" />
          {{ starting ? "启动中…" : status === "failed" || status === "expired" ? "重新开始构建" : "开始构建" }}
        </button>
      </template>
    </div>
  </section>
</template>
