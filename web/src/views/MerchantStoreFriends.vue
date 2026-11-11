<template>
  <section class="page merchant-friends-page">
    <header class="page-head">
      <div>
        <h2>店宠映射</h2>
        <p class="page-desc">
          把一个 C 端店宠 `friend_id` 绑定到真实商家。绑定后 B 端画像扫描器才会处理该商家的会话。
        </p>
      </div>
      <button class="btn btn-ghost" type="button" :disabled="loading" @click="load">
        {{ loading ? "刷新中…" : "刷新" }}
      </button>
    </header>

    <p v-if="error" class="inline-error" role="alert">{{ error }}</p>

    <form class="card bind-card" @submit.prevent="bind">
      <div class="bind-fields">
        <label>
          <span>商家 ID</span>
          <input v-model="merchantId" class="input" placeholder="m_tea_001" required />
        </label>
        <label>
          <span>店宠 friend_id</span>
          <input v-model="friendId" class="input" placeholder="store_tea" required />
        </label>
        <button class="btn btn-primary" type="submit" :disabled="binding">
          {{ binding ? "绑定中…" : "绑定" }}
        </button>
      </div>
      <p class="bind-hint">friend_id 必须先存在于 C 端好友表，否则画像扫描不会产生会话。</p>
    </form>

    <div v-if="loading && !items.length" class="empty-state">正在加载映射…</div>
    <div v-else-if="!items.length" class="empty-state">还没有店宠映射。</div>
    <div v-else class="mapping-list">
      <article v-for="item in items" :key="`${item.merchant_id}:${item.friend_id}`" class="card mapping-card">
        <div>
          <strong>{{ item.merchant_name || item.merchant_id }}</strong>
          <code>{{ item.merchant_id }}</code>
        </div>
        <div class="mapping-right">
          <span class="mapping-friend">{{ item.friend_id }}</span>
          <span class="mapping-status">已绑定</span>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { getJson, postJson } from "../api";
import { toast } from "../store";

const items = ref([]);
const loading = ref(false);
const binding = ref(false);
const error = ref("");
const merchantId = ref("");
const friendId = ref("");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await getJson("/api/c/admin/merchant-store-friends");
    items.value = Array.isArray(data?.items) ? data.items : [];
  } catch (exc) {
    error.value = exc?.detail || exc?.message || "映射加载失败";
  } finally {
    loading.value = false;
  }
}

async function bind() {
  const merchant = merchantId.value.trim();
  const friend = friendId.value.trim();
  if (!merchant || !friend) return;
  binding.value = true;
  error.value = "";
  try {
    await postJson("/api/c/admin/merchant-store-friends", {
      merchant_id: merchant,
      friend_id: friend,
    });
    toast("店宠映射已绑定", "success");
    merchantId.value = "";
    friendId.value = "";
    await load();
  } catch (exc) {
    error.value = exc?.detail || exc?.message || "绑定失败";
  } finally {
    binding.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.merchant-friends-page { max-width: 900px; }
.page-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.page-desc { margin: 6px 0 0; color: var(--text-2); font-size: 12px; line-height: 1.7; }
.bind-card { margin-top: 16px; padding: 14px 16px; }
.bind-fields { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }
.bind-fields label { display: flex; flex: 1; min-width: 190px; flex-direction: column; gap: 5px; }
.bind-fields label span { color: var(--text-3); font-size: 11px; }
.bind-hint { margin: 9px 0 0; color: var(--text-3); font-size: 11px; }
.mapping-list { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.mapping-card { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 14px; }
.mapping-card strong { margin-right: 9px; }
.mapping-card code { color: var(--text-3); font-size: 11px; }
.mapping-right { display: flex; align-items: center; gap: 10px; }
.mapping-friend { font-family: var(--mono); color: var(--text-2); font-size: 11px; }
.mapping-status { padding: 2px 7px; border: 1px solid var(--line); border-radius: 999px; color: var(--text-3); font-size: 10px; }
.empty-state { margin-top: 18px; padding: 28px; text-align: center; color: var(--text-3); border: 1px dashed var(--line); border-radius: 10px; }
.inline-error { color: var(--danger); font-size: 12px; }
</style>
