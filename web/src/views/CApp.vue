<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { getJson, postJson, del } from "../api";

const threads = ref([
  {
    id: "companion",
    name: "小鱼",
    kind: "companion",
    preview: "今天先看什么",
    time: "09:42",
    unread: 0,
  },
  {
    id: "store_demo",
    name: "山野户外旗舰店",
    kind: "merchant",
    preview: "满减活动已更新",
    time: "09:18",
    unread: 2,
  },
  {
    id: "friend_demo",
    name: "小满",
    kind: "friend",
    preview: "周末路线发你了",
    time: "昨天",
    unread: 0,
  },
]);

const messagesByThread = ref({
  companion: [
    {
      id: "m1",
      role: "companion",
      text: "今天先看什么。",
      time: "09:36",
    },
    {
      id: "m2",
      role: "user",
      text: "500 元以内的跑鞋。",
      time: "09:37",
    },
    {
      id: "m3",
      role: "companion",
      text: "轻量跑鞋 P001，标价 299 元，库存 18 件。平台满 299 减 30，以结算页为准。",
      time: "09:37",
      quote: {
        product: "轻量跑鞋 · P001",
        price: "299.00",
        policy: "满 299 减 30",
      },
    },
    {
      id: "m4",
      role: "companion",
      text: "如果你要跑 5 公里以上，我可以再对比缓震款。下单前需要你在商城逐单确认。",
      time: "09:38",
    },
  ],
  store_demo: [
    {
      id: "s1",
      role: "merchant",
      text: "今天有平台满减活动，满 299 减 30。具体适用商品以结算页为准。",
      time: "09:18",
    },
    {
      id: "s2",
      role: "companion",
      text: "活动门槛是 299，你这双跑鞋刚好达到。凑单前先确认是否适用。",
      time: "09:19",
    },
  ],
  friend_demo: [
    {
      id: "f1",
      role: "merchant",
      text: "周末路线发你了，强度不高。",
      time: "昨天",
    },
  ],
});

const activeId = ref("companion");
const draft = ref("");
const typing = ref(false);
const search = ref("");
const showContext = ref(false);
const showThreads = ref(false);
const storeSocketState = ref("offline");
const storeSocketAttempts = ref(0);
let storeSocket = null;
let storeReconnectTimer = null;
let storeManualClose = false;
const companion = ref({
  name: "小鱼",
  level: 4,
  satiety: 62,
  species: "digital_companion",
});
const liveThreadId = ref("");
const liveDraft = ref(null);
const liveOrder = ref(null);
const storeQuote = ref(null);
const hasMoreCompanion = ref(false);
const companionBefore = ref("");
const clearingCompanion = ref(false);
const agentBusy = ref(false);
const agentError = ref("");

const activeThread = computed(() => threads.value.find((item) => item.id === activeId.value) || threads.value[0]);
const messages = computed(() => messagesByThread.value[activeId.value] || []);
const filteredThreads = computed(() => {
  const keyword = search.value.trim();
  if (!keyword) return threads.value;
  return threads.value.filter((item) => item.name.includes(keyword) || item.preview.includes(keyword));
});
const isCompanion = computed(() => activeId.value === "companion");
const planLabel = computed(() => `L${companion.value.level || 4}`);
const statusText = computed(() => {
  if (activeThread.value.kind === "companion") return "在线";
  if (activeThread.value.kind === "merchant") {
    if (storeSocketState.value === "online") return "店宠在线";
    if (storeSocketState.value === "reconnecting") return "正在重连";
    if (storeSocketState.value === "connecting") return "连接中";
    return "连接已断开";
  }
  return "好友";
});
const threadDotClass = computed(() =>
  activeThread.value.kind === "merchant" && storeSocketState.value !== "online" ? "connecting" : "online"
);
const pendingCount = computed(() => {
  if (liveDraft.value || storeQuote.value) return 1;
  if (liveOrder.value) return 0;
  return 1;
});

function cleanReply(text) {
  return String(text || "")
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, "")
    .replace(/[\uFE0F\u200D]/g, "")
    .replace(/！/g, "。")
    .replace(/!/g, "。")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function primaryPolicy(quote) {
  const refs = quote?.policy_refs || [];
  return refs.find((item) => item.kind === "platform_activity") || refs[0] || null;
}

function nowTime() {
  return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    const el = document.getElementById("c-app-thread");
    if (el) el.scrollTop = el.scrollHeight;
  });
}

