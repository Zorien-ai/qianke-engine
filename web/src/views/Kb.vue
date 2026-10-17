<script setup>
/**
 * 知识库页：GET /api/kb/overview 概况 + 文档矩阵 + 索引新鲜度；
 * 企业管理员（overview.can_write）可重建 / 清空。
 *
 * 重建复用既有向导接口：POST /api/wizard/build（upload_id + fields）→ 轮询
 * GET /api/wizard/build/{task_id} 显示步骤进度。**绝不传 dataset**：读哪个库
 * 由登录账号推导（红线）。清空要手输 dataset 字面值做二次确认。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { getJson, postJson } from "../api";
import { toast, toastError } from "../store";

const overview = ref(null);
const loading = ref(true);
const loadError = ref("");

const clearInput = ref("");
const clearing = ref(false);

const build = reactive({
  busy: false,
  taskId: "",
  dataset: "",
  status: "",
  percent: 0,
  steps: [],
  note: "",
  error: "",
  pollTimer: null,
});

const lastSource = computed(() => (overview.value && overview.value.last_source) || null);
const canWrite = computed(() => !!(overview.value && overview.value.can_write));
const rebuildDisabledReason = computed(() => {
  if (!canWrite.value) return "只有企业管理员可以重建数据";
  if (!lastSource.value) return "还没有可复用的构建源，请先去数据导入向导构建一次";
  if (!lastSource.value.available) return "源文件已不在上传目录，请重新导入后再重建";
  return "";
});
const canRebuild = computed(() => !rebuildDisabledReason.value);

const freshness = computed(() => {
  const f = (overview.value && overview.value.freshness) || null;
  if (!f) return { status: "unknown", label: "未知", reason: "", pct: 0, cls: "is-muted" };
  const map = {
    fresh: { label: "索引新鲜", pct: 100, cls: "is-success" },
    stale: { label: "索引落后于源表", pct: 55, cls: "is-warn" },
    unknown: { label: "无基线指纹", pct: 14, cls: "is-muted" },
  };
  const m = map[f.status] || map.unknown;
  return { status: f.status, label: m.label, pct: m.pct, cls: m.cls, reason: f.reason || "" };
});

const maxChunks = computed(() => {
  const docs = (overview.value && overview.value.docs) || [];
  return docs.reduce((n, d) => Math.max(n, Number(d.chunks) || 0), 0) || 1;
});

const srcFields = computed(() => {
  const fields = (lastSource.value && lastSource.value.fields) || {};
  return Object.entries(fields).filter(([, v]) => v);
});

async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    overview.value = await getJson("/api/kb/overview");
  } catch (e) {
    loadError.value = e.detail || e.message || "知识库概况加载失败";
  } finally {
    loading.value = false;
  }
}

/* ---------- 重建 ---------- */
function stopPolling() {
  if (build.pollTimer) {
    clearInterval(build.pollTimer);
    build.pollTimer = null;
  }
}

async function pollBuild() {
  if (!build.taskId) return;
  try {
    const t = await getJson(`/api/wizard/build/${build.taskId}`);
    build.status = t.status || "";
    build.percent = Number(t.percent) || 0;
    build.steps = t.steps || [];
    build.note = t.note || "";
    build.error = t.error || "";
    if (t.status === "done" || t.status === "failed") {
      stopPolling();
      build.busy = false;
      if (t.status === "done") {
        toast("重建完成，知识库概况已刷新", "success", 4200);
        await load();
      } else {
        toast(`重建失败：${t.error || t.note || "未知错误"}`, "error", 7000);
      }
    }
  } catch (e) {
    stopPolling();
    build.busy = false;
    toastError(e);
  }
}

