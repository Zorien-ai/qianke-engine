<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { getJson, postJson, del, postForm } from "../api";

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
const isOnline = ref(typeof navigator === "undefined" ? true : navigator.onLine);
const deferredInstallPrompt = ref(null);
const showInstall = ref(false);
const installHint = ref("");
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
  avatar_url: "",
  user_avatar_url: "",
});
const liveThreadId = ref("");
const liveDraft = ref(null);
const liveOrder = ref(null);
const storeQuote = ref(null);
const hasMoreCompanion = ref(false);
const companionBefore = ref("");
const clearingCompanion = ref(false);
const hasMoreStore = ref(false);
const storeBefore = ref("");
const loadingOlderStore = ref(false);
const storeHistoryHint = ref("");
const agentBusy = ref(false);
const agentError = ref("");
const pendingRetry = ref(null);
const lastStoreSend = ref(null);
const copyTip = ref("");
const showJumpBottom = ref(false);
const composerFocused = ref(false);
const avatarFileInput = ref(null);
const avatarTarget = ref("companion");
const avatarBusy = ref("");
const avatarError = ref("");
const avatarBroken = ref({});
const avatarPreview = ref({ companion: "", user: "" });
const avatarPreviewUrls = new Set();
const AVATAR_MAX_BYTES = 1024 * 1024;
const AVATAR_ACCEPT_TYPES = ["image/png", "image/jpeg", "image/webp"];
let copyTipTimer = null;
let messagePressTimer = null;
let messagePressPoint = null;

const activeThread = computed(() => threads.value.find((item) => item.id === activeId.value) || threads.value[0]);
const messages = computed(() => messagesByThread.value[activeId.value] || []);
const filteredThreads = computed(() => {
  const keyword = search.value.trim();
  if (!keyword) return threads.value;
  return threads.value.filter((item) => item.name.includes(keyword) || item.preview.includes(keyword));
});
const isCompanion = computed(() => activeId.value === "companion");
const planLabel = computed(() => `L${companion.value.level || 4}`);

function messageAuthor(role) {
  if (role === "user") return "我";
  if (role === "companion") return companion.value.name;
  if (role === "merchant") return activeThread.value.name;
  return "系统";
}

function messageAvatarLabel(role) {
  const name = messageAuthor(role);
  return name.slice(0, 1) || "系";
}

// ---------------- 自定义头像（伙伴 / 我的） ----------------
function avatarSrc(kind) {
  const preview = avatarPreview.value[kind] || "";
  if (preview) return preview;
  if (kind === "user") return companion.value.user_avatar_url || "";
  return companion.value.avatar_url || "";
}

function avatarChar(kind) {
  if (kind === "user") {
    const nickname = String(companion.value.user_nickname || "").trim();
    return (nickname || "我").slice(0, 1);
  }
  return String(companion.value.name || "伴").slice(0, 1);
}

function avatarVisible(kind) {
  const src = avatarSrc(kind);
  return Boolean(src) && !avatarBroken.value[src];
}

function onAvatarError(src) {
  if (!src) return;
  avatarBroken.value = { ...avatarBroken.value, [src]: true };
}

function threadAvatarKind(thread) {
  return thread?.kind === "companion" ? "companion" : "";
}

function threadAvatarSrc(thread) {
  const kind = threadAvatarKind(thread);
  return kind ? avatarSrc(kind) : "";
}

function threadAvatarVisible(thread) {
  const kind = threadAvatarKind(thread);
  return kind ? avatarVisible(kind) : false;
}

function revokePreviewUrl(url) {
  if (!url || !avatarPreviewUrls.has(url)) return;
  URL.revokeObjectURL(url);
  avatarPreviewUrls.delete(url);
}

function avatarErrorMessage(error) {
  const detail = error?.payload?.detail;
  if (detail && typeof detail === "object" && detail.message) return detail.message;
  if (typeof error?.detail === "string") return error.detail;
  return error?.message || "头像处理失败，请重试";
}

function openAvatarPicker(kind) {
  if (avatarBusy.value) return;
  avatarTarget.value = kind === "user" ? "user" : "companion";
  avatarError.value = "";
  const input = avatarFileInput.value;
  if (input) {
    input.value = "";
    input.click();
  }
}

