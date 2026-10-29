<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getJson, postJson } from "../api";

const route = useRoute();
const products = ref([]);
const productsLoading = ref(true);
const productsError = ref("");
const companion = ref(null);
const companionError = ref("");
const quote = ref(null);
const quoteError = ref("");
const quoteDraft = ref(null);
const quoteOrder = ref(null);
const quoteBusy = ref(false);
const message = ref("我想买一双轻量跑鞋，预算 500 元以内");
const running = ref(false);
const agentError = ref("");
const reply = ref("");
const draft = ref(null);
const order = ref(null);
const threadId = ref("");
const decisionLoading = ref(false);
const lastAction = ref("");

const hasDraft = computed(() => !!draft.value);
const hasOrder = computed(() => !!order.value);
const canSend = computed(() => !running.value && !decisionLoading.value && !hasDraft.value && message.value.trim().length > 0);

function money(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function productHint(product) {
  return product.stock > 0 ? `库存 ${product.stock}` : "暂时缺货";
}

function speciesLabel(species) {
  const labels = {
    digital_companion: "数字伙伴",
    cat: "猫",
    fish: "鱼",
    robot: "机器人",
    brand_mascot: "品牌吉祥物",
  };
  return labels[species] || species || "伙伴";
}

async function loadCompanion() {
  companionError.value = "";
  try {
    companion.value = await getJson("/api/c/companion");
  } catch (e) {
    companionError.value = e?.detail || e?.message || "伙伴状态加载失败";
  }
}

async function loadQuote() {
  const quoteId = typeof route.query.quote === "string" ? route.query.quote : "";
  if (!quoteId) return;
  try {
    quote.value = await getJson(`/api/c/quotes/${encodeURIComponent(quoteId)}`);
  } catch (e) {
    quoteError.value = e?.detail || e?.message || "聊天报价不存在或已失效";
  }
}

async function prepareQuote() {
  if (!quote.value || quoteBusy.value) return;
  quoteBusy.value = true;
  quoteError.value = "";
  try {
    quoteDraft.value = await postJson(`/api/c/quotes/${encodeURIComponent(quote.value.quote_id)}/prepare`, {});
  } catch (e) {
    quoteError.value = e?.detail || e?.message || "报价转订单失败";
  } finally {
    quoteBusy.value = false;
  }
}

async function confirmQuote() {
  if (!quoteDraft.value || quoteBusy.value) return;
  quoteBusy.value = true;
  quoteError.value = "";
  try {
    const requestId = `c_quote_${Date.now()}`;
    quoteOrder.value = await postJson(
      `/api/c/orders/${encodeURIComponent(quoteDraft.value.order_id)}/confirm`,
      {
        confirmation_token: quoteDraft.value.confirmation_token,
        request_id: requestId,
      }
    );
    quoteDraft.value = null;
    await loadCompanion();
  } catch (e) {
    quoteError.value = e?.detail || e?.message || "订单确认失败";
  } finally {
    quoteBusy.value = false;
  }
}

async function loadProducts() {
  productsLoading.value = true;
  productsError.value = "";
  try {
    const data = await getJson("/api/c/products?limit=12");
    products.value = data?.products || [];
  } catch (e) {
    productsError.value = e?.detail || e?.message || "商品加载失败";
  } finally {
    productsLoading.value = false;
  }
}

async function runAgent() {
  if (!canSend.value) return;
  running.value = true;
  agentError.value = "";
  lastAction.value = "";
  try {
    const data = await postJson("/api/c/agent/run", { message: message.value.trim() });
    reply.value = data?.reply || "";
    threadId.value = data?.thread_id || "";
    if (data?.requires_confirmation && data?.draft) {
      draft.value = data.draft;
      order.value = null;
      lastAction.value = "请核对订单后确认";
    } else if (data?.order) {
      order.value = data.order;
      draft.value = null;
      lastAction.value = "订单已确认";
    }
  } catch (e) {
    agentError.value = e?.detail || e?.message || "导购服务暂时不可用";
  } finally {
    running.value = false;
  }
}

async function decide(approved) {
  if (!threadId.value || !hasDraft.value || decisionLoading.value) return;
  decisionLoading.value = true;
  agentError.value = "";
  try {
    const data = await postJson("/api/c/agent/resume", {
      thread_id: threadId.value,
      approved,
    });
    reply.value = data?.reply || reply.value;
    if (data?.order) {
      order.value = data.order;
      lastAction.value = "订单已确认";
    } else {
      lastAction.value = approved ? "确认完成" : "订单已取消";
    }
    draft.value = null;
    threadId.value = "";
    if (approved) await loadCompanion();
  } catch (e) {
    agentError.value = e?.detail || e?.message || "订单确认失败";
  } finally {
    decisionLoading.value = false;
  }
}

function useProduct(product) {
  message.value = `我想买 ${product.title}，预算 ${Math.ceil(product.price)} 元`;
}

onMounted(() => {
  loadProducts();
  loadCompanion();
  loadQuote();
});
</script>

<template>
  <div class="shop-page">
    <header class="shop-head">
      <div>
        <p class="shop-kicker">C-END · SHOPPING</p>
        <h2>C 端商城体验</h2>
        <p class="shop-subtitle">
          告诉导购你的需求，Agent 会从真实 mock 商品库推荐，并在你确认后才创建模拟订单。
        </p>
      </div>
      <span class="shop-status" role="status">
        <span class="status-dot" />
        模拟订单 · 不接真实支付
      </span>
    </header>

    <section class="shop-grid" aria-label="商品与导购">
      <div class="catalog-panel">
        <div class="panel-head">
          <div>
            <h3>商品目录</h3>
            <p>价格和库存来自确定性商品库</p>
          </div>
          <span class="count">{{ products.length }} 件</span>
        </div>

        <p v-if="productsLoading" class="state-line" role="status">正在加载商品…</p>
        <p v-else-if="productsError" class="state-line state-error" role="alert">{{ productsError }}</p>
        <div v-else-if="!products.length" class="state-box">
          <strong>暂无商品</strong>
          <p>商品库为空，暂时无法推荐。</p>
        </div>
        <div v-else class="product-list">
          <article v-for="product in products" :key="product.product_id" class="product-row">
            <div class="product-mark">{{ product.category.slice(0, 1) }}</div>
            <div class="product-main">
              <div class="product-top">
                <h4>{{ product.title }}</h4>
                <span class="category">{{ product.category }}</span>
              </div>
              <p>{{ product.product_id }} · {{ productHint(product) }}</p>
            </div>
            <div class="product-side">
              <strong>¥{{ money(product.price) }}</strong>
              <button class="ghost-btn" type="button" @click="useProduct(product)">咨询</button>
            </div>
          </article>
        </div>
      </div>

      <div class="assistant-panel">
        <div class="panel-head">
          <div>
            <h3>导购 Agent</h3>
            <p>推荐 → 草稿 → 你确认 → 模拟下单</p>
          </div>
          <span class="agent-badge">LangGraph</span>
        </div>

        <div v-if="companion" class="companion-box">
          <div class="companion-mark" aria-hidden="true">{{ companion.name.slice(0, 1) }}</div>
          <div class="companion-main">
            <span class="companion-label">我的伙伴</span>
            <strong>{{ companion.name }}</strong>
            <p>{{ speciesLabel(companion.species) }} · Lv.{{ companion.level }}</p>
          </div>
          <div class="companion-stats">
            <span>饱食度</span>
            <div
              class="satiety-track"
              role="progressbar"
              :aria-valuenow="companion.satiety"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-label="`${companion.name} 饱食度`"
            >
              <span :style="{ width: `${companion.satiety}%` }" />
            </div>
            <small>{{ companion.satiety }}/100</small>
          </div>
        </div>
        <p v-if="companionError" class="state-line state-error" role="alert">{{ companionError }}</p>

        <section v-if="quote" class="quote-panel" aria-label="聊天报价">
          <div class="quote-panel-head">
            <div>
              <span class="quote-kicker">来自聊天的结构化报价</span>
              <h4>{{ quote.quote_id }}</h4>
            </div>
            <span class="quote-status">{{ quoteOrder ? "已确认" : "待确认" }}</span>
          </div>
          <div class="quote-chips">
            <span v-for="product in quote.product_refs" :key="product.product_id" class="quote-chip">
              {{ product.title || product.product_id }}
            </span>
            <span v-for="policy in quote.policy_refs" :key="policy.policy_id" class="quote-chip policy">
              {{ policy.title || policy.policy_id }}
            </span>
          </div>
          <p v-if="quoteDraft" class="quote-hint">
            草稿金额 ¥{{ money(quoteDraft.original_amount) }}
            <template v-if="quoteDraft.discount_amount"> · 优惠 ¥{{ money(quoteDraft.discount_amount) }}</template>
            · 应付 ¥{{ money(quoteDraft.total_amount) }}
          </p>
          <p v-else class="quote-hint">报价只做引用；确认后才会扣库存。</p>
          <p v-if="quoteError" class="state-line state-error" role="alert">{{ quoteError }}</p>

          <div v-if="quoteOrder" class="quote-order" role="status">
            已创建 {{ quoteOrder.order_id }} · 应付 ¥{{ money(quoteOrder.total_amount) }}
          </div>
          <div v-else-if="quoteDraft" class="quote-actions">
            <button class="ghost-btn" type="button" :disabled="quoteBusy" @click="quoteDraft = null">
              返回
            </button>
            <button class="primary-btn" type="button" :disabled="quoteBusy" @click="confirmQuote">
              {{ quoteBusy ? "提交中…" : "确认并创建模拟订单" }}
            </button>
          </div>
          <div v-else class="quote-actions">
            <button class="primary-btn" type="button" :disabled="quoteBusy" @click="prepareQuote">
              {{ quoteBusy ? "准备中…" : "使用此报价准备订单" }}
            </button>
          </div>
        </section>

        <label class="field-label" for="shop-message">你想买什么？</label>
        <textarea
          id="shop-message"
          v-model="message"
          class="shop-input"
          rows="3"
          :disabled="running || hasDraft"
          placeholder="例如：我想买一双跑鞋，预算 500 元以内"
          @keydown.ctrl.enter="runAgent"
          @keydown.meta.enter="runAgent"
        />
        <div class="send-row">
          <span class="hint">Ctrl / ⌘ + Enter 发送</span>
          <button class="primary-btn" type="button" :disabled="!canSend" @click="runAgent">
            <span v-if="running" class="spinner" aria-hidden="true" />
            {{ running ? "导购思考中…" : "发送给导购" }}
          </button>
        </div>

        <p v-if="agentError" class="state-line state-error" role="alert">{{ agentError }}</p>

        <div v-if="reply" class="reply-box" aria-live="polite">
          <span class="reply-label">导购回复</span>
          <p>{{ reply }}</p>
        </div>

        <section v-if="hasDraft" class="confirm-box" aria-live="polite">
          <div class="confirm-head">
            <div>
              <span class="confirm-kicker">待确认</span>
              <h4>订单草稿</h4>
            </div>
            <strong>¥{{ money(draft.total_amount) }}</strong>
          </div>
          <ul class="draft-items">
            <li v-for="item in draft.items" :key="item.product_id">
              <span>{{ item.title }}</span>
              <span>{{ item.quantity }} × ¥{{ money(item.unit_price) }}</span>
            </li>
          </ul>
          <p class="confirm-note">确认前不会扣库存；商品价格或库存变化后需要重新准备。</p>
          <div class="confirm-actions">
            <button class="ghost-btn" type="button" :disabled="decisionLoading" @click="decide(false)">
              取消
            </button>
            <button class="primary-btn" type="button" :disabled="decisionLoading" @click="decide(true)">
              <span v-if="decisionLoading" class="spinner" aria-hidden="true" />
              {{ decisionLoading ? "提交中…" : "确认并创建模拟订单" }}
            </button>
          </div>
        </section>

        <section v-if="hasOrder" class="order-box" aria-live="polite">
          <span class="confirm-kicker">已创建</span>
          <h4>模拟订单 {{ order.order_id }}</h4>
          <p>{{ order.items?.map((item) => `${item.title} × ${item.quantity}`).join(" / ") }}</p>
          <strong>¥{{ money(order.total_amount) }}</strong>
        </section>

        <p v-if="lastAction && !hasOrder" class="action-line" role="status">{{ lastAction }}</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.shop-page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 8px 0 40px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.shop-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.shop-kicker,
.confirm-kicker {
  margin: 0 0 6px;
  color: var(--primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.shop-head h2 {
  font-size: 24px;
}

.shop-subtitle {
  max-width: 650px;
  margin-top: 7px;
  color: var(--text-2);
  font-size: 13px;
}

.shop-status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: 0 0 auto;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-2);
  font-size: 11px;
  white-space: nowrap;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
}

.shop-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(380px, 0.95fr);
  gap: 18px;
  align-items: start;
}

