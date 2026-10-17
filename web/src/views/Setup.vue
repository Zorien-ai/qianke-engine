<script setup>
/**
 * 四步导入向导（/v2/#/setup）
 *
 * 上传 → 确认字段 → 构建 → 提问，全部对接既有 /api/wizard/* 接口。
 * 前端不传 dataset：读/写哪个数据空间由登录账号推导（红线）。
 *
 * 这个组件只做编排与状态归属：
 *   - 上传批次、字段映射、构建结果在本页持有（切步骤不丢）；
 *   - 四个步骤是独立子组件，负责各自的渲染与动效。
 */
import { computed, onMounted, reactive, ref } from "vue";
import { getJson, postForm, postJson } from "../api";
import { toast, toastError } from "../store";
import SetupStepper from "../components/setup/SetupStepper.vue";
import StepUpload from "../components/setup/StepUpload.vue";
import StepFields from "../components/setup/StepFields.vue";
import StepBuild from "../components/setup/StepBuild.vue";
import StepAsk from "../components/setup/StepAsk.vue";

const UPLOAD_KEY = "v2-wizard-upload-id";

const STEPS = [
  { key: "upload", title: "上传数据", desc: "CSV / Markdown" },
  { key: "fields", title: "确认字段", desc: "映射与预览" },
  { key: "build", title: "构建索引", desc: "写入数据空间" },
  { key: "ask", title: "提问验证", desc: "当场试一句" },
];

const step = ref(1);
const maxStep = ref(1);
const direction = ref("forward");

const analysis = ref(null);
const uploadId = ref("");
const restoring = ref(false);
const uploadingKind = ref("");
const removingName = ref("");
const sampling = ref(false);
const rejected = ref([]);
const step1Message = ref({ text: "", kind: "info" });
const fieldValues = reactive({});

const buildRunning = ref(false);
const buildDone = ref(false);
const buildRecord = ref(null);

const transitionName = computed(() => `step-${direction.value}`);
const hasFiles = computed(() => {
  const s = analysis.value && analysis.value.summary;
  return !!s && (Number(s.csv_count) > 0 || Number(s.md_count) > 0);
});
const summary = computed(() => (analysis.value && analysis.value.summary) || {});
const fieldsPayload = computed(() => {
  const out = {};
  for (const key of Object.keys(fieldValues)) out[key] = fieldValues[key] || null;
  return out;
});
const buildNote = computed(() =>
  buildRecord.value && buildRecord.value.note ? buildRecord.value.note : ""
);

function setMessage(text, kind = "info") {
  step1Message.value = { text: text || "", kind };
}

function clearMessage() {
  step1Message.value = { text: "", kind: "info" };
}

/** 服务端 state → 页面模型（上传 / 删文件 / 示例 / 恢复共用这一条路径） */
function applyState(data) {
  analysis.value = data || null;
  uploadId.value = (data && data.upload_id) || "";
  try {
    if (uploadId.value) localStorage.setItem(UPLOAD_KEY, uploadId.value);
    else localStorage.removeItem(UPLOAD_KEY);
  } catch {
    /* 隐私模式下写不了 localStorage，忽略 */
  }
  for (const key of Object.keys(fieldValues)) delete fieldValues[key];
  for (const f of (data && data.fields) || []) fieldValues[f.key] = f.column || "";
  rejected.value = (data && data.rejected) || [];
}