async function onAvatarFileChange(event) {
  const input = event.target;
  const file = input?.files?.[0];
  if (input) input.value = "";
  if (!file || avatarBusy.value) return;
  const kind = avatarTarget.value === "user" ? "user" : "companion";
  const type = String(file.type || "").toLowerCase();
  if (!AVATAR_ACCEPT_TYPES.includes(type)) {
    avatarError.value = "头像只支持 PNG / JPEG / WebP";
    return;
  }
  if (file.size > AVATAR_MAX_BYTES) {
    avatarError.value = "头像不能超过 1MB";
    return;
  }

  const previewUrl = URL.createObjectURL(file);
  avatarPreviewUrls.add(previewUrl);
  revokePreviewUrl(avatarPreview.value[kind]);
  avatarPreview.value = { ...avatarPreview.value, [kind]: previewUrl };
  avatarBusy.value = kind;
  avatarError.value = "";
  try {
    const form = new FormData();
    form.append("file", file);
    const data = await postForm(`/api/c/companion/avatar/${kind}`, form);
    if (data) companion.value = { ...companion.value, ...data };
    avatarPreview.value = { ...avatarPreview.value, [kind]: "" };
  } catch (error) {
    // 失败回退到上传前的头像 URL；没有则回退首字。
    avatarPreview.value = { ...avatarPreview.value, [kind]: "" };
    avatarError.value = avatarErrorMessage(error);
  } finally {
    revokePreviewUrl(previewUrl);
    avatarBusy.value = "";
  }
}

async function resetAvatar(kind) {
  if (avatarBusy.value) return;
  const target = kind === "user" ? "user" : "companion";
  avatarBusy.value = target;
  avatarError.value = "";
  try {
    const data = await del(`/api/c/companion/avatar/${target}`);
    if (data) companion.value = { ...companion.value, ...data };
  } catch (error) {
    avatarError.value = avatarErrorMessage(error);
  } finally {
    avatarBusy.value = "";
  }
}
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