function pushMessage(message) {
  if (!messagesByThread.value[activeId.value]) messagesByThread.value[activeId.value] = [];
  messagesByThread.value[activeId.value].push({
    id: `local_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    time: nowTime(),
    ...message,
  });
}

function localReply(text) {
  const normalized = text.toLowerCase();
  if (/跑鞋|鞋|跑步/.test(normalized)) {
    return {
      text: "轻量跑鞋 P001，299 元，库存 18 件。平台满 299 减 30，是否适用以结算页为准。",
      quote: { product: "轻量跑鞋 · P001", price: "299.00", policy: "满 299 减 30" },
    };
  }
  if (/活动|优惠|满减|券/.test(normalized)) {
    return {
      text: "当前可查到的活动是满 299 减 30、满 599 减 80。优惠资格和适用商品需要在结算页确认。",
      quote: { product: "平台活动", price: "—", policy: "满 299 减 30" },
    };
  }
  if (/售后|退货|物流|发货/.test(normalized)) {
    return {
      text: "现货商品 48 小时内发出，支持 7 天无理由退货。质量问题由商家承担运费。",
    };
  }
  return {
    text: "我先把问题记录下来。你可以继续看商品，或者切到店宠会话询问活动和售后。",
  };
}

async function loadStoreMessages() {
  try {
    const data = await getJson("/api/c/friends/store_demo/messages?limit=20");
    if (data?.messages?.length) {
      messagesByThread.value.store_demo = data.messages.map((message) => ({
        id: message.message_id,
        role: message.sender_id?.startsWith("companion_")
          ? "companion"
          : message.sender_id?.startsWith("buyer_")
            ? "user"
            : "merchant",
        text: cleanReply(message.content),
        time: (message.created_at || "").slice(11, 16),
      }));
    }
    scrollToBottom();
  } catch {
    // 保留种子会话，避免接口异常时出现空屏。
  }
}

function closeStoreSocket() {
  storeManualClose = true;
  if (storeReconnectTimer) {
    clearTimeout(storeReconnectTimer);
    storeReconnectTimer = null;
  }
  if (storeSocket) {
    storeSocket.onclose = null;
    storeSocket.close();
    storeSocket = null;
  }
  storeSocketState.value = "offline";
}

function scheduleStoreReconnect() {
  if (activeId.value !== "store_demo") return;
  if (storeSocketAttempts.value >= 5) {
    storeSocketState.value = "offline";
    return;
  }
  storeSocketAttempts.value += 1;
  storeSocketState.value = "reconnecting";
  const delay = Math.min(1000 * 2 ** (storeSocketAttempts.value - 1), 8000);
  storeReconnectTimer = setTimeout(() => {
    storeReconnectTimer = null;
    openStoreSocket(true);
  }, delay);
}

function openStoreSocket(isReconnect = false) {
  if (storeReconnectTimer) {
    clearTimeout(storeReconnectTimer);
    storeReconnectTimer = null;
  }
  if (storeSocket) {
    storeSocket.onclose = null;
    storeSocket.close();
    storeSocket = null;
  }
  storeManualClose = false;
  if (!isReconnect) storeSocketAttempts.value = 0;
  try {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    storeSocket = new WebSocket(`${scheme}://${window.location.host}/api/c/ws/chat/store_demo`);
  } catch {
    storeSocketState.value = "fallback";
    scheduleStoreReconnect();
    return;
  }
  storeSocketState.value = "connecting";
  storeSocket.onopen = () => {
    storeSocketAttempts.value = 0;
    storeSocketState.value = "online";
  };
  storeSocket.onmessage = handleStoreSocket;
  storeSocket.onerror = () => {
    storeSocketState.value = "reconnecting";
    if (storeSocket) storeSocket.close();
  };
  storeSocket.onclose = () => {
    storeSocket = null;
    if (storeManualClose) return;
    scheduleStoreReconnect();
  };
}

function handleStoreSocket(event) {
  let payload;
  try {
    payload = JSON.parse(event.data);
  } catch {
    return;
  }
  if (activeId.value !== "store_demo") return;
  if (payload.type === "chat") {
    typing.value = false;
    if (payload.reply) {
      pushMessage({ role: "merchant", text: cleanReply(payload.reply.content) });
      if (payload.reply.metadata?.quote_id) storeQuote.value = payload.reply.metadata;
    }
    if (payload.companion_message) {
      pushMessage({ role: "companion", text: cleanReply(payload.companion_message.content) });
    }
    scrollToBottom();
  } else if (payload.type === "error") {
    typing.value = false;
    agentError.value = payload.error?.message || "店宠暂时无法回应";
  }
}

async function loadCompanionMessages() {
  try {
    const data = await getJson("/api/c/app/messages?thread_id=companion&limit=30");
    if (data?.messages?.length) {
      messagesByThread.value.companion = data.messages.map((message) => ({
        id: message.message_id,
        role: message.role === "user" ? "user" : "companion",
        text: cleanReply(message.content),
        time: (message.created_at || "").slice(11, 16),
        createdAt: message.created_at,
      }));
      hasMoreCompanion.value = data.messages.length >= 30;
      companionBefore.value = data.messages[0]?.created_at || "";
    }
    scrollToBottom();
  } catch {
    // 保留演示种子。
  }
}

async function loadOlderCompanion() {
  if (!hasMoreCompanion.value || !companionBefore.value) return;
  try {
    const data = await getJson(
      `/api/c/app/messages?thread_id=companion&limit=30&before=${encodeURIComponent(companionBefore.value)}`
    );
    const older = (data?.messages || []).map((message) => ({
      id: message.message_id,
      role: message.role === "user" ? "user" : "companion",
      text: cleanReply(message.content),
      time: (message.created_at || "").slice(11, 16),
      createdAt: message.created_at,
    }));
    messagesByThread.value.companion = [...older, ...(messagesByThread.value.companion || [])];
    hasMoreCompanion.value = older.length >= 30;
    companionBefore.value = older[0]?.created_at || companionBefore.value;
  } catch {
    // 加载失败时保留当前消息。
  }
}

async function clearCompanionHistory() {
  if (clearingCompanion.value) return;
  if (!window.confirm("清空小鱼会话？此操作不可撤销。")) return;
  clearingCompanion.value = true;
  try {
    await del("/api/c/app/messages?thread_id=companion");
    messagesByThread.value.companion = [];
    hasMoreCompanion.value = false;
    companionBefore.value = "";
    liveThreadId.value = "";
  } catch (error) {
    agentError.value = error?.detail || error?.message || "清空会话失败";
  } finally {
    clearingCompanion.value = false;
  }
}

async function persistAppMessage(role, content, metadata = {}) {
  try {
    await postJson("/api/c/app/messages", {
      thread_id: "companion",
      role,
      content,
      metadata,
    });
  } catch {
    // 消息持久化失败不阻断当前对话。
  }
}

async function send() {
  const text = draft.value.trim();
  if (!text || typing.value) return;
  pushMessage({ role: "user", text });
  draft.value = "";
  scrollToBottom();

  if (activeId.value === "store_demo") {
    if (storeSocket && storeSocket.readyState === WebSocket.OPEN) {
      typing.value = true;
      agentError.value = "";
      storeSocket.send(JSON.stringify({ content: text }));
      return;
    }
    typing.value = true;
    try {
      const result = await postJson("/api/c/friends/store_demo/messages", { content: text });
      if (result.reply) {
        pushMessage({ role: "merchant", text: cleanReply(result.reply.content) });
        if (result.reply.metadata?.quote_id) storeQuote.value = result.reply.metadata;
      }
      if (result.companion_message) {
        pushMessage({ role: "companion", text: cleanReply(result.companion_message.content) });
      }
      agentError.value = "";
    } catch (error) {
      agentError.value = error?.detail || error?.message || "店宠暂时无法回应";
      pushMessage({ role: "merchant", text: "店宠暂时忙碌，请稍后再试。" });
    } finally {
      typing.value = false;
      scrollToBottom();
    }
    return;
  }

  if (activeId.value !== "companion") {
    typing.value = true;
    await new Promise((resolve) => setTimeout(resolve, 520));
    pushMessage({ role: "merchant", text: "收到，我稍后回复你。" });
    typing.value = false;
    scrollToBottom();
    return;
  }

  await persistAppMessage("user", text);
  typing.value = true;
  try {
    const result = await postJson("/api/c/agent/run", {
      message: text,
      thread_id: liveThreadId.value || undefined,
    });
    liveThreadId.value = result.thread_id || liveThreadId.value;
    agentError.value = "";
    const replyText = cleanReply(result.reply) || "已处理，请查看当前待确认信息。";
    pushMessage({
      role: "companion",
      text: replyText,
    });
    await persistAppMessage("companion", replyText);
    if (result.draft) {
      liveDraft.value = result.draft;
      liveOrder.value = null;
    } else if (result.order) {
      liveOrder.value = result.order;
      liveThreadId.value = "";
    } else {
      liveThreadId.value = "";
    }
  } catch (error) {
    agentError.value = error?.detail || error?.message || "小鱼暂时无法回应";
    const fallback = localReply(text);
    pushMessage({ role: "companion", ...fallback });
    await persistAppMessage("companion", fallback.text);
  } finally {
    typing.value = false;
    scrollToBottom();
  }
}

async function confirmLiveOrder() {
  if (!liveThreadId.value || !liveDraft.value || agentBusy.value) return;
  agentBusy.value = true;
  agentError.value = "";
  try {
    const result = await postJson("/api/c/agent/resume", {
      thread_id: liveThreadId.value,
      approved: true,
    });
    liveOrder.value = result.order;
    liveDraft.value = null;
    const replyText = result.order
      ? `订单 ${result.order.order_id} 已创建。可以在订单页查看报价和确认记录。`
      : "订单已确认。";
    pushMessage({ role: "companion", text: replyText });
    await persistAppMessage("companion", replyText, { order_id: result.order?.order_id || null });
  } catch (error) {
    agentError.value = error?.detail || error?.message || "订单确认失败";
  } finally {
    agentBusy.value = false;
    scrollToBottom();
  }
}

async function sendPrompt(prompt) {
  if (typing.value) return;
  if (activeId.value === "store_demo") {
    draft.value = `@店宠 ${prompt}`;
  } else if (activeId.value === "companion") {
    draft.value = prompt === "看 500 元以内的跑鞋"
      ? "看 500 元以内的跑鞋，买 1 双，直接生成待确认订单"
      : prompt;
  } else {
    draft.value = prompt;
  }
  await send();
}

async function loadCompanion() {
  try {
    const data = await getJson("/api/c/companion");
    if (data) companion.value = { ...companion.value, ...data };
  } catch {
    // UI 参考页在未登录/接口不可用时仍可展示静态状态。
  }
}

async function switchThread(id) {
  closeStoreSocket();
  activeId.value = id;
  showContext.value = false;
  if (id === "store_demo") {
    await loadStoreMessages();
    openStoreSocket();
  }
  scrollToBottom();
}

function toggleContext() {
  showContext.value = !showContext.value;
}

function openThreads() {
  showThreads.value = true;
}

function selectMobileThread(id) {
  showThreads.value = false;
  switchThread(id);
}

onMounted(async () => {
  await Promise.all([loadCompanion(), loadCompanionMessages()]);
  scrollToBottom();
});

onBeforeUnmount(closeStoreSocket);
</script>

<template>
  <div class="c-app">
    <div class="c-shell">
      <aside class="c-sidebar" aria-label="C 端导航">
        <div class="c-brand">
          <span class="c-brand-mark">千客</span>
          <span class="c-brand-sub">C 端</span>
        </div>

        <label class="c-search">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.2-3.2" />
          </svg>
          <input v-model="search" type="search" placeholder="搜索对话或商品" aria-label="搜索对话或商品" />
        </label>

        <nav class="c-nav" aria-label="主要导航">
          <RouterLink class="c-nav-item active" to="/c/app">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.9 8.9 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
              <path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01" />
            </svg>
            <span>对话</span>
          </RouterLink>
          <RouterLink class="c-nav-item" to="/c">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
              <path d="M3 6h18M16 10a4 4 0 0 1-8 0" />
            </svg>
            <span>商城</span>
          </RouterLink>
          <RouterLink class="c-nav-item" to="/c/orders">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <path d="M6 2h12v20l-3-2-3 2-3-2-3 2z" />
              <path d="M9 7h6M9 11h6M9 15h4" />
            </svg>
            <span>订单</span>
          </RouterLink>
        </nav>

        <section class="c-thread-list" aria-label="会话列表">
          <div class="c-section-row">
            <span>会话</span>
            <span>{{ filteredThreads.length }}</span>
          </div>
          <button
            v-for="thread in filteredThreads"
            :key="thread.id"
            type="button"
            class="c-thread-row"
            :class="{ active: activeId === thread.id }"
            @click="switchThread(thread.id)"
          >
            <span class="c-avatar small" :class="thread.kind">{{ thread.name.slice(0, 1) }}</span>
            <span class="c-thread-copy">
              <strong>{{ thread.name }}</strong>
              <small>{{ thread.preview }}</small>
            </span>
            <span class="c-thread-meta">
              <time>{{ thread.time }}</time>
              <span v-if="thread.unread" class="c-unread">{{ thread.unread }}</span>
            </span>
          </button>
        </section>

        <RouterLink class="c-companion-mini" to="/c/app">
          <span class="c-avatar">{{ companion.name.slice(0, 1) }}</span>
          <span class="c-companion-copy">
            <strong>{{ companion.name }}</strong>
            <span><i class="c-dot online" />{{ planLabel }} · 在线</span>
          </span>
          <span class="c-satiety">{{ companion.satiety }}%</span>
        </RouterLink>
      </aside>

      <main class="c-main">
        <header class="c-topbar">
          <div class="c-topbar-left">
            <span class="c-mobile-brand">千客</span>
            <span class="c-topbar-divider" />
            <span class="c-topbar-crumb">对话</span>
          </div>
          <div class="c-topbar-right">
            <span class="c-plan"><i class="c-dot plan" />{{ planLabel }}</span>
            <button class="c-icon-btn" type="button" aria-label="打开当前会话信息" @click="toggleContext">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 11v5M12 8h.01" />
              </svg>
            </button>
            <span class="c-avatar top">伴</span>
          </div>
        </header>

        <section class="c-chat" aria-label="与小鱼的对话">
          <header class="c-chat-head">
            <div class="c-chat-identity">
              <button class="c-back-btn" type="button" aria-label="返回消息列表" @click="openThreads">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
                  <path d="m15 18-6-6 6-6" />
                </svg>
              </button>
              <span class="c-avatar">{{ activeThread.name.slice(0, 1) }}</span>
              <div>
                <h1>{{ activeThread.name }}</h1>
                <p><i class="c-dot" :class="threadDotClass" />{{ statusText }}<span class="c-head-divider">·</span>只做建议，成交需你确认</p>
              </div>
            </div>
            <div class="c-chat-actions">
              <button class="c-icon-btn" type="button" aria-label="当前会话信息" @click="toggleContext">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 11v5M12 8h.01" />
                </svg>
              </button>
            </div>
          </header>

          <div id="c-app-thread" class="c-thread" aria-live="polite">
            <div v-if="activeId === 'companion' && hasMoreCompanion" class="c-load-more-row">
              <button type="button" class="c-load-more" @click="loadOlderCompanion">加载更早消息</button>
            </div>
            <div class="c-date-line"><span>今天</span></div>
            <p v-if="!messages.length" class="c-empty-thread">开始新的对话。</p>
            <article
              v-for="message in messages"
              :key="message.id"
              class="c-message"
              :class="[message.role]"
            >
              <div class="c-message-meta">
                <span>{{ message.role === "user" ? "我" : message.role === "companion" ? companion.name : message.role === "merchant" ? activeThread.name : "系统" }}</span>
                <time>{{ message.time }}</time>
              </div>
              <p class="c-bubble">
                {{ message.text }}
                <time class="c-bubble-time">{{ message.time }}</time>
              </p>
              <div v-if="message.quote" class="c-quote-attachment">
                <span class="c-quote-label">报价引用</span>
                <div class="c-quote-row">
                  <strong>{{ message.quote.product }}</strong>
                  <span>¥{{ message.quote.price }}</span>
                </div>
                <span class="c-quote-policy">{{ message.quote.policy }} · 以结算页为准</span>
              </div>
            </article>
            <div v-if="typing" class="c-typing" role="status">
              <i /><i /><i />
              <span>{{ activeThread.name }}正在输入</span>
            </div>
          </div>

          <div class="c-prompt-row">
            <button type="button" class="c-prompt" @click="sendPrompt('看 500 元以内的跑鞋')">看 500 元以内的跑鞋</button>
            <button type="button" class="c-prompt" @click="sendPrompt('查平台活动')">查平台活动</button>
            <button type="button" class="c-prompt" @click="sendPrompt('问店宠售后')">问店宠售后</button>
          </div>

          <form class="c-composer" @submit.prevent="send">
            <label class="sr-only" for="c-app-input">输入消息</label>
            <div class="c-composer-row">
              <button class="c-tool-btn" type="button" aria-label="添加附件" disabled>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>
              <textarea
                id="c-app-input"
                v-model="draft"
                rows="1"
                placeholder="问商品、活动或售后"
                @keydown.enter.exact.prevent="send"
              />
              <button type="submit" class="c-send-btn" :disabled="!draft.trim() || typing" aria-label="发送">
                <span class="c-send-label">发送</span>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
                  <path d="m5 12 14-7-4 14-3-6-7-1z" />
                </svg>
              </button>
            </div>
            <div class="c-composer-foot">
              <span>Enter 发送 · Shift + Enter 换行</span>
            </div>
          </form>
        </section>
      </main>

      <aside class="c-context" :class="{ open: showContext }" aria-label="当前会话信息">
        <div class="c-context-scroll">
          <div class="c-context-head">
            <span>本期概览</span>
            <time>09:42</time>
          </div>

          <section class="c-overview">
            <p class="c-eyebrow">本月支出</p>
            <div class="c-overview-value">
              <strong>¥1,286</strong>
              <span class="c-trend">+12% vs 上月</span>
            </div>
            <svg class="c-spark" viewBox="0 0 232 84" role="img" aria-label="最近七天消费趋势">
              <g class="c-spark-grid" aria-hidden="true">
                <line x1="0" y1="20" x2="232" y2="20" />
                <line x1="0" y1="42" x2="232" y2="42" />
                <line x1="0" y1="64" x2="232" y2="64" />
              </g>
              <path class="c-spark-area" d="M0 67 L0 60 L33 52 L66 56 L99 38 L132 44 L165 27 L198 33 L232 18 L232 84 L0 84 Z" />
              <polyline class="c-spark-line" points="0,60 33,52 66,56 99,38 132,44 165,27 198,33 232,18" />
              <circle class="c-spark-point" cx="232" cy="18" r="2.5" />
            </svg>
            <div class="c-spark-axis"><span>周一</span><span>周日</span></div>
          </section>

          <section class="c-context-section">
            <header><span>待确认</span><span class="c-count">{{ pendingCount }}</span></header>
            <div v-if="liveDraft" class="c-quote-card">
              <div class="c-quote-card-top">
                <span class="c-quote-card-label">小鱼生成的订单草稿</span>
                <span class="c-dot waiting" />
              </div>
              <strong>{{ liveDraft.items?.[0]?.title || "订单草稿" }}</strong>
              <div class="c-quote-price">
                <span>¥{{ Number(liveDraft.total_amount || 0).toFixed(2) }}</span>
                <small v-if="liveDraft.discount_amount">优惠 ¥{{ Number(liveDraft.discount_amount).toFixed(2) }}</small>
              </div>
              <p>确认后才会创建订单，确认前不会扣库存。</p>
              <button class="c-confirm-btn" type="button" :disabled="agentBusy" @click="confirmLiveOrder">
                {{ agentBusy ? "提交中" : "确认并创建订单" }}
              </button>
            </div>
            <div v-else-if="liveOrder" class="c-order-created">
              订单 {{ liveOrder.order_id }} 已创建 · ¥{{ Number(liveOrder.total_amount || 0).toFixed(2) }}
            </div>
            <div v-else-if="storeQuote" class="c-quote-card">
              <div class="c-quote-card-top">
                <span class="c-quote-card-label">来自店宠的结构化报价</span>
                <span class="c-dot waiting" />
              </div>
              <strong>{{ storeQuote.product_refs?.[0]?.title || "平台活动引用" }}</strong>
              <div class="c-quote-price">
                <span v-if="storeQuote.product_refs?.[0]?.price">¥{{ Number(storeQuote.product_refs[0].price).toFixed(2) }}</span>
                <small>{{ primaryPolicy(storeQuote)?.title || "以结算页为准" }}</small>
              </div>
              <p>报价只做引用，成交前需在商城逐单确认。</p>
              <RouterLink
                :to="{ path: '/c', query: { quote: storeQuote.quote_id } }"
                class="c-text-link"
              >
                查看报价 <span>→</span>
              </RouterLink>
            </div>
            <div v-else class="c-quote-card">
              <div class="c-quote-card-top">
                <span class="c-quote-card-label">来自店宠的报价</span>
                <span class="c-dot waiting" />
              </div>
              <strong>轻量跑鞋 · P001</strong>
              <div class="c-quote-price"><span>¥299.00</span><small>满 299 减 30</small></div>
              <p>成交前需在商城逐单确认。</p>
              <RouterLink to="/c" class="c-text-link">查看商城 <span>→</span></RouterLink>
            </div>
            <p v-if="agentError" class="c-inline-error" role="alert">{{ agentError }}</p>
          </section>

          <section class="c-context-section">
            <header><span>最近订单</span><RouterLink to="/c/orders" class="c-context-link">全部</RouterLink></header>
            <div class="c-order-row">
              <span class="c-order-mark">P</span>
              <span><strong>轻量跑鞋</strong><small>10 月 29 日 · 待确认</small></span>
              <span class="c-order-amount">¥269</span>
            </div>
            <div class="c-order-row">
              <span class="c-order-mark">P</span>
              <span><strong>通勤双肩包</strong><small>10 月 24 日 · 已确认</small></span>
              <span class="c-order-amount">¥199</span>
            </div>
          </section>

          <section class="c-context-section">
            <header><span>会话</span><span class="c-context-link">仅小鱼</span></header>
            <button
              class="c-danger-link"
              type="button"
              :disabled="clearingCompanion"
              @click="clearCompanionHistory"
            >
              {{ clearingCompanion ? "清理中…" : "清空小鱼会话" }}
            </button>
          </section>

          <p class="c-context-note">演示数据 · 仅用于界面参考</p>
        </div>
      </aside>
    </div>

    <div v-if="showThreads" class="c-mobile-thread-screen" role="dialog" aria-label="消息列表">
      <header class="c-mobile-thread-head">
        <button type="button" class="c-icon-btn" aria-label="返回对话" @click="showThreads = false">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </button>
        <h1>消息</h1>
        <button type="button" class="c-icon-btn" aria-label="新建会话" disabled>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </header>
      <label class="c-mobile-search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.2-3.2" />
        </svg>
        <input v-model="search" type="search" placeholder="搜索" aria-label="搜索会话" />
      </label>
      <div class="c-mobile-thread-list">
        <button
          v-for="thread in filteredThreads"
          :key="thread.id"
          type="button"
          class="c-mobile-thread-row"
          @click="selectMobileThread(thread.id)"
        >
          <span class="c-avatar" :class="thread.kind">{{ thread.name.slice(0, 1) }}</span>
          <span class="c-mobile-thread-copy">
            <span>
              <strong>{{ thread.name }}</strong>
              <time>{{ thread.time }}</time>
            </span>
            <small>{{ thread.preview }}</small>
          </span>
          <span v-if="thread.unread" class="c-unread">{{ thread.unread }}</span>
        </button>
      </div>
    </div>

    <nav class="c-mobile-nav" aria-label="移动端导航">
      <RouterLink to="/c/app" class="active">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.9 8.9 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
          <path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01" />
        </svg>
        <span>对话</span>
      </RouterLink>
      <RouterLink to="/c">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
          <path d="M3 6h18M16 10a4 4 0 0 1-8 0" />
        </svg>
        <span>商城</span>
      </RouterLink>
      <RouterLink to="/c/orders">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <path d="M6 2h12v20l-3-2-3 2-3-2-3 2z" />
          <path d="M9 7h6M9 11h6M9 15h4" />
        </svg>
        <span>订单</span>
      </RouterLink>
      <button type="button" @click="toggleContext">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5M12 8h.01" />
        </svg>
        <span>概览</span>
      </button>
    </nav>
  </div>
</template>

<style scoped>
.c-app {
  --c-bg: #0f0f11;
  --c-bg-soft: #131315;
  --c-panel: #161618;
  --c-panel-2: #1b1b1e;
  --c-panel-3: #202023;
  --c-line: #29292d;
  --c-line-soft: #232326;
  --c-text: #e7e7e9;
  --c-text-2: #a3a3aa;
  --c-text-3: #707078;
  --c-accent: #8d96a3;
  --c-positive: #7e9888;
  --c-warning: #a89a7c;
  --c-negative: #a17b7b;
  min-height: 100dvh;
  background: var(--c-bg);
  color: var(--c-text);
  font-family: Inter, "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif;
  font-size: 13px;
  line-height: 1.55;
  letter-spacing: 0.005em;
}

.c-app *,
.c-app *::before,
.c-app *::after {
  box-sizing: border-box;
}

.c-shell {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr) 304px;
  min-height: 100dvh;
  background: var(--c-bg);
}

