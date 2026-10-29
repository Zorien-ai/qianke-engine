<script setup>
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api";
import { toastError } from "../store";

const orders = ref([]);
const quotes = ref([]);
const summary = ref({});
const loading = ref(true);
const error = ref("");

function money(value) {
  return `¥${Number(value || 0).toFixed(2)}`;
}
function date(value) {
  return value ? String(value).replace("T", " ").slice(0, 19) : "—";
}
function policyLabel(policy) {
  return policy.title || policy.policy_id || "政策";
}
function productLabel(product) {
  return product.title || product.product_id || "商品";
}

const pendingQuotes = computed(() => summary.value.pending_quotes || 0);
const quoteStatus = computed(() => summary.value.quote_status || {});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await getJson("/api/c/admin/audit?limit=50");
    orders.value = data?.orders || [];
    quotes.value = data?.quotes || [];
    summary.value = data?.summary || {};
  } catch (e) {
    error.value = e?.detail || e?.message || "审计数据加载失败";
    toastError?.(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="page admin-page">
    <div class="admin-hero">
      <div>
        <div class="monitor-kicker">C-END AUDIT</div>
        <div class="admin-title-line">
          <h2>C 端交易审计</h2>
          <span class="badge is-warn">系统管理员</span>
        </div>
        <p class="card-sub">
          查看聊天报价、订单和活动政策的绑定关系；只读，不提供改价或改单入口。
        </p>
      </div>
      <button type="button" class="btn btn-ghost" :disabled="loading" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="card"><div class="skeleton" style="height:100px"></div></div>
    <div v-else-if="error" class="card">
      <div class="empty-state">
        <div class="empty-title">加载失败</div>
        <div class="empty-desc">{{ error }}</div>
      </div>
    </div>

    <template v-else>
      <section class="audit-stats">
        <div class="audit-stat">
          <span>已确认订单</span>
          <strong>{{ summary.order_count || 0 }}</strong>
          <small>最近 50 条</small>
        </div>
        <div class="audit-stat">
          <span>成交金额</span>
          <strong>{{ money(summary.gmv || 0) }}</strong>
          <small>按订单应付合计</small>
        </div>
        <div class="audit-stat">
          <span>报价记录</span>
          <strong>{{ summary.quote_count || 0 }}</strong>
          <small>最近 50 条</small>
        </div>
        <div class="audit-stat">
          <span>待确认报价</span>
          <strong>{{ pendingQuotes }}</strong>
          <small>PENDING</small>
        </div>
      </section>

      <section class="card">
        <div class="admin-section-head">
          <strong>订单与报价绑定</strong>
          <span class="field-hint">quote_id / policy_ids / 原价 / 优惠</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>订单</th>
                <th>买家</th>
                <th>报价</th>
                <th>政策</th>
                <th>原价</th>
                <th>优惠</th>
                <th>应付</th>
                <th>确认时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="order in orders" :key="order.order_id">
                <td class="mono">{{ order.order_id }}</td>
                <td>{{ order.buyer_id }}</td>
                <td class="mono">{{ order.quote_id || "—" }}</td>
                <td>
                  <span v-for="policy in order.policy_ids" :key="policy" class="audit-chip">{{ policy }}</span>
                  <span v-if="!order.policy_ids?.length" class="field-hint">—</span>
                </td>
                <td>{{ money(order.original_amount) }}</td>
                <td>{{ money(order.discount_amount) }}</td>
                <td><strong>{{ money(order.total_amount) }}</strong></td>
                <td class="field-hint">{{ date(order.confirmed_at) }}</td>
              </tr>
              <tr v-if="!orders.length">
                <td colspan="8" class="field-hint">暂无已确认订单</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card" style="margin-top:16px">
        <div class="admin-section-head">
          <strong>结构化报价</strong>
          <span class="field-hint">
            {{ quoteStatus.PENDING || 0 }} pending · {{ quoteStatus.CONSUMED || 0 }} consumed · {{ quoteStatus.CANCELLED || 0 }} cancelled
          </span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>报价</th>
                <th>买家</th>
                <th>状态</th>
                <th>商品</th>
                <th>政策</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="quote in quotes" :key="quote.quote_id">
                <td class="mono">{{ quote.quote_id }}</td>
                <td>{{ quote.buyer_id }}</td>
                <td><span class="badge" :class="{ 'is-ok': quote.status === 'CONSUMED', 'is-warn': quote.status === 'PENDING' }">{{ quote.status }}</span></td>
                <td>
                  <span v-for="product in quote.product_refs" :key="product.product_id" class="audit-chip">
                    {{ productLabel(product) }} × {{ product.quantity || 1 }}
                  </span>
                  <span v-if="!quote.product_refs?.length" class="field-hint">—</span>
                </td>
                <td>
                  <span v-for="policy in quote.policy_refs" :key="policy.policy_id" class="audit-chip">
                    {{ policyLabel(policy) }}
                  </span>
                  <span v-if="!quote.policy_refs?.length" class="field-hint">—</span>
                </td>
                <td class="field-hint">{{ date(quote.created_at) }}</td>
              </tr>
              <tr v-if="!quotes.length">
                <td colspan="6" class="field-hint">暂无报价记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.audit-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.audit-stat {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface);
}

.audit-stat span {
  color: var(--muted);
  font-size: 11px;
}

.audit-stat strong {
  font-family: var(--mono);
  font-size: 22px;
  font-weight: 600;
}

.audit-stat small {
  color: var(--muted);
  font-size: 9px;
}

.audit-chip {
  display: inline-block;
  margin: 1px 3px 1px 0;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 10px;
}

.mono {
  font-family: var(--mono);
  font-size: 10px;
}

.admin-section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
}

@media (max-width: 820px) {
  .audit-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
