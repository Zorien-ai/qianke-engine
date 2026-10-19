<script setup>
/**
 * 知识库画像卡牌墙：只读当前登录账号的数据空间。
 * 每页 20 条；不接收前端 dataset；姓名由后端脱敏返回。
 */
import { computed, onMounted, ref, watch } from "vue";
import { getJson } from "../../api";
import { toastError } from "../../store";

const props = defineProps({
  dataset: { type: String, default: "" },
});

const PAGE_SIZE = 20;
const items = ref([]);
const total = ref(0);
const totalPages = ref(0);
const page = ref(1);
const loading = ref(false);
const error = ref("");

const canPrev = computed(() => page.value > 1 && !loading.value);
const canNext = computed(() => page.value < totalPages.value && !loading.value);
const isEmpty = computed(() => !loading.value && !error.value && !items.value.length);

function money(value) {
  if (value === null || value === undefined) return "—";
  return `¥${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
function gender(value) {
  if (value === "女") return "♀ 女";
  if (value === "男") return "♂ 男";
  return value ? `⚪ ${value}` : "性别未提供";
}
function level(value) {
  return value ? `💎 ${value}` : "等级未提供";
}
function avatarChar(item) {
  if (item.name) return item.name.slice(0, 1);
  return String(item.user_id || "U").slice(-2);
}

async function load(targetPage = page.value) {
  if (loading.value) return;
  loading.value = true;
  error.value = "";
  try {
    const data = await getJson(`/api/kb/profiles?page=${targetPage}&size=${PAGE_SIZE}`);
    items.value = data.items || [];
    total.value = Number(data.total) || 0;
    totalPages.value = Number(data.total_pages) || 0;
    page.value = Number(data.page) || targetPage;
  } catch (e) {
    error.value = e.detail || e.message || "画像数据加载失败";
  } finally {
    loading.value = false;
  }
}

function prev() {
  if (canPrev.value) load(page.value - 1);
}
function next() {
  if (canNext.value) load(page.value + 1);
}

onMounted(() => load(1));
watch(() => props.dataset, () => load(1));
</script>

<template>
  <section class="card kb-visual profile-wall">
    <div class="visual-head">
      <div>
        <div class="visual-kicker">USER PROFILE WALL</div>
        <div class="visual-title">
          用户画像浏览
          <span class="badge">{{ total }} 位用户</span>
        </div>
        <p class="card-sub visual-sub">
          这里不是抽象统计，是当前数据空间里真实聚合出来的用户画像。每页 20 位，点击翻页。
        </p>
      </div>
      <div class="row-actions">
        <span class="field-hint">🧩 实时读取 · 只读</span>
        <button type="button" class="btn btn-ghost" :disabled="loading" @click="load(page)">
          {{ loading ? "加载中…" : "查看画像" }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="profile-grid">
      <div v-for="i in 8" :key="i" class="profile-card profile-skeleton">
        <div class="skeleton" style="height: 18px; width: 42%"></div>
        <div class="skeleton" style="height: 28px; width: 64%; margin-top: 16px"></div>
        <div class="skeleton" style="height: 13px; width: 82%; margin-top: 18px"></div>
        <div class="skeleton" style="height: 13px; width: 60%; margin-top: 10px"></div>
      </div>
    </div>

    <div v-else-if="error" class="alert is-error">
      {{ error }}
      <div style="margin-top: 10px">
        <button type="button" class="btn btn-sm btn-ghost" @click="load(page)">重试</button>
      </div>
    </div>

    <div v-else-if="isEmpty" class="empty-state" style="padding: 30px 10px">
      <div class="empty-emoji">🃏</div>
      <div class="empty-title">还没有可展示的用户画像</div>
      <div class="empty-desc">构建数据后，这里会显示真实的结构化画像卡牌。</div>
    </div>

    <template v-else>
      <div class="profile-grid">
        <article
          v-for="item in items"
          :key="item.user_id"
          class="profile-card"
          :title="`${item.user_id} · ${item.city || '城市未知'}`"
        >
          <div class="profile-top">
            <div class="profile-avatar">{{ avatarChar(item) }}</div>
            <div class="profile-identity">
              <div class="profile-id">{{ item.user_id }}</div>
              <div v-if="item.name" class="profile-name">{{ item.name }}</div>
            </div>
            <span class="profile-level">{{ item.member_level || "未标注" }}</span>
          </div>

          <div class="profile-tags">
            <span class="profile-tag">📍 {{ item.city || "城市未知" }}</span>
            <span class="profile-tag">{{ gender(item.gender) }}</span>
            <span class="profile-tag">{{ level(item.member_level) }}</span>
          </div>

          <div class="profile-stats">
            <div>
              <b>{{ money(item.avg_amount) }}</b>
              <span>客单价</span>
            </div>
            <div>
              <b>{{ Number(item.order_count || 0).toLocaleString() }}<small> 笔</small></b>
              <span>订单数</span>
            </div>
          </div>

          <div class="profile-pref">
            <span>偏好</span>
            <b>{{ item.top_category || "暂未识别" }}</b>
            <span v-if="item.age" class="profile-age">{{ item.age }} 岁</span>
          </div>
        </article>
      </div>

      <div class="profile-pager">
        <span class="field-hint">第 {{ page }} / {{ totalPages || 1 }} 页 · 共 {{ total }} 位</span>
        <div class="row-actions">
          <button type="button" class="btn btn-sm btn-ghost" :disabled="!canPrev" @click="prev">← 上一页</button>
          <button type="button" class="btn btn-sm btn-ghost" :disabled="!canNext" @click="next">下一页 →</button>
        </div>
      </div>
    </template>
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
  margin-top: 4px;
  font-size: 18px;
  font-weight: 650;
}
.visual-sub { margin-top: 5px; max-width: 680px; line-height: 1.6; }

.profile-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 12px;
}
.profile-card {
  position: relative;
  padding: 14px 15px 13px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background:
    radial-gradient(180px 120px at 100% 0%, var(--primary-soft), transparent 70%),
    var(--surface);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
  overflow: hidden;
}
.profile-card::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  background: linear-gradient(115deg, transparent 20%, rgba(255, 255, 255, 0.32) 48%, transparent 72%);
  transition: opacity 0.2s ease;
}
.profile-card:hover {
  transform: translateY(-3px);
  border-color: color-mix(in srgb, var(--primary) 28%, var(--border));
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.1);
}
.profile-card:hover::after { opacity: 0.45; }
.profile-skeleton { min-height: 170px; }
.profile-top { display: flex; align-items: center; gap: 10px; }
.profile-avatar {
  width: 32px;
  height: 32px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 10px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
}
.profile-identity { flex: 1; min-width: 0; }
.profile-id { font-family: var(--font-mono, monospace); font-size: 12px; color: var(--muted); }
.profile-name { margin-top: 2px; font-size: 16px; font-weight: 650; }
.profile-level {
  flex: none;
  max-width: 78px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 3px 7px;
  border-radius: 999px;
  font-size: 10px;
  color: var(--primary);
  background: var(--primary-soft);
}
.profile-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 13px; }
.profile-tag {
  padding: 3px 7px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 10.5px;
  color: var(--text-2);
  background: var(--surface-2);
}
.profile-stats {
  display: flex;
  gap: 20px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.profile-stats b { display: block; font-size: 19px; letter-spacing: -0.02em; color: var(--text); }
.profile-stats b small { font-size: 11px; font-weight: 500; color: var(--muted); }
.profile-stats span { display: block; margin-top: 2px; font-size: 10.5px; color: var(--muted); }
.profile-pref {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 11px;
  font-size: 11.5px;
  color: var(--muted);
}
.profile-pref b { color: var(--text-2); font-weight: 600; }
.profile-age { margin-left: auto; font-size: 10.5px; color: var(--muted); }
.profile-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
@media (max-width: 640px) {
  .profile-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .profile-card { padding: 12px; }
  .profile-level { display: none; }
  .profile-stats { gap: 12px; }
  .profile-stats b { font-size: 17px; }
}
</style>