.c-sidebar {
  display: flex;
  flex-direction: column;
  gap: 24px;
  min-width: 0;
  padding: 24px 16px;
  border-right: 1px solid var(--c-line-soft);
  background: var(--c-panel);
}

.c-brand {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 0 8px;
}

.c-brand-mark {
  color: var(--c-text);
  font-size: 20px;
  font-weight: 650;
  letter-spacing: 0.04em;
}

.c-brand-sub {
  color: var(--c-text-3);
  font-size: 10px;
  letter-spacing: 0.16em;
}

.c-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--c-line);
  border-radius: 10px;
  background: var(--c-bg-soft);
  color: var(--c-text-3);
}

.c-search svg {
  width: 15px;
  height: 15px;
  flex: 0 0 15px;
}

.c-search input {
  min-width: 0;
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--c-text);
  font: inherit;
  font-size: 12px;
}

.c-search input::placeholder {
  color: var(--c-text-3);
}

.c-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.c-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 38px;
  padding: 0 10px;
  border-radius: 8px;
  color: var(--c-text-2);
  font-size: 12px;
  text-decoration: none;
}

.c-nav-item svg {
  width: 17px;
  height: 17px;
  color: var(--c-text-3);
}

.c-nav-item:hover {
  background: var(--c-panel-2);
  color: var(--c-text);
}