.catalog-panel,
.assistant-panel {
  min-width: 0;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 13px;
  border-bottom: 1px solid var(--border);
}

.panel-head h3 {
  font-size: 16px;
}

.panel-head p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
}

.count,
.agent-badge {
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--surface-3);
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 11px;
  white-space: nowrap;
}

.companion-box {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.companion-mark {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 50%;
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 700;
}

.companion-main {
  min-width: 0;
  flex: 1;
}

.companion-label {
  display: block;
  color: var(--muted);
  font-size: 10px;
}

.companion-main strong {
  display: block;
  font-size: 13px;
}

.companion-main p {
  margin-top: 2px;
  color: var(--muted);
  font-size: 11px;
}

.companion-stats {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 4px;
  flex: 0 0 86px;
  color: var(--muted);
  font-size: 10px;
}

.satiety-track {
  width: 86px;
  height: 5px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--border);
}

.satiety-track > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
}

.companion-stats small {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 9px;
}

.quote-panel {
  margin-top: 12px;
  padding: 11px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.quote-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.quote-kicker {
  color: var(--primary);
  font-size: 10px;
  font-weight: 700;
}

.quote-panel-head h4 {
  margin-top: 3px;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 500;
}

.quote-status {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--warn-soft);
  color: var(--warn);
  font-size: 9px;
}

