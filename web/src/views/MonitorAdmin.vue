<script setup>
/**
 * 平台管理端：租户消耗排行 + 模型销售价配置。
 * 内部成本价不可在页面修改；销售价留空表示暂未定价。
 */
import { onMounted, ref } from "vue";
import { getJson, putJson } from "../api";
import { toast, toastError } from "../store";

const tenants = ref([]);
const prices = ref([]);
const loading = ref(true);
const error = ref("");
const saving = ref(false);

function num(value) { return Number(value || 0).toLocaleString(); }
function money(value) { const n = Number(value || 0); return `¥${n.toFixed(Math.abs(n) > 0 && Math.abs(n) < 0.01 ? 4 : 2)}`; }
function date(value) { return value ? String(value).replace("T", " ").slice(0, 19) : "—"; }

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [t, p] = await Promise.all([
      getJson("/api/admin/monitor/tenants"),
      getJson("/api/admin/billing/prices"),
    ]);
    tenants.value = t.items || [];
    prices.value = (p.items || []).map((x) => ({
      ...x,
      input_sale_per_1k: x.input_sale_per_1k ?? "",
      output_sale_per_1k: x.output_sale_per_1k ?? "",
    }));
  } catch (e) {
    error.value = e.detail || e.message || "管理数据加载失败";
  } finally {
    loading.value = false;
  }
}

async function savePrices() {
  if (saving.value) return;
  saving.value = true;
  try {
    const items = prices.value.map((x) => ({
      model: x.model,
      input_sale_per_1k: x.input_sale_per_1k === "" ? null : Number(x.input_sale_per_1k),
      output_sale_per_1k: x.output_sale_per_1k === "" ? null : Number(x.output_sale_per_1k),
    }));
    const resp = await putJson("/api/admin/billing/prices", { items });
    prices.value = (resp.items || []).map((x) => ({
      ...x,
      input_sale_per_1k: x.input_sale_per_1k ?? "",
      output_sale_per_1k: x.output_sale_per_1k ?? "",
    }));
    toast("销售价已保存", "success");
  } catch (e) {
    toastError(e);
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="page admin-page">
    <div class="admin-hero">
      <div>
        <div class="monitor-kicker">PLATFORM CONTROL</div>
        <div class="admin-title-line"><h2>平台监控与计费</h2><span class="badge is-warn">系统管理员</span></div>
        <p class="card-sub">跨租户 Token / 成本排行与模型销售价配置。内部成本价只读，销售价留空表示暂未定价。</p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="card"><div class="skeleton" style="height:100px"></div></div>
    <div v-else-if="error" class="card"><div class="empty-state"><div class="empty-title">加载失败</div><div class="empty-desc">{{ error }}</div></div></div>
    <template v-else>
      <section class="card">
        <div class="admin-section-head"><strong>租户消耗排行</strong><span class="field-hint">最近 100 个租户</span></div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>租户</th><th>请求</th><th>Token</th><th>内部成本</th><th>余额</th><th>最近活跃</th></tr></thead>
            <tbody>
              <tr v-for="t in tenants" :key="t.tenant_id">
                <td>{{ t.name }} <span class="field-hint">{{ t.tenant_id }}</span></td>
                <td>{{ num(t.requests) }}</td><td>{{ num(t.tokens) }}</td><td>{{ money(t.cost) }}</td>
                <td>{{ num(t.balance_tokens) }}</td><td>{{ date(t.last_seen) }}</td>
              </tr>
              <tr v-if="!tenants.length"><td colspan="6" class="field-hint">暂无租户数据</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card" style="margin-top:16px">
        <div class="admin-section-head"><strong>模型价格</strong><span class="field-hint">内部成本只读 · 销售价可配置</span></div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>模型</th><th>输入成本 / 1K</th><th>输出成本 / 1K</th><th>输入销售价 / 1K</th><th>输出销售价 / 1K</th></tr></thead>
            <tbody>
              <tr v-for="p in prices" :key="p.model">
                <td>{{ p.model }}</td>
                <td>{{ money(p.input_cost_per_1k) }}</td>
                <td>{{ money(p.output_cost_per_1k) }}</td>
                <td><input v-model="p.input_sale_per_1k" type="number" min="0" step="0.0001" placeholder="未定价" class="price-input" /></td>
                <td><input v-model="p.output_sale_per_1k" type="number" min="0" step="0.0001" placeholder="未定价" class="price-input" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="row-actions" style="justify-content:flex-end;margin-top:12px">
          <button type="button" class="btn btn-primary" :disabled="saving" @click="savePrices">{{ saving ? "保存中…" : "保存销售价" }}</button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.admin-page { max-width: 1250px; }
.admin-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }
.monitor-kicker { font-family: var(--font-mono, monospace); font-size: 10px; letter-spacing: .14em; color: var(--primary); font-weight: 700; }
.admin-title-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.admin-title-line h2 { margin: 0; font-size: 22px; }
.admin-section-head { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; font-size: 13px; }
.price-input { width: 130px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface-2); color: var(--text); font-size: 12px; }
</style>