.c-nav-item.active {
  background: var(--c-panel-3);
  color: var(--c-text);
  font-weight: 600;
}

.c-nav-item.active svg {
  color: var(--c-text-2);
}

.c-thread-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
}

.c-section-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px 8px;
  color: var(--c-text-3);
  font-size: 10px;
  letter-spacing: 0.04em;
}

.c-thread-row {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--c-text);
  text-align: left;
  cursor: pointer;
  font: inherit;
}

.c-thread-row:hover {
  background: var(--c-panel-2);
}

.c-thread-row.active {
  background: var(--c-panel-3);
}

.c-avatar {
  display: inline-grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border: 1px solid var(--c-line);
  border-radius: 50%;
  background: var(--c-panel-3);
  color: var(--c-text-2);
  font-size: 12px;
  font-weight: 600;
}

.c-avatar.small {
  width: 30px;
  height: 30px;
  flex-basis: 30px;
  font-size: 11px;
}

.c-avatar.merchant {
  border-radius: 9px;
}

.c-thread-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.c-thread-copy strong,
.c-thread-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-thread-copy strong {
  font-size: 12px;
  font-weight: 500;
}

.c-thread-copy small {
  color: var(--c-text-3);
  font-size: 10px;
}

.c-thread-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  color: var(--c-text-3);
  font-size: 9px;
}