.quote-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}

.quote-chip {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 10px;
}

.quote-chip.policy {
  background: var(--primary-soft);
  color: var(--primary);
}

.quote-hint {
  margin-top: 8px;
  color: var(--muted);
  font-size: 10px;
}

.quote-actions {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
  margin-top: 9px;
}

.quote-order {
  margin-top: 9px;
  padding: 7px 8px;
  border-radius: var(--radius-xs);
  background: var(--success-soft);
  color: var(--success);
  font-size: 11px;
}

.product-list {
  display: flex;
  flex-direction: column;
}

.product-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}

.product-row:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.product-mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  border-radius: var(--radius-xs);
  background: var(--surface-3);
  color: var(--text-2);
  font-weight: 700;
}

.product-main {
  min-width: 0;
  flex: 1;
}

.product-top {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.product-top h4 {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.category {
  flex: 0 0 auto;
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 10px;
}

.product-main p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
}

.product-side {
  display: flex;
  align-items: flex-end;
  flex-direction: column;
  gap: 5px;
  flex: 0 0 auto;
}

.product-side strong {
  font-family: var(--mono);
  font-size: 13px;
}

.field-label {
  display: block;
  margin: 15px 0 6px;
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}

.shop-input {
  width: 100%;
  resize: vertical;
  min-height: 78px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text);
  font: inherit;
  font-size: 13px;
  line-height: 1.6;
}

