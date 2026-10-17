<script setup>
/**
 * 第 1 步：上传交易数据 / 规则文档。
 *
 * 这里只做「该不该收」的本地预检（后缀、空文件），真正的编码转换、行数、
 * 列名解析全部由服务端完成——上传接口返回的 state 就是页面模型。
 * 拖拽框：hover 内发光、dragover 流光、drop 脉冲、键盘可聚焦（Enter / Space）。
 */
import { computed, ref } from "vue";
import { downloadDocTemplate } from "../../lib/docTemplate";

const props = defineProps({
  analysis: { type: Object, default: null },
  message: { type: Object, default: () => ({ text: "", kind: "info" }) },
  rejected: { type: Array, default: () => [] },
  restoring: { type: Boolean, default: false },
  uploading: { type: String, default: "" }, // "" | "csv" | "md"
  removing: { type: String, default: "" }, // 正在移除的文件名
  sampling: { type: Boolean, default: false },
});

const emit = defineEmits(["files", "remove", "sample", "next"]);

const csvInput = ref(null);
const mdInput = ref(null);
const overKind = ref("");
const flashKind = ref("");
let flashTimer = null;

const csvFiles = computed(() => (props.analysis && props.analysis.csv_files) || []);
const mdFiles = computed(() => (props.analysis && props.analysis.md_files) || []);
const summary = computed(() => (props.analysis && props.analysis.summary) || null);
const hasFiles = computed(() => {
  const s = summary.value;
  return !!s && (Number(s.csv_count) > 0 || Number(s.md_count) > 0);
});
const canNext = computed(() => hasFiles.value && !props.uploading && !props.restoring);

const MD_RE = /\.(md|markdown)$/i;
const TABLE_RE = /\.(csv|txt)$/i;

function fmtSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function encodingLabel(encoding) {
  if (!encoding) return "";
  return /^utf-8/i.test(encoding) ? "UTF-8" : `原始 ${encoding} → 已转 UTF-8`;
}

function pick(kind) {
  if (props.uploading) return;
  const input = kind === "csv" ? csvInput.value : mdInput.value;
  if (input) input.click();
}

function onPick(kind, event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (files.length) emit("files", kind, files);
}

function onEnter(kind) {
  overKind.value = kind;
}

function onOver(kind, event) {
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  overKind.value = kind;
}

function onLeave(kind, event) {
  // 进入子元素也会触发 dragleave：只有相关目标不在框内时才真正取消
  if (event.currentTarget && event.relatedTarget && event.currentTarget.contains(event.relatedTarget)) {
    return;
  }
  if (overKind.value === kind) overKind.value = "";
}

function onDrop(kind, event) {
  event.preventDefault();
  overKind.value = "";
  const files = Array.from((event.dataTransfer && event.dataTransfer.files) || []);
  if (!files.length) return;
  flashKind.value = kind;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => (flashKind.value = ""), 700);
  emit("files", kind, files);
}

function removeFile(kind, name) {
  if (props.removing) return;
  emit("remove", kind, name);
}

const ICON_CSV =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>';
const ICON_MD =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="11" x2="14" y2="11"/></svg>';
</script>