.c-unread {
  display: grid;
  place-items: center;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--c-panel-3);
  color: var(--c-text-2);
  font-size: 9px;
}

.c-companion-mini {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-top: auto;
  padding: 10px;
  border: 1px solid var(--c-line-soft);
  border-radius: 10px;
  background: var(--c-bg-soft);
  color: var(--c-text);
  text-decoration: none;
}

.c-companion-mini .c-avatar {
  width: 30px;
  height: 30px;
  flex-basis: 30px;
  font-size: 11px;
}

.c-companion-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.c-companion-copy strong {
  font-size: 11px;
  font-weight: 500;
}

.c-companion-copy span {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--c-text-3);
  font-size: 9px;
}

.c-dot {
  display: inline-block;
  width: 5px;
  height: 5px;
  flex: 0 0 5px;
  border-radius: 50%;
  background: var(--c-text-3);
}

.c-dot.online {
  background: var(--c-positive);
}

.c-dot.connecting {
  background: var(--c-warning);
}

.c-dot.plan {
  background: var(--c-accent);
}

.c-dot.waiting {
  background: var(--c-warning);
}

.c-satiety {
  color: var(--c-text-3);
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 9px;
}

.c-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.c-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 20px;
  border-bottom: 1px solid var(--c-line-soft);
  background: var(--c-bg);
}

