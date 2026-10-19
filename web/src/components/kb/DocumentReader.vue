<script setup>
/**
 * 文档管理 / 阅读器：
 * - 文档矩阵：切片数、字符数、占比条
 * - 点击文档打开全屏抽屉
 * - Tab A 原文阅读（后端 raw API + Markdown 渲染）
 * - Tab B RAG 切片（块编号 + 字数 + 原始 chunk）
 *
 * 文档 id 是后端哈希；前端不传 dataset，抽屉只展示当前租户内容。
 */
import { computed, onMounted, ref, watch } from "vue";
import { getJson } from "../../api";
import { renderMarkdown } from "../../lib/markdown";

const props = defineProps({
  dataset: { type: String, default: "" },
});

const docs = ref([]);
const docsLoading = ref(false);
const docsError = ref("");
const activeDoc = ref(null);
const activeTab = ref("raw");
const chunks = ref([]);
const chunksLoading = ref(false);
const chunksError = ref("");
const rawContent = ref("");
const rawSource = ref("");
const rawLoading = ref(false);
const rawError = ref("");
const drawerOpen = ref(false);
const truncated = ref(false);

const docsCount = computed(() => docs.value.length);
const totalChunks = computed(() => docs.value.reduce((n, d) => n + Number(d.chunks || 0), 0));
const maxChunks = computed(() => Math.max(1, ...docs.value.map((d) => Number(d.chunks || 0))));
const rawHtml = computed(() => renderMarkdown(String(rawContent.value || "").replace(/^\uFEFF/, "")));

function fmtNumber(value) {
  return Number(value || 0).toLocaleString();
}
function pad(index) {
  return String(index).padStart(2, "0");
}
function barWidth(doc) {
  return `${Math.max(3, (Number(doc.chunks || 0) / maxChunks.value) * 100)}%`;
}
function rawSourceLabel(source) {
  if (source === "upload") return "上传批次原始文件";
  if (source === "repo_docs") return "仓库文档原文";
  if (source === "chunks_reconstructed") return "由切片重建（源文件不可用）";
  return source || "未知来源";
}

async function loadDocs() {
  docsLoading.value = true;
  docsError.value = "";
  try {
    const data = await getJson("/api/kb/documents");
    docs.value = data.items || [];
  } catch (e) {
    docsError.value = e.detail || e.message || "文档列表加载失败";
  } finally {
    docsLoading.value = false;
  }
}

async function openDoc(doc) {
  if (!doc || chunksLoading.value || rawLoading.value) return;
  activeDoc.value = doc;
  drawerOpen.value = true;
  activeTab.value = "raw";
  chunks.value = [];
  chunksError.value = "";
  rawContent.value = "";
  rawError.value = "";
  rawSource.value = "";
  truncated.value = false;
  chunksLoading.value = true;
  rawLoading.value = true;

  const [chunkResult, rawResult] = await Promise.allSettled([
    getJson(`/api/kb/documents/${encodeURIComponent(doc.doc_id)}/chunks`),
    getJson(`/api/kb/docs/${encodeURIComponent(doc.doc_id)}/raw`),
  ]);

  if (chunkResult.status === "fulfilled") {
    chunks.value = chunkResult.value.items || [];
    truncated.value = !!chunkResult.value.truncated;
    if (chunkResult.value.document) activeDoc.value = { ...doc, ...chunkResult.value.document };
  } else {
    chunksError.value = chunkResult.reason?.detail || chunkResult.reason?.message || "文档切片加载失败";
  }
  if (rawResult.status === "fulfilled") {
    rawContent.value = rawResult.value.document?.content || "";
    rawSource.value = rawResult.value.document?.source || "";
  } else {
    rawError.value = rawResult.reason?.detail || rawResult.reason?.message || "原文加载失败";
  }
  chunksLoading.value = false;
  rawLoading.value = false;
}

function closeDrawer() {
  drawerOpen.value = false;
  activeDoc.value = null;
  chunks.value = [];
  rawContent.value = "";
  chunksError.value = "";
  rawError.value = "";
}

onMounted(loadDocs);
watch(() => props.dataset, loadDocs);
</script>

