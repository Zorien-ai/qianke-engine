<script setup>
/**
 * Token 账单：钱包、套餐、用量、充值（演示支付）与自动开票。
 * 内部成本价先可见；销售价由管理端后续配置。
 */
import { computed, onMounted, ref } from "vue";
import { getJson, postJson } from "../api";
import { toast, toastError } from "../store";

const wallet = ref(null);
const packs = ref([]);
const usage = ref([]);
const invoices = ref([]);
const loading = ref(true);
const error = ref("");
const recharging = ref("");
const selectedRange = ref("30d");

const balance = computed(() => Number(wallet.value?.balance_tokens || 0));
const planUsed = computed(() => Number(wallet.value?.plan_used_tokens || 0));
const planTokens = computed(() => Number(wallet.value?.plan_tokens || 0));
const usagePct = computed(() => (planTokens.value ? Math.min(100, (planUsed.value / planTokens.value) * 100) : 0));
const totalTokens = computed(() => usage.value.reduce((n, x) => n + Number(x.tokens || 0), 0));
const totalCost = computed(() => usage.value.reduce((n, x) => n + Number(x.cost || 0), 0));
const totalSales = computed(() => usage.value.reduce((n, x) => n + Number(x.sales || 0), 0));

function num(value) { return Number(value || 0).toLocaleString(); }
function money(value) { const n = Number(value || 0); return `¥${n.toFixed(Math.abs(n) > 0 && Math.abs(n) < 0.01 ? 4 : 2)}`; }
function date(value) { return value ? String(value).replace("T", " ").slice(0, 19) : "—"; }

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [w, p, u, inv] = await Promise.all([
      getJson("/api/billing/wallet"),
      getJson("/api/billing/packs"),
      getJson(`/api/billing/usage?range=${selectedRange.value}`),
      getJson("/api/billing/invoices"),
    ]);
    wallet.value = w.wallet;
    packs.value = p.items || [];
    usage.value = u.items || [];
    invoices.value = inv.items || [];
  } catch (e) {
    error.value = e.detail || e.message || "账单数据加载失败";
  } finally {
    loading.value = false;
  }
}

async function recharge(pack) {
  if (recharging.value) return;
  recharging.value = pack.pack_id;
  try {
    const result = await postJson("/api/billing/recharge", { pack_id: pack.pack_id });
    toast(`充值成功：${num(result.tokens)} Token，已自动开票`, "success");
    await load();
  } catch (e) {
    toastError(e);
  } finally {
    recharging.value = "";
  }
}

function viewInvoice(invoice) {
  window.open(`/api/billing/invoices/${encodeURIComponent(invoice.invoice_id)}/html`, "_blank", "noopener");
}

onMounted(load);
</script>

