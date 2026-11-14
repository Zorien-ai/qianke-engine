<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import CompanionAvatar from "../components/CompanionAvatar.vue";
import { getJson, postJson, patchJson, del, postForm } from "../api";
import { productMatchesQuery } from "../catalogSearch";
import { cart, cartItemKey, cartLineMax, cartCheckoutPayload } from "../cart";

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
    unread: 0,
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
const pendingMode = ref("");
const mentionOpen = ref(false);
const mentionQuery = ref("");
const mentionIndex = ref(0);
const isDemoAccount = ref(false);

/* ---------- 未读 / @ 提及（全部以接口数据为准） ---------- */
const THREAD_IDS = ["companion", "store_demo", "friend_demo"];
const MENTION_THREAD_MAP = {
  "@小鱼": "companion",
  "@店宠": "store_demo",
  "@小满": "friend_demo",
};
const unreadCounts = ref({ companion: 0, store_demo: 0, friend_demo: 0 });
const mentionUnread = ref(0);
const mentionBusy = ref(false);
const unreadMentions = ref([]);
let unreadTimer = null;
let unreadRefreshTimer = null;
let incomingReadTimer = null;

function unreadOf(threadId) {
  return Number(unreadCounts.value[threadId] || 0);
}

function isKnownThread(threadId) {
  const id = String(threadId || "");
  return THREAD_IDS.includes(id)
    || merchantThreads.value.some((item) => item.id === id)
    || groups.value.some((item) => item.group_id === id);
}

function mentionThreadId(token) {
  return MENTION_THREAD_MAP[String(token || "").trim()] || "";
}

/** 拉取各会话未读数 + 未读 @ 数；页面隐藏时跳过 */
async function refreshUnread() {
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
  try {
    const data = await getJson("/api/c/threads/unread");
    const payload = data?.threads || {};
    const next = { companion: 0, store_demo: 0, friend_demo: 0 };
    for (const [threadId, count] of Object.entries(payload)) {
      next[threadId] = Number(count || 0);
    }
    unreadCounts.value = next;
    mentionUnread.value = Number(data?.mentions || 0);
  } catch {
    // 未读接口失败不打断会话，保留上一次成功的数据
  }
}

/** 进入会话：先乐观清零角标，再 POST read 并刷新未读 */
async function markThreadRead(threadId) {
  const id = String(threadId || "");
  if (!isKnownThread(id)) return;
  unreadCounts.value = { ...unreadCounts.value, [id]: 0 };
  try {
    await postJson(`/api/c/threads/${encodeURIComponent(id)}/read`, {});
  } catch {
    // 失败交给下一次轮询/进入会话校正
  }
  await refreshUnread();
}

/** 收到消息后合并刷新，避免每条消息都打一次未读接口 */
function scheduleUnreadRefresh() {
  if (unreadRefreshTimer) return;
  unreadRefreshTimer = window.setTimeout(() => {
    unreadRefreshTimer = null;
    refreshUnread();
  }, 400);
}

/** 消息落在当前打开的会话里：节流标记已读，避免自己的活跃会话出现未读角标 */
function scheduleIncomingRead() {
  if (incomingReadTimer) return;
  incomingReadTimer = window.setTimeout(() => {
    incomingReadTimer = null;
    if (document.visibilityState === "hidden") return;
    markThreadRead(activeId.value);
  }, 500);
}

function startUnreadPolling() {
  stopUnreadPolling();
  unreadTimer = window.setInterval(refreshUnread, 20000);
}

function stopUnreadPolling() {
  if (unreadTimer) {
    clearInterval(unreadTimer);
    unreadTimer = null;
  }
}

/** 页面隐藏暂停未读轮询与群重连，回到前台立即刷新并恢复 */
function onVisibilityChange() {
  if (document.visibilityState === "hidden") {
    stopUnreadPolling();
    if (groupReconnectTimer) {
      clearTimeout(groupReconnectTimer);
      groupReconnectTimer = null;
    }
    return;
  }
  refreshUnread();
  startUnreadPolling();
  resumeGroupSocket();
}

/** 点击消息里的 @ 文本：单聊切到对应会话；群聊内只做高亮提醒不切走 */
async function openMentionThread(token) {
  const id = mentionThreadId(token);
  if (!id) return;
  if (isGroupThread(activeId.value)) {
    showGroupMentionHint(token);
    return;
  }
  if (activeId.value === id) {
    await markThreadRead(id);
    return;
  }
  await switchThread(id);
}

/** 点击 @N 通知：标记全部提及已读，并打开最近一条未读提及所在会话 */
async function openUnreadMentions() {
  if (mentionBusy.value) return;
  mentionBusy.value = true;
  try {
    let target = unreadMentions.value[0] || null;
    if (!target) {
      const data = await getJson("/api/c/mentions?unread_only=1&limit=20");
      unreadMentions.value = Array.isArray(data?.mentions) ? data.mentions : [];
      target = unreadMentions.value[0] || null;
    }
    await postJson("/api/c/mentions/read", {});
    mentionUnread.value = 0;
    unreadMentions.value = [];
    const targetId = isKnownThread(target?.thread_id) ? target.thread_id : "";
    if (!targetId) {
      await refreshUnread();
    } else if (activeId.value === targetId) {
      await markThreadRead(targetId);
    } else {
      await switchThread(targetId);
    }
  } catch {
    // 标记失败时保留 @N，等用户重试或轮询恢复
  } finally {
    mentionBusy.value = false;
  }
}

const mentionOptions = computed(() => {
  const query = mentionQuery.value.trim().toLowerCase();
  const thread = allThreads.value.find((item) => item.id === activeId.value) || null;
  let options;
  if (thread?.kind === "group") {
    // 群聊：选择器列出全部群成员，可多次插入（再点 @ / 输入 @ 即可继续）
    options = (thread.members || []).map((member) => ({
      label: member.name,
      token: GROUP_MENTION_TOKENS[member.member_id] || `@${member.name}`,
      desc: GROUP_MEMBER_KIND_LABELS[member.kind] || member.kind || "成员",
    }));
  } else {
    const byThread = {
      companion: [{ label: "小鱼", token: "@小鱼", desc: "你的购物伙伴" }],
      store_demo: [{ label: "山野店宠", token: "@店宠", desc: "售前 / 售后 / 砍价" }],
      friend_demo: [{ label: "小满", token: "@小满", desc: "好友 · 周末徒步" }],
    };
    options = byThread[activeId.value] || [];
  }
  return options.filter((item) => {
    if (!query) return true;
    return item.label.toLowerCase().includes(query) || item.token.toLowerCase().includes(query);
  });
});
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
let storeSocketFriendId = "store_demo";
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
const memories = ref([]);
const memoryDigests = ref([]);
const memoriesError = ref("");
const memoryBusy = ref("");
const diaries = ref([]);
const diaryEnabled = ref(false);
const diaryError = ref("");
const diaryBusy = ref(false);
const rhythm = ref({
  enabled: false,
  quiet_start: "22:00",
  quiet_end: "09:00",
  pause_until: null,
});
const rhythmError = ref("");
const rhythmSaving = ref(false);
const liveThreadId = ref("");
const liveDraft = ref(null);
const liveOrder = ref(null);
const storeQuote = ref(null);
// 双宠谈判：negotiating 防重复调用；negotiationRejected 用于隐藏静态演示报价卡
const negotiating = ref(false);
const negotiateError = ref("");
const negotiationRejected = ref(false);
const negotiationOpen = ref(false);
const negotiationNeed = ref("");
const negotiationBudget = ref(500);
const negotiationQuantity = ref(1);
const negotiationMerchant = ref("");
const negotiationFriendId = ref("");
const negotiationEchoUser = ref(true);
const negotiationFormError = ref("");
const negotiationSku = ref("");
const negotiationSkuSpec = ref("");
const negotiationSkuOptions = ref([]);
const negotiationSkuLoading = ref(false);
const negotiationProductTitle = ref("");
const negotiationProductOptions = ref([]);
const negotiationProductId = ref("");
const negotiationProductSearch = ref("");
const negotiationCartHint = ref("");
const cartItems = cart.items;
const cartOpen = ref(false);
const cartDrawerError = ref("");
const cartEditItem = ref(null);
const cartEditSku = ref("");
const cartEditQuantity = ref(1);
const cartEditOptions = ref([]);
const cartEditLoading = ref(false);
const cartEditError = ref("");
const hasMoreCompanion = ref(false);
const companionBefore = ref("");
const clearingCompanion = ref(false);
const logoutBusy = ref(false);
const logoutError = ref("");
const hasMoreStore = ref(false);
const storeBefore = ref("");
const loadingOlderStore = ref(false);
const storeHistoryHint = ref("");
const agentBusy = ref(false);
const agentError = ref("");
// 右侧「最近订单」：真实订单，数据来自 GET /api/c/orders（只取最近 3 条）
const recentOrders = ref([]);
const recentOrdersLoading = ref(false);
const recentOrdersError = ref("");
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
let previousBodyOverflow = "";
let messagePressTimer = null;
let messagePressPoint = null;

/* ---------- 群聊：GET /api/c/groups，群消息按群 ID 独立缓存 ---------- */
const groups = ref([]);
const groupsError = ref("");
const groupMessagesLoading = ref(false);
const groupMentionHint = ref("");
let groupMentionHintTimer = null;

/* ---------- 群聊 WebSocket：优先实时链路，HTTP POST 保留回退 ---------- */
const groupSocketState = ref("offline"); // offline | connecting | online | reconnecting | fallback
const groupSocketAttempts = ref(0);
const groupSocketGroupId = ref("");
const lastGroupSend = ref(null);
let groupSocket = null;
let groupReconnectTimer = null;
let groupManualClose = false;

const GROUP_MENTION_TOKENS = {
  companion: "@小鱼",
  store_demo: "@店宠",
  friend_demo: "@小满",
};
const GROUP_MEMBER_KIND_LABELS = {
  companion: "伙伴",
  merchant: "商家",
  friend: "好友",
};

const groupThreads = computed(() =>
  groups.value.map((item) => ({
    id: item.group_id,
    name: item.name,
    kind: "group",
    preview: "群聊",
    time: "",
    unread: 0,
    members: Array.isArray(item.members) ? item.members : [],
  }))
);

/** 群会话在前，单聊保持原有顺序 */
const merchantThreads = ref([]);
/** 群会话在前，动态商家店宠其次，单聊保持原有顺序 */
const allThreads = computed(() => [
  ...groupThreads.value,
  ...merchantThreads.value,
  ...threads.value,
]);

function threadMemberCount(thread) {
  return thread?.kind === "group" ? thread.members?.length || 0 : 0;
}

function isGroupThread(threadId) {
  return allThreads.value.find((item) => item.id === threadId)?.kind === "group";
}

const activeThread = computed(() => allThreads.value.find((item) => item.id === activeId.value) || allThreads.value[0]);
const messages = computed(() => messagesByThread.value[activeId.value] || []);
const filteredThreads = computed(() => {
  const keyword = search.value.trim();
  if (!keyword) return allThreads.value;
  return allThreads.value.filter((item) => {
    const memberNames = (item.members || []).map((member) => member.name).join(" ");
    return item.name.includes(keyword) || item.preview.includes(keyword) || memberNames.includes(keyword);
  });
});
const isCompanion = computed(() => activeId.value === "companion");
const planLabel = computed(() => `L${companion.value.level || 4}`);

function messageAuthor(role, message = null) {
  const custom = String(message?.author || "").trim();
  if (custom) return custom;
  if (role === "user") return "我";
  if (role === "companion") return companion.value.name;
  if (role === "merchant") return activeThread.value.name;
  return "系统";
}

function messageAvatarLabel(role, message = null) {
  const name = messageAuthor(role, message);
  return name.slice(0, 1) || "系";
}