.shop-input:focus {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.shop-input:disabled {
  cursor: not-allowed;
  opacity: 0.68;
}

.send-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 9px;
}

.hint {
  color: var(--muted);
  font-size: 11px;
}

.primary-btn,
.ghost-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 32px;
  border-radius: var(--radius-xs);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.primary-btn {
  padding: 0 13px;
  border: 1px solid var(--primary);
  background: var(--primary);
  color: #fff;
}

.primary-btn:hover:not(:disabled) {
  background: var(--primary-strong);
}

.primary-btn:disabled,
.ghost-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.ghost-btn {
  padding: 0 10px;
  border: 1px solid var(--border-strong);
  background: transparent;
  color: var(--text-2);
}

.ghost-btn:hover:not(:disabled) {
  background: var(--surface-2);
}

.spinner {
  width: 11px;
  height: 11px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.state-line {
  margin-top: 13px;
  color: var(--muted);
  font-size: 12px;
}

.state-error {
  color: var(--danger);
}

.state-box {
  padding: 28px 12px;
  text-align: center;
  color: var(--muted);
  font-size: 12px;
}

.state-box strong {
  display: block;
  margin-bottom: 4px;
  color: var(--text-2);
}

.reply-box,
.confirm-box,
.order-box {
  margin-top: 14px;
  padding: 13px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
}

.reply-label {
  display: block;
  margin-bottom: 5px;
  color: var(--muted);
  font-size: 11px;
}

.reply-box p {
  color: var(--text-2);
  font-size: 13px;
  white-space: pre-wrap;
}

.confirm-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.confirm-head h4 {
  font-size: 14px;
}

.confirm-head strong {
  font-family: var(--mono);
  font-size: 16px;
}

.draft-items {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 11px 0 0;
  padding: 10px 0 0;
  border-top: 1px solid var(--border);
  list-style: none;
}

.draft-items li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-2);
  font-size: 12px;
}

.confirm-note {
  margin-top: 11px;
  color: var(--muted);
  font-size: 11px;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 13px;
}

.order-box h4 {
  margin-top: 3px;
  font-size: 14px;
}

.order-box p {
  margin: 7px 0;
  color: var(--text-2);
  font-size: 12px;
}

.order-box strong {
  font-family: var(--mono);
  font-size: 16px;
}

.action-line {
  margin-top: 12px;
  color: var(--text-2);
  font-size: 12px;
}

@media (max-width: 920px) {
  .shop-grid {
    grid-template-columns: 1fr;
  }

  .shop-head {
    flex-direction: column;
  }
}

@media (max-width: 560px) {
  .shop-head,
  .catalog-panel,
  .assistant-panel {
    padding: 14px;
  }

  .send-row {
    align-items: flex-start;
    flex-direction: column;
  }

  .primary-btn {
    width: 100%;
  }
}
</style>
