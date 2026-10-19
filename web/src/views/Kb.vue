<script setup>
/**
 * 知识库总览：只保留 4 个可点击指标卡 + 数据状态。
 * 文档/切片 → /kb/docs，画像 → /kb/profiles，构建时间 → /kb/history。
 * 数据集仍由登录账号推导，前端不传 dataset。
 */
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api";
import { freshnessReason, freshnessText } from "../lib/wizardCache";

const overview = ref(null);
const loading = ref(true);
const loadError = ref("");

const totals = computed(() => (overview.value && overview.value.totals) || { docs: 0, chunks: 0, profiles: 0 });
const builtAt = computed(() => (overview.value && overview.value.built_at) || "—");
const modeLabel = computed(() => (overview.value && overview.value.mode === "demo" ? "演示数据集" : "企业数据空间"));

const freshness = computed(() => {
  const f = (overview.value && overview.value.freshness) || null;
  const map = {
    fresh: { pct: 100, cls: "is-success" },
    stale: { pct: 55, cls: "is-warn" },
    unknown: { pct: 14, cls: "is-muted" },
  };
  const status = (f && f.status) || "unknown";
  const m = map[status] || map.unknown;
  return {
    status,
    label: freshnessText(status),
    reason: freshnessReason(status, f && f.reason),
    pct: m.pct,
    cls: m.cls,
  };
});

function countText(value) {
  return Number(value || 0).toLocaleString();
}

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

onMounted(load);
</script>

<template>
  <div class="page kb-overview">
    <div v-if="loading" class="card">
      <div class="skeleton" style="height: 26px; width: 30%"></div>
      <div class="skeleton" style="height: 100px; margin-top: 16px"></div>
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
      <div class="kb-hero">
        <div>
          <div class="kb-title-line">
            <h2 style="font-size: 22px">知识库概况</h2>
            <span class="kb-dataset">{{ overview.dataset }}</span>
            <span class="badge" :class="overview.mode === 'demo' ? 'is-warn' : 'is-primary'">
              {{ modeLabel }}
            </span>
            <span class="badge" :class="overview.ready ? 'is-success' : 'is-muted'">
              {{ overview.ready ? "已构建" : "未构建" }}
            </span>
          </div>
          <p class="card-sub" style="margin-top: 7px">
            所有指标都来自当前账号的数据空间。点击卡片进入对应的数据视图。
          </p>
        </div>
        <div class="row-actions">
          <RouterLink class="btn btn-ghost" to="/kb/history">构建历史</RouterLink>
          <button type="button" class="btn btn-ghost" @click="load">刷新</button>
        </div>
      </div>

      <div class="stat-grid kb-nav-grid">
        <RouterLink to="/kb/docs" class="stat-card kb-nav-card">
          <div class="kb-nav-head">
            <span class="stat-label">文档</span>
            <span class="kb-nav-arrow">→</span>
          </div>
          <div class="stat-value">{{ countText(totals.docs) }}</div>
          <div class="stat-extra">参与检索的文档篇数 · 查看文档池</div>
        </RouterLink>

        <RouterLink to="/kb/docs" class="stat-card kb-nav-card">
          <div class="kb-nav-head">
            <span class="stat-label">切片</span>
            <span class="kb-nav-arrow">→</span>
          </div>
          <div class="stat-value">{{ countText(totals.chunks) }}</div>
          <div class="stat-extra">写入 wiki_vectors 的 RAG 文本块</div>
        </RouterLink>

        <RouterLink to="/kb/profiles" class="stat-card kb-nav-card">
          <div class="kb-nav-head">
            <span class="stat-label">用户画像</span>
            <span class="kb-nav-arrow">→</span>
          </div>
          <div class="stat-value">{{ countText(totals.profiles) }}</div>
          <div class="stat-extra">结构化画像条数 · 浏览画像卡牌</div>
        </RouterLink>

        <RouterLink to="/kb/history" class="stat-card kb-nav-card">
          <div class="kb-nav-head">
            <span class="stat-label">最近构建时间</span>
            <span class="kb-nav-arrow">→</span>
          </div>
          <div class="stat-value kb-time-value">{{ builtAt }}</div>
          <div class="stat-extra">查看构建流水与耗时</div>
        </RouterLink>
      </div>

      <div class="freshness-card" :title="`技术值：${freshness.status}`">
        <span class="status-dot" :class="`is-${freshness.status}`"></span>
        <div>
          <div class="freshness-kicker">数据状态</div>
          <div class="freshness-text">{{ freshness.label }}</div>
          <div class="freshness-reason">{{ freshness.reason || "暂无数据状态信息" }}</div>
        </div>
        <div class="freshness-bar progress progress-lg" :class="freshness.cls">
          <div class="progress-fill" :style="{ width: `${freshness.pct}%` }"></div>
        </div>
      </div>

      <div v-if="overview.notes && overview.notes.length" class="alert is-info" style="margin-top: 16px">
        <div v-for="(n, i) in overview.notes" :key="i">{{ n }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.kb-overview { max-width: 1200px; }
.kb-nav-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.kb-nav-card {
  display: block;
  color: inherit;
  text-decoration: none;
  cursor: pointer;
  position: relative;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.kb-nav-card:hover {
  transform: translateY(-4px);
  border-color: color-mix(in srgb, var(--primary) 30%, var(--border));
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.12);
}
.kb-nav-card:active { transform: translateY(-1px); }
.kb-nav-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.kb-nav-arrow {
  font-size: 17px;
  color: var(--primary);
  opacity: 0.55;
  transition: transform 0.18s ease, opacity 0.18s ease;
}
.kb-nav-card:hover .kb-nav-arrow { transform: translateX(3px); opacity: 1; }
.kb-time-value { font-size: 18px !important; line-height: 1.35 !important; word-break: break-all; }
@media (max-width: 900px) {
  .kb-nav-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 560px) {
  .kb-nav-grid { grid-template-columns: 1fr; }
}
</style>