async function rebuild() {
  const src = lastSource.value;
  if (!src || !src.upload_id || build.busy) return;
  if (!src.available) {
    toast("源文件已不在上传目录，无法自动重建，请重新导入数据", "error");
    return;
  }
  build.busy = true;
  build.percent = 0;
  build.steps = [];
  build.note = "正在提交构建任务…";
  build.error = "";
  try {
    // 只传 upload_id + fields；dataset 由后端按账号推导（红线）
    const res = await postJson("/api/wizard/build", {
      upload_id: src.upload_id,
      fields: src.fields || {},
    });
    build.taskId = res.task_id || "";
    build.dataset = res.dataset || "";
    build.status = "running";
    build.note = "构建任务已启动，正在清理并重写数据…";
    stopPolling();
    build.pollTimer = setInterval(pollBuild, 1200);
    await pollBuild();
  } catch (e) {
    build.busy = false;
    build.note = "";
    toastError(e);
  }
}

/* ---------- 清空 ---------- */
async function clearAll() {
  const ds = ((overview.value && overview.value.dataset) || "").trim();
  if (!ds) return;
  if (clearInput.value.trim() !== ds) {
    toast(`请输入数据集名「${ds}」以确认清空`, "warn");
    return;
  }
  clearing.value = true;
  try {
    const res = await postJson("/api/kb/clear", { confirm: clearInput.value.trim() });
    const cleared = res.cleared || {};
    toast(
      `已清空：画像 ${cleared.profiles ?? 0} · 切片 ${cleared.chunks ?? 0} · 文档 ${cleared.docs ?? 0} · 索引 ${cleared.index ?? 0}`,
      "success",
      5200
    );
    clearInput.value = "";
    await load();
  } catch (e) {
    toastError(e);
  } finally {
    clearing.value = false;
  }
}

onMounted(load);
onBeforeUnmount(stopPolling);

function stepIcon(status) {
  if (status === "done") return "✓";
  if (status === "running") return "•";
  if (status === "failed") return "✕";
  if (status === "skipped") return "–";
  return "·";
}
</script>