.c-topbar-left,
.c-topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.c-mobile-brand {
  display: none;
  color: var(--c-text);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.c-topbar-divider {
  width: 1px;
  height: 14px;
  background: var(--c-line);
}

.c-topbar-crumb {
  color: var(--c-text-2);
  font-size: 11px;
}

.c-plan {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--c-text-2);
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
}

.c-icon-btn {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--c-text-2);
  cursor: pointer;
}

.c-icon-btn:hover {
  border-color: var(--c-line);
  background: var(--c-panel-2);
}

.c-icon-btn svg {
  width: 16px;
  height: 16px;
}

.c-avatar.top {
  width: 28px;
  height: 28px;
  flex-basis: 28px;
  font-size: 10px;
}

.c-chat {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  max-width: 840px;
  width: 100%;
  margin: 0 auto;
  padding: 0 32px 20px;
}

.c-chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 0 16px;
  border-bottom: 1px solid var(--c-line-soft);
}

.c-chat-identity {
  display: flex;
  align-items: center;
  gap: 11px;
}

.c-back-btn {
  display: none;
  place-items: center;
  width: 28px;
  height: 32px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--c-text-2);
  cursor: pointer;
}

.c-back-btn svg {
  width: 20px;
  height: 20px;
}

.c-chat-identity h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 560;
}

.c-chat-identity p {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 2px 0 0;
  color: var(--c-text-3);
  font-size: 10px;
}

.c-head-divider {
  color: var(--c-line);
}

.c-chat-actions {
  display: flex;
  gap: 4px;
}

.c-thread {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 18px;
  overflow-y: auto;
  padding: 20px 2px 12px;
  scrollbar-width: thin;
  scrollbar-color: var(--c-line) transparent;
}

.c-date-line {
  display: flex;
  justify-content: center;
  color: var(--c-text-3);
  font-size: 9px;
}

.c-load-more-row {
  display: flex;
  justify-content: center;
}

.c-load-more {
  padding: 4px 10px;
  border: 1px solid var(--c-line);
  border-radius: 999px;
  background: transparent;
  color: var(--c-text-3);
  font: inherit;
  font-size: 9px;
  cursor: pointer;
}

.c-load-more:hover {
  color: var(--c-text-2);
  border-color: var(--c-text-3);
}

.c-empty-thread {
  margin: auto;
  color: var(--c-text-3);
  font-size: 11px;
}

.c-date-line span {
  padding: 2px 8px;
  border: 1px solid var(--c-line-soft);
  border-radius: 999px;
}

.c-message {
  display: flex;
  max-width: 78%;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
}

.c-message.user {
  align-self: flex-end;
  align-items: flex-end;
}

.c-message-meta {
  display: flex;
  gap: 6px;
  color: var(--c-text-3);
  font-size: 9px;
}

.c-message-meta span {
  color: var(--c-text-2);
}

.c-bubble {
  margin: 0;
  padding: 10px 12px 7px;
  border: 1px solid var(--c-line-soft);
  border-radius: 10px;
  border-top-left-radius: 4px;
  background: var(--c-panel);
  color: var(--c-text-2);
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.c-bubble-time {
  display: none;
  margin-left: 10px;
  color: var(--c-text-3);
  font-size: 8px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.c-message.user .c-bubble {
  border-color: var(--c-line);
  border-radius: 10px;
  border-top-right-radius: 4px;
  background: var(--c-panel-2);
  color: var(--c-text);
}

.c-message.merchant .c-bubble {
  background: var(--c-bg-soft);
}

.c-quote-attachment {
  display: flex;
  width: min(300px, 100%);
  flex-direction: column;
  gap: 6px;
  margin-top: 2px;
  padding: 9px 10px;
  border: 1px solid var(--c-line);
  border-radius: 8px;
  background: var(--c-bg-soft);
}

.c-quote-label {
  color: var(--c-text-3);
  font-size: 9px;
  letter-spacing: 0.04em;
}

.c-quote-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 11px;
}

.c-quote-row strong {
  font-weight: 500;
}

.c-quote-row span {
  color: var(--c-text-2);
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
}

.c-quote-policy {
  color: var(--c-text-3);
  font-size: 9px;
}

.c-typing {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--c-text-3);
  font-size: 9px;
}

.c-typing i {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--c-text-3);
  animation: c-typing 1.2s infinite ease-in-out;
}