<template>
  <section class="step-card">
    <div class="step-head">
      <div>
        <div class="step-kicker">第 1 步 · 上传数据</div>
        <h3 class="step-title">把这次要导入的文件拖进来</h3>
        <p class="step-desc">
          交易数据（CSV / TXT）用于生成用户画像；规则文档（.md）用于回答业务问题。
          可以分多次追加，也可以先用示例数据把流程跑一遍。
        </p>
      </div>
      <button type="button" class="btn btn-ghost btn-sm" @click="downloadDocTemplate">
        下载规则文档模板
      </button>
    </div>

    <div v-if="restoring" class="restore-hint">
      <span class="spinner spinner-sm" />
      正在恢复上次的上传批次…
    </div>

    <div class="dz-grid">
      <div class="dz-col">
        <div
          class="dropzone"
          :class="{
            'is-over': overKind === 'csv',
            'is-flash': flashKind === 'csv',
            'is-busy': uploading === 'csv',
          }"
          role="button"
          tabindex="0"
          aria-label="上传交易数据（CSV 或 TXT，支持多文件）"
          @click="pick('csv')"
          @keydown.enter.prevent="pick('csv')"
          @keydown.space.prevent="pick('csv')"
          @dragenter.prevent="onEnter('csv')"
          @dragover="onOver('csv', $event)"
          @dragleave="onLeave('csv', $event)"
          @drop="onDrop('csv', $event)"
        >
          <span class="dz-glow" aria-hidden="true" />
          <span class="dz-icon" v-html="ICON_CSV" />
          <span class="dz-type">交易数据</span>
          <span class="dz-hint">
            <b>.csv / .txt</b> · 支持多文件 · 拖到这里或点击选择
          </span>
          <span v-if="uploading === 'csv'" class="dz-busy">
            <span class="spinner spinner-sm" /> 上传并解析中…
          </span>
        </div>

        <div class="file-panel">
          <div class="file-panel-head">
            <b>交易文件 <span class="badge">{{ csvFiles.length }}</span></b>
            <span class="field-hint">行数、列名由服务端真实读取</span>
          </div>
          <ul v-if="csvFiles.length" class="file-list">
            <li v-for="f in csvFiles" :key="f.name" class="file-item">
              <span class="file-main">
                <span class="file-name" :title="f.name">{{ f.name }}</span>
                <span class="file-meta">
                  {{ Number(f.row_count || 0).toLocaleString() }} 行 ·
                  {{ (f.columns || []).length }} 列 ·
                  {{ fmtSize(f.size) }}
                  <template v-if="encodingLabel(f.encoding)"> · {{ encodingLabel(f.encoding) }}</template>
                </span>
              </span>
              <button
                type="button"
                class="file-remove"
                :disabled="!!removing"
                :title="`移除 ${f.name}`"
                @click.stop="removeFile('csv', f.name)"
              >
                <span v-if="removing === f.name" class="spinner spinner-sm" />
                <span v-else>×</span>
              </button>
            </li>
          </ul>
          <div v-else class="file-empty">还没有交易文件</div>
        </div>
      </div>

      <div class="dz-col">
        <div
          class="dropzone"
          :class="{
            'is-over': overKind === 'md',
            'is-flash': flashKind === 'md',
            'is-busy': uploading === 'md',
          }"
          role="button"
          tabindex="0"
          aria-label="上传规则文档（Markdown，支持多文件）"
          @click="pick('md')"
          @keydown.enter.prevent="pick('md')"
          @keydown.space.prevent="pick('md')"
          @dragenter.prevent="onEnter('md')"
          @dragover="onOver('md', $event)"
          @dragleave="onLeave('md', $event)"
          @drop="onDrop('md', $event)"
        >
          <span class="dz-glow" aria-hidden="true" />
          <span class="dz-icon" v-html="ICON_MD" />
          <span class="dz-type">规则文档</span>
          <span class="dz-hint">
            <b>.md / .markdown</b> · 支持多文件 · 标题层级越清楚，引用越准
          </span>
          <span v-if="uploading === 'md'" class="dz-busy">
            <span class="spinner spinner-sm" /> 上传并解析中…
          </span>
        </div>

        <div class="file-panel">
          <div class="file-panel-head">
            <b>规则文档 <span class="badge">{{ mdFiles.length }}</span></b>
            <span class="field-hint">按 # / ## / ### 标题切分</span>
          </div>
          <ul v-if="mdFiles.length" class="file-list">
            <li v-for="f in mdFiles" :key="f.name" class="file-item">
              <span class="file-main">
                <span class="file-name" :title="f.name">{{ f.name }}</span>
                <span class="file-meta">
                  {{ Number(f.chars || 0).toLocaleString() }} 字 · {{ fmtSize(f.size) }}
                  <template v-if="encodingLabel(f.encoding)"> · {{ encodingLabel(f.encoding) }}</template>
                </span>
              </span>
              <button
                type="button"
                class="file-remove"
                :disabled="!!removing"
                :title="`移除 ${f.name}`"
                @click.stop="removeFile('md', f.name)"
              >
                <span v-if="removing === f.name" class="spinner spinner-sm" />
                <span v-else>×</span>
              </button>
            </li>
          </ul>
          <div v-else class="file-empty">还没有规则文档（只传文档也可以构建，只是不生成画像）</div>
        </div>
      </div>
    </div>

    <input ref="csvInput" type="file" accept=".csv,.txt" multiple hidden @change="onPick('csv', $event)" />
    <input ref="mdInput" type="file" accept=".md,.markdown" multiple hidden @change="onPick('md', $event)" />

    <div v-if="summary && hasFiles" class="summary-row">
      <span class="summary-chip"><b>{{ summary.csv_count }}</b> 个数据文件</span>
      <span class="summary-chip"><b>{{ summary.md_count }}</b> 篇规则文档</span>
      <span class="summary-chip"><b>{{ Number(summary.total_rows || 0).toLocaleString() }}</b> 行交易记录</span>
      <span class="summary-chip"><b>{{ summary.total_chunks }}</b> 个预计分块</span>
      <span class="summary-chip">
        <b>{{ summary.detected_fields }}/{{ summary.total_fields }}</b> 个字段自动识别
      </span>
    </div>

    <div v-if="rejected.length" class="alert is-warn">
      <div>
        <strong>以下文件没有被加入：</strong>
        <div v-for="(line, i) in rejected" :key="i">· {{ line }}</div>
      </div>
    </div>

    <div v-if="message.text" class="alert" :class="`is-${message.kind}`">
      {{ message.text }}
    </div>

    <div class="step-footer">
      <button type="button" class="btn btn-ghost" :disabled="sampling || !!uploading" @click="$emit('sample')">
        <span v-if="sampling" class="spinner spinner-sm" />
        {{ sampling ? "正在填充示例数据…" : "用示例数据填满" }}
      </button>
      <span class="spacer" />
      <span v-if="!hasFiles" class="field-hint">至少添加一个文件才能进入下一步</span>
      <button type="button" class="btn btn-primary" :disabled="!canNext" @click="$emit('next')">
        下一步：确认字段 →
      </button>
    </div>
  </section>
</template>
