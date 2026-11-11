<template>
  <section class="page chat-profiles-page">
    <header class="page-head">
      <div>
        <h2>会话用户画像</h2>
        <p class="page-desc">
          由 C 买家 ↔ 商家店宠会话在 30 分钟空闲后抽取；只读，可删除/失效。批量导入画像不在此页。
        </p>
      </div>
      <div class="page-actions">
        <select v-model="merchantFilter" class="input" @change="load">
          <option value="">全部商家</option>
          <option v-for="item in merchants" :key="item" :value="item">{{ item }}</option>
        </select>
        <button class="btn btn-ghost" type="button" :disabled="loading" @click="load">
          {{ loading ? "刷新中…" : "刷新" }}
        </button>
      </div>
    </header>

    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>
    <div v-if="loading && !profiles.length" class="empty-state">正在加载会话画像…</div>
    <div v-else-if="!profiles.length" class="empty-state">
      还没有会话画像。C 买家与店宠聊过，且 30 分钟无新消息后会自动生成。
    </div>
    <div v-else class="profile-list">
      <article v-for="item in profiles" :key="item.profile_id" class="card profile-card">
        <header class="profile-head">
          <div>
            <strong>{{ item.buyer_id }}</strong>
            <code>{{ item.merchant_id }}</code>
          </div>
          <div class="profile-actions">
            <span class="badge">置信度 {{ Math.round(Number(item.confidence || 0) * 100) }}%</span>
            <button class="btn btn-danger btn-sm" type="button" :disabled="deleting === item.profile_id" @click="remove(item)">
              {{ deleting === item.profile_id ? "删除中…" : "删除/失效" }}
            </button>
          </div>
        </header>
        <p class="profile-summary">{{ item.profile_text || "暂无摘要" }}</p>
        <dl class="profile-meta">
          <div><dt>版本</dt><dd>{{ item.version }}</dd></div>
          <div><dt>来源消息</dt><dd>{{ item.source_message_count }}</dd></div>
          <div><dt>抽取时间</dt><dd>{{ formatTime(item.extracted_at) }}</dd></div>
        </dl>
        <details class="profile-json">
          <summary>展开 JSON</summary>
          <pre>{{ JSON.stringify(item.profile || {}, null, 2) }}</pre>
        </details>
      </article>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { getJson, del } from "../api";
import { toast } from "../store";

const profiles = ref([]);
const loading = ref(false);
const error = ref("");
const merchantFilter = ref("");
const deleting = ref("");

const merchants = computed(() => {
  const values = profiles.value.map((item) => item.merchant_id).filter(Boolean);
  return [...new Set(values)].sort();
});

function formatTime(value) {
  return String(value || "").replace("T", " ").slice(0, 19) || "—";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const query = merchantFilter.value
      ? `?merchant_id=${encodeURIComponent(merchantFilter.value)}&limit=100`
      : "?limit=100";
    const data = await getJson(`/api/c/admin/chat-profiles${query}`);
    profiles.value = Array.isArray(data?.profiles) ? data.profiles : [];
  } catch (exc) {
    error.value = exc?.detail || exc?.message || "画像加载失败";
    profiles.value = [];
  } finally {
    loading.value = false;
  }
}

async function remove(item) {
  if (!window.confirm(`删除 ${item.buyer_id} 在 ${item.merchant_id} 的会话画像？`)) return;
  deleting.value = item.profile_id;
  try {
    await del(`/api/c/admin/chat-profiles/${encodeURIComponent(item.merchant_id)}/${encodeURIComponent(item.buyer_id)}`);
    toast("画像已失效", "success");
    await load();
  } catch (exc) {
    toast(exc?.detail || exc?.message || "删除失败", "error");
  } finally {
    deleting.value = "";
  }
}

onMounted(load);
</script>

<style scoped>
.chat-profiles-page { max-width: 1100px; }
.page-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.page-desc { margin: 6px 0 0; color: var(--text-2); font-size: 12px; line-height: 1.7; }
.page-actions { display: flex; gap: 8px; align-items: center; }
.profile-list { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
.profile-card { padding: 14px 16px; }
.profile-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.profile-head strong { margin-right: 8px; }
.profile-head code { color: var(--text-3); font-size: 11px; }
.profile-actions { display: flex; gap: 8px; align-items: center; }
.profile-summary { margin: 10px 0 0; color: var(--text-2); font-size: 12px; line-height: 1.7; }
.profile-meta { display: flex; gap: 22px; margin: 10px 0 0; font-size: 11px; }
.profile-meta div { display: flex; gap: 6px; }
.profile-meta dt { color: var(--text-3); }
.profile-meta dd { margin: 0; color: var(--text-2); }
.profile-json { margin-top: 10px; border-top: 1px dashed var(--line); padding-top: 8px; }
.profile-json summary { cursor: pointer; color: var(--text-3); font-size: 11px; }
.profile-json pre { max-height: 280px; overflow: auto; margin: 8px 0 0; padding: 10px; border-radius: 8px; background: var(--bg-soft); color: var(--text-2); font-size: 11px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.badge { padding: 2px 7px; border: 1px solid var(--line); border-radius: 999px; color: var(--text-3); font-size: 10px; }
.btn-sm { padding: 4px 8px; font-size: 11px; }
.empty-state { margin-top: 20px; padding: 28px; text-align: center; color: var(--text-3); border: 1px dashed var(--line); border-radius: 10px; }
.inline-error { color: var(--danger); font-size: 12px; }
</style>