.c-typing i:nth-child(2) { animation-delay: 120ms; }
.c-typing i:nth-child(3) { animation-delay: 240ms; }
.c-typing span { margin-left: 4px; }

@keyframes c-typing {
  0%, 80%, 100% { opacity: 0.25; }
  40% { opacity: 1; }
}

.c-prompt-row {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 8px 0;
  scrollbar-width: none;
}

.c-prompt-row::-webkit-scrollbar { display: none; }

.c-prompt {
  flex: 0 0 auto;
  padding: 6px 9px;
  border: 1px solid var(--c-line);
  border-radius: 999px;
  background: transparent;
  color: var(--c-text-2);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.c-prompt:hover {
  border-color: var(--c-text-3);
  color: var(--c-text);
}

.c-composer {
  padding: 12px;
  border: 1px solid var(--c-line);
  border-radius: 12px;
  background: var(--c-panel);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.c-composer-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.c-tool-btn {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--c-text-3);
}

.c-tool-btn svg {
  width: 17px;
  height: 17px;
}

.c-composer textarea {
  display: block;
  width: 100%;
  min-height: 24px;
  max-height: 120px;
  padding: 0;
  border: 0;
  outline: 0;
  resize: none;
  background: transparent;
  color: var(--c-text);
  font: inherit;
  font-size: 12px;
  line-height: 1.6;
}

.c-composer textarea::placeholder {
  color: var(--c-text-3);
}

.c-composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 8px;
}

.c-composer-foot > span {
  color: var(--c-text-3);
  font-size: 9px;
}

.c-send-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--c-line);
  border-radius: 8px;
  background: var(--c-panel-2);
  color: var(--c-text);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.c-send-btn:hover:not(:disabled) {
  background: var(--c-panel-3);
}

.c-send-btn:disabled {
  color: var(--c-text-3);
  cursor: not-allowed;
}

.c-send-btn svg {
  width: 13px;
  height: 13px;
}

.c-context {
  min-width: 0;
  border-left: 1px solid var(--c-line-soft);
  background: var(--c-panel);
}

.c-context-scroll {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 24px 20px;
}

.c-context-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--c-text-2);
  font-size: 11px;
}

.c-context-head time {
  color: var(--c-text-3);
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 9px;
}

.c-overview {
  padding: 14px;
  border: 1px solid var(--c-line-soft);
  border-radius: 10px;
  background: var(--c-bg-soft);
}

.c-eyebrow {
  margin: 0;
  color: var(--c-text-3);
  font-size: 9px;
}

.c-overview-value {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 4px;
}

.c-overview-value strong {
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 22px;
  font-weight: 500;
  letter-spacing: -0.02em;
}

.c-trend {
  color: var(--c-positive);
  font-size: 9px;
}

.c-spark {
  display: block;
  width: 100%;
  height: auto;
  margin-top: 12px;
  overflow: visible;
}

.c-spark-grid line {
  stroke: var(--c-line);
  stroke-width: 0.5;
  opacity: 0.5;
}

.c-spark-area {
  fill: var(--c-accent);
  opacity: 0.06;
}

.c-spark-line {
  fill: none;
  stroke: var(--c-accent);
  stroke-width: 1.5;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.c-spark-point {
  fill: var(--c-bg-soft);
  stroke: var(--c-accent);
  stroke-width: 1.5;
}

.c-spark-axis {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  color: var(--c-text-3);
  font-size: 8px;
}

.c-context-section {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.c-context-section header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--c-text-2);
  font-size: 10px;
}

.c-count {
  display: grid;
  place-items: center;
  min-width: 16px;
  height: 16px;
  border-radius: 999px;
  background: var(--c-panel-3);
  color: var(--c-text-2);
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 9px;
}

.c-context-link {
  color: var(--c-text-3);
  font-size: 9px;
  text-decoration: none;
}

.c-danger-link {
  align-self: flex-start;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--c-text-3);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.c-danger-link:hover:not(:disabled) {
  color: var(--c-negative);
}

.c-danger-link:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.c-context-link:hover {
  color: var(--c-text-2);
}

.c-quote-card {
  padding: 12px;
  border: 1px solid var(--c-line);
  border-radius: 10px;
  background: var(--c-bg-soft);
}

.c-quote-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 7px;
}

.c-quote-card-label {
  color: var(--c-text-3);
  font-size: 9px;
}

.c-quote-card strong {
  display: block;
  font-size: 12px;
  font-weight: 500;
}

.c-quote-price {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 3px;
}

.c-quote-price span {
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 16px;
}

.c-quote-price small {
  color: var(--c-text-3);
  font-size: 9px;
}

.c-quote-card p {
  margin: 7px 0 8px;
  color: var(--c-text-3);
  font-size: 9px;
}

.c-text-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--c-text-2);
  font-size: 10px;
  text-decoration: none;
}

.c-text-link:hover {
  color: var(--c-text);
}

.c-confirm-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 32px;
  margin-top: 9px;
  border: 1px solid var(--c-line);
  border-radius: 8px;
  background: var(--c-panel-2);
  color: var(--c-text);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.c-confirm-btn:hover:not(:disabled) {
  background: var(--c-panel-3);
}

.c-confirm-btn:disabled {
  color: var(--c-text-3);
  cursor: not-allowed;
}

.c-order-created {
  padding: 10px;
  border: 1px solid var(--c-line);
  border-radius: 8px;
  background: var(--c-bg-soft);
  color: var(--c-text-2);
  font-size: 10px;
}

.c-inline-error {
  margin: 0;
  color: var(--c-negative);
  font-size: 9px;
}

.c-order-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 0;
  border-bottom: 1px solid var(--c-line-soft);
}

.c-order-row:last-of-type {
  border-bottom: 0;
}

.c-order-mark {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  border: 1px solid var(--c-line);
  border-radius: 7px;
  color: var(--c-text-3);
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
}

.c-order-row > span:nth-child(2) {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 1px;
}

.c-order-row strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 10px;
  font-weight: 500;
}

.c-order-row small {
  color: var(--c-text-3);
  font-size: 9px;
}

.c-order-amount {
  color: var(--c-text-2);
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 10px;
}

.c-context-note {
  margin: 0;
  color: var(--c-text-3);
  font-size: 9px;
}

.c-mobile-nav {
  display: none;
}

.c-mobile-thread-screen {
  display: none;
}