<template>
  <section class="card kb-visual document-reader">
    <div class="visual-head">
      <div>
        <div class="visual-kicker">DOCUMENT MATRIX · RAG CHUNKS</div>
        <div class="visual-title">
          文档矩阵
          <span class="badge">{{ docsCount }} 篇文档</span>
          <span class="badge">{{ fmtNumber(totalChunks) }} 个切片</span>
        </div>
        <p class="card-sub visual-sub">
          客户上传的 Markdown 会被切成 RAG 文本块，再写入向量库。点击任意文档，可查看原文和 AI 实际吃进去的切片。
        </p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="docsLoading" @click="loadDocs">
        {{ docsLoading ? "加载中…" : "刷新文档" }}
      </button>
    </div>

    <div v-if="docsLoading" class="doc-skeleton">
      <div v-for="i in 5" :key="i" class="skeleton" style="height: 48px"></div>
    </div>

    <div v-else-if="docsError" class="alert is-error">
      {{ docsError }}
      <div style="margin-top: 10px">
        <button type="button" class="btn btn-sm btn-ghost" @click="loadDocs">重试</button>
      </div>
    </div>

    <div v-else-if="!docs.length" class="empty-state" style="padding: 30px 10px">
      <div class="empty-emoji">📄</div>
      <div class="empty-title">还没有可解析的文档</div>
      <div class="empty-desc">在数据导入向导上传 Markdown 并构建后，这里会展示文档矩阵和切片预览。</div>
    </div>

    <div v-else class="doc-list">
      <button
        v-for="doc in docs"
        :key="doc.doc_id"
        type="button"
        class="doc-row"
        @click="openDoc(doc)"
      >
        <span class="doc-icon">MD</span>
        <span class="doc-main">
          <strong>{{ doc.name }}</strong>
          <span class="doc-bar"><i :style="{ width: barWidth(doc) }"></i></span>
        </span>
        <span class="doc-meta">{{ fmtNumber(doc.chunks) }} 切片</span>
        <span class="doc-meta">{{ fmtNumber(doc.chars) }} 字符</span>
        <span class="doc-open">阅读 <i>→</i></span>
      </button>
    </div>

    <Teleport to="body">
      <div v-if="drawerOpen" class="doc-overlay" @click.self="closeDrawer">
        <aside class="doc-drawer" role="dialog" aria-modal="true" aria-label="文档阅读器">
          <header class="doc-drawer-head">
            <div>
              <div class="visual-kicker">DOCUMENT READER</div>
              <h3>{{ activeDoc?.name || "文档" }}</h3>
              <p class="field-hint">
                {{ fmtNumber(activeDoc?.chunks) }} 个切片 · {{ fmtNumber(activeDoc?.chars) }} 字符
                <span v-if="truncated">（切片最多展示 500 块）</span>
              </p>
            </div>
            <button type="button" class="icon-btn doc-close" aria-label="关闭" @click="closeDrawer">×</button>
          </header>

          <div class="doc-tabs" role="tablist" aria-label="文档视图">
            <button
              type="button"
              class="doc-tab"
              :class="{ 'is-active': activeTab === 'raw' }"
              role="tab"
              :aria-selected="activeTab === 'raw'"
              @click="activeTab = 'raw'"
            >
              原文阅读
            </button>
            <button
              type="button"
              class="doc-tab"
              :class="{ 'is-active': activeTab === 'chunks' }"
              role="tab"
              :aria-selected="activeTab === 'chunks'"
              @click="activeTab = 'chunks'"
            >
              RAG 切片
            </button>
            <span class="spacer"></span>
            <span v-if="activeTab === 'raw' && rawSource" class="badge">{{ rawSourceLabel(rawSource) }}</span>
          </div>

          <template v-if="activeTab === 'raw'">
            <div v-if="rawLoading" class="doc-state">
              <span class="spinner" />
              <p>正在读取原文…</p>
            </div>
            <div v-else-if="rawError" class="doc-state">
              <div class="alert is-error">{{ rawError }}</div>
              <button type="button" class="btn btn-ghost" @click="openDoc(activeDoc)">重试</button>
            </div>
            <div v-else class="raw-reader" v-html="rawHtml"></div>
          </template>

          <template v-else>
            <div v-if="chunksLoading" class="doc-state">
              <span class="spinner" />
              <p>正在读取切片…</p>
            </div>
            <div v-else-if="chunksError" class="doc-state">
              <div class="alert is-error">{{ chunksError }}</div>
              <button type="button" class="btn btn-ghost" @click="openDoc(activeDoc)">重试</button>
            </div>
            <template v-else>
              <div class="chunk-hint">
                展示的是写入检索库的真实文本块，不是重新润色后的摘要。
              </div>
              <div class="chunk-list">
                <article v-for="chunk in chunks" :key="chunk.id" class="chunk-card">
                  <div class="chunk-head">
                    <span class="chunk-index">块编号 {{ pad(chunk.chunk_index) }}</span>
                    <span class="badge">{{ fmtNumber(chunk.chars) }} 字</span>
                    <span v-if="chunk.parent_key" class="chunk-parent">{{ chunk.parent_key }}</span>
                  </div>
                  <pre class="chunk-text">{{ chunk.text }}</pre>
                </article>
              </div>
            </template>
          </template>
        </aside>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.kb-visual { margin-bottom: 16px; }