function messageSegments(text) {
  const value = String(text || "");
  const pattern = /(@(?:店宠|小鱼|小满))/g;
  const parts = [];
  let last = 0;
  let match;
  while ((match = pattern.exec(value)) !== null) {
    if (match.index > last) parts.push({ text: value.slice(last, match.index), mention: false });
    parts.push({ text: match[0], mention: true });
    last = match.index + match[0].length;
  }
  if (last < value.length) parts.push({ text: value.slice(last), mention: false });
  return parts.length ? parts : [{ text: value, mention: false }];
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
const groupSocketStatusLabel = computed(() => {
  if (groupSocketState.value === "online") return "在线";
  if (groupSocketState.value === "connecting") return "连接中";
  if (groupSocketState.value === "reconnecting") return "重连中";
  if (groupSocketState.value === "fallback") return "HTTP 回退";
  return "离线";
});

const statusText = computed(() => {
  if (activeThread.value.kind === "group") {
    return `群聊 · ${threadMemberCount(activeThread.value)} 人 · ${groupSocketStatusLabel.value}`;
  }
  if (activeThread.value.kind === "companion") return "在线";
  if (activeThread.value.kind === "merchant") {
    if (storeSocketState.value === "online") return "店宠在线";
    if (storeSocketState.value === "reconnecting") return "正在重连";
    if (storeSocketState.value === "connecting") return "连接中";
    return "连接已断开";
  }
  return "好友";
});
const avatarMenuOpen = ref(false);
const avatarExpression = ref("");
const avatarTip = ref("");
const companionState = ref("idle");
const topAvatarRef = ref(null);
const headAvatarRef = ref(null);
const avatarExpressions = ["happy", "surprised", "sleepy", "squinted", "confused", "neutral"];
const voiceReplyEnabled = ref(false);
const voiceListening = ref(false);
const voiceSupported = ref(
  typeof window !== "undefined" &&
    Boolean(window.SpeechRecognition || window.webkitSpeechRecognition),
);
const voiceSynthesisSupported = ref(
  typeof window !== "undefined" && "speechSynthesis" in window,
);
const voiceRate = ref(1.02);
const voiceURI = ref("");
const voiceOptions = ref([]);
const VOICE_PREFS_KEY = "qianke_voice_prefs";
let speechRecognition = null;
let lipSyncTimer = null;
let lipFallbackTimer = null;
let lipFrameIndex = 0;
const lipFrames = ["happy", "neutral", "surprised", "calm", "squinted"];
let avatarExpressionIndex = 0;
let avatarIdleTimer = null;
let avatarTransientTimer = null;
let avatarTipTimer = null;
let avatarExpressionTimer = null;

const avatarState = computed(() => {
  if (typing.value || agentBusy.value) return "thinking";
  if (liveDraft.value) return "waiting";
  if (liveOrder.value) return "happy";
  return companionState.value;
});

function clearTimer(name) {
  if (name === "idle" && avatarIdleTimer) {
    clearTimeout(avatarIdleTimer);
    avatarIdleTimer = null;
  }
  if (name === "transient" && avatarTransientTimer) {
    clearTimeout(avatarTransientTimer);
    avatarTransientTimer = null;
  }
  if (name === "tip" && avatarTipTimer) {
    clearTimeout(avatarTipTimer);
    avatarTipTimer = null;
  }
  if (name === "expression" && avatarExpressionTimer) {
    clearTimeout(avatarExpressionTimer);
    avatarExpressionTimer = null;
  }
}

function resetAvatarIdleTimer() {
  clearTimer("idle");
  avatarIdleTimer = setTimeout(() => {
    if (!typing.value && !agentBusy.value && !liveDraft.value) {
      companionState.value = "sleeping";
    }
  }, 90000);
}

function setCompanionState(state, holdMs = 0) {
  clearTimer("transient");
  companionState.value = state;
  resetAvatarIdleTimer();
  if (holdMs > 0) {
    avatarTransientTimer = setTimeout(() => {
      if (!typing.value && !agentBusy.value && !liveDraft.value) {
        companionState.value = "idle";
      }
    }, holdMs);
  }
}

function wakeCompanion() {
  if (companionState.value === "sleeping") {
    setCompanionState("waking", 700);
  } else {
    resetAvatarIdleTimer();
  }
}

function showAvatarTip(text) {
  clearTimer("tip");
  avatarTip.value = text;
  avatarTipTimer = setTimeout(() => {
    avatarTip.value = "";
  }, 1800);
}

function pokeCompanions(kind) {
  topAvatarRef.value?.poke(kind);
  headAvatarRef.value?.poke(kind);
}

function onAvatarPoke() {
  wakeCompanion();
  avatarMenuOpen.value = !avatarMenuOpen.value;
}

function feedCompanion() {
  wakeCompanion();
  setCompanionState("fed", 1600);
  pokeCompanions("bounce");
  showAvatarTip("小鱼吃饱了");
  avatarMenuOpen.value = false;
}

function petCompanion() {
  wakeCompanion();
  setCompanionState("petted", 1600);
  pokeCompanions("nod");
  showAvatarTip("小鱼蹭了蹭你");
  avatarMenuOpen.value = false;
}

function cycleAvatarExpression() {
  wakeCompanion();
  avatarExpressionIndex = (avatarExpressionIndex + 1) % avatarExpressions.length;
  setAvatarExpression(avatarExpressions[avatarExpressionIndex]);
  showAvatarTip("换了个表情");
  avatarMenuOpen.value = false;
}

function onCompanionActivity() {
  if (companionState.value === "sleeping") wakeCompanion();
  else resetAvatarIdleTimer();
}

function setAvatarExpression(name, holdMs = 1800) {
  clearTimer("expression");
  avatarExpression.value = name;
  avatarExpressionTimer = setTimeout(() => {
    avatarExpression.value = "";
  }, holdMs);
}

function emotionFor(text) {
  const value = String(text || "");
  if (/(抱歉|遗憾|没货|失败|取消|退款|不能|无法)/.test(value)) return "sad";
  if (/(居然|竟然|没想到|惊喜|惊讶|真的吗)/.test(value)) return "surprised";
  if (/(可能|也许|不确定|需要确认|查一下)/.test(value)) return "confused";
  if (/(可以|喜欢|舒服|很棒|不错|优惠|成功|好的|没问题)/.test(value)) return "happy";
  return "neutral";
}

function applyReplyEmotion(text) {
  const emotion = emotionFor(text);
  setAvatarExpression(emotion, 2200);
}

function stopLipSync() {
  if (lipSyncTimer) {
    clearInterval(lipSyncTimer);
    lipSyncTimer = null;
  }
  if (lipFallbackTimer) {
    clearTimeout(lipFallbackTimer);
    lipFallbackTimer = null;
  }
}

function pulseLipSync() {
  avatarExpression.value = lipFrames[lipFrameIndex % lipFrames.length];
  lipFrameIndex += 1;
}

function startLipSync() {
  stopLipSync();
  setCompanionState("speaking");
  lipFrameIndex = 0;
  pulseLipSync();
  // boundary 事件在部分浏览器/语音下不触发，保留低频兜底，但优先由 boundary 驱动。
  lipFallbackTimer = setTimeout(() => {
    if (!lipSyncTimer) {
      lipSyncTimer = setInterval(pulseLipSync, 220);
    }
  }, 500);
}

function loadVoiceOptions() {
  if (!voiceSynthesisSupported.value) return;
  const all = window.speechSynthesis.getVoices() || [];
  const zh = all.filter((voice) => /^zh/i.test(voice.lang));
  voiceOptions.value = (zh.length ? zh : all).map((voice) => ({
    uri: voice.voiceURI,
    label: `${voice.name} (${voice.lang})`,
  }));
  if (!voiceURI.value && voiceOptions.value.length) {
    voiceURI.value = voiceOptions.value[0].uri;
  }
}

function previewVoice() {
  if (!voiceSynthesisSupported.value) {
    showAvatarTip("当前浏览器不支持朗读");
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance("你好，我是小鱼。今天想逛点什么？");
  utterance.lang = "zh-CN";
  utterance.rate = Number(voiceRate.value) || 1;
  const selected = window.speechSynthesis
    .getVoices()
    .find((voice) => voice.voiceURI === voiceURI.value);
  if (selected) utterance.voice = selected;
  utterance.onstart = () => startLipSync();
  utterance.onend = () => {
    stopLipSync();
    setCompanionState("idle");
    avatarExpression.value = "neutral";
  };
  utterance.onerror = utterance.onend;
  window.speechSynthesis.speak(utterance);
}

function saveVoicePrefs() {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(
      VOICE_PREFS_KEY,
      JSON.stringify({
        enabled: voiceReplyEnabled.value,
        rate: voiceRate.value,
        voiceURI: voiceURI.value,
      }),
    );
  } catch (error) {
    /* 隐私模式下 localStorage 不可用，忽略 */
  }
}

function restoreVoicePrefs() {
  if (typeof localStorage === "undefined") return;
  try {
    const raw = localStorage.getItem(VOICE_PREFS_KEY);
    if (!raw) return;
    const prefs = JSON.parse(raw);
    voiceReplyEnabled.value = Boolean(prefs.enabled);
    const rate = Number(prefs.rate);
    if (Number.isFinite(rate)) voiceRate.value = Math.min(1.3, Math.max(0.8, rate));
    if (typeof prefs.voiceURI === "string") voiceURI.value = prefs.voiceURI;
  } catch (error) {
    /* 配置损坏时回落默认值 */
  }
}

watch([voiceReplyEnabled, voiceRate, voiceURI], () => saveVoicePrefs());

function stopSpeaking() {
  stopLipSync();
  if (typeof window !== "undefined" && window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  setCompanionState("idle");
  avatarExpression.value = "neutral";
}

function speakReply(text) {
  if (!voiceReplyEnabled.value || !voiceSynthesisSupported.value) {
    applyReplyEmotion(text);
    return;
  }
  const content = String(text || "").trim().slice(0, 320);
  if (!content) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(content);
  utterance.lang = "zh-CN";
  utterance.rate = Number(voiceRate.value) || 1;
  utterance.pitch = 1.05;
  const selected = window.speechSynthesis
    .getVoices()
    .find((voice) => voice.voiceURI === voiceURI.value);
  if (selected) utterance.voice = selected;
  utterance.onstart = () => startLipSync();
  utterance.onboundary = () => {
    if (lipFallbackTimer) {
      clearTimeout(lipFallbackTimer);
      lipFallbackTimer = null;
    }
    pulseLipSync();
  };
  utterance.onend = () => {
    stopLipSync();
    setCompanionState("idle");
    applyReplyEmotion(content);
  };
  utterance.onerror = () => {
    stopLipSync();
    setCompanionState("idle");
    applyReplyEmotion(content);
  };
  window.speechSynthesis.speak(utterance);
}

function toggleVoiceReply() {
  if (!voiceSynthesisSupported.value) {
    showAvatarTip("当前浏览器不支持朗读");
    return;
  }
  voiceReplyEnabled.value = !voiceReplyEnabled.value;
  if (!voiceReplyEnabled.value) stopSpeaking();
  showAvatarTip(voiceReplyEnabled.value ? "小鱼会读出来" : "已关闭朗读");
}

function toggleVoiceInput() {
  if (!voiceSupported.value) {
    showAvatarTip("当前浏览器不支持语音输入");
    return;
  }
  if (voiceListening.value) {
    speechRecognition?.stop();
    return;
  }
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  speechRecognition = new Recognition();
  speechRecognition.lang = "zh-CN";
  speechRecognition.interimResults = true;
  speechRecognition.continuous = false;
  speechRecognition.onstart = () => {
    voiceListening.value = true;
    setCompanionState("listening");
    showAvatarTip("正在听…");
  };
  speechRecognition.onresult = (event) => {
    let transcript = "";
    for (let i = 0; i < event.results.length; i += 1) {
      transcript += event.results[i][0]?.transcript || "";
    }
    if (transcript.trim()) draft.value = transcript.trim();
  };
  speechRecognition.onerror = () => {
    voiceListening.value = false;
    showAvatarTip("没有听清，再试一次");
    setCompanionState("idle");
  };
  speechRecognition.onend = () => {
    voiceListening.value = false;
    if (companionState.value === "listening") setCompanionState("idle");
  };
  try {
    speechRecognition.start();
  } catch (error) {
    voiceListening.value = false;
    showAvatarTip("语音输入启动失败");
  }
}

const threadDotClass = computed(() => {
  if (activeThread.value.kind === "group") {
    return groupSocketState.value === "online" ? "online" : "connecting";
  }
  return activeThread.value.kind === "merchant" && storeSocketState.value !== "online"
    ? "connecting"
    : "online";
});
const pendingCount = computed(() => {
  if (liveDraft.value || storeQuote.value) return 1;
  return 0;
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
  // 用 nextTick 在 DOM 更新后、浏览器绘制前直接定位，避免每次加载都看到
  // 内容从顶部滚动到底部的过程。
  nextTick(() => {
    const el = document.getElementById("c-app-thread");
    if (el) el.scrollTop = el.scrollHeight;
  });
}

function onComposerFocus() {
  composerFocused.value = true;
  syncViewportHeight();
  window.setTimeout(scrollToBottom, 120);
  wakeCompanion();
  if (!typing.value && !agentBusy.value) setCompanionState("listening");
}

function onComposerBlur() {
  composerFocused.value = false;
  closeMention();
  if (companionState.value === "listening") setCompanionState("idle");
  // iOS 键盘收起不一定立刻触发 visualViewport resize，显式复位一次。
  window.setTimeout(() => {
    syncViewportHeight();
    window.scrollTo(0, 0);
  }, 80);
}

function syncViewportHeight() {
  const viewport = window.visualViewport;
  const layoutHeight = window.innerHeight;
  const keyboardOpen = Boolean(viewport && viewport.height < layoutHeight - 120);
  // 键盘没开时一律回到布局视口高度，避免 iOS 关闭键盘后 visualViewport
  // 残留小高度，导致 CApp 只占半屏、下方留白。
  const height = composerFocused.value && keyboardOpen ? viewport.height : layoutHeight;
  if (!height) return;
  document.documentElement.style.setProperty("--c-vh", `${height}px`);
  // 外壳始终固定在 top:0；不再使用 offsetTop，避免键盘收起后整页悬空。
  document.documentElement.style.setProperty("--c-vh-offset", "0px");
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

function closeMention() {
  mentionOpen.value = false;
  mentionQuery.value = "";
  mentionIndex.value = 0;
}

function updateMention(input) {
  if (!input) return;
  const before = input.value.slice(0, input.selectionStart || 0);
  const match = before.match(/(?:^|\s)@([^\s@]*)$/);
  if (!match) {
    closeMention();
    return;
  }
  mentionOpen.value = true;
  mentionQuery.value = match[1] || "";
  mentionIndex.value = 0;
}

function onComposerInput(event) {
  resizeComposer(event);
  updateMention(event?.target);
  onCompanionActivity();
}

function startMention() {
  const input = document.getElementById("c-app-input");
  if (!input) return;
  const pos = input.selectionStart ?? draft.value.length;
  const before = draft.value.slice(0, pos);
  const after = draft.value.slice(pos);
  const needsSpace = before && !/\s$/.test(before);
  draft.value = `${before}${needsSpace ? " " : ""}@${after}`;
  mentionOpen.value = true;
  mentionQuery.value = "";
  mentionIndex.value = 0;
  window.requestAnimationFrame(() => {
    input.focus();
    const next = input.value.length - after.length;
    input.setSelectionRange(next, next);
  });
}

function selectMention(option) {
  const input = document.getElementById("c-app-input");
  if (!input || !option) return;
  const pos = input.selectionStart ?? draft.value.length;
  const before = draft.value.slice(0, pos);
  const after = draft.value.slice(pos);
  const replaced = before.replace(/@([^\s@]*)$/, `${option.token} `);
  draft.value = `${replaced}${after}`;
  closeMention();
  window.requestAnimationFrame(() => {
    input.focus();
    input.setSelectionRange(replaced.length, replaced.length);
    resizeComposer({ target: input });
  });
}

function onComposerKeydown(event) {
  if (mentionOpen.value && mentionOptions.value.length) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      mentionIndex.value = (mentionIndex.value + 1) % mentionOptions.value.length;
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      mentionIndex.value = (mentionIndex.value - 1 + mentionOptions.value.length) % mentionOptions.value.length;
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      selectMention(mentionOptions.value[mentionIndex.value]);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeMention();
      return;
    }
  }
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send();
  }
}

function pushMessage(message) {
  if (!messagesByThread.value[activeId.value]) messagesByThread.value[activeId.value] = [];
  messagesByThread.value[activeId.value].push({
    id: `local_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    time: nowTime(),
    ...message,
  });
  // 收到（非自己发送的）消息后刷新未读；当前会话内的消息同时节流标记已读
  if (message.role !== "user") {
    scheduleUnreadRefresh();
    scheduleIncomingRead();
  }
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
    productRefs: Array.isArray(message.metadata?.product_refs) ? message.metadata.product_refs : [],
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

async function loadMerchantThreads() {
  try {
    const data = await getJson("/api/c/friends");
    const existing = new Set(["store_demo", "friend_demo"]);
    merchantThreads.value = (data?.friends || [])
      .filter((friend) => friend.kind === "merchant" && !existing.has(friend.friend_id))
      .map((friend) => ({
        id: friend.friend_id,
        name: friend.name,
        kind: "merchant",
        preview: friend.note || "店宠",
        time: "",
        unread: 0,
      }));
  } catch {
    merchantThreads.value = [];
  }
}

async function loadStoreMessages(friendId = "store_demo") {
  storeHistoryHint.value = "";
  try {
    const data = await getJson(
      `/api/c/friends/${encodeURIComponent(friendId)}/messages?limit=20`
    );
    if (data?.messages?.length) {
      messagesByThread.value[friendId] = data.messages.map(mapStoreMessage);
      hasMoreStore.value = data.messages.length >= 20;
      storeBefore.value = storeCursor(data.messages[0]);
    } else {
      messagesByThread.value[friendId] = [];
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
  const friendId = activeId.value;
  loadingOlderStore.value = true;
  storeHistoryHint.value = "";
  try {
    const data = await getJson(
      `/api/c/friends/${encodeURIComponent(friendId)}/messages?limit=20&before=${encodeURIComponent(storeBefore.value)}`
    );
    const raw = data?.messages || [];
    const existing = new Set((messagesByThread.value[friendId] || []).map((message) => message.id));
    const older = raw
      .map(mapStoreMessage)
      .filter((message) => message.id && !existing.has(message.id));
    messagesByThread.value[friendId] = [...older, ...(messagesByThread.value[friendId] || [])];
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
  const target = allThreads.value.find((item) => item.id === activeId.value);
  if (!target || target.kind !== "merchant") return;
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

function openStoreSocket(isReconnect = false, friendId = null) {
  if (friendId) storeSocketFriendId = friendId;
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
    storeSocket = new WebSocket(
      `${scheme}://${window.location.host}/api/c/ws/chat/${encodeURIComponent(storeSocketFriendId)}`
    );
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
  const target = allThreads.value.find((item) => item.id === activeId.value);
  if (!target || target.kind !== "merchant") return;
  if (payload.type === "chat") {
    typing.value = false;
    pendingRetry.value = null;
    lastStoreSend.value = null;
    if (payload.reply) {
      pushMessage({
        role: "merchant",
        text: cleanReply(payload.reply.content),
        productRefs: Array.isArray(payload.reply.metadata?.product_refs) ? payload.reply.metadata.product_refs : [],
      });
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
        threadId: activeId.value,
        text: lastStoreSend.value.text,
        clientId: lastStoreSend.value.clientId,
      };
      lastStoreSend.value = null;
    }
  }
}

/* ---------- 群聊数据（GET /api/c/groups、GET /api/c/groups/{id}/messages） ---------- */
function groupErrorMessage(error) {
  const detail = error?.payload?.detail;
  if (detail && typeof detail === "object") {
    return detail.message || detail.code || "群聊暂时不可用，请稍后再试";
  }
  return error?.detail || error?.message || "群聊暂时不可用，请稍后再试";
}

function mapGroupMessage(message) {
  const senderName = String(message?.sender_name || "").trim() || "群成员";
  const own =
    senderName === "我" || String(message?.sender_id || "").startsWith("buyer_");
  return {
    id: message?.message_id || `gmsg_local_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    role: own ? "user" : "merchant",
    author: senderName,
    text: cleanReply(message?.content),
    time: (message?.created_at || "").slice(11, 16),
    createdAt: message?.created_at || "",
    group: true,
  };
}

async function loadGroupMessages(groupId) {
  groupMessagesLoading.value = true;
  groupsError.value = "";
  try {
    const data = await getJson(
      `/api/c/groups/${encodeURIComponent(groupId)}/messages?limit=30`
    );
    messagesByThread.value[groupId] = (Array.isArray(data?.messages) ? data.messages : []).map(
      mapGroupMessage
    );
  } catch (error) {
    groupsError.value = groupErrorMessage(error);
  } finally {
    groupMessagesLoading.value = false;
    scrollToBottom();
  }
}

/** 挂载时拉群列表；默认进入「周末徒步群」 */
async function loadGroups() {
  try {
    const data = await getJson("/api/c/groups");
    groups.value = Array.isArray(data?.groups) ? data.groups : [];
    groupsError.value = "";
    const preferred =
      groups.value.find((item) => item.name === "周末徒步群") || groups.value[0];
    if (preferred && activeId.value === "companion" && isDemoAccount.value) {
      await switchThread(preferred.group_id);
    }
  } catch (error) {
    groups.value = [];
    groupsError.value = groupErrorMessage(error);
  }
}

function showGroupMentionHint(token) {
  const name = String(token || "").replace(/^@/, "");
  groupMentionHint.value = `群聊内 @${name} 只作提醒，不切换会话`;
  if (groupMentionHintTimer) clearTimeout(groupMentionHintTimer);
  groupMentionHintTimer = window.setTimeout(() => {
    groupMentionHint.value = "";
    groupMentionHintTimer = null;
  }, 2200);
}

/** 群 replies 按接口顺序逐条上屏；自己的 message 已在本地展示，不重复渲染 */
function appendGroupReplies(replies, threadId = activeId.value) {
  const targetId = String(threadId || activeId.value);
  const list =
    messagesByThread.value[targetId] ||
    (messagesByThread.value[targetId] = []);
  for (const reply of Array.isArray(replies) ? replies : []) {
    const text = cleanReply(reply?.content);
    if (!text) continue;
    list.push({
      id: `local_${Date.now()}_${Math.random().toString(16).slice(2)}`,
      role: "merchant",
      author: String(reply?.sender_name || "").trim() || "群成员",
      text,
      time: nowTime(),
      group: true,
    });
  }
  scheduleUnreadRefresh();
  if (activeId.value === targetId) {
    scheduleIncomingRead();
    scrollToBottom();
  }
}

function closeGroupSocket() {
  groupManualClose = true;
  if (groupReconnectTimer) {
    clearTimeout(groupReconnectTimer);
    groupReconnectTimer = null;
  }
  if (groupSocket) {
    groupSocket.onclose = null;
    groupSocket.close();
    groupSocket = null;
  }
  groupSocketState.value = "offline";
  groupSocketGroupId.value = "";
}

function scheduleGroupReconnect() {
  if (!isGroupThread(activeId.value)) return;
  if (typeof document !== "undefined" && document.visibilityState === "hidden") {
    // 页面隐藏暂停重连，回到前台由 onVisibilityChange 恢复
    groupSocketState.value = "reconnecting";
    return;
  }
  if (groupSocketAttempts.value >= 5) {
    groupSocketState.value = "offline";
    return;
  }
  groupSocketAttempts.value += 1;
  groupSocketState.value = "reconnecting";
  const delay = Math.min(1000 * 2 ** (groupSocketAttempts.value - 1), 8000);
  groupReconnectTimer = setTimeout(() => {
    groupReconnectTimer = null;
    if (
      isGroupThread(activeId.value) &&
      document.visibilityState !== "hidden"
    ) {
      openGroupSocket(activeId.value, true);
    }
  }, delay);
}

function openGroupSocket(groupId, isReconnect = false) {
  if (!isGroupThread(groupId)) return;
  if (
    groupSocket &&
    groupSocketGroupId.value === groupId &&
    [WebSocket.CONNECTING, WebSocket.OPEN].includes(groupSocket.readyState)
  ) {
    return;
  }
  if (groupReconnectTimer) {
    clearTimeout(groupReconnectTimer);
    groupReconnectTimer = null;
  }
  if (groupSocket) {
    groupSocket.onclose = null;
    groupSocket.close();
    groupSocket = null;
  }
  groupManualClose = false;
  if (!isReconnect) groupSocketAttempts.value = 0;
  groupSocketGroupId.value = groupId;
  let socket;
  try {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(
      `${scheme}://${window.location.host}/api/c/ws/group/${encodeURIComponent(groupId)}`
    );
  } catch {
    groupSocketState.value = "fallback";
    return;
  }
  groupSocket = socket;
  groupSocketState.value = "connecting";
  socket.onopen = () => {
    if (groupSocket !== socket) return;
    groupSocketAttempts.value = 0;
    groupSocketState.value = "online";
  };
  socket.onmessage = handleGroupSocket;
  socket.onerror = () => {
    if (groupSocket === socket) groupSocketState.value = "reconnecting";
  };
  socket.onclose = () => {
    if (groupSocket === socket) groupSocket = null;
    if (groupManualClose) return;
    if (activeId.value !== groupId || !isGroupThread(activeId.value)) {
      groupSocketState.value = "offline";
      return;
    }
    scheduleGroupReconnect();
  };
}

