<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { getJson, postJson } from "../api";

const props = defineProps({
  open: { type: Boolean, default: false },
  friendId: { type: String, default: "" },
  merchantName: { type: String, default: "" },
  title: { type: String, default: "砍价" },
  sku: { type: String, default: "" },
  items: { type: Array, default: () => [] },
});
const emit = defineEmits(["close", "quote-created"]);

const session = ref(null);
const loading = ref(false);
const sending = ref(false);
const accepting = ref(false);
const error = ref("");
const input = ref("");
const chatRef = ref(null);

const currentOffer = computed(() => session.value?.current_offer || null);
const transcript = computed(() => session.value?.transcript || []);
const items = computed(() => session.value?.items || []);
const canAccept = computed(() =>
  session.value?.status === "NEGOTIATING" && currentOffer.value && !accepting.value
);
const statusLabel = computed(() => {
  const status = session.value?.status;
  if (status === "WAITING_APPROVAL") return "等待商家确认";
  if (status === "ACCEPTED") return "报价已生成";
  if (status === "REJECTED") return "本次未成交";
  if (status === "EXPIRED") return "砍价已过期";
  return "协商中";
});

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", { hour12: false });
}

function money(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(2) : "—";
}

async function scrollBottom() {
  await nextTick();
  if (chatRef.value) chatRef.value.scrollTop = chatRef.value.scrollHeight;
}

async function createSession() {
  if (!props.open || !props.friendId) return;
  loading.value = true;
  error.value = "";
  session.value = null;
  try {
    const payload = {
      friend_id: props.friendId,
      ...(props.sku ? { sku: props.sku } : {}),
      ...(props.items?.length ? { items: props.items } : {}),
    };
    session.value = await postJson("/api/c/bargains", payload);
    await scrollBottom();
  } catch (exc) {
    error.value = exc?.detail?.message || exc?.detail || exc?.message || "打开砍价失败";
  } finally {
    loading.value = false;
  }
}

async function refresh() {
  if (!session.value?.bargain_id) return;
  loading.value = true;
  error.value = "";
  try {
    session.value = await getJson(`/api/c/bargains/${encodeURIComponent(session.value.bargain_id)}`);
    await scrollBottom();
    if (session.value?.quote?.quote_id) {
      emit("quote-created", session.value.quote);
    }
  } catch (exc) {
    error.value = exc?.detail?.message || exc?.detail || exc?.message || "刷新失败";
  } finally {
    loading.value = false;
  }
}

async function send() {
  const text = String(input.value || "").trim();
  if (!text || !session.value?.bargain_id || sending.value) return;
  sending.value = true;
  error.value = "";
  try {
    session.value = await postJson(
      `/api/c/bargains/${encodeURIComponent(session.value.bargain_id)}/messages`,
      { message: text },
    );
    input.value = "";
    await scrollBottom();
    if (session.value?.quote?.quote_id) {
      emit("quote-created", session.value.quote);
    }
  } catch (exc) {
    error.value = exc?.detail?.message || exc?.detail || exc?.message || "发送失败";
  } finally {
    sending.value = false;
  }
}

async function accept() {
  if (!session.value?.bargain_id || !currentOffer.value || accepting.value) return;
  accepting.value = true;
  error.value = "";
  try {
    session.value = await postJson(
      `/api/c/bargains/${encodeURIComponent(session.value.bargain_id)}/accept`,
      { offer_id: currentOffer.value.offer_id || "" },
    );
    await scrollBottom();
    if (session.value?.quote?.quote_id) {
      emit("quote-created", session.value.quote);
    }
  } catch (exc) {
    error.value = exc?.detail?.message || exc?.detail || exc?.message || "接受报价失败";
  } finally {
    accepting.value = false;
  }
}

function close() {
  emit("close");
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      if (!session.value) void createSession();
    } else {
      session.value = null;
      input.value = "";
      error.value = "";
    }
  },
  { immediate: true },
);

watch(
  () => [props.friendId, props.sku, props.items?.length],
  () => {
    if (props.open && session.value) void createSession();
  },
);
</script>