function newClientMessageId() {
  return `cmsg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

function showCopyTip(text = "已复制") {
  copyTip.value = text;
  if (copyTipTimer) clearTimeout(copyTipTimer);
  copyTipTimer = window.setTimeout(() => {
    copyTip.value = "";
    copyTipTimer = null;
  }, 1600);
}

async function copyMessage(text) {
  const value = String(text || "").trim();
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    showCopyTip("已复制");
  } catch {
    try {
      const area = document.createElement("textarea");
      area.value = value;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      showCopyTip("已复制");
    } catch {
      showCopyTip("复制失败");
    }
  }
}

function onMessagePress(event, message) {
  if (event.pointerType === "mouse") return;
  messagePressPoint = { x: event.clientX, y: event.clientY };
  if (messagePressTimer) clearTimeout(messagePressTimer);
  messagePressTimer = window.setTimeout(() => {
    messagePressTimer = null;
    copyMessage(message.text);
  }, 520);
}

function onMessageMove(event) {
  if (!messagePressTimer || !messagePressPoint) return;
  if (Math.abs(event.clientX - messagePressPoint.x) > 10 || Math.abs(event.clientY - messagePressPoint.y) > 10) {
    clearTimeout(messagePressTimer);
    messagePressTimer = null;
  }
}

function onMessageRelease() {
  if (messagePressTimer) clearTimeout(messagePressTimer);
  messagePressTimer = null;
  messagePressPoint = null;
}

function onThreadScroll(event) {
  const el = event?.target;
  if (!el) return;
  showJumpBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight > 160;
}

function scrollToBottom() {
  showJumpBottom.value = false;
  requestAnimationFrame(() => {
    const el = document.getElementById("c-app-thread");
    if (el) el.scrollTop = el.scrollHeight;
  });
}

function onComposerFocus() {
  composerFocused.value = true;
  syncViewportHeight();
  window.setTimeout(scrollToBottom, 120);
}

function onComposerBlur() {
  composerFocused.value = false;
}

function syncViewportHeight() {
  const height = window.visualViewport?.height || window.innerHeight;
  if (!height) return;
  document.documentElement.style.setProperty("--c-vh", `${height}px`);
}

function onViewportResize() {
  syncViewportHeight();
  scrollToBottom();
}

function resizeComposer(event) {
  const el = event?.target;
  if (!el || el.tagName !== "TEXTAREA") return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
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

function mapStoreMessage(message) {
  return {
    id: message.message_id,
    role: message.sender_id?.startsWith("companion_")
      ? "companion"
      : message.sender_id?.startsWith("buyer_")
        ? "user"
        : "merchant",
    text: cleanReply(message.content),
    time: (message.created_at || "").slice(11, 16),
    createdAt: message.created_at,
  };
}

// 与后端 social.get_messages 的稳定游标一致：created_at + message_id 兜底同一时间戳。
function storeCursor(message) {
  if (!message?.created_at) return "";
  return message.message_id
    ? `${message.created_at}|${message.message_id}`
    : message.created_at;
}

async function loadStoreMessages() {
  storeHistoryHint.value = "";
  try {
    const data = await getJson("/api/c/friends/store_demo/messages?limit=20");
    if (data?.messages?.length) {
      messagesByThread.value.store_demo = data.messages.map(mapStoreMessage);
      hasMoreStore.value = data.messages.length >= 20;
      storeBefore.value = storeCursor(data.messages[0]);
    } else {
      hasMoreStore.value = false;
      storeBefore.value = "";
    }
    scrollToBottom();
  } catch {
    // 保留种子会话，避免接口异常时出现空屏。
  }
}

async function loadOlderStore() {
  if (!hasMoreStore.value || !storeBefore.value || loadingOlderStore.value) return;
  loadingOlderStore.value = true;
  storeHistoryHint.value = "";
  try {
    const data = await getJson(
      `/api/c/friends/store_demo/messages?limit=20&before=${encodeURIComponent(storeBefore.value)}`
    );
    const raw = data?.messages || [];
    const existing = new Set((messagesByThread.value.store_demo || []).map((message) => message.id));
    const older = raw
      .map(mapStoreMessage)
      .filter((message) => message.id && !existing.has(message.id));
    messagesByThread.value.store_demo = [...older, ...(messagesByThread.value.store_demo || [])];
    hasMoreStore.value = raw.length >= 20;
    if (raw.length) storeBefore.value = storeCursor(raw[0]);
  } catch (error) {
    // 加载失败只做轻提示，保留当前消息与滚动位置。
    storeHistoryHint.value = error?.detail || error?.message || "更早消息加载失败，请稍后重试";
  } finally {
    loadingOlderStore.value = false;
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
    pendingRetry.value = null;
    lastStoreSend.value = null;
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
    if (lastStoreSend.value) {
      pendingRetry.value = {
        threadId: "store_demo",
        text: lastStoreSend.value.text,
        clientId: lastStoreSend.value.clientId,
      };
      lastStoreSend.value = null;
    }
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
  const clientId = newClientMessageId();
  pushMessage({ role: "user", text });
  draft.value = "";
  const input = document.getElementById("c-app-input");
  if (input) input.style.height = "auto";
  pendingRetry.value = null;
  scrollToBottom();
  await deliverText(text, false, clientId);
}

async function retrySend() {
  const failed = pendingRetry.value;
  if (!failed || typing.value) return;
  if (failed.threadId !== activeId.value) {
    pendingRetry.value = null;
    return;
  }
  pendingRetry.value = null;
  agentError.value = "";
  await deliverText(failed.text, true, failed.clientId);
}

function clearRetry() {
  pendingRetry.value = null;
}

async function deliverText(text, isRetry = false, clientId = null) {
  if (activeId.value === "store_demo") {
    if (storeSocket && storeSocket.readyState === WebSocket.OPEN) {
      typing.value = true;
      agentError.value = "";
      lastStoreSend.value = { text, clientId };
      storeSocket.send(JSON.stringify({ content: text, client_message_id: clientId || undefined }));
      return;
    }
    typing.value = true;
    try {
      const result = await postJson("/api/c/friends/store_demo/messages", {
        content: text,
        client_message_id: clientId || undefined,
      });
      if (result.reply) {
        pushMessage({ role: "merchant", text: cleanReply(result.reply.content) });
        if (result.reply.metadata?.quote_id) storeQuote.value = result.reply.metadata;
      }
      if (result.companion_message) {
        pushMessage({ role: "companion", text: cleanReply(result.companion_message.content) });
      }
      lastStoreSend.value = null;
      agentError.value = "";
    } catch (error) {
      lastStoreSend.value = null;
      agentError.value = error?.detail || error?.message || "店宠暂时无法回应";
      pendingRetry.value = { threadId: activeId.value, text, clientId };
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

  if (!isRetry) await persistAppMessage("user", text);
  typing.value = true;
  try {
    const result = await postJson("/api/c/agent/run", {
      message: text,
      thread_id: liveThreadId.value || undefined,
      client_message_id: clientId || undefined,
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
    pendingRetry.value = { threadId: activeId.value, text, clientId };
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
    if (data) {
      companion.value = { ...companion.value, ...data };
      avatarBroken.value = {};
    }
  } catch {
    // UI 参考页在未登录/接口不可用时仍可展示静态状态。
  }
}

async function switchThread(id) {
  closeStoreSocket();
  lastStoreSend.value = null;
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

function onBeforeInstall(event) {
  event.preventDefault();
  deferredInstallPrompt.value = event;
  showInstall.value = true;
}

function onOnline() {
  isOnline.value = true;
}

function onOffline() {
  isOnline.value = false;
}

async function installPwa() {
  const prompt = deferredInstallPrompt.value;
  if (!prompt) return;
  prompt.prompt();
  try {
    await prompt.userChoice;
  } finally {
    deferredInstallPrompt.value = null;
    showInstall.value = false;
  }
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
  syncViewportHeight();
  window.visualViewport?.addEventListener("resize", onViewportResize);
  window.visualViewport?.addEventListener("scroll", onViewportResize);
  window.addEventListener("online", onOnline);
  window.addEventListener("offline", onOffline);
  window.addEventListener("beforeinstallprompt", onBeforeInstall);
  const standalone =
    window.matchMedia?.("(display-mode: standalone)")?.matches || window.navigator.standalone === true;
  if (!standalone && /iPad|iPhone|iPod/.test(window.navigator.userAgent || "")) {
    installHint.value = "Safari：分享 → 添加到主屏幕";
    showInstall.value = true;
  }
  scrollToBottom();
});

onBeforeUnmount(() => {
  if (copyTipTimer) clearTimeout(copyTipTimer);
  if (messagePressTimer) clearTimeout(messagePressTimer);
  for (const url of avatarPreviewUrls) URL.revokeObjectURL(url);
  avatarPreviewUrls.clear();
  window.visualViewport?.removeEventListener("resize", onViewportResize);
  window.visualViewport?.removeEventListener("scroll", onViewportResize);
  window.removeEventListener("online", onOnline);
  window.removeEventListener("offline", onOffline);
  window.removeEventListener("beforeinstallprompt", onBeforeInstall);
  closeStoreSocket();
});
</script>

<template>
  <div class="c-app" :class="{ 'keyboard-open': composerFocused }">
    <div v-if="!isOnline" class="c-offline-banner" role="status">
      当前处于离线状态，恢复连接后消息会自动继续。
    </div>

    <div v-if="showInstall" class="c-install-banner" role="status">
      <div class="c-install-copy">
        <strong>安装千客</strong>
        <small>{{ installHint || "添加到主屏幕，像 App 一样打开" }}</small>
      </div>
      <button v-if="deferredInstallPrompt" type="button" class="c-install-btn" @click="installPwa">安装</button>
      <button type="button" class="c-install-dismiss" aria-label="关闭安装提示" @click="showInstall = false">关闭</button>
    </div>

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
            <span class="c-avatar small" :class="thread.kind">
              <img
                v-if="threadAvatarVisible(thread)"
                :src="threadAvatarSrc(thread)"
                alt=""
                @error="onAvatarError(threadAvatarSrc(thread))"
              />
              <template v-else>{{ thread.name.slice(0, 1) }}</template>
            </span>
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
          <span class="c-avatar">
            <img
              v-if="avatarVisible('companion')"
              :src="avatarSrc('companion')"
              alt=""
              @error="onAvatarError(avatarSrc('companion'))"
            />
            <template v-else>{{ avatarChar('companion') }}</template>
          </span>
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
            <button
              type="button"
              class="c-avatar top c-avatar-btn"
              :aria-label="avatarBusy === 'companion' ? '伙伴头像上传中' : '更换伙伴头像'"
              @click="openAvatarPicker('companion')"
            >
              <img
                v-if="avatarVisible('companion')"
                :src="avatarSrc('companion')"
                alt=""
                @error="onAvatarError(avatarSrc('companion'))"
              />
              <template v-else>{{ avatarChar('companion') }}</template>
            </button>
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
              <button
                v-if="activeThread.kind === 'companion'"
                type="button"
                class="c-avatar c-avatar-btn"
                aria-label="更换伙伴头像"
                @click="openAvatarPicker('companion')"
              >
                <img
                  v-if="avatarVisible('companion')"
                  :src="avatarSrc('companion')"
                  alt=""
                  @error="onAvatarError(avatarSrc('companion'))"
                />
                <template v-else>{{ avatarChar('companion') }}</template>
              </button>
              <span v-else class="c-avatar">{{ activeThread.name.slice(0, 1) }}</span>
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

          <div id="c-app-thread" class="c-thread" aria-live="polite" @scroll="onThreadScroll">
            <div
              v-if="(activeId === 'companion' && hasMoreCompanion) || (activeId === 'store_demo' && hasMoreStore)"
              class="c-load-more-row"
            >
              <button
                v-if="activeId === 'companion'"
                type="button"
                class="c-load-more"
                @click="loadOlderCompanion"
              >加载更早消息</button>
              <button
                v-else
                type="button"
                class="c-load-more"
                :disabled="loadingOlderStore"
                @click="loadOlderStore"
              >{{ loadingOlderStore ? "加载中…" : "加载更早消息" }}</button>
              <span
                v-if="activeId === 'store_demo' && storeHistoryHint"
                class="c-load-more-hint"
              >{{ storeHistoryHint }}</span>
            </div>
            <div class="c-date-line"><span>今天</span></div>
            <p v-if="!messages.length" class="c-empty-thread">开始新的对话。</p>
            <article
              v-for="message in messages"
              :key="message.id"
              class="c-message"
              :class="[message.role]"
              @pointerdown="onMessagePress($event, message)"
              @pointermove="onMessageMove"
              @pointerup="onMessageRelease"
              @pointercancel="onMessageRelease"
              @pointerleave="onMessageRelease"
            >
              <button
                v-if="message.role === 'user' || message.role === 'companion'"
                type="button"
                class="c-msg-avatar"
                :class="message.role"
                :aria-label="message.role === 'user' ? '更换我的头像' : '更换伙伴头像'"
                @click.stop="openAvatarPicker(message.role === 'user' ? 'user' : 'companion')"
              >
                <img
                  v-if="avatarVisible(message.role === 'user' ? 'user' : 'companion')"
                  :src="avatarSrc(message.role === 'user' ? 'user' : 'companion')"
                  alt=""
                  @error="onAvatarError(avatarSrc(message.role === 'user' ? 'user' : 'companion'))"
                />
                <template v-else>{{ messageAvatarLabel(message.role) }}</template>
              </button>
              <span
                v-else
                class="c-msg-avatar"
                :class="message.role"
                aria-hidden="true"
              >{{ messageAvatarLabel(message.role) }}</span>
              <div class="c-message-content">
                <div class="c-message-meta">
                  <span>{{ messageAuthor(message.role) }}</span>
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
              </div>
            </article>
            <div v-if="typing" class="c-typing" role="status">
              <i /><i /><i />
              <span>{{ activeThread.name }}正在输入</span>
            </div>
          </div>

          <button
            v-if="showJumpBottom"
            type="button"
            class="c-jump-bottom"
            @click="scrollToBottom"
          >
            回到底部
          </button>

          <div
            v-if="pendingRetry && pendingRetry.threadId === activeId"
            class="c-retry-row"
            role="alert"
          >
            <span>消息没有发出去，内容已保留。</span>
            <button type="button" class="c-retry-btn" @click="retrySend">重试</button>
            <button type="button" class="c-retry-dismiss" @click="clearRetry">忽略</button>
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
                @focus="onComposerFocus"
                @blur="onComposerBlur"
                @input="resizeComposer"
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

      <div v-if="copyTip" class="c-copy-toast" role="status">{{ copyTip }}</div>

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
            <header><span>头像</span><span class="c-context-link">PNG / JPEG / WebP · ≤1MB</span></header>
            <div class="c-avatar-row">
              <span class="c-avatar small">
                <img
                  v-if="avatarVisible('companion')"
                  :src="avatarSrc('companion')"
                  alt=""
                  @error="onAvatarError(avatarSrc('companion'))"
                />
                <template v-else>{{ avatarChar('companion') }}</template>
              </span>
              <span class="c-avatar-row-copy">
                <strong>伙伴头像</strong>
                <small>{{ avatarBusy === 'companion' ? '上传中…' : (companion.avatar_url ? '自定义头像' : '未设置，显示首字') }}</small>
              </span>
              <button
                class="c-avatar-action"
                type="button"
                :disabled="Boolean(avatarBusy)"
                @click="openAvatarPicker('companion')"
              >{{ avatarBusy === 'companion' ? '上传中' : '更换' }}</button>
              <button
                v-if="companion.avatar_url"
                class="c-avatar-action subtle"
                type="button"
                :disabled="Boolean(avatarBusy)"
                @click="resetAvatar('companion')"
              >恢复默认</button>
            </div>
            <div class="c-avatar-row">
              <span class="c-avatar small">
                <img
                  v-if="avatarVisible('user')"
                  :src="avatarSrc('user')"
                  alt=""
                  @error="onAvatarError(avatarSrc('user'))"
                />
                <template v-else>{{ avatarChar('user') }}</template>
              </span>
              <span class="c-avatar-row-copy">
                <strong>我的头像</strong>
                <small>{{ avatarBusy === 'user' ? '上传中…' : (companion.user_avatar_url ? '自定义头像' : '未设置，显示首字') }}</small>
              </span>
              <button
                class="c-avatar-action"
                type="button"
                :disabled="Boolean(avatarBusy)"
                @click="openAvatarPicker('user')"
              >{{ avatarBusy === 'user' ? '上传中' : '更换' }}</button>
              <button
                v-if="companion.user_avatar_url"
                class="c-avatar-action subtle"
                type="button"
                :disabled="Boolean(avatarBusy)"
                @click="resetAvatar('user')"
              >恢复默认</button>
            </div>
            <p v-if="avatarError" class="c-inline-error" role="alert">{{ avatarError }}</p>
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
          <span class="c-avatar" :class="thread.kind">
            <img
              v-if="threadAvatarVisible(thread)"
              :src="threadAvatarSrc(thread)"
              alt=""
              @error="onAvatarError(threadAvatarSrc(thread))"
            />
            <template v-else>{{ thread.name.slice(0, 1) }}</template>
          </span>
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

    <input
      ref="avatarFileInput"
      class="c-avatar-file"
      type="file"
      accept="image/png,image/jpeg,image/webp"
      aria-label="选择头像文件"
      @change="onAvatarFileChange"
    />
  </div>
</template>

<style scoped>
.c-app {
  --c-bg: #ffffff;
  --c-bg-soft: #fcfcfb;
  --c-panel: #ffffff;
  --c-panel-2: #f6f6f3;
  --c-panel-3: #efefeb;
  --c-line: #e4e4de;
  --c-line-soft: #efefeb;
  --c-text: #171715;
  --c-text-2: #5c5c56;
  --c-text-3: #6b6b64;
  --c-accent: #587376;
  --c-positive: #6f8f7a;
  --c-warning: #7a6340;
  --c-negative: #8a4f4f;
  min-height: 100dvh;
  background: var(--c-bg);
  color: var(--c-text);
  color-scheme: light;
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

.c-load-more:disabled {
  cursor: default;
  opacity: 0.6;
}

.c-load-more-hint {
  margin-left: 8px;
  align-self: center;
  color: var(--c-text-3);
  font-size: 9px;
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

.c-offline-banner {
  position: fixed;
  top: 0;
  right: 0;
  left: 0;
  z-index: 60;
  padding: 7px 16px;
  background: var(--c-warning);
  color: #16130d;
  font-size: 10px;
  text-align: center;
}

.c-install-banner {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 60;
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 360px;
  padding: 12px 14px;
  border: 1px solid var(--c-line);
  border-radius: 10px;
  background: var(--c-panel);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.08);
}

.c-install-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.c-install-copy strong {
  font-size: 11px;
  font-weight: 600;
}

.c-install-copy small {
  color: var(--c-text-3);
  font-size: 9px;
}

.c-install-btn,
.c-install-dismiss {
  padding: 5px 8px;
  border: 1px solid var(--c-line);
  border-radius: 7px;
  background: transparent;
  color: var(--c-text-2);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.c-install-btn {
  border-color: var(--c-text-3);
  color: var(--c-text);
}

.c-install-dismiss {
  color: var(--c-text-3);
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
    border-color: var(--c-line);
    background: var(--c-panel-2);
    color: var(--c-text);
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

  .c-install-banner {
    right: 16px;
    bottom: calc(64px + env(safe-area-inset-bottom));
    left: 16px;
    max-width: none;
  }
}
/* ===== 白色极简对话：纸面、行式消息、细线输入 ===== */
.c-app .c-shell,
.c-app .c-main {
  background: var(--c-bg);
}

.c-app .c-sidebar {
  border-right-color: var(--c-line);
  background: var(--c-bg-soft);
}

.c-app .c-search,
.c-app .c-composer {
  background: var(--c-panel);
}

.c-app .c-search {
  border-radius: 8px;
}

.c-app .c-thread-row {
  border-radius: 8px;
}

.c-app .c-thread-row:hover {
  background: var(--c-panel-2);
}

.c-app .c-thread-row.active {
  background: var(--c-panel-3);
}

.c-app .c-avatar {
  border-color: var(--c-line);
  background: var(--c-panel);
  color: var(--c-text-2);
}

.c-app .c-avatar.merchant {
  background: var(--c-panel-2);
}

.c-app .c-topbar {
  border-bottom-color: var(--c-line);
  background: var(--c-bg);
}

.c-app .c-chat {
  max-width: 920px;
  padding-bottom: 24px;
}

.c-app .c-chat-head {
  padding: 18px 0 15px;
  border-bottom-color: var(--c-line);
}

.c-app .c-thread {
  gap: 22px;
  padding-top: 24px;
}

.c-app .c-date-line span {
  padding: 0;
  border: 0;
  color: var(--c-text-3);
}

.c-app .c-message {
  display: flex;
  max-width: 84%;
  flex-direction: row;
  align-items: flex-start;
  gap: 8px;
}

.c-app .c-message.user {
  max-width: 78%;
  flex-direction: row-reverse;
  align-items: flex-start;
}

.c-app .c-message-content {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.c-app .c-message.user .c-message-content {
  align-items: flex-end;
}

.c-app .c-msg-avatar {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border: 1px solid var(--c-line);
  border-radius: 50%;
  background: var(--c-panel-2);
  color: var(--c-text-2);
  font-size: 10px;
  font-weight: 500;
}

.c-app .c-msg-avatar.user {
  border-color: var(--c-line);
  background: var(--c-panel);
  color: var(--c-text);
}

.c-app .c-msg-avatar.merchant {
  border-radius: 8px;
}

.c-app .c-message-meta {
  color: var(--c-text-3);
}

.c-app .c-message-meta span {
  color: var(--c-text-2);
  font-weight: 500;
}

.c-app .c-bubble {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--c-text);
  font-size: 13px;
  line-height: 1.75;
}

.c-app .c-message.merchant .c-bubble,
.c-app .c-message.companion .c-bubble {
  background: transparent;
}

.c-app .c-message.user .c-bubble {
  padding: 9px 11px 6px;
  border: 1px solid var(--c-text);
  border-radius: 10px;
  background: var(--c-text);
  color: var(--c-bg);
}

.c-app .c-message.user .c-bubble-time {
  color: rgba(255, 255, 255, 0.55);
}

.c-app .c-bubble-time {
  display: inline;
  color: var(--c-text-3);
}

.c-app .c-quote-attachment {
  border-color: var(--c-line);
  border-radius: 8px;
  background: var(--c-panel);
}

.c-app .c-load-more {
  border-radius: 8px;
  background: var(--c-panel);
}

.c-app .c-prompt {
  border-radius: 8px;
  background: var(--c-panel);
}

.c-app .c-retry-row {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 4px 0 6px;
  padding: 7px 9px;
  border: 1px solid rgba(122, 99, 64, 0.22);
  border-radius: 8px;
  background: rgba(160, 138, 100, 0.08);
  color: var(--c-warning);
  font-size: 9px;
}

.c-app .c-retry-row > span {
  min-width: 0;
  flex: 1;
}

.c-app .c-retry-btn,
.c-app .c-retry-dismiss {
  padding: 3px 7px;
  border: 1px solid currentColor;
  border-radius: 6px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 9px;
  cursor: pointer;
}

.c-app .c-retry-dismiss {
  border-color: transparent;
  color: var(--c-text-3);
}

.c-app .c-jump-bottom {
  align-self: center;
  margin: -4px auto 6px;
  padding: 5px 10px;
  border: 1px solid var(--c-line);
  border-radius: 999px;
  background: var(--c-panel);
  color: var(--c-text-2);
  font: inherit;
  font-size: 9px;
  cursor: pointer;
}

.c-app .c-copy-toast {
  position: fixed;
  bottom: calc(118px + env(safe-area-inset-bottom));
  left: 50%;
  z-index: 70;
  padding: 7px 11px;
  border: 1px solid var(--c-text);
  border-radius: 999px;
  background: var(--c-text);
  color: var(--c-bg);
  font-size: 10px;
  transform: translateX(-50%);
}

.c-app .c-composer {
  padding: 7px 7px 7px 12px;
  border-color: var(--c-line);
  border-radius: 12px;
  box-shadow: none;
}

.c-app .c-composer textarea {
  font-size: 12px;
}

.c-app .c-send-btn {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border-color: var(--c-text);
  border-radius: 50%;
  background: var(--c-text);
  color: var(--c-bg);
}

.c-app .c-send-btn .c-send-label {
  display: none;
}

.c-app .c-send-btn svg {
  width: 14px;
  height: 14px;
}

.c-app .c-send-btn:hover:not(:disabled) {
  background: #2b2b27;
}

.c-app .c-send-btn:disabled {
  border-color: var(--c-line);
  background: var(--c-panel-3);
  color: var(--c-text-3);
}

.c-app .c-context {
  border-left-color: var(--c-line);
  background: var(--c-bg-soft);
}

.c-app .c-context-head,
.c-app .c-context-section,
.c-app .c-context-section header {
  border-color: var(--c-line);
}

.c-app .c-quote-card {
  border-color: var(--c-line);
  background: var(--c-panel);
}

.c-app .c-offline-banner {
  border-bottom: 1px solid var(--c-line);
  background: var(--c-panel-2);
  color: var(--c-text-2);
}

.c-app .c-install-banner {
  border-color: var(--c-line);
  background: var(--c-panel);
  box-shadow: 0 2px 8px rgba(15, 15, 17, 0.06);
}

.c-app .c-unread {
  background: var(--c-text);
  color: var(--c-bg);
}

.c-app .c-spark-area {
  opacity: 0.08;
}

/* 移动端对话：更紧凑的头部、更清晰的发件块 */
@media (max-width: 760px) {
  .c-app {
    height: var(--c-vh, 100dvh);
    min-height: 0;
  }

  .c-app .c-shell {
    height: 100%;
    min-height: 0;
  }

  .c-app .c-main {
    height: 100%;
    min-height: 0;
  }

  .c-app .c-chat {
    min-height: 0;
  }

  .c-app.keyboard-open .c-mobile-nav {
    display: none;
  }

  .c-app.keyboard-open .c-main {
    padding-bottom: env(safe-area-inset-bottom);
  }

  .c-app .c-copy-toast {
    bottom: calc(84px + env(safe-area-inset-bottom));
  }

  .c-app .c-message {
    max-width: 88%;
  }

  .c-app .c-message.user {
    max-width: 84%;
  }

  .c-app .c-msg-avatar {
    width: 30px;
    height: 30px;
    flex-basis: 30px;
  }

  .c-app .c-back-btn {
    width: 36px;
    height: 36px;
    margin-left: -8px;
    border-radius: 8px;
  }

  .c-app .c-chat-head {
    padding: calc(10px + env(safe-area-inset-top)) 0 12px;
  }

  .c-app .c-chat {
    padding-bottom: 16px;
  }

  .c-app .c-prompt-row {
    padding-top: 6px;
  }
}

/* ---------------- 自定义头像 ---------------- */
.c-avatar img,
.c-msg-avatar img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: inherit;
}

.c-avatar-btn {
  padding: 0;
  overflow: hidden;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.15s ease;
}

.c-avatar-btn:hover {
  border-color: var(--c-text-3);
}

.c-avatar-btn:focus-visible {
  outline: 2px solid var(--c-accent);
  outline-offset: 2px;
}

.c-app button.c-msg-avatar {
  padding: 0;
  overflow: hidden;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.15s ease;
}

.c-app button.c-msg-avatar:hover {
  border-color: var(--c-text-3);
}

.c-avatar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}

.c-avatar-row-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 1px;
}

.c-avatar-row-copy strong {
  color: var(--c-text);
  font-size: 11px;
  font-weight: 500;
}

.c-avatar-row-copy small {
  color: var(--c-text-3);
  font-size: 10px;
}

.c-avatar-action {
  padding: 4px 10px;
  border: 1px solid var(--c-line);
  border-radius: 999px;
  background: var(--c-bg);
  color: var(--c-text-2);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.c-avatar-action:hover:not(:disabled) {
  border-color: var(--c-text-3);
  color: var(--c-text);
}

.c-avatar-action.subtle {
  border-color: transparent;
  color: var(--c-text-3);
}

.c-avatar-action:disabled {
  cursor: default;
  opacity: 0.55;
}

.c-avatar-file {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  border: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

</style>