function handleGroupSocket(event) {
  let payload;
  try {
    payload = JSON.parse(event.data);
  } catch {
    return;
  }
  if (!payload || !isGroupThread(activeId.value)) return;
  if (groupSocketGroupId.value !== activeId.value) return;
  if (payload.type === "group_chat") {
    typing.value = false;
    lastGroupSend.value = null;
    pendingRetry.value = null;
    agentError.value = "";
    appendGroupReplies(payload.replies, groupSocketGroupId.value);
  } else if (payload.type === "error") {
    typing.value = false;
    agentError.value = payload.error?.message || "群消息发送失败";
    if (lastGroupSend.value) {
      pendingRetry.value = {
        threadId: activeId.value,
        text: lastGroupSend.value.text,
        clientId: lastGroupSend.value.clientId,
      };
      lastGroupSend.value = null;
    }
  }
}

/** 回到前台时若群 socket 不在线则恢复连接 */
function resumeGroupSocket() {
  if (!isGroupThread(activeId.value)) return;
  if (
    groupSocket &&
    [WebSocket.CONNECTING, WebSocket.OPEN].includes(groupSocket.readyState)
  ) {
    return;
  }
  openGroupSocket(activeId.value, true);
}

async function loadAgentSession() {
  try {
    const data = await getJson("/api/c/agent/session");
    if (data?.thread_id) liveThreadId.value = data.thread_id;
    if (data?.interrupted && data?.draft) {
      liveDraft.value = data.draft;
      liveOrder.value = null;
    }
  } catch {
    // 会话恢复失败时保留当前页面内存中的 thread 作为降级。
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
        productRefs: Array.isArray(message.metadata?.product_refs) ? message.metadata.product_refs : [],
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
      productRefs: Array.isArray(message.metadata?.product_refs) ? message.metadata.product_refs : [],
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

async function logoutC() {
  if (logoutBusy.value) return;
  if (!window.confirm("退出当前账号？")) return;
  logoutBusy.value = true;
  logoutError.value = "";
  try {
    await postJson("/auth/logout", {});
    window.location.assign("/c/login");
  } catch (error) {
    logoutError.value = error?.detail || error?.message || "退出失败，请稍后再试";
  } finally {
    logoutBusy.value = false;
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
  closeMention();
  // 小伴不是议价方：识别到砍价意图时，直接转到当前店铺的砍价确认层。
  if (activeThread.value.kind === "companion" && isBargainIntent(text) && latestMerchantThread()) {
    pushMessage({ role: "user", text });
    draft.value = "";
    const input = document.getElementById("c-app-input");
    if (input) input.style.height = "auto";
    pendingRetry.value = null;
    scrollToBottom();
    openNegotiationForPrompt(text);
    return;
  }
  const clientId = newClientMessageId();
  const mode = pendingMode.value;
  pendingMode.value = "";
  pushMessage({ role: "user", text });
  draft.value = "";
  const input = document.getElementById("c-app-input");
  if (input) input.style.height = "auto";
  pendingRetry.value = null;
  scrollToBottom();
  await deliverText(text, false, clientId, mode);
  // 发送后刷新未读（其它会话可能有新消息），当前会话保持已读
  await refreshUnread();
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
  await deliverText(failed.text, true, failed.clientId, failed.mode || "");
}

function clearRetry() {
  pendingRetry.value = null;
}

async function deliverText(text, isRetry = false, clientId = null, mode = "") {
  if (isGroupThread(activeId.value)) {
    typing.value = true;
    agentError.value = "";
    const groupId = activeId.value;
    const socket = groupSocket;
    // 优先 WebSocket：用户消息已在 send() 本地展示，这里只等服务端 group_chat
    if (
      socket &&
      socket.readyState === WebSocket.OPEN &&
      groupSocketGroupId.value === groupId
    ) {
      lastGroupSend.value = { text, clientId };
      try {
        socket.send(JSON.stringify({ content: text }));
        return;
      } catch {
        // 发送失败：断开后回退 HTTP，不重复上屏用户消息
        lastGroupSend.value = null;
        closeGroupSocket();
      }
    }
    try {
      const result = await postJson(
        `/api/c/groups/${encodeURIComponent(groupId)}/messages`,
        { content: text }
      );
      // HTTP 回退同样按接口 replies 顺序逐条上屏，作者名取 sender_name（不伪造）
      appendGroupReplies(result?.replies, groupId);
      pendingRetry.value = null;
      lastGroupSend.value = null;
    } catch (error) {
      agentError.value = groupErrorMessage(error);
      pendingRetry.value = { threadId: groupId, text, clientId };
    } finally {
      if (activeId.value === groupId) {
        typing.value = false;
        scrollToBottom();
      }
    }
    return;
  }

  const activeThreadForSend = allThreads.value.find((item) => item.id === activeId.value);
  if (activeThreadForSend?.kind === "merchant") {
    if (storeSocket && storeSocket.readyState === WebSocket.OPEN) {
      typing.value = true;
      agentError.value = "";
      lastStoreSend.value = { text, clientId };
      storeSocket.send(JSON.stringify({ content: text, client_message_id: clientId || undefined }));
      return;
    }
    typing.value = true;
    try {
      const result = await postJson(
        `/api/c/friends/${encodeURIComponent(activeId.value)}/messages`,
        {
          content: text,
          client_message_id: clientId || undefined,
        }
      );
      if (result.reply) {
        pushMessage({
          role: "merchant",
          text: cleanReply(result.reply.content),
          productRefs: Array.isArray(result.reply.metadata?.product_refs) ? result.reply.metadata.product_refs : [],
        });
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
      if (!agentError.value) setCompanionState("streaming", 1400);
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
      mode: mode || undefined,
    });
    liveThreadId.value = result.thread_id || liveThreadId.value;
    agentError.value = "";
    const replyText = cleanReply(result.reply) || "已处理，请查看当前待确认信息。";
    const productRefs = Array.isArray(result.product_refs) ? result.product_refs : [];
    pushMessage({
      role: "companion",
      text: replyText,
      productRefs,
    });
    await persistAppMessage("companion", replyText, productRefs.length ? { product_refs: productRefs } : {});
    applyReplyEmotion(replyText);
    speakReply(replyText);
    if (result.memories_added) await loadMemories();
    if (result.draft) {
      liveDraft.value = result.draft;
      liveOrder.value = null;
    } else if (result.order) {
      liveOrder.value = result.order;
      liveThreadId.value = "";
      loadRecentOrders();
    }
  } catch (error) {
    agentError.value = error?.detail || error?.message || "小鱼暂时无法回应";
    pendingRetry.value = { threadId: activeId.value, text, clientId, mode };
  } finally {
    typing.value = false;
    if (!agentError.value) setCompanionState("streaming", 1400);
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
    setCompanionState("happy", 2200);
    const replyText = result.order
      ? `订单 ${result.order.order_id} 已创建。可以在订单页查看报价和确认记录。`
      : "订单已确认。";
    pushMessage({ role: "companion", text: replyText });
    await persistAppMessage("companion", replyText, { order_id: result.order?.order_id || null });
    await loadRecentOrders();
  } catch (error) {
    agentError.value = error?.detail || error?.message || "订单确认失败";
  } finally {
    agentBusy.value = false;
    scrollToBottom();
  }
}

async function sendPrompt(prompt, mode = "") {
  if (typing.value) return;
  pendingMode.value = mode;
  const promptThread = allThreads.value.find((item) => item.id === activeId.value);
  if (promptThread?.kind === "merchant") {
    draft.value = `@店宠 ${prompt}`;
  } else {
    draft.value = prompt;
  }
  await send();
}

/* ---------- 双宠谈判（C 伙伴 ↔ 商家店宠，受控报价） ---------- */
const NEGOTIATION_DEFAULT_BUDGET = 500;
const NEGOTIATION_REASON_LABELS = {
  BUDGET_TOO_LOW: "预算内没有可成交的方案，小鱼建议等平台活动或换个商品再试。",
  MERCHANT_NO_MATCH: "店里暂时没有匹配且有库存的商品，小鱼建议换个关键词再试。",
};

function negotiationErrorMessage(error) {
  const detail = error?.payload?.detail;
  if (detail && typeof detail === "object") {
    return detail.message || detail.code || "双宠谈判暂时不可用，请稍后再试";
  }
  return error?.detail || error?.message || "双宠谈判暂时不可用，请稍后再试";
}

function normalizeNegotiationNeed(text) {
  const original = String(text || "").replace(/\s+/g, " ").trim();
  let value = original
    .replace(/@\S+/g, " ")
    .replace(/让小鱼去砍价[:：]?/g, " ")
    .replace(/[（(].*?[)）]/g, " ")
    .replace(/[，。！？；,.!?;]/g, " ");
  value = value
    .replace(/(?:这款|这个|这件|它|帮我|想买|我要买|推荐一款|推荐一下|推荐|看看|看一下|看|以内|以下)/g, " ")
    .replace(/(?:多少钱|有优惠吗|有优惠|怎么卖|价格|能便宜吗|便宜点|砍(?:个|一下|点)?价|吗|呢|呀|啊)/g, " ")
    .replace(/\d+\s*(?:元|块)/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!value && isBargainIntent(original)) return "";
  return (value || original).slice(0, 40);
}

function latestMerchantThread() {
  const merchants = allThreads.value.filter((thread) => thread.kind === "merchant");
  return merchants[merchants.length - 1] || null;
}

function isBargainIntent(text) {
  return /砍(?:个|一下|点)?价|议价|便宜点|能不能便宜|能便宜|降价|优惠点|杀价/.test(String(text || ""));
}

function needFromConversation(threadId) {
  const list = messagesByThread.value[threadId] || [];
  for (let index = list.length - 1; index >= 0; index -= 1) {
    const message = list[index];
    if (!message || message.role !== "user") continue;
    const raw = String(message.text || "").replace(/@\S+/g, " ").replace(/\s+/g, " ").trim();
    if (!raw || isBargainIntent(raw)) continue;
    return normalizeNegotiationNeed(raw);
  }
  return "";
}

function negotiationNeedFromThread() {
  const list = messagesByThread.value[activeId.value] || [];
  // 优先用户最近一句：通常就是「我想砍什么」；没有用户消息时才用店宠回复。
  for (const role of ["user", "merchant"]) {
    for (let index = list.length - 1; index >= 0; index -= 1) {
      const message = list[index];
      if (!message || message.role !== role) continue;
      const text = String(message.text || "")
        .replace(/@\S+/g, " ")
        .replace(/让小鱼去砍价[:：]?/g, " ")
        .replace(/\s+/g, " ")
        .trim();
      if (text) return normalizeNegotiationNeed(text);
    }
  }
  return "";
}

function negotiationBudgetFromThread() {
  const list = messagesByThread.value[activeId.value] || [];
  // 只从用户自己的话里取预算，避免把店宠报价误当成用户预算。
  for (let index = list.length - 1; index >= 0; index -= 1) {
    if (list[index]?.role !== "user") continue;
    const text = String(list[index]?.text || "");
    const match = text.match(/(\d{2,6})\s*(?:元|块)/) || text.match(/(?:预算|¥|￥)\s*(\d{2,6})/);
    if (match) {
      const value = Number(match[1]);
      if (value >= 1) return value;
    }
  }
  return NEGOTIATION_DEFAULT_BUDGET;
}

function rememberedLastProduct() {
  try {
    return JSON.parse(localStorage.getItem("qianke:lastProduct") || "null");
  } catch {
    return null;
  }
}

function fallbackProductNeed() {
  const remembered = rememberedLastProduct();
  const rememberedTitle = String(remembered?.title || "").trim();
  if (rememberedTitle) return rememberedTitle;
  const quoteTitle = String(storeQuote.value?.product_refs?.[0]?.title || "").trim();
  if (quoteTitle) return quoteTitle;
  const latest = recentOrders.value?.[0];
  const item = latest?.items?.[0];
  return String(item?.title || "").trim();
}

const filteredNegotiationProducts = computed(() => {
  const keyword = String(negotiationProductSearch.value || "").trim();
  if (!keyword) return negotiationProductOptions.value;
  return negotiationProductOptions.value.filter((product) => productMatchesQuery(product, keyword));
});

const visibleCartItems = computed(() =>
  cartItems.value.filter(
    (item) => !item.friend_id || item.friend_id === String(negotiationFriendId.value || "").trim()
  )
);
const cartCount = computed(() =>
  visibleCartItems.value.reduce((sum, item) => sum + Number(item.quantity || 0), 0)
);
const cartTotal = computed(() =>
  visibleCartItems.value.reduce(
    (sum, item) => sum + Number(item.price || 0) * Number(item.quantity || 0),
    0
  )
);
const globalCartCount = computed(() =>
  cartItems.value.reduce((sum, item) => sum + Number(item.quantity || 0), 0)
);
const globalCartTotal = computed(() =>
  cartItems.value.reduce(
    (sum, item) => sum + Number(item.price || 0) * Number(item.quantity || 0),
    0
  )
);
const cartEditActiveSku = computed(() =>
  cartEditOptions.value.find((sku) => sku.sku === cartEditSku.value) || null
);
const cartEditMaxQuantity = computed(() =>
  Math.max(1, Math.min(20, Number(cartEditActiveSku.value?.stock || 1) || 1))
);

function addSelectedToCart() {
  const product = negotiationProductOptions.value.find((item) => item.product_id === negotiationProductId.value);
  const sku = negotiationSkuOptions.value.find((item) => item.sku === negotiationSku.value);
  if (!product || !sku || !sku.in_stock) {
    negotiationCartHint.value = "请选择有库存的商品和规格";
    return;
  }
  try {
    cart.add({
      friend_id: String(negotiationFriendId.value || "").trim(),
      merchant_name: negotiationMerchant.value,
      product_id: product.product_id,
      title: product.title,
      image_url: product.image_url,
      ...sku,
      quantity: Math.max(1, Math.min(cartLineMax(sku), Number(negotiationQuantity.value) || 1)),
    });
    negotiationCartHint.value = `已加入购物车：${product.title} ${sku.spec}`;
  } catch (error) {
    negotiationCartHint.value = error.message;
  }
}

function removeCartItem(item) { cart.remove(item); }
function changeCartItemQuantity(item, delta) { cart.setQuantity(item, item.quantity + delta); }

function openCartDrawer() {
  cartDrawerError.value = "";
  cartOpen.value = true;
}

function closeCartDrawer() {
  cartOpen.value = false;
}

function openCartCheckout() {
  const items = cartItems.value;
  if (!items.length) return;
  const friendId = String(items[0].friend_id || "").trim();
  if (items.some((item) => String(item.friend_id || "").trim() !== friendId)) {
    cartDrawerError.value = "购物车里有多个商家的商品，请分开结算";
    return;
  }
  cartOpen.value = false;
  cartDrawerError.value = "";
  negotiationFriendId.value = friendId;
  negotiationMerchant.value = String(items[0].merchant_name || latestMerchantThread()?.name || "");
  negotiationNeed.value = "购物车合并报价";
  negotiationBudget.value = Math.max(1, Math.ceil(globalCartTotal.value));
  negotiationQuantity.value = 1;
  negotiationSku.value = "";
  negotiationSkuSpec.value = "";
  negotiationSkuOptions.value = [];
  negotiationProductId.value = "";
  negotiationProductOptions.value = [];
  negotiationFormError.value = "";
  negotiationCartHint.value = "";
  negotiationOpen.value = true;
  void loadNegotiationSkuOptions();
}

async function openCartItemEditor(item) {
  if (!item) return;
  cartEditItem.value = item;
  cartEditSku.value = String(item.sku || "");
  cartEditQuantity.value = Math.max(1, Number(item.quantity || 1));
  cartEditOptions.value = [];
  cartEditError.value = "";
  cartEditLoading.value = true;
  try {
    const friendId = String(item.friend_id || negotiationFriendId.value || "").trim();
    if (!friendId) throw new Error("缺少商家信息");
    const data = await getJson(
      `/api/c/merchant/products?friend_id=${encodeURIComponent(friendId)}&limit=12`
    );
    const products = Array.isArray(data?.products) ? data.products : [];
    const product = products.find((entry) => entry.product_id === item.product_id);
    if (!product) throw new Error("商品已下架或不在当前店铺");
    cartEditOptions.value = (Array.isArray(product.skus) ? product.skus : [])
      .filter((sku) => sku && sku.sku)
      .map((sku) => ({
        sku: String(sku.sku),
        spec: String(sku.spec || "默认规格"),
        price: Number(sku.price || 0),
        stock: Number(sku.stock || 0),
        in_stock: sku.in_stock !== false && Number(sku.stock || 0) > 0,
      }));
    const known = cartEditOptions.value.find((sku) => sku.sku === cartEditSku.value);
    const selected = known || cartEditOptions.value.find((sku) => sku.in_stock) || cartEditOptions.value[0];
    if (selected) {
      cartEditSku.value = selected.sku;
      cartEditQuantity.value = Math.max(
        1,
        Math.min(Number(selected.stock || 1), cartEditQuantity.value, 20)
      );
    }
  } catch (error) {
    cartEditError.value = error?.detail || error?.message || "规格读取失败";
  } finally {
    cartEditLoading.value = false;
  }
}

function closeCartItemEditor() {
  cartEditItem.value = null;
  cartEditError.value = "";
  cartEditOptions.value = [];
}

function changeCartEditQuantity(delta) {
  const next = Number(cartEditQuantity.value || 1) + Number(delta || 0);
  cartEditQuantity.value = Math.max(1, Math.min(cartEditMaxQuantity.value, next));
}

function saveCartEdit() {
  const original = cartEditItem.value;
  const sku = cartEditActiveSku.value;
  if (!original || !sku) {
    cartEditError.value = "请选择有效规格";
    return;
  }
  if (!sku.in_stock) {
    cartEditError.value = "这个规格暂时缺货";
    return;
  }
  try {
    cart.edit(original, sku, cartEditQuantity.value);
    closeCartItemEditor();
  } catch (error) {
    cartEditError.value = error.message;
  }
}

function clearCurrentCart() {
  cart.clearMerchant(String(negotiationFriendId.value || "").trim());
}

async function confirmCartQuote() {
  if (!visibleCartItems.value.length || negotiating.value) return;
  let payload;
  try {
    payload = cartCheckoutPayload(visibleCartItems.value);
  } catch (error) {
    negotiationFormError.value = error.message;
    return;
  }
  const budget = Math.max(1, Number(negotiationBudget.value) || NEGOTIATION_DEFAULT_BUDGET);
  negotiationOpen.value = false;
  await runNegotiation("购物车合并报价", budget, 1, {
    friendId: payload.friend_id,
    echoUser: negotiationEchoUser.value,
    items: payload.items,
  });
  // Keep cart contents until CShop confirms the order successfully.
}

function quoteRefCount(quote) {
  const refs = Array.isArray(quote?.product_refs) ? quote.product_refs : [];
  return refs.reduce((sum, ref) => sum + Number(ref?.quantity || 1), 0);
}

function quoteOriginalTotal(quote) {
  const refs = Array.isArray(quote?.product_refs) ? quote.product_refs : [];
  return refs.reduce(
    (sum, ref) => sum + Number(ref?.price || ref?.unit_price || 0) * Number(ref?.quantity || 1),
    0
  );
}

function quoteDiscountTotal(quote) {
  const policies = Array.isArray(quote?.policy_refs) ? quote.policy_refs : [];
  return policies.reduce((sum, policy) => sum + Number(policy?.discount_amount || 0), 0);
}

function quotePayableTotal(quote) {
  return Math.max(0, quoteOriginalTotal(quote) - quoteDiscountTotal(quote));
}

function openNegotiation(options = {}) {
  if (negotiating.value || typing.value) return;
  const active = activeThread.value;
  const merchant = active.kind === "merchant" ? active : latestMerchantThread();
  negotiationFriendId.value = merchant?.id || "";
  negotiationMerchant.value = merchant?.name || "";
  negotiationNeed.value =
    String(options.need || "").trim() ||
    negotiationNeedFromThread() ||
    (merchant?.id ? needFromConversation(merchant.id) : "") ||
    fallbackProductNeed();
  const remembered = rememberedLastProduct();
  const rememberedTitle = String(remembered?.title || "").trim();
  negotiationSku.value = String(options.sku || remembered?.sku || "").trim();
  negotiationSkuSpec.value = String(remembered?.spec || "").trim();
  negotiationSkuOptions.value = [];
  negotiationSkuLoading.value = false;
  negotiationProductTitle.value = rememberedTitle;
  negotiationProductOptions.value = [];
  negotiationProductId.value = String(remembered?.product_id || "").trim();
  negotiationProductSearch.value = "";
  negotiationCartHint.value = "";
  negotiationBudget.value = negotiationBudgetFromThread();
  negotiationQuantity.value = Math.max(
    1,
    Math.min(20, Number(remembered?.quantity || options.quantity || 1) || 1),
  );
  negotiationEchoUser.value = options.echoUser !== false;
  negotiationFormError.value = "";
  negotiationOpen.value = true;
  void loadNegotiationSkuOptions();
}

async function loadNegotiationSkuOptions() {
  const friendId = String(negotiationFriendId.value || "").trim();
  if (!friendId) return;
  const need = String(negotiationNeed.value || "").trim();
  const preferredSku = String(negotiationSku.value || "").trim();
  const preferredProductId = String(negotiationProductId.value || "").trim();
  negotiationSkuLoading.value = true;
  try {
    const data = await getJson(
      `/api/c/merchant/products?friend_id=${encodeURIComponent(friendId)}&limit=12`
    );
    const products = (Array.isArray(data?.products) ? data.products : [])
      .filter((item) => item && item.product_id && item.title)
      .map((item) => ({
        product_id: String(item.product_id),
        title: String(item.title),
        category: String(item.category || ""),
        brand: String(item.brand || ""),
        price: Number(item.price || 0),
        stock: Number(item.stock || 0),
        image_url: String(item.image_url || item.images?.[0]?.url || ""),
        skus: Array.isArray(item.skus) ? item.skus : [],
      }));
    negotiationProductOptions.value = products;
    let product = products.find((item) => item.product_id === preferredProductId);
    if (!product && need) {
      product = products.find((item) => {
        const title = item.title.trim();
        return title && (title.includes(need) || need.includes(title));
      });
    }
    if (!product) return;
    applyNegotiationProduct(product, preferredSku, false);
  } catch {
    // 商品/规格读取失败时保留手动输入，不阻断砍价
  } finally {
    negotiationSkuLoading.value = false;
  }
}

function applyNegotiationProduct(product, preferredSku = "", syncNeed = false) {
  if (!product) return;
  negotiationProductId.value = String(product.product_id || "");
  negotiationProductTitle.value = String(product.title || "").trim();
  if (syncNeed) negotiationNeed.value = negotiationProductTitle.value;
  negotiationSkuOptions.value = (Array.isArray(product.skus) ? product.skus : [])
    .filter((item) => item && item.sku)
    .map((item) => ({
      sku: String(item.sku),
      spec: String(item.spec || "默认规格"),
      price: Number(item.price || 0),
      stock: Number(item.stock || 0),
      in_stock: item.in_stock !== false && Number(item.stock || 0) > 0,
    }));
  const known = negotiationSkuOptions.value.find((item) => item.sku === preferredSku);
  const selected = known || negotiationSkuOptions.value.find((item) => item.in_stock) || negotiationSkuOptions.value[0];
  if (selected) {
    negotiationSku.value = selected.sku;
    negotiationSkuSpec.value = selected.spec;
  }
}

function selectNegotiationProduct(productId) {
  if (!productId) {
    negotiationProductId.value = "";
    negotiationSkuOptions.value = [];
    negotiationSku.value = "";
    negotiationSkuSpec.value = "";
    return;
  }
  const product = negotiationProductOptions.value.find((item) => item.product_id === productId);
  if (product) applyNegotiationProduct(product, negotiationSku.value, true);
}

function selectNegotiationSku(skuValue) {
  const selected = negotiationSkuOptions.value.find((item) => item.sku === skuValue);
  negotiationSku.value = String(skuValue || "");
  negotiationSkuSpec.value = selected?.spec || "";
}

function openNegotiationForPrompt(text) {
  openNegotiation({
    need: normalizeNegotiationNeed(text),
    echoUser: false,
  });
}

function closeNegotiation() {
  if (negotiating.value) return;
  negotiationOpen.value = false;
  negotiationFormError.value = "";
}

async function confirmNegotiation() {
  const need = String(negotiationNeed.value || "").trim();
  const budget = Math.max(1, Number(negotiationBudget.value) || NEGOTIATION_DEFAULT_BUDGET);
  const quantity = Math.max(1, Math.min(20, Number(negotiationQuantity.value) || 1));
  if (!need) {
    negotiationFormError.value = "先告诉小鱼想砍什么商品";
    return;
  }
  negotiationOpen.value = false;
  const selectedSku =
    negotiationSku.value ||
    negotiationSkuOptions.value.find((item) => item.in_stock)?.sku ||
    negotiationSkuOptions.value[0]?.sku ||
    "";
  await runNegotiation(need, budget, quantity, {
    friendId: negotiationFriendId.value,
    echoUser: negotiationEchoUser.value,
    sku: selectedSku,
  });
}

async function runNegotiation(need, budget = NEGOTIATION_DEFAULT_BUDGET, quantity = 1, options = {}) {
  // 调用中禁止重复点击；typing 同时会禁用发送按钮/回车提交
  if (negotiating.value || typing.value) return;
  negotiateError.value = "";
  const explicitFriend = String(options.friendId || negotiationFriendId.value || "").trim();
  const negotiationThread = explicitFriend || (activeThread.value.kind === "merchant" ? activeId.value : "companion");
  if (!explicitFriend && activeId.value !== negotiationThread) await switchThread(negotiationThread);
  negotiating.value = true;
  typing.value = true;
  negotiationRejected.value = false;
  if (options.echoUser !== false) {
    pushMessage({
      role: "user",
      text: `让小鱼去砍价：${need}，预算 ¥${budget}`,
    });
  }
  scrollToBottom();
  try {
    const sku = String(options.sku || negotiationSku.value || "").trim();
    const cartPayload = Array.isArray(options.items)
      ? options.items.map((item) => ({
          sku: String(item.sku || ""),
          quantity: Math.max(1, Math.min(20, Number(item.quantity) || 1)),
        }))
      : [];
    const data = await postJson("/api/c/negotiations", {
      need,
      budget,
      quantity,
      friend_id: explicitFriend || (negotiationThread !== "companion" ? negotiationThread : undefined),
      ...(sku && !cartPayload.length ? { sku } : {}),
      ...(cartPayload.length ? { items: cartPayload } : {}),
    });
    const transcript = Array.isArray(data?.transcript) ? data.transcript : [];
    for (const item of transcript) {
      const text = cleanReply(item?.text);
      if (!text) continue;
      pushMessage({
        role: item?.actor === "b_pet" ? "merchant" : "companion",
        text,
        author: String(item?.name || "").trim() || undefined,
      });
    }
    if (String(data?.status || "").toUpperCase() === "ACCEPTED" && data?.quote) {
      // 复用既有结构化报价卡 / 查看报价链接；成交仍由用户在商城逐单确认
      storeQuote.value = { ...data.quote, cart_quote: cartPayload.length > 0 };
      negotiationRejected.value = false;
    } else {
      // 拒绝时不生成报价卡，只补一条伙伴解释（原因码映射为界面文案）
      negotiationRejected.value = true;
      const reasonText = NEGOTIATION_REASON_LABELS[String(data?.reason || "").toUpperCase()];
      pushMessage({
        role: "companion",
        text: reasonText || "这次没有谈成，小鱼建议稍后再试。",
      });
    }
  } catch (error) {
    negotiateError.value = negotiationErrorMessage(error);
  } finally {
    negotiating.value = false;
    typing.value = false;
    scrollToBottom();
  }
}

/* ---------- 最近订单（真实数据，GET /api/c/orders?limit=3） ---------- */
function orderStatusLabel(order) {
  // 售后工单已退款 / 商家订单已退款：最近订单同样显示「已退款」
  if (String(order?.after_sale?.status || "").toUpperCase() === "REFUNDED") return "已退款";
  const raw = String(order?.merchant_status || order?.status || "").trim();
  if (!raw) return "已确认";
  const labels = {
    CREATED: "已创建",
    PENDING: "待确认",
    CONFIRMED: "已确认",
    PAID: "已支付",
    SHIPPED: "已发货",
    DELIVERING: "配送中",
    COMPLETED: "已完成",
    CANCELLED: "已取消",
    CANCELED: "已取消",
    REFUNDED: "已退款",
  };
  return labels[raw.toUpperCase()] || raw;
}

/** 侧栏只有 304px：日期只到「几月几日」，完整时间留给订单页 */
function orderDateLabel(value) {
  const text = String(value || "");
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return text.slice(0, 10);
  return `${Number(match[2])} 月 ${Number(match[3])} 日`;
}

function orderTitle(order) {
  const first = Array.isArray(order?.items) ? order.items[0] : null;
  return first?.title || first?.product_id || order?.merchant_order_id || order?.order_id || "订单";
}

function orderAmountLabel(order) {
  const amount = Number(order?.total_amount || 0);
  return Number.isInteger(amount) ? `¥${amount}` : `¥${amount.toFixed(2)}`;
}

/** 标记位：M = 有商家订单号，P = 平台模拟订单 */
function orderMark(order) {
  return order?.merchant_order_id ? "M" : "P";
}

/* ---------- 物流（承运商 + 运单号；侧栏空间小，只显示承运商与单号后 4 位） ---------- */
function logisticsTail(value) {
  const text = String(value || "").trim();
  return text.length > 4 ? `…${text.slice(-4)}` : text;
}

function orderLogisticsShort(order) {
  const carrier = String(order?.merchant_carrier || "").trim();
  const tracking = String(order?.merchant_tracking_no || "").trim();
  if (!tracking) return carrier;
  return `${carrier || "物流"} · ${logisticsTail(tracking)}`;
}

function orderLogisticsTitle(order) {
  const carrier = String(order?.merchant_carrier || "").trim() || "物流";
  const tracking = String(order?.merchant_tracking_no || "").trim();
  return tracking ? `${carrier} ${tracking}` : carrier;
}

async function loadRecentOrders() {
  recentOrdersLoading.value = true;
  try {
    const data = await getJson("/api/c/orders?limit=3");
    recentOrders.value = Array.isArray(data?.orders) ? data.orders : [];
    recentOrdersError.value = "";
  } catch (error) {
    // 加载失败只做轻提示：保留上一次成功拿到的列表，不用空态覆盖历史
    recentOrdersError.value = error?.detail || error?.message || "最近订单加载失败";
  } finally {
    recentOrdersLoading.value = false;
  }
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

async function loadMemories() {
  memoriesError.value = "";
  try {
    const data = await getJson("/api/c/companion/memories");
    memories.value = Array.isArray(data?.memories) ? data.memories : [];
    memoryDigests.value = Array.isArray(data?.digests) ? data.digests : [];
    diaryEnabled.value = Boolean(data?.diary_enabled);
  } catch (error) {
    memories.value = [];
    memoriesError.value = error?.detail || error?.message || "记忆加载失败";
  }
}

function memoryKindLabel(kind) {
  return { preference: "偏好", boundary: "边界", fact: "信息", event: "事件" }[kind] || "记忆";
}

async function removeMemory(memoryId) {
  if (!memoryId || memoryBusy.value) return;
  memoryBusy.value = memoryId;
  try {
    await del(`/api/c/companion/memories/${encodeURIComponent(memoryId)}`);
    await loadMemories();
  } catch (error) {
    memoriesError.value = error?.detail || error?.message || "删除记忆失败";
  } finally {
    memoryBusy.value = "";
  }
}

async function clearMemories() {
  if (memoryBusy.value || !memories.value.length) return;
  if (!window.confirm("清空小鱼记得的事？此操作不可撤销。")) return;
  memoryBusy.value = "all";
  try {
    await del("/api/c/companion/memories");
    await loadMemories();
  } catch (error) {
    memoriesError.value = error?.detail || error?.message || "清空记忆失败";
  } finally {
    memoryBusy.value = "";
  }
}

async function loadDiary() {
  diaryError.value = "";
  try {
    const data = await getJson("/api/c/companion/diary?limit=10");
    diaryEnabled.value = Boolean(data?.enabled);
    diaries.value = Array.isArray(data?.diaries) ? data.diaries : [];
  } catch (error) {
    diaryError.value = error?.detail || error?.message || "日记加载失败";
  }
}

async function setDiaryEnabled(enabled) {
  if (diaryBusy.value) return;
  diaryBusy.value = true;
  diaryError.value = "";
  try {
    const data = await patchJson("/api/c/companion/diary", { enabled });
    diaryEnabled.value = Boolean(data?.enabled);
    await loadDiary();
  } catch (error) {
    diaryError.value = error?.detail || error?.message || "日记设置失败";
  } finally {
    diaryBusy.value = false;
  }
}

async function loadRhythm() {
  rhythmError.value = "";
  try {
    const data = await getJson("/api/c/companion/rhythm");
    if (data) rhythm.value = { ...rhythm.value, ...data };
  } catch (error) {
    rhythmError.value = error?.detail || error?.message || "关系节奏加载失败";
  }
}

async function setRhythmEnabled(enabled) {
  if (rhythmSaving.value) return;
  rhythmSaving.value = true;
  rhythmError.value = "";
  try {
    const data = await patchJson("/api/c/companion/rhythm", { enabled: Boolean(enabled) });
    if (data) rhythm.value = { ...rhythm.value, ...data };
  } catch (error) {
    rhythmError.value = error?.detail || error?.message || "保存关系节奏失败";
  } finally {
    rhythmSaving.value = false;
  }
}

async function pauseRhythm() {
  if (rhythmSaving.value) return;
  rhythmSaving.value = true;
  rhythmError.value = "";
  try {
    const data = await patchJson("/api/c/companion/rhythm", { pause_hours: 24 * 7 });
    if (data) rhythm.value = { ...rhythm.value, ...data };
  } catch (error) {
    rhythmError.value = error?.detail || error?.message || "暂停失败";
  } finally {
    rhythmSaving.value = false;
  }
}

async function loadAccountContext() {
  try {
    const data = await getJson("/whoami");
    isDemoAccount.value = Boolean(data?.account?.is_demo);
  } catch {
    // 读取失败按真实账号处理，避免把演示数据当成用户历史。
    isDemoAccount.value = false;
  }
}

function stripDemoSeedForRealAccount() {
  if (isDemoAccount.value) return;
  threads.value = threads.value.filter((thread) => thread.id === "companion");
  messagesByThread.value = { companion: [] };
}

async function pollCheckin() {
  try {
    const data = await postJson("/api/c/companion/checkin", {});
    const checkin = data?.checkin;
    if (checkin?.content) {
      pushMessage({ role: "companion", text: cleanReply(checkin.content) });
      scrollToBottom();
    }
  } catch {
    // 主动回访失败不影响正常聊天。
  }
}

async function switchThread(id) {
  const leavingGroup = isGroupThread(activeId.value);
  closeGroupSocket();
  closeStoreSocket();
  lastStoreSend.value = null;
  lastGroupSend.value = null;
  if (leavingGroup) typing.value = false;
  activeId.value = id;
  showContext.value = false;
  // 切回会话时刷新最近订单：订单可能在别的页面/商城刚创建，右侧栏不能停在旧数据
  loadRecentOrders();
  const target = allThreads.value.find((item) => item.id === id);
  if (target?.kind === "group") {
    // 进入群：标记已读、加载历史消息并建立群 WebSocket
    markThreadRead(id);
    await loadGroupMessages(id);
    openGroupSocket(id);
  } else {
    // 进入会话即标记已读并把角标清零，之后以后端未读接口为准
    markThreadRead(id);
    if (target?.kind === "merchant") {
      await loadStoreMessages(id);
      openStoreSocket(false, id);
    }
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
  previousBodyOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  document.body.style.position = "fixed";
  document.body.style.top = "0";
  document.body.style.width = "100%";
  await loadAccountContext();
  stripDemoSeedForRealAccount();
  await loadMerchantThreads();
  cart.reload();
  await loadAgentSession();
  await Promise.all([loadCompanion(), loadCompanionMessages(), loadRecentOrders(), loadMemories(), loadRhythm(), loadDiary()]);
  await pollCheckin();
  await refreshUnread();
  startUnreadPolling();
  document.addEventListener("visibilitychange", onVisibilityChange);
  document.addEventListener("pointerdown", onCompanionActivity, { passive: true });
  document.addEventListener("keydown", onCompanionActivity);
  restoreVoicePrefs();
  loadVoiceOptions();
  if (voiceSynthesisSupported.value) {
    window.speechSynthesis.addEventListener?.("voiceschanged", loadVoiceOptions);
  }
  resetAvatarIdleTimer();
  syncViewportHeight();
  window.visualViewport?.addEventListener("resize", onViewportResize);
  window.visualViewport?.addEventListener("scroll", onViewportResize);
  window.addEventListener("resize", onViewportResize);
  window.addEventListener("online", onOnline);
  window.addEventListener("offline", onOffline);
  window.addEventListener("beforeinstallprompt", onBeforeInstall);
  const standalone =
    window.matchMedia?.("(display-mode: standalone)")?.matches || window.navigator.standalone === true;
  if (!standalone && /iPad|iPhone|iPod/.test(window.navigator.userAgent || "")) {
    installHint.value = "Safari：分享 → 添加到主屏幕";
    showInstall.value = true;
  }
  await loadGroups();
  scrollToBottom();
});

onBeforeUnmount(() => {
  document.body.style.overflow = previousBodyOverflow;
  document.body.style.position = "";
  document.body.style.top = "";
  document.body.style.width = "";
  if (copyTipTimer) clearTimeout(copyTipTimer);
  if (messagePressTimer) clearTimeout(messagePressTimer);
  if (groupMentionHintTimer) clearTimeout(groupMentionHintTimer);
  stopUnreadPolling();
  if (unreadRefreshTimer) {
    clearTimeout(unreadRefreshTimer);
    unreadRefreshTimer = null;
  }
  if (incomingReadTimer) {
    clearTimeout(incomingReadTimer);
    incomingReadTimer = null;
  }
  document.removeEventListener("visibilitychange", onVisibilityChange);
  document.removeEventListener("pointerdown", onCompanionActivity);
  document.removeEventListener("keydown", onCompanionActivity);
  clearTimer("idle");
  clearTimer("transient");
  clearTimer("tip");
  clearTimer("expression");
  stopLipSync();
  if (voiceSynthesisSupported.value) {
    window.speechSynthesis.removeEventListener?.("voiceschanged", loadVoiceOptions);
  }
  speechRecognition?.abort?.();
  if (voiceReplyEnabled.value && typeof window !== "undefined" && window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  for (const url of avatarPreviewUrls) URL.revokeObjectURL(url);
  avatarPreviewUrls.clear();
  window.visualViewport?.removeEventListener("resize", onViewportResize);
  window.visualViewport?.removeEventListener("scroll", onViewportResize);
  window.removeEventListener("resize", onViewportResize);
  window.removeEventListener("online", onOnline);
  window.removeEventListener("offline", onOffline);
  window.removeEventListener("beforeinstallprompt", onBeforeInstall);
  closeGroupSocket();
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

    <div v-if="negotiationOpen" class="c-negotiate-mask" @click.self="closeNegotiation">
      <form class="c-negotiate-sheet" role="dialog" aria-modal="true" aria-labelledby="c-negotiate-title" @submit.prevent="confirmNegotiation">
        <header class="c-negotiate-head">
          <div>
            <strong id="c-negotiate-title">让小鱼去砍价</strong>
            <p>商品从当前对话自动带出，可以修改。</p>
          </div>
          <button type="button" class="c-negotiate-close" aria-label="关闭" @click="closeNegotiation">×</button>
        </header>
        <p v-if="negotiationMerchant" class="c-negotiate-merchant">当前商家 · {{ negotiationMerchant }}</p>
        <div v-if="negotiationProductOptions.length" class="c-negotiate-products">
          <div class="c-negotiate-products-head">
            <span>从店铺选择</span>
            <small>{{ filteredNegotiationProducts.length }} / {{ negotiationProductOptions.length }} 件</small>
          </div>
          <label class="c-product-search">
            <span aria-hidden="true">⌕</span>
            <input v-model.trim="negotiationProductSearch" type="search" placeholder="搜商品、分类或品牌" />
          </label>
          <div class="c-product-cards" role="list">
            <button
              v-for="product in filteredNegotiationProducts"
              :key="product.product_id"
              type="button"
              class="c-product-card"
              :class="{ active: negotiationProductId === product.product_id }"
              role="listitem"
              @click="selectNegotiationProduct(product.product_id)"
            >
              <span class="c-product-thumb">
                <img
                  v-if="product.image_url"
                  :src="product.image_url"
                  :alt="product.title"
                  loading="lazy"
                  @error="$event.target.style.display = 'none'"
                />
                <span class="c-product-placeholder">{{ product.category.slice(0, 1) || "茶" }}</span>
              </span>
              <span class="c-product-info">
                <strong>{{ product.title }}</strong>
                <small>{{ product.category }} · ¥{{ Number(product.price).toFixed(2) }}</small>
                <em>{{ product.skus.length }} 个规格 · 库存 {{ product.stock }}</em>
              </span>
            </button>
          </div>
          <p v-if="!filteredNegotiationProducts.length" class="c-negotiate-hint">没有匹配的商品，试试其他关键词。</p>
        </div>
        <label class="c-negotiate-field">
          <span>想砍的商品</span>
          <input v-model="negotiationNeed" type="text" maxlength="80" placeholder="想买的商品名称" @change="loadNegotiationSkuOptions" />
        </label>
        <p v-if="negotiationSkuLoading" class="c-negotiate-hint">正在读取规格…</p>
        <label v-else-if="negotiationSkuOptions.length" class="c-negotiate-field">
          <span>规格</span>
          <select :value="negotiationSku" @change="selectNegotiationSku($event.target.value)">
            <option v-for="sku in negotiationSkuOptions" :key="sku.sku" :value="sku.sku" :disabled="!sku.in_stock">
              {{ sku.spec }} · ¥{{ Number(sku.price).toFixed(2) }}{{ sku.in_stock ? "" : "（缺货）" }}
            </option>
          </select>
        </label>
        <p v-else-if="negotiationSku" class="c-negotiate-hint">
          规格 · {{ negotiationSkuSpec || negotiationSku }}
        </p>
        <div class="c-cart-add-row">
          <button type="button" class="c-cart-add" :disabled="negotiating" @click="addSelectedToCart">加入购物车</button>
          <span v-if="negotiationCartHint">{{ negotiationCartHint }}</span>
          <span v-else-if="visibleCartItems.length">购物车 {{ cartCount }} 件 · ¥{{ cartTotal.toFixed(2) }}</span>
        </div>
        <div v-if="visibleCartItems.length" class="c-cart-panel">
          <div class="c-cart-head">
            <strong>购物车 · {{ cartCount }} 件</strong>
            <button type="button" @click="clearCurrentCart">清空</button>
          </div>
          <div class="c-cart-list">
            <div v-for="item in visibleCartItems" :key="cartItemKey(item)" class="c-cart-item">
              <span class="c-cart-thumb">
                <img v-if="item.image_url" :src="item.image_url" :alt="item.title" loading="lazy" @error="$event.target.style.display = 'none'" />
                <span>{{ item.title.slice(0, 1) }}</span>
              </span>
              <span class="c-cart-info">
                <strong>{{ item.title }}</strong>
                <small>{{ item.spec }} · ¥{{ Number(item.price).toFixed(2) }}</small>
              </span>
              <button type="button" class="c-cart-edit" @click="openCartItemEditor(item)">改规格</button>
              <span class="c-cart-qty">
                <button type="button" aria-label="减少数量" :disabled="Number(item.quantity) <= 1" @click="changeCartItemQuantity(item, -1)">−</button>
                <strong>{{ item.quantity }}</strong>
                <button type="button" aria-label="增加数量" :disabled="Number(item.quantity) >= cartLineMax(item)" @click="changeCartItemQuantity(item, 1)">＋</button>
              </span>
              <button type="button" class="c-cart-remove" :aria-label="`移除 ${item.title}`" @click="removeCartItem(item)">×</button>
            </div>
          </div>
          <button type="button" class="c-cart-merge" :disabled="negotiating" @click="confirmCartQuote">
            {{ negotiating ? "合并报价中…" : `购物车合并报价 · ¥${cartTotal.toFixed(2)}` }}
          </button>
        </div>
        <div class="c-negotiate-row">
          <label class="c-negotiate-field">
            <span>预算（元）</span>
            <input v-model.number="negotiationBudget" type="number" min="1" max="100000" inputmode="numeric" />
          </label>
          <label class="c-negotiate-field">
            <span>数量</span>
            <input v-model.number="negotiationQuantity" type="number" min="1" max="20" inputmode="numeric" />
          </label>
        </div>
        <p v-if="negotiationFormError" class="c-inline-error" role="alert">{{ negotiationFormError }}</p>
        <div class="c-negotiate-actions">
          <button type="button" class="c-negotiate-cancel" @click="closeNegotiation">取消</button>
          <button type="submit" class="c-negotiate-submit" :disabled="negotiating">{{ negotiating ? "谈判中…" : "开始谈判" }}</button>
        </div>
      </form>
    </div>

    <div v-if="cartOpen" class="c-cart-drawer-mask" @click.self="closeCartDrawer">
      <aside class="c-cart-drawer" role="dialog" aria-modal="true" aria-labelledby="c-cart-drawer-title">
        <header class="c-cart-drawer-head">
          <div>
            <strong id="c-cart-drawer-title">购物车</strong>
            <small>{{ globalCartCount }} 件 · ¥{{ globalCartTotal.toFixed(2) }}</small>
          </div>
          <button type="button" class="c-icon-btn" aria-label="关闭购物车" @click="closeCartDrawer">×</button>
        </header>
        <div v-if="!cartItems.length" class="c-cart-drawer-empty">
          <strong>购物车是空的</strong>
          <p>在砍价确认层里选商品，加入购物车。</p>
        </div>
        <div v-else class="c-cart-drawer-list">
          <div v-for="item in cartItems" :key="cartItemKey(item)" class="c-cart-drawer-item">
            <span class="c-cart-thumb">
              <img v-if="item.image_url" :src="item.image_url" :alt="item.title" loading="lazy" @error="$event.target.style.display = 'none'" />
              <span>{{ item.title.slice(0, 1) }}</span>
            </span>
            <div class="c-cart-drawer-copy">
              <strong>{{ item.title }}</strong>
              <small>{{ item.merchant_name }} · {{ item.spec }}</small>
              <span>¥{{ Number(item.price).toFixed(2) }}</span>
            </div>
            <button type="button" class="c-cart-edit" @click="openCartItemEditor(item)">改规格</button>
            <div class="c-cart-qty">
              <button type="button" aria-label="减少数量" :disabled="Number(item.quantity) <= 1" @click="changeCartItemQuantity(item, -1)">−</button>
              <strong>{{ item.quantity }}</strong>
              <button type="button" aria-label="增加数量" :disabled="Number(item.quantity) >= cartLineMax(item)" @click="changeCartItemQuantity(item, 1)">＋</button>
            </div>
            <button type="button" class="c-cart-remove" :aria-label="`移除 ${item.title}`" @click="removeCartItem(item)">×</button>
          </div>
        </div>
        <p v-if="cartDrawerError" class="c-inline-error" role="alert">{{ cartDrawerError }}</p>
        <footer v-if="cartItems.length" class="c-cart-drawer-foot">
          <div><span>合计</span><strong>¥{{ globalCartTotal.toFixed(2) }}</strong></div>
          <button type="button" class="c-cart-checkout" @click="openCartCheckout">去合并报价</button>
        </footer>
      </aside>
    </div>

    <div v-if="cartEditItem" class="c-cart-editor-mask" @click.self="closeCartItemEditor">
      <section class="c-cart-editor" role="dialog" aria-modal="true" aria-labelledby="c-cart-editor-title">
        <header class="c-cart-editor-head">
          <div>
            <strong id="c-cart-editor-title">改规格</strong>
            <small>{{ cartEditItem.title }}</small>
          </div>
          <button type="button" class="c-icon-btn" aria-label="关闭改规格" @click="closeCartItemEditor">×</button>
        </header>
        <p v-if="cartEditLoading" class="c-cart-editor-hint">正在读取规格…</p>
        <p v-else-if="cartEditError" class="c-inline-error" role="alert">{{ cartEditError }}</p>
        <template v-else>
          <label class="c-cart-editor-field">
            <span>规格</span>
            <select v-model="cartEditSku">
              <option v-for="sku in cartEditOptions" :key="sku.sku" :value="sku.sku" :disabled="!sku.in_stock">
                {{ sku.spec }} · ¥{{ Number(sku.price).toFixed(2) }}{{ sku.in_stock ? "" : "（缺货）" }}
              </option>
            </select>
          </label>
          <div class="c-cart-editor-row">
            <span>数量</span>
            <div class="c-cart-qty">
              <button type="button" aria-label="减少数量" :disabled="cartEditQuantity <= 1" @click="changeCartEditQuantity(-1)">−</button>
              <strong>{{ cartEditQuantity }}</strong>
              <button type="button" aria-label="增加数量" :disabled="cartEditQuantity >= cartEditMaxQuantity" @click="changeCartEditQuantity(1)">＋</button>
            </div>
            <small>库存 {{ cartEditActiveSku?.stock ?? 0 }}</small>
          </div>
          <p class="c-cart-editor-sum">
            单价 ¥{{ Number(cartEditActiveSku?.price || 0).toFixed(2) }}
            · 小计 ¥{{ (Number(cartEditActiveSku?.price || 0) * Number(cartEditQuantity || 1)).toFixed(2) }}
          </p>
          <div class="c-cart-editor-actions">
            <button type="button" class="c-cart-editor-cancel" @click="closeCartItemEditor">取消</button>
            <button type="button" class="c-cart-editor-save" @click="saveCartEdit">保存规格</button>
          </div>
        </template>
      </section>
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
          <RouterLink class="c-nav-item" to="/c/home">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m3 11 9-8 9 8" /><path d="M5 10v10h14V10" /><path d="M10 20v-6h4v6" /></svg>
            <span>首页</span>
          </RouterLink>
          <RouterLink class="c-nav-item active" to="/c/app">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.9 8.9 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
              <path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01" />
            </svg>
            <span>聊</span>
          </RouterLink>
          <RouterLink class="c-nav-item" to="/c">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
              <path d="M3 6h18M16 10a4 4 0 0 1-8 0" />
            </svg>
            <span>逛</span>
          </RouterLink>
          <RouterLink class="c-nav-item" to="/c/orders">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <path d="M6 2h12v20l-3-2-3 2-3-2-3 2z" />
              <path d="M9 7h6M9 11h6M9 15h4" />
            </svg>
            <span>订单</span>
          </RouterLink>
          <RouterLink class="c-nav-item" to="/c/social">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 9 9 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
            </svg>
            <span>消息</span>
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
              <strong>
                {{ thread.name }}<span v-if="thread.kind === 'group'" class="c-group-tag">群</span>
              </strong>
              <small v-if="thread.kind === 'group'">{{ threadMemberCount(thread) }} 人 · {{ thread.preview }}</small>
              <small v-else>{{ thread.preview }}</small>
            </span>
            <span class="c-thread-meta">
              <time>{{ thread.time }}</time>
              <span v-if="unreadOf(thread.id)" class="c-unread">{{ unreadOf(thread.id) }}</span>
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
            <button
              v-if="mentionUnread > 0"
              type="button"
              class="c-mention-notif"
              :disabled="mentionBusy"
              :aria-label="`${mentionUnread} 条未读 @ 提及`"
              title="未读 @：点击标记已读并打开会话"
              @click="openUnreadMentions"
            >@{{ mentionUnread }}</button>
            <span class="c-plan"><i class="c-dot plan" />{{ planLabel }}</span>
            <button class="c-icon-btn" type="button" aria-label="打开当前会话信息" @click="toggleContext">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                <circle cx="12" cy="12" r="9" />
                <path d="M12 11v5M12 8h.01" />
              </svg>
            </button>
            <button
              type="button"
              class="c-icon-btn c-voice-toggle"
              :class="{ 'is-active': voiceReplyEnabled }"
              :aria-label="voiceReplyEnabled ? '关闭朗读' : '朗读小鱼回复'"
              :title="voiceReplyEnabled ? '关闭朗读' : '朗读小鱼回复'"
              @click="toggleVoiceReply"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                <path d="M11 5 6 9H3v6h3l5 4z" />
                <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
              </svg>
            </button>
            <CompanionAvatar
              v-if="!avatarVisible('companion')"
              ref="topAvatarRef"
              class="c-top-avatar"
              :size="44"
              :state="avatarState"
              :expression="avatarExpression"
              fallback="小"
              label="戳一下小鱼"
              @poke="onAvatarPoke"
            />
            <button
              v-else
              type="button"
              class="c-avatar top c-avatar-btn"
              :aria-label="avatarBusy === 'companion' ? '伙伴头像上传中' : '更换伙伴头像'"
              @click="openAvatarPicker('companion')"
            >
              <img
                :src="avatarSrc('companion')"
                alt=""
                @error="onAvatarError(avatarSrc('companion'))"
              />
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
              <CompanionAvatar
                v-if="activeThread.kind === 'companion' && !avatarVisible('companion')"
                ref="headAvatarRef"
                :size="40"
                :state="avatarState"
                :expression="avatarExpression"
                fallback="小"
                label="戳一下小鱼"
                @poke="onAvatarPoke"
              />
              <button
                v-else-if="activeThread.kind === 'companion'"
                type="button"
                class="c-avatar c-avatar-btn"
                aria-label="更换伙伴头像"
                @click="openAvatarPicker('companion')"
              >
                <img
                  :src="avatarSrc('companion')"
                  alt=""
                  @error="onAvatarError(avatarSrc('companion'))"
                />
              </button>
              <span v-else class="c-avatar">{{ activeThread.name.slice(0, 1) }}</span>
              <div>
                <h1>{{ activeThread.name }}</h1>
                <p><i class="c-dot" :class="threadDotClass" />{{ statusText }}<span class="c-head-divider">·</span>只做建议，成交需你确认</p>
              </div>
            </div>
            <div class="c-chat-actions">
              <button
                type="button"
                class="c-icon-btn c-cart-trigger"
                :aria-label="`购物车，${globalCartCount} 件`"
                title="购物车"
                @click="openCartDrawer"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                  <path d="M3 4h2l2.2 10.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.6L20 8H6" />
                  <circle cx="9.5" cy="19" r="1.2" />
                  <circle cx="17" cy="19" r="1.2" />
                </svg>
                <span v-if="globalCartCount" class="c-cart-trigger-badge">{{ globalCartCount }}</span>
              </button>
              <button
                type="button"
                class="c-icon-btn c-voice-toggle"
                :class="{ 'is-active': voiceReplyEnabled }"
                :aria-label="voiceReplyEnabled ? '关闭朗读' : '朗读小鱼回复'"
                :title="voiceReplyEnabled ? '关闭朗读' : '朗读小鱼回复'"
                @click="toggleVoiceReply"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                  <path d="M11 5 6 9H3v6h3l5 4z" />
                  <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
                </svg>
              </button>
              <button
                v-if="mentionUnread > 0"
                type="button"
                class="c-mention-notif"
                :disabled="mentionBusy"
                :aria-label="`${mentionUnread} 条未读 @ 提及`"
                title="未读 @：点击标记已读并打开会话"
                @click="openUnreadMentions"
              >@{{ mentionUnread }}</button>
              <button class="c-icon-btn" type="button" aria-label="当前会话信息" @click="toggleContext">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 11v5M12 8h.01" />
                </svg>
              </button>
            </div>
            <div v-if="avatarMenuOpen" class="c-avatar-menu-backdrop" @click="avatarMenuOpen = false" />
            <div v-if="avatarMenuOpen" class="c-avatar-menu" role="menu" aria-label="和小鱼互动" @click.stop>
              <button type="button" role="menuitem" @click="feedCompanion">喂食</button>
              <button type="button" role="menuitem" @click="petCompanion">摸摸</button>
              <button type="button" role="menuitem" @click="cycleAvatarExpression">换表情</button>
            </div>
            <div v-if="avatarTip" class="c-avatar-tip" role="status">{{ avatarTip }}</div>
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
                <template v-else>{{ messageAvatarLabel(message.role, message) }}</template>
              </button>
              <span
                v-else
                class="c-msg-avatar"
                :class="message.role"
                aria-hidden="true"
              >{{ messageAvatarLabel(message.role, message) }}</span>
              <div class="c-message-content">
                <div class="c-message-meta">
                  <span>{{ messageAuthor(message.role, message) }}</span>
                  <time>{{ message.time }}</time>
                </div>
                <p class="c-bubble">
                  <span
                    v-for="(part, index) in messageSegments(message.text)"
                    :key="index"
                    :class="{ 'c-mention-token': part.mention }"
                    :role="part.mention ? 'button' : null"
                    :tabindex="part.mention ? 0 : null"
                    :title="part.mention ? '切换到该会话' : null"
                    @click="part.mention && openMentionThread(part.text)"
                    @keydown.enter.prevent="part.mention && openMentionThread(part.text)"
                    @keydown.space.prevent="part.mention && openMentionThread(part.text)"
                    @pointerdown="part.mention && $event.stopPropagation()"
                  >{{ part.text }}</span>
                  <time class="c-bubble-time">{{ message.time }}</time>
                </p>
                <div v-if="message.productRefs?.length" class="c-product-refs">
                  <div v-for="item in message.productRefs" :key="`${item.product_id}-${item.sku}`" class="c-product-ref">
                    <img v-if="item.thumb_url || item.image_url" :src="item.thumb_url || item.image_url" :alt="item.title" loading="lazy" @error="$event.target.style.display = 'none'" />
                    <div>
                      <strong>{{ item.title }}</strong>
                      <small>{{ item.spec || item.sku }} · ¥{{ Number(item.price || 0).toFixed(2) }}</small>
                    </div>
                  </div>
                </div>
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
              <span>{{ activeThread.kind === 'group' ? '群成员正在输入' : `${activeThread.name}正在输入` }}</span>
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

          <div v-if="activeThread.kind !== 'group'" class="c-prompt-row">
            <template v-if="activeId === 'companion'">
              <button type="button" class="c-prompt" @click="sendPrompt('陪我聊聊', 'companion')">陪我聊聊</button>
              <button type="button" class="c-prompt" @click="sendPrompt('帮我挑东西', 'advisor')">帮我挑东西</button>
            </template>
            <button type="button" class="c-prompt" @click="sendPrompt('看看有什么推荐', 'advisor')">看看有什么推荐</button>
            <button type="button" class="c-prompt" @click="sendPrompt('查平台活动', 'advisor')">查平台活动</button>
            <button type="button" class="c-prompt" @click="sendPrompt('问店宠售后', 'transaction')">问店宠售后</button>
            <button
              type="button"
              class="c-prompt is-negotiate"
              :disabled="negotiating || typing"
              @click="openNegotiation"
            >{{ negotiating ? "双宠谈判中…" : "让小鱼去砍价" }}</button>
          </div>
          <p v-if="negotiateError" class="c-inline-error c-negotiate-error" role="status">
            {{ negotiateError }}
          </p>
          <p v-if="groupMentionHint" class="c-group-mention-hint" role="status">
            {{ groupMentionHint }}
          </p>
          <p v-if="groupsError && activeThread.kind === 'group'" class="c-inline-error" role="status">
            {{ groupsError }}
          </p>

          <form class="c-composer" @submit.prevent="send">
            <div v-if="mentionOpen && mentionOptions.length" class="c-mention-pop" role="listbox" aria-label="选择提及对象">
              <button
                v-for="(option, index) in mentionOptions"
                :key="option.token"
                type="button"
                class="c-mention-option"
                :class="{ active: index === mentionIndex }"
                role="option"
                :aria-selected="index === mentionIndex"
                @mousedown.prevent="selectMention(option)"
                @mouseenter="mentionIndex = index"
              >
                <strong>{{ option.label }}</strong>
                <small>{{ option.token }} · {{ option.desc }}</small>
              </button>
            </div>
            <label class="sr-only" for="c-app-input">输入消息</label>
            <div class="c-composer-row">
              <button class="c-tool-btn" type="button" aria-label="添加附件" disabled>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>
              <button class="c-tool-btn c-mention-btn" type="button" aria-label="提及" @click="startMention">@</button>
              <button
                class="c-tool-btn c-voice-btn"
                :class="{ 'is-recording': voiceListening }"
                type="button"
                :aria-label="voiceListening ? '停止语音输入' : '语音输入'"
                :aria-pressed="voiceListening"
                @click="toggleVoiceInput"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
                  <rect x="9" y="3" width="6" height="11" rx="3" />
                  <path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" />
                </svg>
              </button>
              <textarea
                id="c-app-input"
                v-model="draft"
                rows="1"
                :placeholder="activeThread.kind === 'group' ? `在${activeThread.name}里发消息，可 @ 成员` : (activeId === 'companion' ? '想聊什么，或者要买什么' : '问商品、活动或售后')"
                @focus="onComposerFocus"
                @blur="onComposerBlur"
                @input="onComposerInput"
                @keydown="onComposerKeydown"
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
            <template v-if="isDemoAccount">
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
            </template>
            <div v-else class="c-overview-value">
              <strong>—</strong>
              <span class="c-trend">暂无消费数据</span>
            </div>
          </section>

          <section v-if="activeId === 'companion'" class="c-context-section">
            <header>
              <span>小鱼记得的事</span>
              <button
                v-if="memories.length"
                type="button"
                class="c-context-link c-memory-clear"
                :disabled="!!memoryBusy"
                @click="clearMemories"
              >清空</button>
            </header>
            <p v-if="memoriesError" class="c-inline-error" role="status">{{ memoriesError }}</p>
            <p v-else-if="!memories.length" class="c-memory-empty">
              直接说“我喜欢…”或“别推荐…”，小鱼会记住；你随时可以删除。
            </p>
            <ul v-else class="c-memory-list">
              <li v-for="item in memories" :key="item.memory_id" class="c-memory-item">
                <span class="c-memory-kind">{{ memoryKindLabel(item.kind) }}</span>
                <span class="c-memory-text">{{ item.content }}</span>
                <button
                  type="button"
                  class="c-memory-remove"
                  :disabled="memoryBusy === item.memory_id"
                  aria-label="删除这条记忆"
                  @click="removeMemory(item.memory_id)"
                >删</button>
              </li>
            </ul>
          </section>

          <section v-if="activeId === 'companion'" class="c-context-section">
            <header>
              <span>小鱼的日记</span>
              <label class="c-diary-toggle">
                <input
                  type="checkbox"
                  :checked="diaryEnabled"
                  :disabled="diaryBusy"
                  @change="setDiaryEnabled($event.target.checked)"
                />
                <span>每天写</span>
              </label>
            </header>
            <p v-if="diaryError" class="c-inline-error" role="status">{{ diaryError }}</p>
            <p v-else-if="!diaryEnabled" class="c-memory-empty">
              默认关闭。开启后小鱼每天基于当天对话写一篇日记，只自己看，不自动变成偏好。
            </p>
            <p v-else-if="!diaries.length" class="c-memory-empty">还没有日记，今晚之后会出现在这里。</p>
            <div v-else class="c-diary-list">
              <article v-for="item in diaries" :key="item.diary_id" class="c-diary-item">
                <time>{{ item.diary_date }}</time>
                <p>{{ item.content }}</p>
              </article>
            </div>
          </section>

          <section v-if="activeId === 'companion'" class="c-context-section">
            <header>
              <span>声音</span>
              <span class="c-context-link">{{ voiceReplyEnabled ? "朗读已开" : "默认关闭" }}</span>
            </header>
            <label class="c-voice-row">
              <input type="checkbox" :checked="voiceReplyEnabled" @change="toggleVoiceReply" />
              <span>朗读小鱼回复</span>
            </label>
            <label v-if="voiceOptions.length" class="c-voice-field">
              <span>音色</span>
              <select v-model="voiceURI">
                <option v-for="voice in voiceOptions" :key="voice.uri" :value="voice.uri">{{ voice.label }}</option>
              </select>
            </label>
            <label class="c-voice-field">
              <span>语速 {{ Number(voiceRate).toFixed(2) }}×</span>
              <input v-model.number="voiceRate" type="range" min="0.8" max="1.3" step="0.05" />
            </label>
            <button type="button" class="c-context-link" :disabled="!voiceSynthesisSupported" @click="previewVoice">
              试听
            </button>
            <p v-if="!voiceSynthesisSupported" class="c-memory-empty">当前浏览器不支持朗读。</p>
          </section>

          <section v-if="activeId === 'companion'" class="c-context-section">
            <header>
              <span>关系节奏</span>
              <span class="c-context-link">{{ rhythm.enabled ? "已开启" : "默认关闭" }}</span>
            </header>
            <label class="c-rhythm-row">
              <input
                type="checkbox"
                :checked="rhythm.enabled"
                :disabled="rhythmSaving"
                @change="setRhythmEnabled($event.target.checked)"
              />
              <span>允许小鱼偶尔主动问候</span>
            </label>
            <p class="c-memory-empty">
              仅站内消息，不免打扰 {{ rhythm.quiet_start }}–{{ rhythm.quiet_end }}；每天最多 1 条，每周最多 3 条。
            </p>
            <button
              type="button"
              class="c-context-link c-rhythm-pause"
              :disabled="rhythmSaving || !rhythm.enabled"
              @click="pauseRhythm"
            >暂停一周</button>
            <p v-if="rhythmError" class="c-inline-error" role="status">{{ rhythmError }}</p>
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
              <strong>
                {{ storeQuote.product_refs?.[0]?.title || "平台活动引用" }}
                <template v-if="quoteRefCount(storeQuote) > 1"> 等 {{ quoteRefCount(storeQuote) }} 件</template>
              </strong>
              <div class="c-quote-price">
                <span>¥{{ quotePayableTotal(storeQuote).toFixed(2) }}</span>
                <small>{{ primaryPolicy(storeQuote)?.title || "以结算页为准" }}</small>
              </div>
              <p>报价只做引用，成交前需在商城逐单确认。</p>
              <RouterLink
                :to="{
                  path: '/c',
                  query: {
                    quote: storeQuote.quote_id,
                    cart: storeQuote.cart_quote ? '1' : undefined,
                    friend_id: storeQuote.friend_id || activeId,
                    merchant_id: storeQuote.merchant_id,
                    merchant_name: storeQuote.merchant_name,
                  },
                }"
                class="c-text-link"
              >
                查看报价 <span>→</span>
              </RouterLink>
            </div>
            <p v-if="agentError" class="c-inline-error" role="alert">{{ agentError }}</p>
          </section>

          <section class="c-context-section">
            <header><span>最近订单</span><RouterLink to="/c/orders" class="c-context-link">全部</RouterLink></header>
            <p v-if="recentOrdersError" class="c-inline-error" role="status">{{ recentOrdersError }}</p>
            <p v-if="recentOrdersLoading && !recentOrders.length" class="c-order-hint" role="status">
              正在读取订单…
            </p>
            <p v-else-if="!recentOrders.length" class="c-order-hint">还没有订单</p>
            <div v-for="order in recentOrders" :key="order.order_id" class="c-order-row">
              <span
                class="c-order-mark"
                :title="order.merchant_order_id ? '商家订单' : '平台订单'"
              >{{ orderMark(order) }}</span>
              <span>
                <strong :title="order.merchant_order_id || order.order_id">{{ orderTitle(order) }}</strong>
                <small>
                  {{ orderDateLabel(order.confirmed_at || order.created_at) }} ·
                  {{ orderStatusLabel(order) }}
                </small>
                <small
                  v-if="orderLogisticsShort(order)"
                  class="c-order-logistics"
                  :title="orderLogisticsTitle(order)"
                >{{ orderLogisticsShort(order) }}</small>
              </span>
              <span class="c-order-amount">{{ orderAmountLabel(order) }}</span>
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
            <header><span>账号</span><span class="c-context-link">消费者</span></header>
            <button
              class="c-danger-link"
              type="button"
              :disabled="logoutBusy"
              @click="logoutC"
            >{{ logoutBusy ? "退出中…" : "退出登录" }}</button>
            <p v-if="logoutError" class="c-inline-error" role="alert">{{ logoutError }}</p>
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

          <p class="c-context-note">订单为实时数据 · 其余为界面参考</p>
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
        <div class="c-mobile-thread-actions">
          <button
            v-if="mentionUnread > 0"
            type="button"
            class="c-mention-notif"
            :disabled="mentionBusy"
            :aria-label="`${mentionUnread} 条未读 @ 提及`"
            title="未读 @：点击标记已读并打开会话"
            @click="openUnreadMentions"
          >@{{ mentionUnread }}</button>
          <button type="button" class="c-icon-btn" aria-label="新建会话" disabled>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
        </div>
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
              <strong>
                {{ thread.name }}<span v-if="thread.kind === 'group'" class="c-group-tag">群</span>
              </strong>
              <time>{{ thread.time }}</time>
            </span>
            <small v-if="thread.kind === 'group'">{{ threadMemberCount(thread) }} 人 · {{ thread.preview }}</small>
            <small v-else>{{ thread.preview }}</small>
          </span>
          <span v-if="unreadOf(thread.id)" class="c-unread">{{ unreadOf(thread.id) }}</span>
        </button>
      </div>
      <div class="c-mobile-account">
        <span>当前账号 · 消费者</span>
        <button type="button" class="c-danger-link" :disabled="logoutBusy" @click="logoutC">
          {{ logoutBusy ? "退出中…" : "退出登录" }}
        </button>
      </div>
      <p v-if="logoutError" class="c-inline-error c-mobile-account-error" role="alert">{{ logoutError }}</p>
    </div>

    <nav class="c-mobile-nav" aria-label="移动端导航">
      <RouterLink to="/c/home">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="m3 11 9-8 9 8" /><path d="M5 10v10h14V10" /><path d="M10 20v-6h4v6" /></svg>
        <span>首页</span>
      </RouterLink>
      <RouterLink to="/c/app" class="active">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 8.9 8.9 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
          <path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01" />
        </svg>
        <span>聊</span>
      </RouterLink>
      <RouterLink to="/c">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
          <path d="M3 6h18M16 10a4 4 0 0 1-8 0" />
        </svg>
        <span>逛</span>
      </RouterLink>
      <RouterLink to="/c/orders">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <path d="M6 2h12v20l-3-2-3 2-3-2-3 2z" />
          <path d="M9 7h6M9 11h6M9 15h4" />
        </svg>
        <span>订单</span>
      </RouterLink>
      <RouterLink to="/c/social">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
          <path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 9 9 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z" />
        </svg>
        <span>消息</span>
      </RouterLink>
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
.c-mobile-account {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 12px 16px calc(16px + env(safe-area-inset-bottom));
  padding: 12px 14px;
  border: 1px solid var(--c-line);
  border-radius: 14px;
  background: var(--c-panel);
  color: var(--c-text-2);
  font-size: 12px;
}

.c-mobile-account .c-danger-link {
  flex: none;
  margin: 0;
}

.c-mobile-account-error {
  margin: 0 16px 16px;
}

.c-app {
  -webkit-text-size-adjust: 100%;
  --c-bg: #f7f3ea;
  --c-bg-soft: #fffdf8;
  --c-panel: #fffdf8;
  --c-panel-2: #f1eadf;
  --c-panel-3: #e8dfd1;
  --c-line: #e4dccd;
  --c-line-soft: #eee6d8;
  --c-text: #1e1b16;
  --c-text-2: #6b6258;
  --c-text-3: #8a7f72;
  --c-accent: #d95f3b;
  --c-accent-soft: #f6e3da;
  --c-positive: #6f7f63;
  --c-warning: #b4492f;
  --c-negative: #a33f36;
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

/* 桌面三栏固定视口高度：中间对话区独立滚动，不再让整个页面无限变长 */
@media (min-width: 981px) {
  .c-app {
    height: 100dvh;
    overflow: hidden;
  }

  .c-shell {
    height: 100%;
    min-height: 0;
  }

  .c-sidebar,
  .c-context {
    height: 100%;
    min-height: 0;
    overflow-y: auto;
  }

  .c-main {
    height: 100%;
    min-height: 0;
    overflow: hidden;
  }

  .c-chat {
    height: 100%;
    min-height: 0;
  }
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
  background: var(--c-accent-soft, #f6e3da);
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

/* 群会话标识：低饱和胶囊，不打断会话列表节奏 */
.c-group-tag {
  display: inline-block;
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 3px;
  background: var(--c-bg-soft);
  color: var(--c-text-3);
  font-size: 8px;
  font-weight: 500;
  line-height: 14px;
  vertical-align: 1px;
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

.c-topbar-right :deep(.c-top-avatar) {
  border-color: color-mix(in srgb, var(--c-accent) 55%, var(--c-line));
  background: var(--c-panel);
  box-shadow: 0 0 0 4px var(--c-accent-soft);
}

.c-topbar-right :deep(.c-top-avatar:hover) {
  border-color: var(--c-accent);
  box-shadow: 0 0 0 5px var(--c-accent-soft);
}

.c-topbar-right :deep(.companion-avatar-fallback) {
  font-size: 14px;
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
  width: 44px;
  height: 44px;
  flex-basis: 44px;
  font-size: 13px;
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

/* @ 未读通知：低饱和描边胶囊，不抢对话视觉 */
.c-mention-notif {
  display: inline-flex;
  height: 22px;
  align-items: center;
  justify-content: center;
  padding: 0 8px;
  border: 1px solid color-mix(in srgb, var(--c-accent) 45%, var(--c-line));
  border-radius: 999px;
  background: transparent;
  color: var(--c-accent);
  font: inherit;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
}

.c-mention-notif:hover:not(:disabled) {
  border-color: var(--c-accent);
}

.c-mention-notif:disabled {
  opacity: 0.6;
  cursor: default;
}

.c-mobile-thread-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.c-thread {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 18px;
  overflow-y: scroll;
  scroll-behavior: auto;
  scrollbar-gutter: stable;
  padding: 20px 2px 12px;
  scrollbar-width: thin;
  scrollbar-color: var(--c-line-strong) var(--c-panel-2);
}

.c-thread::-webkit-scrollbar {
  width: 10px;
}

.c-thread::-webkit-scrollbar-track {
  border-radius: 999px;
  background: var(--c-panel-2);
}

.c-thread::-webkit-scrollbar-thumb {
  min-height: 42px;
  border: 2px solid var(--c-panel-2);
  border-radius: 999px;
  background: var(--c-line-strong);
}

.c-thread::-webkit-scrollbar-thumb:hover {
  background: var(--c-text-3);
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

.c-product-refs {
  display: flex;
  max-width: min(420px, 100%);
  flex-wrap: wrap;
  gap: 7px;
  padding: 2px 0;
}

.c-product-ref {
  display: flex;
  flex: 1 1 150px;
  max-width: 210px;
  align-items: center;
  gap: 7px;
  min-width: 0;
  padding: 5px;
  border: 1px solid var(--c-line);
  border-radius: 8px;
  background: var(--c-panel);
}

.c-product-ref img {
  flex: 0 0 42px;
  width: 42px;
  height: 42px;
  border-radius: 6px;
  object-fit: cover;
  background: var(--c-bg-soft);
}

.c-product-ref div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.c-product-ref strong {
  overflow: hidden;
  font-size: 10px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-product-ref small {
  overflow: hidden;
  color: var(--c-text-3);
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.c-prompt:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* 双宠谈判入口：低饱和强调色，和普通快捷问题区分但不抢视觉 */
.c-prompt.is-negotiate {
  border-color: color-mix(in srgb, var(--c-accent) 45%, var(--c-line));
  color: var(--c-accent);
}

.c-prompt.is-negotiate:hover:not(:disabled) {
  border-color: var(--c-accent);
  color: var(--c-text);
}

.c-negotiate-error {
  margin: 0;
  padding: 0 0 6px;
}

.c-negotiate-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(30, 27, 22, 0.28);
}

.c-negotiate-sheet {
  width: min(420px, 100%);
  margin: 0;
  padding: 18px;
  border: 1px solid var(--c-line);
  border-radius: 18px;
  background: var(--c-panel);
  box-shadow: 0 18px 50px rgba(30, 27, 22, 0.2);
}

.c-negotiate-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.c-negotiate-head strong {
  display: block;
  font-size: 16px;
  font-weight: 600;
}

.c-negotiate-head p {
  margin: 3px 0 0;
  color: var(--c-text-3);
  font-size: 11px;
}

.c-negotiate-close {
  flex: none;
  width: 28px;
  height: 28px;
  border: 1px solid var(--c-line);
  border-radius: 50%;
  background: transparent;
  color: var(--c-text-2);
  font: inherit;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}

.c-negotiate-merchant {
  margin: 14px 0 10px;
  padding: 7px 9px;
  border-radius: 9px;
  background: var(--c-panel-2);
  color: var(--c-text-2);
  font-size: 11px;
}

.c-negotiate-field {
  display: block;
  margin-top: 12px;
}

.c-negotiate-field > span {
  display: block;
  margin-bottom: 5px;
  color: var(--c-text-2);
  font-size: 11px;
}

.c-negotiate-field input {
  width: 100%;
  height: 42px;
  padding: 0 11px;
  border: 1px solid var(--c-line);
  border-radius: 10px;
  background: var(--c-bg-soft);
  color: var(--c-text);
  font: inherit;
  font-size: 16px;
  outline: none;
}

.c-negotiate-field input:focus {
  border-color: var(--c-accent);
}

.c-negotiate-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.c-negotiate-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
}

.c-negotiate-cancel,
.c-negotiate-submit {
  min-height: 40px;
  padding: 0 16px;
  border-radius: 10px;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.c-negotiate-cancel {
  border: 1px solid var(--c-line);
  background: transparent;
  color: var(--c-text-2);
}

.c-negotiate-submit {
  border: 1px solid var(--c-accent);
  background: var(--c-accent);
  color: #fffdf8;
}

.c-negotiate-submit:disabled {
  opacity: 0.6;
  cursor: default;
}

@media (max-width: 760px) {
  .c-negotiate-mask {
    place-items: end center;
    padding: 0;
  }

  .c-negotiate-sheet {
    width: 100%;
    padding: 18px 16px calc(18px + env(safe-area-inset-bottom));
    border-radius: 18px 18px 0 0;
  }
}

/* 群内点击 @ 的轻提示：只做一次短暂反馈，不占聊天空间 */
.c-group-mention-hint {
  margin: 0;
  padding: 0 0 6px;
  color: var(--c-text-3);
  font-size: 10px;
  line-height: 1.5;
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
  caret-color: var(--c-text);
  font: inherit;
  font-size: 16px;
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

.c-memory-clear {
  border: 0;
  padding: 0;
  background: none;
  cursor: pointer;
}

.c-memory-empty {
  margin: 0;
  color: var(--c-text-3);
  font-size: 10px;
  line-height: 1.7;
}

.c-memory-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.c-memory-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 8px;
  border: 1px solid var(--c-line-soft);
  border-radius: 8px;
  background: var(--c-bg-soft);
  color: var(--c-text-2);
  font-size: 10px;
}

.c-memory-kind {
  flex: none;
  color: var(--c-text-3);
  font-size: 9px;
}

.c-memory-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-memory-remove {
  flex: none;
  border: 0;
  padding: 0;
  background: none;
  color: var(--c-text-3);
  font-size: 9px;
  cursor: pointer;
}

.c-memory-remove:hover,
.c-memory-clear:hover {
  color: var(--c-text);
}

.c-diary-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--c-text-3);
  font-size: 9px;
  cursor: pointer;
}

.c-diary-toggle input {
  width: 12px;
  height: 12px;
  accent-color: var(--c-text);
}

.c-diary-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.c-diary-item {
  padding: 8px 9px;
  border: 1px solid var(--c-line-soft);
  border-radius: 8px;
  background: var(--c-bg-soft);
}

.c-diary-item time {
  color: var(--c-text-3);
  font-size: 9px;
}

.c-diary-item p {
  margin: 5px 0 0;
  color: var(--c-text-2);
  font-size: 10px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.c-rhythm-row {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--c-text-2);
  font-size: 10px;
  cursor: pointer;
}

.c-rhythm-row input {
  width: 14px;
  height: 14px;
  accent-color: var(--c-text);
}

.c-rhythm-pause {
  align-self: flex-start;
  border: 0;
  padding: 0;
  background: none;
  cursor: pointer;
}

.c-rhythm-pause:disabled {
  cursor: default;
  opacity: 0.45;
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
  overflow: hidden;
  color: var(--c-text-3);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 物流行：承运商 + 单号后 4 位，完整单号放 title；继承 small 的省略号 */
.c-order-row .c-order-logistics {
  color: var(--c-accent);
}

.c-order-hint {
  margin: 0;
  padding: 7px 0;
  color: var(--c-text-3);
  font-size: 9px;
  line-height: 1.5;
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
    font-size: 16px;
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
    color: var(--c-accent);
    font-weight: 700;
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
    top: calc(8px + env(safe-area-inset-top));
    right: 12px;
    bottom: auto;
    left: 12px;
    max-width: none;
    z-index: 80;
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

.c-app .c-composer {
  position: relative;
}

.c-app .c-mention-btn {
  width: 24px;
  min-width: 24px;
  padding: 0;
  font-size: 13px;
  font-weight: 500;
}

.c-app .c-mention-pop {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  right: 0;
  z-index: 8;
  display: grid;
  gap: 2px;
  padding: 5px;
  border: 1px solid var(--c-line);
  border-radius: 10px;
  background: var(--c-panel);
  box-shadow: 0 8px 24px rgba(20, 20, 18, 0.08);
}

.c-app .c-mention-option {
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  padding: 7px 8px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--c-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.c-app .c-mention-option.active,
.c-app .c-mention-option:hover {
  background: var(--c-panel-2);
}

.c-app .c-mention-option strong {
  font-size: 10px;
  font-weight: 500;
}

.c-app .c-mention-option small {
  overflow: hidden;
  color: var(--c-text-3);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.c-app .c-mention-token {
  color: var(--c-accent);
  font-weight: 500;
}

/* 可点击的 @ 文本：保留既有高亮，只补交互态 */
.c-app .c-mention-token[role="button"] {
  border-radius: 3px;
  cursor: pointer;
}

.c-app .c-mention-token[role="button"]:hover,
.c-app .c-mention-token[role="button"]:focus-visible {
  background: color-mix(in srgb, var(--c-accent) 12%, transparent);
  outline: none;
}

.c-app .c-message.user .c-bubble .c-mention-token {
  color: var(--c-bg);
  text-decoration: underline;
  text-underline-offset: 2px;
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
  font-size: 16px;
  caret-color: var(--c-text);
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
    position: fixed;
    top: 0;
    right: 0;
    bottom: auto;
    left: 0;
    height: var(--c-vh, 100dvh);
    min-height: 0;
    overflow: hidden;
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



/* ---------- 小鱼互动菜单 ---------- */
.c-chat-head {
  position: relative;
}

.c-avatar-menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: transparent;
}

.c-avatar-menu {
  position: absolute;
  z-index: 41;
  top: 56px;
  left: 58px;
  min-width: 108px;
  padding: 5px;
  border: 1px solid var(--c-line);
  border-radius: 12px;
  background: var(--c-panel);
  box-shadow: 0 12px 28px rgba(30, 27, 22, 0.14);
}

.c-avatar-menu button {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--c-text-2);
  font: inherit;
  font-size: 11px;
  text-align: left;
  cursor: pointer;
}

.c-avatar-menu button:hover {
  background: var(--c-accent-soft, #f6e3da);
  color: var(--c-text);
}

.c-avatar-tip {
  position: absolute;
  z-index: 42;
  top: 56px;
  left: 108px;
  max-width: 140px;
  padding: 6px 9px;
  border: 1px solid var(--c-line);
  border-radius: 10px 10px 10px 2px;
  background: var(--c-bg-soft);
  color: var(--c-text-2);
  font-size: 10px;
  white-space: nowrap;
  pointer-events: none;
}


/* ---------- 语音输入 / 朗读 ---------- */
.c-voice-toggle.is-active {
  border-color: var(--c-accent);
  background: var(--c-accent-soft);
  color: var(--c-accent);
}

.c-voice-btn.is-recording {
  border-color: var(--c-accent);
  background: var(--c-accent-soft);
  color: var(--c-accent);
  animation: c-voice-pulse 1.1s ease-in-out infinite;
}

@keyframes c-voice-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(217, 95, 59, 0.18); }
  50% { box-shadow: 0 0 0 5px rgba(217, 95, 59, 0.04); }
}


.c-voice-row,
.c-voice-field {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--c-text-2);
  font-size: 10px;
}

.c-voice-row input {
  width: 13px;
  height: 13px;
  accent-color: var(--c-accent);
}

.c-voice-field {
  justify-content: space-between;
}

.c-voice-field select {
  min-width: 0;
  max-width: 150px;
  padding: 4px 6px;
  border: 1px solid var(--c-line);
  border-radius: 7px;
  background: var(--c-bg-soft);
  color: var(--c-text-2);
  font: inherit;
  font-size: 10px;
}

.c-voice-field input[type="range"] {
  width: 110px;
  accent-color: var(--c-accent);
}

.c-negotiate-hint {
  margin: 0 0 10px;
  padding: 7px 9px;
  border-radius: 7px;
  background: var(--bg-soft, #f7f3ea);
  color: var(--text-2, #6b6258);
  font-size: 11px;
}

.c-negotiate-field select {
  width: 100%;
  min-height: 38px;
  padding: 0 9px;
  border: 1px solid var(--border, #e4dccd);
  border-radius: 8px;
  background: var(--surface, #fffdf8);
  color: inherit;
  font: inherit;
  font-size: 13px;
}


.c-negotiate-products {
  margin: 0 0 12px;
}

.c-negotiate-products-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  color: var(--text-2, #6b6258);
  font-size: 11px;
}

.c-negotiate-products-head small {
  color: var(--muted, #948b7e);
  font-size: 9px;
}

.c-product-search {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  padding: 0 9px;
  border: 1px solid var(--border, #e4dccd);
  border-radius: 8px;
  background: var(--surface, #fffdf8);
}

.c-product-search span {
  color: var(--muted, #948b7e);
  font-size: 16px;
}

.c-product-search input {
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 12px;
}

.c-product-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  max-height: 238px;
  margin-top: 8px;
  overflow-y: auto;
  padding-right: 2px;
}

.c-product-card {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  padding: 6px;
  border: 1px solid var(--border, #e4dccd);
  border-radius: 9px;
  background: var(--surface, #fffdf8);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.c-product-card.active {
  border-color: var(--primary, #a8623f);
  background: var(--primary-soft, #f6e3da);
}

.c-product-thumb {
  position: relative;
  flex: 0 0 42px;
  width: 42px;
  height: 42px;
  overflow: hidden;
  border-radius: 7px;
  background: linear-gradient(145deg, #e6ecdb, #d7e2c9);
}

.c-product-thumb img {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.c-product-placeholder {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #7d8b6b;
  font-size: 14px;
  font-weight: 700;
}

.c-product-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 2px;
}

.c-product-info strong {
  overflow: hidden;
  font-size: 11px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-product-info small,
.c-product-info em {
  overflow: hidden;
  color: var(--muted, #948b7e);
  font-size: 9px;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-product-card.active .c-product-info small {
  color: #9d4c31;
}


.c-cart-add-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0 12px;
  min-height: 22px;
}

.c-cart-add {
  flex: 0 0 auto;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid var(--border, #e4dccd);
  border-radius: 7px;
  background: transparent;
  color: var(--text-2, #6b6258);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.c-cart-add-row > span {
  color: var(--muted, #948b7e);
  font-size: 9px;
}

.c-cart-panel {
  margin: 0 0 13px;
  padding: 8px;
  border: 1px solid var(--border, #e4dccd);
  border-radius: 9px;
  background: var(--bg-soft, #f7f3ea);
}

.c-cart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  color: var(--text-2, #6b6258);
  font-size: 10px;
}

.c-cart-head button {
  border: 0;
  background: transparent;
  color: var(--muted, #948b7e);
  font: inherit;
  font-size: 9px;
  cursor: pointer;
}

.c-cart-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.c-cart-item {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.c-cart-thumb {
  position: relative;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  overflow: hidden;
  border-radius: 5px;
  background: #e6ecdb;
}

.c-cart-thumb img {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.c-cart-thumb > span {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #7d8b6b;
  font-size: 10px;
  font-weight: 700;
}

.c-cart-info {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  gap: 1px;
}

.c-cart-info strong {
  overflow: hidden;
  font-size: 10px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-cart-info small {
  overflow: hidden;
  color: var(--muted, #948b7e);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-cart-remove {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--muted, #948b7e);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}

.c-cart-merge {
  width: 100%;
  min-height: 32px;
  margin-top: 7px;
  border: 1px solid var(--primary, #a8623f);
  border-radius: 7px;
  background: var(--primary-soft, #f6e3da);
  color: #9d4c31;
  font: inherit;
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
}

.c-cart-merge:disabled {
  cursor: wait;
  opacity: 0.6;
}


/* ---------- P2.6 全局购物车抽屉 ---------- */
.c-cart-trigger {
  position: relative;
}

.c-cart-trigger-badge {
  position: absolute;
  top: -3px;
  right: -3px;
  display: grid;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  place-items: center;
  border-radius: 999px;
  background: var(--c-accent, #a8623f);
  color: #fff;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 8px;
  font-weight: 700;
  line-height: 1;
}

.c-cart-drawer-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  justify-content: flex-end;
  background: rgba(41, 37, 31, 0.34);
  backdrop-filter: blur(2px);
}

.c-cart-drawer {
  display: flex;
  width: min(420px, 94vw);
  height: 100%;
  flex-direction: column;
  padding: 16px;
  background: var(--c-bg, #fbf8f1);
  box-shadow: -12px 0 40px rgba(50, 44, 35, 0.16);
}

.c-cart-drawer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--c-line-soft, #ece4d8);
}

.c-cart-drawer-head strong {
  display: block;
  font-size: 15px;
}

.c-cart-drawer-head small {
  display: block;
  margin-top: 3px;
  color: var(--c-text-3, #948b7e);
  font-size: 10px;
}

.c-cart-drawer-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 6px;
  color: var(--c-text-3, #948b7e);
  text-align: center;
}

.c-cart-drawer-empty strong {
  color: var(--c-text-2, #6b6258);
  font-size: 13px;
}

.c-cart-drawer-empty p {
  margin: 0;
  font-size: 10px;
}

.c-cart-drawer-list {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  padding: 10px 0;
}

.c-cart-drawer-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--c-line-soft, #ece4d8);
  border-radius: 9px;
  background: var(--c-panel, #fffdf8);
}

.c-cart-drawer-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.c-cart-drawer-copy strong {
  overflow: hidden;
  font-size: 11px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-cart-drawer-copy small {
  overflow: hidden;
  color: var(--c-text-3, #948b7e);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.c-cart-drawer-copy > span {
  color: #9d4c31;
  font-size: 10px;
  font-weight: 600;
}

.c-cart-drawer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--c-line-soft, #ece4d8);
}

.c-cart-drawer-foot > div {
  display: flex;
  align-items: baseline;
  gap: 6px;
  color: var(--c-text-3, #948b7e);
  font-size: 10px;
}

.c-cart-drawer-foot strong {
  color: #9d4c31;
  font-size: 16px;
}

.c-cart-checkout {
  min-height: 36px;
  padding: 0 14px;
  border: 0;
  border-radius: 8px;
  background: var(--c-accent, #a8623f);
  color: #fff;
  font: inherit;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.c-cart-qty {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 2px;
}

.c-cart-qty button {
  width: 20px;
  height: 20px;
  border: 1px solid var(--c-line-soft, #ece4d8);
  border-radius: 5px;
  background: transparent;
  color: var(--c-text-2, #6b6258);
  font: inherit;
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
}

.c-cart-qty button:disabled {
  cursor: default;
  opacity: 0.35;
}

.c-cart-qty strong {
  min-width: 15px;
  color: var(--c-text-2, #6b6258);
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 9px;
  text-align: center;
}

@media (max-width: 760px) {
  .c-cart-drawer {
    width: 100%;
    padding: 14px;
  }
}


.c-cart-edit {
  flex: 0 0 auto;
  padding: 2px 5px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--c-text-3, #948b7e);
  font: inherit;
  font-size: 8px;
  cursor: pointer;
}

.c-cart-edit:hover {
  background: var(--c-accent-soft, #f6e3da);
  color: #9d4c31;
}

.c-cart-editor-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(41, 37, 31, 0.4);
  backdrop-filter: blur(2px);
}

.c-cart-editor {
  width: min(360px, 92vw);
  padding: 16px;
  border: 1px solid var(--c-line-soft, #ece4d8);
  border-radius: 12px;
  background: var(--c-bg, #fbf8f1);
  box-shadow: 0 18px 50px rgba(50, 44, 35, 0.22);
}

.c-cart-editor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.c-cart-editor-head strong {
  display: block;
  font-size: 14px;
}

.c-cart-editor-head small {
  display: block;
  margin-top: 3px;
  color: var(--c-text-3, #948b7e);
  font-size: 10px;
}

.c-cart-editor-hint {
  margin: 0;
  color: var(--c-text-3, #948b7e);
  font-size: 11px;
}

.c-cart-editor-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 12px;
  color: var(--c-text-2, #6b6258);
  font-size: 10px;
}

.c-cart-editor-field select {
  width: 100%;
  min-height: 36px;
  padding: 0 8px;
  border: 1px solid var(--c-line-soft, #ece4d8);
  border-radius: 8px;
  background: var(--c-panel, #fffdf8);
  color: inherit;
  font: inherit;
  font-size: 11px;
}

.c-cart-editor-row {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--c-text-2, #6b6258);
  font-size: 10px;
}

.c-cart-editor-row small {
  color: var(--c-text-3, #948b7e);
  font-size: 9px;
}

.c-cart-editor-sum {
  margin: 12px 0;
  padding: 8px 9px;
  border-radius: 7px;
  background: var(--c-bg-soft, #f7f3ea);
  color: var(--c-text-2, #6b6258);
  font-size: 10px;
}

.c-cart-editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.c-cart-editor-cancel,
.c-cart-editor-save {
  min-height: 34px;
  padding: 0 12px;
  border-radius: 7px;
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

.c-cart-editor-cancel {
  border: 1px solid var(--c-line-soft, #ece4d8);
  background: transparent;
  color: var(--c-text-2, #6b6258);
}

.c-cart-editor-save {
  border: 1px solid var(--c-accent, #a8623f);
  background: var(--c-accent, #a8623f);
  color: #fff;
  font-weight: 600;
}

</style>