@media (max-width: 760px) {
  .c-topbar {
    display: none;
  }

  .c-chat {
    padding-top: 0;
  }

  .c-chat-head {
    position: sticky;
    top: 0;
    z-index: 5;
    padding: 8px 0 10px;
    background: var(--c-bg);
  }

  .c-back-btn {
    display: grid;
  }

  .c-message-meta {
    display: none;
  }

  .c-bubble-time {
    display: inline-block;
  }

  .c-message.user .c-bubble {
    border-color: #2a3a31;
    background: #1e2a24;
    color: #dfe8e2;
  }

  .c-thread {
    padding-top: 12px;
    padding-bottom: 4px;
  }

  .c-composer {
    padding: 8px 0 10px;
    border: 0;
    background: transparent;
    box-shadow: none;
    border-radius: 0;
  }

  .c-composer-row {
    align-items: center;
    gap: 4px;
    padding: 4px 4px 4px 8px;
    border: 1px solid var(--c-line);
    border-radius: 22px;
    background: var(--c-panel);
  }

  .c-tool-btn {
    width: 26px;
    height: 26px;
    flex-basis: 26px;
  }

  .c-composer textarea {
    padding: 4px 0;
    font-size: 13px;
  }

  .c-send-btn {
    width: 32px;
    height: 32px;
    flex: 0 0 32px;
    justify-content: center;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: var(--c-panel-3);
  }

  .c-send-label {
    display: none;
  }

  .c-composer-foot {
    display: none;
  }

  .c-mobile-thread-screen {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: flex;
    flex-direction: column;
    background: var(--c-bg);
    color: var(--c-text);
  }

  .c-mobile-thread-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 56px;
    padding: 0 12px;
    border-bottom: 1px solid var(--c-line-soft);
  }

  .c-mobile-thread-head h1 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }

  .c-mobile-search {
    display: flex;
    align-items: center;
    gap: 8px;
    height: 36px;
    margin: 12px 16px;
    padding: 0 10px;
    border: 1px solid var(--c-line);
    border-radius: 10px;
    background: var(--c-panel);
    color: var(--c-text-3);
  }

  .c-mobile-search svg {
    width: 15px;
    height: 15px;
    flex: 0 0 15px;
  }

  .c-mobile-search input {
    min-width: 0;
    width: 100%;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--c-text);
    font: inherit;
    font-size: 12px;
  }

  .c-mobile-thread-list {
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    padding: 0 8px;
  }

  .c-mobile-thread-row {
    display: flex;
    align-items: center;
    gap: 11px;
    width: 100%;
    padding: 11px 8px;
    border: 0;
    border-bottom: 1px solid var(--c-line-soft);
    background: transparent;
    color: var(--c-text);
    text-align: left;
    font: inherit;
    cursor: pointer;
  }

  .c-mobile-thread-row:last-child {
    border-bottom: 0;
  }

  .c-mobile-thread-copy {
    display: flex;
    min-width: 0;
    flex: 1;
    flex-direction: column;
    gap: 3px;
  }

  .c-mobile-thread-copy > span {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
  }

  .c-mobile-thread-copy strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    font-weight: 500;
  }

  .c-mobile-thread-copy time {
    color: var(--c-text-3);
    font-size: 9px;
  }

  .c-mobile-thread-copy small {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--c-text-3);
    font-size: 11px;
  }
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

@media (max-width: 980px) {
  .c-shell {
    grid-template-columns: 216px minmax(0, 1fr);
  }

  .c-context {
    display: none;
  }

  .c-context.open {
    position: fixed;
    inset: 56px 0 0 auto;
    z-index: 20;
    display: block;
    width: min(320px, 88vw);
    border-left: 1px solid var(--c-line);
    box-shadow: -4px 0 8px rgba(0, 0, 0, 0.08);
  }

  .c-chat {
    padding-right: 24px;
    padding-left: 24px;
  }
}

@media (max-width: 760px) {
  .c-shell {
    display: flex;
    min-height: 100dvh;
    flex-direction: column;
  }

  .c-sidebar {
    display: none;
  }

  .c-main {
    min-height: 100dvh;
    padding-bottom: 64px;
  }

  .c-topbar {
    height: 52px;
    padding: 0 16px;
  }

  .c-mobile-brand,
  .c-topbar-divider {
    display: inline-block;
  }

  .c-topbar-crumb {
    display: none;
  }

  .c-chat {
    max-width: none;
    padding: 0 16px 12px;
  }

  .c-chat-head {
    padding: 16px 0 12px;
  }

  .c-chat-head h1 {
    font-size: 15px;
  }

  .c-chat-head p {
    font-size: 9px;
  }

  .c-message {
    max-width: 88%;
  }

  .c-thread {
    gap: 16px;
    padding-top: 16px;
  }

  .c-prompt-row {
    padding: 8px 0 10px;
  }

  .c-composer {
    padding: 10px;
  }

  .c-composer-foot > span {
    display: none;
  }

  .c-composer-foot {
    justify-content: flex-end;
  }

  .c-mobile-nav {
    position: fixed;
    right: 0;
    bottom: 0;
    left: 0;
    z-index: 30;
    display: flex;
    align-items: center;
    justify-content: space-around;
    height: 56px;
    border-top: 1px solid var(--c-line);
    background: var(--c-panel);
    padding-bottom: env(safe-area-inset-bottom);
  }

  .c-mobile-nav a,
  .c-mobile-nav button {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    border: 0;
    background: transparent;
    color: var(--c-text-3);
    font: inherit;
    font-size: 9px;
    text-decoration: none;
    cursor: pointer;
  }

  .c-mobile-nav a.active {
    color: var(--c-text);
    font-weight: 600;
  }

  .c-mobile-nav svg {
    width: 18px;
    height: 18px;
  }

  .c-context.open {
    inset: 52px 0 0 auto;
    width: min(320px, 92vw);
  }

  .c-context-scroll {
    padding: 20px 16px;
  }
}

/* iOS PWA safe area：只在移动端生效，桌面端 env() 为 0。 */
@media (max-width: 760px) {
  .c-main {
    padding-bottom: calc(64px + env(safe-area-inset-bottom));
  }

  .c-chat-head {
    padding-top: calc(8px + env(safe-area-inset-top));
  }

  .c-mobile-nav {
    height: calc(56px + env(safe-area-inset-bottom));
    padding-bottom: env(safe-area-inset-bottom);
  }

  .c-mobile-thread-head {
    height: calc(56px + env(safe-area-inset-top));
    padding-top: env(safe-area-inset-top);
  }

  .c-mobile-thread-screen {
    padding-bottom: env(safe-area-inset-bottom);
  }
}
</style>