.visual-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.visual-kicker {
  font-family: var(--font-mono, monospace);
  font-size: 10px;
  letter-spacing: 0.15em;
  color: var(--primary);
  font-weight: 700;
}
.visual-title {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
  margin-top: 4px;
  font-size: 18px;
  font-weight: 650;
}
.visual-sub { margin-top: 5px; max-width: 760px; line-height: 1.6; }
.doc-list { display: flex; flex-direction: column; gap: 8px; }
.doc-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: var(--surface-2);
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;
}
.doc-row:hover {
  transform: translateX(2px);
  border-color: color-mix(in srgb, var(--primary) 28%, var(--border));
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.07);
}
.doc-icon {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--primary-soft);
  color: var(--primary);
  font-family: var(--font-mono, monospace);
  font-size: 10px;
  font-weight: 700;
}
.doc-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 7px; }
.doc-main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.doc-bar { display: block; height: 4px; border-radius: 99px; background: var(--border); overflow: hidden; }
.doc-bar i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--primary), #9b7bff); }
.doc-meta { flex: none; color: var(--muted); font-size: 11px; white-space: nowrap; }
.doc-open { flex: none; color: var(--primary); font-size: 11px; white-space: nowrap; }
.doc-open i { font-style: normal; margin-left: 3px; }
.doc-skeleton { display: flex; flex-direction: column; gap: 8px; }
.doc-overlay {
  position: fixed;
  inset: 0;
  z-index: 2100;
  display: flex;
  justify-content: flex-end;
  background: rgba(8, 8, 12, 0.42);
  backdrop-filter: blur(3px);
}
.doc-drawer {
  width: min(920px, 97vw);
  height: 100%;
  overflow: auto;
  padding: 24px 28px 40px;
  background: var(--surface);
  border-left: 1px solid var(--border);
  box-shadow: -24px 0 70px rgba(0, 0, 0, 0.22);
}
.doc-drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}
.doc-drawer-head h3 { margin: 5px 0 4px; font-size: 21px; }
.doc-close { font-size: 22px; line-height: 1; }
.doc-tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}
.doc-tab {
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  padding: 7px 13px;
  border-radius: 8px;
  font-size: 12.5px;
  cursor: pointer;
}
.doc-tab:hover { color: var(--text); background: var(--surface-2); }
.doc-tab.is-active { color: var(--primary); background: var(--primary-soft); border-color: color-mix(in srgb, var(--primary) 20%, transparent); font-weight: 650; }
.doc-state {
  min-height: 280px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 12px;
  color: var(--muted);
  text-align: center;
}
.raw-reader {
  margin-top: 16px;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.8;
}
.raw-reader :deep(h1), .raw-reader :deep(h2), .raw-reader :deep(h3) { color: var(--text); }
.raw-reader :deep(pre) { overflow: auto; padding: 10px; border-radius: 8px; background: var(--surface-2); }
.raw-reader :deep(blockquote) { margin-left: 0; padding-left: 12px; border-left: 3px solid var(--primary); color: var(--muted); }
.chunk-hint {
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: 9px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12px;
}
.chunk-list { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }
.chunk-card {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: var(--surface-2);
}
.chunk-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.chunk-index {
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  color: var(--primary);
  font-weight: 700;
}
.chunk-parent {
  margin-left: auto;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: 10px;
}
.chunk-text {
  margin: 10px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-2);
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.7;
}
@media (max-width: 700px) {
  .doc-drawer { width: 100vw; padding: 18px 16px 28px; }
  .doc-meta { display: none; }
  .doc-open { display: none; }
}
</style>