function goStep(target) {
  if (target === step.value) return;
  if (target < 1 || target > STEPS.length) return;
  direction.value = target > step.value ? "forward" : "back";
  step.value = target;
  // 到达过的最远步骤：只有它能被步骤条回跳；前进由各步骤自己的校验控制
  maxStep.value = Math.max(maxStep.value, target);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function onStepperSelect(target) {
  if (buildRunning.value) {
    toast("构建进行中，完成后再切换步骤", "warn");
    return;
  }
  if (target > maxStep.value) return;
  goStep(target);
}

/* ---------- 第 1 步：上传 ---------- */
const MD_RE = /\.(md|markdown)$/i;
const TABLE_RE = /\.(csv|txt)$/i;

async function onFiles(kind, files) {
  if (uploadingKind.value || !files.length) return;
  const localRejected = [];
  const form = new FormData();
  for (const f of files) {
    if (kind === "md" && !MD_RE.test(f.name)) {
      localRejected.push(`${f.name}（这是文档，要放到左边「交易数据」）`);
      continue;
    }
    if (kind === "csv" && MD_RE.test(f.name)) {
      localRejected.push(`${f.name}（这是文档，要放到右边「规则文档」）`);
      continue;
    }
    if (!MD_RE.test(f.name) && !TABLE_RE.test(f.name)) {
      localRejected.push(`${f.name}（只支持 .csv / .txt 与 .md）`);
      continue;
    }
    if (!f.size) {
      localRejected.push(`${f.name}（空文件）`);
      continue;
    }
    form.append("files", f);
  }

  if (!form.has("files")) {
    rejected.value = localRejected;
    setMessage("以下文件没有被加入：\n· " + localRejected.join("\n· "), "warn");
    return;
  }
  if (uploadId.value) form.append("upload_id", uploadId.value);

  uploadingKind.value = kind;
  clearMessage();
  try {
    const data = await postForm("/api/wizard/upload", form);
    applyState(data);
    const all = localRejected.concat(data.rejected || []);
    rejected.value = all;
    if (all.length) {
      setMessage("部分文件没有被加入，原因见下方提示。", "warn");
    } else {
      const s = data.summary || {};
      setMessage(
        `已上传并读取：交易数据 ${s.csv_count || 0} 个（共 ${Number(s.total_rows || 0).toLocaleString()} 行）` +
          ` / 规则文档 ${s.md_count || 0} 篇。点「下一步：确认字段」继续。`,
        "success"
      );
    }
  } catch (e) {
    toastError(e);
    setMessage((e && (e.detail || e.message)) || "上传失败", "error");
  } finally {
    uploadingKind.value = "";
  }
}

async function onRemove(kind, name) {
  if (!uploadId.value || removingName.value) return;
  removingName.value = name;
  clearMessage();
  try {
    const data = await postJson("/api/wizard/upload/remove", {
      upload_id: uploadId.value,
      name,
    });
    applyState(data);
    setMessage(`已移除 ${name}。`, "info");
  } catch (e) {
    toastError(e);
    setMessage((e && (e.detail || e.message)) || "移除失败", "error");
  } finally {
    removingName.value = "";
  }
}

async function loadSample() {
  if (sampling.value) return;
  sampling.value = true;
  clearMessage();
  try {
    const data = await getJson("/api/wizard/sample");
    applyState(data);
    const s = data.summary || {};
    setMessage(
      `示例数据已填好（${s.csv_count || 0} 个 CSV / ${s.md_count || 0} 篇文档，共 ${Number(
        s.total_rows || 0
      ).toLocaleString()} 行）。可以直接进入下一步。`,
      "success"
    );
  } catch (e) {
    toastError(e);
    setMessage((e && (e.detail || e.message)) || "示例数据加载失败", "error");
  } finally {
    sampling.value = false;
  }
}

/* ---------- 步骤流转 ---------- */
function goFields() {
  if (!hasFiles.value) return;
  clearMessage();
  goStep(2);
}

function goBuild() {
  goStep(3);
}

function onFieldUpdate(key, value) {
  fieldValues[key] = value;
}

function onBuildRunning(running) {
  buildRunning.value = !!running;
}

function onBuildDone(payload) {
  buildDone.value = true;
  buildRecord.value = payload || null;
  maxStep.value = Math.max(maxStep.value, 4);
}

function goAsk() {
  maxStep.value = Math.max(maxStep.value, 4);
  goStep(4);
}

/* ---------- 刷新恢复 ---------- */
async function restoreUpload() {
  let saved = "";
  try {
    saved = localStorage.getItem(UPLOAD_KEY) || "";
  } catch {
    return;
  }
  if (!saved) return;
  restoring.value = true;
  try {
    const data = await getJson(`/api/wizard/upload/${encodeURIComponent(saved)}`);
    applyState(data);
    const s = data.summary || {};
    if (s.csv_count || s.md_count) {
      setMessage(
        `已恢复上次的上传（交易数据 ${s.csv_count || 0} 个 / 规则文档 ${s.md_count || 0} 篇）。` +
          "如需换一批数据，请先移除文件或重新上传。",
        "info"
      );
    }
  } catch (e) {
    try {
      localStorage.removeItem(UPLOAD_KEY);
    } catch {
      /* 忽略 */
    }
    analysis.value = null;
    uploadId.value = "";
    // 404 / 403（批次没了 / 不是自己的批次）静默回空态，不打扰用户
    if (e && e.status !== 404 && e.status !== 403) {
      setMessage((e && (e.detail || e.message)) || "", "warn");
    }
  } finally {
    restoring.value = false;
  }
}

onMounted(restoreUpload);
</script>

<template>
  <div class="page setup-page">
    <!-- 顶部：浅色渐变 + 毛玻璃，不用老页面的紫色大色块 -->
    <header class="setup-hero">
      <div class="setup-hero-content">
        <div class="setup-kicker">
          <span class="setup-kicker-dot" />
          数据导入 · 四步走
        </div>
        <h2 class="setup-title">把数据变成<br />能回答问题的知识库</h2>
        <p class="setup-sub">
          上传交易数据与规则文档，确认字段，构建索引，然后当场提问验证。
          整个过程只操作当前登录账号的数据空间——数据集由账号推导，页面不指定库。
        </p>
        <div class="setup-hero-meta">
          <span class="setup-chip">仅管理员可操作</span>
          <span class="setup-chip">示例数据一键填满</span>
          <span class="setup-chip">构建会清空并重写当前数据空间</span>
        </div>
      </div>
      <span class="setup-hero-orb setup-hero-orb-a" aria-hidden="true" />
      <span class="setup-hero-orb setup-hero-orb-b" aria-hidden="true" />
    </header>

    <SetupStepper
      :steps="STEPS"
      :current="step"
      :max-step="maxStep"
      :disabled="buildRunning"
      @select="onStepperSelect"
    />

    <Transition :name="transitionName" mode="out-in">
      <StepUpload
        v-if="step === 1"
        key="upload"
        :analysis="analysis"
        :message="step1Message"
        :rejected="rejected"
        :restoring="restoring"
        :uploading="uploadingKind"
        :removing="removingName"
        :sampling="sampling"
        @files="onFiles"
        @remove="onRemove"
        @sample="loadSample"
        @next="goFields"
      />
      <StepFields
        v-else-if="step === 2"
        key="fields"
        :analysis="analysis"
        :fields="fieldValues"
        @update="onFieldUpdate"
        @back="goStep(1)"
        @next="goBuild"
      />
      <StepBuild
        v-else-if="step === 3"
        key="build"
        :upload-id="uploadId"
        :fields="fieldsPayload"
        :summary="summary"
        :previous-result="buildRecord"
        @back="goStep(2)"
        @done="onBuildDone"
        @running="onBuildRunning"
        @ask="goAsk"
      />
      <StepAsk
        v-else
        key="ask"
        :upload-id="uploadId"
        :build-note="buildNote"
        @back="goStep(3)"
      />
    </Transition>
  </div>
</template>