<template>
  <div class="page billing-page">
    <div class="billing-hero">
      <div>
        <div class="monitor-kicker">TOKEN WALLET · INVOICING</div>
        <div class="billing-title-line">
          <h2>Token 账单</h2>
          <span class="badge is-primary">按 Token 计费</span>
        </div>
        <p class="card-sub">当前数据空间的 Token 余额、用量与发票。销售价尚未配置时，页面展示内部成本价。</p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="card"><div class="skeleton" style="height:110px"></div></div>
    <div v-else-if="error" class="card">
      <div class="empty-state">
        <div class="empty-emoji">🧾</div>
        <div class="empty-title">账单加载失败</div>
        <div class="empty-desc">{{ error }}</div>
        <button type="button" class="btn btn-primary" @click="load">重试</button>
      </div>
    </div>

    <template v-else-if="wallet">
      <div class="wallet-card">
        <div class="wallet-main">
          <span class="wallet-label">可用 Token 余额</span>
          <b>{{ num(balance) }}</b>
          <span class="wallet-sub">套餐 {{ wallet.plan_name || "Trial" }} · 本周期已用 {{ num(planUsed) }} / {{ num(planTokens) }}</span>
          <div class="wallet-bar"><i :style="{ width: `${usagePct}%` }"></i></div>
        </div>
        <div class="wallet-side">
          <div><span>本周期成本</span><b>{{ money(totalCost) }}</b></div>
          <div><span>销售金额</span><b>{{ money(totalSales) }}</b></div>
          <div><span>发票</span><b>{{ invoices.length }} 张</b></div>
        </div>
      </div>

      <section class="card" style="margin-top:16px">
        <div class="billing-section-head">
          <div><strong>Token 包</strong><span class="field-hint">演示环境：点击后模拟支付成功并自动开票</span></div>
          <span class="badge">内部成本价 / 销售价待配置</span>
        </div>
        <div class="pack-grid">
          <article v-for="pack in packs" :key="pack.pack_id" class="pack-card">
            <span class="pack-name">{{ pack.name }}</span>
            <b>{{ money(pack.price) }}</b>
            <span class="pack-tokens">{{ num(pack.tokens) }} tokens</span>
            <button type="button" class="btn btn-primary" :disabled="!!recharging" @click="recharge(pack)">
              {{ recharging === pack.pack_id ? "处理中…" : "充值" }}
            </button>
          </article>
        </div>
      </section>

      <div class="billing-grid">
        <section class="card">
          <div class="billing-section-head"><strong>用量明细</strong><span class="field-hint">按功能 / 模型</span></div>
          <div class="table-wrap">
            <table class="table">
              <thead><tr><th>功能</th><th>模型</th><th>调用</th><th>Token</th><th>内部成本</th><th>销售金额</th></tr></thead>
              <tbody>
                <tr v-for="item in usage" :key="`${item.feature}-${item.model}`">
                  <td>{{ item.feature }}</td><td>{{ item.model }}</td><td>{{ num(item.calls) }}</td>
                  <td>{{ num(item.tokens) }}</td><td>{{ money(item.cost) }}</td><td>{{ money(item.sales) }}</td>
                </tr>
                <tr v-if="!usage.length"><td colspan="6" class="field-hint">暂无用量</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="card">
          <div class="billing-section-head"><strong>发票</strong><span class="field-hint">自动开票记录</span></div>
          <div v-if="!invoices.length" class="empty-desc" style="padding:20px 0">暂无发票</div>
          <div v-else class="invoice-list">
            <div v-for="inv in invoices" :key="inv.invoice_id" class="invoice-row">
              <div>
                <strong>{{ inv.title || "Token 服务发票" }}</strong>
                <span>{{ inv.invoice_id }} · {{ date(inv.created_at) }}</span>
              </div>
              <b>{{ money(inv.amount) }}</b>
              <button type="button" class="btn btn-sm btn-ghost" @click="viewInvoice(inv)">查看</button>
            </div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.billing-page { max-width: 1250px; }
.billing-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 18px; }
.monitor-kicker { font-family: var(--font-mono, monospace); font-size: 10px; letter-spacing: .14em; color: var(--primary); font-weight: 700; }
.billing-title-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.billing-title-line h2 { margin: 0; font-size: 22px; }
.wallet-card { display: flex; justify-content: space-between; gap: 20px; flex-wrap: wrap; padding: 22px; border: 1px solid var(--border); border-radius: 14px; background: radial-gradient(300px 120px at 100% 0%, var(--primary-soft), transparent 70%), var(--surface); }
.wallet-main { min-width: 280px; flex: 1; }
.wallet-label { display: block; color: var(--muted); font-size: 12px; }
.wallet-main b { display: block; margin-top: 8px; font-size: 34px; letter-spacing: -.04em; }
.wallet-sub { display: block; margin-top: 6px; color: var(--muted); font-size: 11.5px; }
.wallet-bar { width: min(460px, 100%); height: 5px; margin-top: 14px; overflow: hidden; border-radius: 99px; background: var(--border); }
.wallet-bar i { display: block; height: 100%; border-radius: inherit; background: var(--primary); }
.wallet-side { display: flex; gap: 28px; flex-wrap: wrap; align-items: flex-end; }
.wallet-side div { display: flex; flex-direction: column; gap: 5px; }
.wallet-side span { color: var(--muted); font-size: 11px; }
.wallet-side b { font-size: 17px; }
.billing-section-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.billing-section-head strong { font-size: 14px; }
.billing-section-head .field-hint { margin-left: 8px; }
.pack-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.pack-card { display: flex; flex-direction: column; gap: 7px; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface-2); }
.pack-name { color: var(--muted); font-size: 12px; }
.pack-card b { font-size: 25px; }
.pack-tokens { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
.billing-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 16px; margin-top: 16px; }
.invoice-list { display: flex; flex-direction: column; gap: 6px; }
.invoice-row { display: flex; align-items: center; gap: 8px; padding: 9px 0; border-bottom: 1px solid var(--border); }
.invoice-row > div { flex: 1; min-width: 0; }
.invoice-row strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.invoice-row span { display: block; color: var(--muted); font-size: 10.5px; margin-top: 3px; }
.invoice-row b { font-size: 12px; }
@media (max-width: 900px) { .billing-grid { grid-template-columns: 1fr; } .pack-grid { grid-template-columns: 1fr; } }
</style>