<template>
  <div class="page">
    <div v-if="loading" class="card">
      <div class="skeleton" style="height: 26px; width: 30%"></div>
      <div class="skeleton" style="height: 90px; margin-top: 16px"></div>
    </div>

    <div v-else-if="loadError" class="card">
      <div class="empty-state">
        <div class="empty-emoji">🧩</div>
        <div class="empty-title">知识库概况加载失败</div>
        <div class="empty-desc">{{ loadError }}</div>
        <button type="button" class="btn btn-primary" @click="load">重试</button>
      </div>
    </div>

    <template v-else-if="overview">
      <!-- 标题行 -->
      <div class="kb-hero">
        <div>
          <div class="kb-title-line">
            <h2 style="font-size: 20px">知识库概况</h2>
            <span class="kb-dataset">{{ overview.dataset }}</span>
            <span class="badge" :class="overview.mode === 'demo' ? 'is-warn' : 'is-primary'">
              {{ overview.mode === "demo" ? "演示数据集" : "企业数据空间" }}
            </span>
            <span class="badge" v-if="overview.ready" :class="overview.empty ? 'is-warn' : 'is-success'">
              {{ overview.empty ? "已构建 · 空" : "已构建" }}
            </span>
            <span class="badge" v-else>未构建</span>
          </div>
          <p class="card-sub" style="margin-top: 6px">
            数据来源由登录账号推导；这里只展示当前数据空间的真实概况，重建/清空也只会作用在它上面。
          </p>
        </div>
        <div class="row-actions">
          <a class="btn btn-ghost" href="/wizard">去数据导入</a>
          <button type="button" class="btn btn-ghost" @click="load">刷新</button>
        </div>
      </div>

      <!-- 只读说明 -->
      <div v-if="!canWrite && overview.readonly_reason" class="alert is-info" style="margin-bottom: 16px">
        {{ overview.readonly_reason }}
      </div>

      <!-- 未构建 -->
      <div v-if="!overview.ready" class="card">
        <div class="empty-state">
          <div class="empty-emoji">🌱</div>
          <div class="empty-title">这个数据空间还没有构建</div>
          <div class="empty-desc">
            上传 CSV / Markdown 并完成一次构建后，这里会显示文档数、切片数、画像数、索引新鲜度与文档矩阵。
          </div>
          <a class="btn btn-primary" href="/wizard">去数据导入向导</a>
        </div>
      </div>

      <template v-else>
        <!-- 概况卡 -->
        <div class="stat-grid">
          <div class="stat-card">
            <div class="stat-value">{{ Number(overview.totals?.docs ?? 0).toLocaleString() }}</div>
            <div class="stat-label">文档</div>
            <div class="stat-extra">参与检索的文档篇数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ Number(overview.totals?.chunks ?? 0).toLocaleString() }}</div>
            <div class="stat-label">切片</div>
            <div class="stat-extra">写入 wiki_vectors 的分块数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ Number(overview.totals?.profiles ?? 0).toLocaleString() }}</div>
            <div class="stat-label">用户画像</div>
            <div class="stat-extra">结构化画像条数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value" style="font-size: 19px; line-height: 1.4">
              {{ overview.built_at || "—" }}
            </div>
            <div class="stat-label">最近构建时间</div>
            <div class="stat-extra">{{ overview.freshness?.reason || "无新鲜度说明" }}</div>
          </div>
        </div>

        <!-- 索引新鲜度 -->
        <div class="freshness-card">
          <span class="status-dot" :class="`is-${overview.freshness?.status || 'unknown'}`"></span>
          <div>
            <div class="freshness-text">{{ freshness.label }}</div>
            <div class="freshness-reason">{{ freshness.reason || "没有可用的新鲜度基线" }}</div>
          </div>
          <div class="freshness-bar progress progress-lg" :class="freshness.cls">
            <div class="progress-fill" :style="{ width: `${freshness.pct}%` }"></div>
          </div>
        </div>

        <!-- 文档矩阵 -->
        <section class="card">
          <div class="card-title">
            <span class="dot"></span>文档矩阵
            <span class="badge">{{ overview.docs?.length || 0 }} 篇</span>
            <span class="spacer"></span>
            <span class="card-sub">按切片数排序 · 占比条以最大文档为基准</span>
          </div>
          <div v-if="overview.docs && overview.docs.length" class="doc-matrix">
            <div v-for="doc in overview.docs" :key="doc.doc_name" class="doc-row">
              <span class="doc-name" :title="doc.doc_name">{{ doc.doc_name }}</span>
              <span class="doc-num">{{ doc.chunks }} 切片</span>
              <span class="doc-num">{{ Number(doc.chars || 0).toLocaleString() }} 字符</span>
              <div class="doc-bar progress">
                <div class="progress-fill" :style="{ width: `${Math.max(3, (Number(doc.chunks) / maxChunks) * 100)}%` }"></div>
              </div>
            </div>
          </div>
          <div v-else class="empty-state" style="padding: 28px 10px">
            <div class="empty-desc">
              已构建但还没有文档。可以去
              <a href="/wizard">数据导入向导</a>
              上传 Markdown 文档后重建。
            </div>
          </div>
        </section>

        <!-- 操作区 -->
        <section class="kb-op-card">
          <div class="card-title"><span class="dot"></span>数据维护</div>

          <template v-if="canWrite">
            <div class="meta-list" style="margin-bottom: 14px">
              <div class="meta-row">
                <dt>最近构建源</dt>
                <dd>
                  <template v-if="lastSource">
                    <code>{{ lastSource.upload_id }}</code>
                    <span class="field-hint" style="margin-left: 8px">
                      CSV {{ lastSource.csv ?? 0 }} 个 · 文档 {{ lastSource.md ?? 0 }} 篇 ·
                      {{ lastSource.built_at || "—" }}
                    </span>
                  </template>
                  <template v-else>无（还没通过向导构建过）</template>
                </dd>
              </div>
              <div class="meta-row" v-if="srcFields.length">
                <dt>字段映射</dt>
                <dd>
                  <span v-for="[k, v] in srcFields" :key="k" class="tag" style="margin-right: 6px">{{ k }} → {{ v }}</span>
                </dd>
              </div>
              <div class="meta-row" v-if="lastSource">
                <dt>源文件</dt>
                <dd>
                  <span class="badge" :class="lastSource.available ? 'is-success' : 'is-danger'">
                    {{ lastSource.available ? "仍在磁盘" : "已删除（需重新导入）" }}
                  </span>
                </dd>
              </div>
            </div>

            <div class="row-actions">
              <button type="button" class="btn btn-primary" :disabled="!canRebuild || build.busy" :title="rebuildDisabledReason" @click="rebuild">
                <span v-if="build.busy" class="spinner spinner-sm" />
                {{ build.busy ? "重建中…" : "重建索引" }}
              </button>
              <span class="field-hint">{{ rebuildDisabledReason || "复用最近一次构建源，会清空并重写当前数据空间" }}</span>
            </div>

            <!-- 构建进度 -->
            <div v-if="build.busy || build.status === 'failed'" style="margin-top: 16px">
              <div class="answer-head" style="margin-bottom: 8px">
                <span class="status-dot" :class="{ 'is-running': build.busy, 'is-error': build.status === 'failed' }"></span>
                <span class="freshness-text">{{ build.busy ? "构建进行中" : "构建失败" }} · {{ build.percent }}%</span>
                <span class="card-sub" v-if="build.dataset">目标数据集 {{ build.dataset }}</span>
              </div>
              <div class="progress progress-lg" :class="{ 'is-danger': build.status === 'failed' }">
                <div class="progress-fill" :style="{ width: `${build.percent}%` }"></div>
              </div>
              <p class="build-note" v-if="build.note">{{ build.note }}</p>
              <div class="build-steps">
                <div v-for="st in build.steps" :key="st.key" class="build-step">
                  <span class="step-dot" :class="`is-${st.status}`">{{ stepIcon(st.status) }}</span>
                  <span class="build-step-label">{{ st.label }}</span>
                  <div class="progress" :class="{ 'is-success': st.status === 'done', 'is-muted': st.status === 'skipped' }">
                    <div class="progress-fill" :style="{ width: `${st.percent || 0}%` }"></div>
                  </div>
                  <span class="build-step-pct">{{ st.percent || 0 }}%</span>
                </div>
              </div>
              <p v-if="build.error" class="alert is-error" style="margin-top: 10px">{{ build.error }}</p>
            </div>

            <!-- 危险区：清空 -->
            <div class="danger-zone">
              <div style="font-size: 13px; font-weight: 650; color: var(--danger)">
                清空当前数据空间（不可恢复）
              </div>
              <p class="field-hint" style="margin-top: 4px">
                会清空画像 / 切片 / 检索索引，保留界面配置与源文件。请输入数据集名
                <code>{{ overview.dataset }}</code> 后确认：
              </p>
              <div class="clear-form">
                <input v-model="clearInput" class="input" :placeholder="`输入 ${overview.dataset}`" :disabled="clearing" />
                <button
                  type="button"
                  class="btn btn-danger"
                  :disabled="clearing || clearInput.trim() !== overview.dataset"
                  @click="clearAll"
                >
                  <span v-if="clearing" class="spinner spinner-sm" />
                  {{ clearing ? "清空中…" : "确认清空" }}
                </button>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="empty-state" style="padding: 22px 8px">
              <div class="empty-emoji">🔒</div>
              <div class="empty-title">只读账号</div>
              <div class="empty-desc">
                {{ overview.readonly_reason || "只有企业管理员可以重建或清空数据。" }}
                你可以查看概况与文档矩阵；如需导入数据，请联系本企业管理员。
              </div>
            </div>
          </template>
        </section>

        <!-- 备注 -->
        <div v-if="overview.notes && overview.notes.length" class="alert is-info" style="margin-top: 16px">
          <div>
            <div v-for="(n, i) in overview.notes" :key="i">{{ n }}</div>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>
