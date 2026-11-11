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

    <section class="card sop-card">
      <header class="sop-head">
        <div>
          <h3>商家级 SOP</h3>
          <p>店宠的商品/售后/发货口径按 merchant_id 读取，不再共用一套。</p>
        </div>
        <button class="btn btn-ghost" type="button" :disabled="sopLoading" @click="loadSops">
          {{ sopLoading ? "刷新中…" : "刷新" }}
        </button>
      </header>
      <div class="sop-fields">
        <label><span>商家 ID</span><input v-model="sopMerchantId" class="input" placeholder="m_tea_001" /></label>
        <label><span>主题</span><input v-model="sopTopic" class="input" placeholder="shipping" /></label>
        <label><span>标题</span><input v-model="sopTitle" class="input" placeholder="茶叶发货时效" /></label>
        <label class="sop-content"><span>内容</span><textarea v-model="sopContent" rows="3" class="input" /></label>
        <button class="btn btn-primary" type="button" :disabled="sopSaving" @click="saveSop">
          {{ sopSaving ? "保存中…" : "保存 SOP" }}
        </button>
      </div>
      <p v-if="sopError" class="inline-error" role="alert">{{ sopError }}</p>
      <p v-if="sopMessage" class="sop-success" role="status">{{ sopMessage }}</p>
      <div class="sop-list">
        <article v-for="sop in sops" :key="`${sop.merchant_id}:${sop.topic}`" class="sop-row">
          <strong>{{ sop.merchant_id }} · {{ sop.title }}</strong>
          <p>{{ sop.content }}</p>
        </article>
        <p v-if="!sops.length && !sopLoading" class="empty-state">还没有商家 SOP。</p>
      </div>
    </section>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { getJson, postJson, putJson } from "../api";
import { toast } from "../store";

const items = ref([]);
const loading = ref(false);
const binding = ref(false);
const error = ref("");
const merchantId = ref("");
const friendId = ref("");
const sops = ref([]);
const sopLoading = ref(false);
const sopSaving = ref(false);
const sopError = ref("");
const sopMessage = ref("");
const sopMerchantId = ref("m_tea_001");
const sopTopic = ref("shipping");
const sopTitle = ref("茶叶发货时效");
const sopContent = ref("茶叶现货 48 小时内发出，礼盒装会加防震包装。");

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await getJson("/api/c/admin/merchant-store-friends");
    items.value = Array.isArray(data?.items) ? data.items : [];
    await loadSops();
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

async function loadSops() {
  sopLoading.value = true;
  try {
    const data = await getJson("/api/c/admin/merchant-sops");
    sops.value = Array.isArray(data?.items) ? data.items : [];
  } catch (exc) {
    sopError.value = exc?.detail || exc?.message || "SOP 加载失败";
  } finally {
    sopLoading.value = false;
  }
}

async function saveSop() {
  if (sopSaving.value) return;
  const merchant = sopMerchantId.value.trim();
  const topic = sopTopic.value.trim();
  const title = sopTitle.value.trim();
  const content = sopContent.value.trim();
  if (!merchant || !topic || !title || !content) return;
  sopSaving.value = true;
  sopError.value = "";
  sopMessage.value = "";
  try {
    await putJson("/api/c/admin/merchant-sops", {
      merchant_id: merchant,
      topic,
      title,
      content,
    });
    sopMessage.value = "SOP 已保存";
    await loadSops();
  } catch (exc) {
    sopError.value = exc?.detail || exc?.message || "SOP 保存失败";
  } finally {
    sopSaving.value = false;
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


.sop-card { margin-top: 16px; padding: 14px 16px; }
.sop-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.sop-head h3 { margin: 0; }
.sop-head p { margin: 4px 0 0; color: var(--text-3); font-size: 11px; }
.sop-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 12px; align-items: end; }
.sop-fields label { display: flex; flex-direction: column; gap: 4px; }
.sop-fields label span { color: var(--text-3); font-size: 11px; }
.sop-fields .sop-content { grid-column: 1 / -1; }
.sop-fields textarea { resize: vertical; }
.sop-fields .btn { justify-self: start; }
.sop-success { color: var(--success); font-size: 12px; }
.sop-list { display: flex; flex-direction: column; gap: 7px; margin-top: 12px; }
.sop-row { padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-2); }
.sop-row strong { font-size: 12px; }
.sop-row p { margin: 3px 0 0; color: var(--text-2); font-size: 11px; }
</style>