<template>
  <div v-if="open" class="bargain-mask" @click.self="close">
    <section class="bargain-sheet" role="dialog" aria-modal="true" aria-labelledby="bargain-title">
      <header class="bargain-head">
        <div>
          <span class="bargain-kicker">自由砍价 · 多轮协商</span>
          <h3 id="bargain-title">{{ title || "和店宠谈谈" }}</h3>
          <p v-if="merchantName">{{ merchantName }} · 价格和库存来自商家</p>
        </div>
        <button type="button" class="bargain-close" aria-label="关闭" @click="close">×</button>
      </header>

      <div v-if="loading && !session" class="bargain-loading">正在找店宠…</div>

      <template v-else>
        <div class="bargain-summary">
          <div v-for="item in items" :key="item.sku" class="bargain-item">
            <span>{{ item.title }} <small>{{ item.spec }} ×{{ item.quantity }}</small></span>
            <strong>¥{{ money(item.subtotal) }}</strong>
          </div>
          <div class="bargain-summary-row">
            <span>商品小计</span><strong>¥{{ money(session?.list_total) }}</strong>
          </div>
          <div v-if="session?.platform_discount" class="bargain-summary-row">
            <span>平台满减</span><strong>-¥{{ money(session.platform_discount) }}</strong>
          </div>
          <div v-if="currentOffer" class="bargain-summary-row bargain-payable">
            <span>当前方案</span>
            <strong>¥{{ money(currentOffer.payable) }}</strong>
          </div>
          <p v-if="currentOffer?.merchant_discount > 0" class="bargain-saving">
            商家让利 ¥{{ money(currentOffer.merchant_discount) }}
            <span v-if="currentOffer.approval_required">· 需商家确认</span>
          </p>
        </div>

        <div ref="chatRef" class="bargain-chat" aria-live="polite">
          <div
            v-for="(message, index) in transcript"
            :key="index"
            class="bargain-message"
            :class="message.actor === 'c_pet' ? 'is-me' : 'is-shop'"
          >
            <span class="bargain-actor">{{ message.name }}</span>
            <p>{{ message.text }}</p>
            <div v-if="message.offer && message.offer.payable" class="bargain-inline-offer">
              报价 ¥{{ money(message.offer.payable) }}
              <span v-if="message.offer.approval_required">· 待商家确认</span>
            </div>
          </div>
        </div>

        <div v-if="error" class="bargain-error" role="alert">{{ error }}</div>

        <div v-if="session?.status === 'WAITING_APPROVAL'" class="bargain-status is-waiting">
          <strong>已提交商家确认</strong>
          <span>店长确认 ¥{{ money(session.current_offer?.payable) }} 后，报价才会生效。</span>
          <button type="button" class="bargain-link" :disabled="loading" @click="refresh">刷新状态</button>
        </div>
        <div v-else-if="session?.status === 'ACCEPTED'" class="bargain-status is-accepted">
          <strong>报价已生成</strong>
          <span>¥{{ money(session.current_offer?.payable) }}，请在商城确认订单。</span>
        </div>
        <div v-else-if="session?.status === 'REJECTED'" class="bargain-status is-rejected">
          <strong>本次未成交</strong>
          <span>可以关闭后重新发起，或按原价购买。</span>
        </div>

        <form v-if="session?.status === 'NEGOTIATING'" class="bargain-compose" @submit.prevent="send">
          <input
            v-model="input"
            type="text"
            maxlength="200"
            placeholder="比如：180 能卖吗 / 再便宜点 / 190 可以"
            :disabled="sending"
          />
          <button type="submit" :disabled="sending || !input.trim()">{{ sending ? "发送中…" : "发送" }}</button>
        </form>

        <div v-if="canAccept" class="bargain-actions">
          <button type="button" class="bargain-accept" :disabled="accepting" @click="accept">
            {{ accepting ? "提交中…" : currentOffer?.approval_required ? "提交商家确认" : "接受这个报价" }}
          </button>
          <span>不会自动下单，最终仍需你确认订单。</span>
        </div>
        <p v-if="session?.expires_at" class="bargain-expire">本会话有效至 {{ formatTime(session.expires_at) }}</p>
      </template>
    </section>
  </div>
</template>

<style scoped>
.bargain-mask {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding: 20px;
  background: rgba(20, 24, 28, 0.42);
}
.bargain-sheet {
  width: min(560px, 100%);
  max-height: min(760px, calc(100vh - 40px));
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e6e0d8;
  border-radius: 18px;
  background: #fffdf9;
  box-shadow: 0 24px 80px rgba(34, 29, 24, 0.24);
}
.bargain-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 20px 22px 14px;
  border-bottom: 1px solid #eee7de;
}
.bargain-kicker { color: #a8623f; font-size: 11px; letter-spacing: .08em; }
.bargain-head h3 { margin: 4px 0; font-size: 20px; color: #2a2521; }
.bargain-head p { margin: 0; color: #8e8176; font-size: 12px; }
.bargain-close { width: 32px; height: 32px; border: 0; border-radius: 50%; background: #f3eee7; color: #6d6157; font-size: 22px; cursor: pointer; }
.bargain-loading { padding: 40px; text-align: center; color: #8e8176; }
.bargain-summary { padding: 14px 22px 10px; border-bottom: 1px solid #f1ebe3; background: #fbf8f2; }
.bargain-item, .bargain-summary-row { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; color: #5f554c; font-size: 13px; }
.bargain-item small { color: #9b8d80; }
.bargain-summary-row strong { color: #352c26; }
.bargain-payable { margin-top: 7px; padding-top: 9px; border-top: 1px dashed #ddd2c5; font-weight: 700; }
.bargain-payable strong { color: #a8623f; font-size: 19px; }
.bargain-saving { margin: 6px 0 0; color: #9b5b36; font-size: 12px; }
.bargain-chat { min-height: 140px; max-height: 330px; overflow-y: auto; padding: 16px 22px; display: flex; flex-direction: column; gap: 10px; }
.bargain-message { max-width: 88%; padding: 9px 12px; border-radius: 12px; font-size: 13px; line-height: 1.55; }
.bargain-message p { margin: 3px 0 0; white-space: pre-wrap; }
.bargain-message.is-me { align-self: flex-end; background: #f1e5d8; color: #3c3029; border-bottom-right-radius: 4px; }
.bargain-message.is-shop { align-self: flex-start; background: #f3f4f0; color: #374039; border-bottom-left-radius: 4px; }
.bargain-actor { color: #9a8c7e; font-size: 10px; }
.bargain-inline-offer { margin-top: 7px; padding: 6px 8px; border-radius: 7px; background: #fff; color: #9b5b36; font-weight: 700; }
.bargain-error { margin: 0 22px 8px; padding: 8px 10px; border-radius: 8px; background: #fbeceb; color: #a33a33; font-size: 12px; }
.bargain-status { margin: 0 22px 10px; padding: 10px 12px; border-radius: 10px; display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; font-size: 12px; }
.bargain-status strong { font-size: 13px; }
.bargain-status.is-waiting { background: #fff4df; color: #815a21; }
.bargain-status.is-accepted { background: #eaf4ea; color: #39633e; }
.bargain-status.is-rejected { background: #f5ecea; color: #83473f; }
.bargain-link { border: 0; background: transparent; color: inherit; text-decoration: underline; cursor: pointer; font-size: 12px; }
.bargain-compose { display: flex; gap: 8px; margin: 0 22px; padding: 10px 0; border-top: 1px solid #eee7de; }
.bargain-compose input { flex: 1; min-width: 0; border: 1px solid #ddd3c7; border-radius: 9px; padding: 10px 11px; background: #fff; color: #332b25; font-size: 14px; }
.bargain-compose button, .bargain-accept { border: 0; border-radius: 9px; padding: 10px 15px; background: #a8623f; color: #fff; font-weight: 700; cursor: pointer; }
.bargain-compose button:disabled, .bargain-accept:disabled { opacity: .5; cursor: wait; }
.bargain-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin: 10px 22px 14px; }
.bargain-actions span { color: #9a8c7e; font-size: 11px; }
.bargain-expire { margin: 0 22px 16px; color: #a99b8d; font-size: 11px; }
@media (max-width: 520px) {
  .bargain-mask { padding: 0; }
  .bargain-sheet { width: 100%; max-height: calc(100vh - 12px); border-radius: 16px 16px 0 0; }
  .bargain-chat { max-height: 36vh; }
}
</style>
