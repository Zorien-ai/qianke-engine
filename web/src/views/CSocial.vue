<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { del, getJson, patchJson, postJson } from "../api";
import { toast } from "../store";

const router = useRouter();

const section = ref("conversations"); // conversations | contacts
const loading = ref(true);
const refreshing = ref(false);
const error = ref("");
const search = ref("");
const friends = ref([]);
const groups = ref([]);
const requests = ref([]);
const notices = ref([]);
const prefs = ref({});
const unread = ref({});
const lastMessages = ref({});
const showHidden = ref(false);
const contactFilter = ref("all");
const suggestions = ref([]);
const suggestionBusy = ref("");
const suggestionError = ref("");
const ignoredSuggestions = ref(loadIgnoredSuggestions());
const requestsOpen = ref(false);
const noticesOpen = ref(false);
const actionItem = ref(null);
const actionType = ref("conversation");

const active = ref(null);
const messages = ref([]);
const messagesLoading = ref(false);
const chatError = ref("");
const draft = ref("");
const sending = ref(false);
const socketState = ref("offline");
let socket = null;
let unreadTimer = null;

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "friend", label: "好友" },
  { key: "merchant", label: "店宠" },
  { key: "group", label: "群聊" },
];

function loadIgnoredSuggestions() {
  try {
    const parsed = JSON.parse(localStorage.getItem("qianke:c:ignoredSuggestions") || "[]");
    return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
  } catch {
    return new Set();
  }
}

function persistIgnoredSuggestions() {
  try {
    localStorage.setItem("qianke:c:ignoredSuggestions", JSON.stringify([...ignoredSuggestions.value]));
  } catch {
    // 本机存储不可用时仍保留当前会话状态
  }
}

function friendKindLabel(kind) {
  if (kind === "merchant") return "店宠";
  if (kind === "group") return "群聊";
  return "好友";
}

function initial(name) {
  return String(name || "?").trim().slice(0, 1).toUpperCase() || "?";
}

function preview(content) {
  const text = String(content || "").replace(/\s+/g, " ").trim();
  return text.length > 26 ? `${text.slice(0, 26)}…` : text;
}

function prefOf(threadId) {
  return prefs.value[threadId] || { pinned: false, muted: false, hidden: false };
}

function unreadOf(threadId) {
  return Number(unread.value[threadId] || 0);
}

function itemTime(item) {
  return item.last?.created_at || item.created_at || "";
}

function lastPreview(item) {
  if (!item.last) return item.note || "开始聊天";
  if (item.last.metadata?.quote_id) return "[结构化报价]";
  return preview(item.last.content);
}

const hiddenThreads = computed(
  () =>
    friends.value.filter((friend) => prefOf(friend.friend_id).hidden).length +
    groups.value.filter((group) => prefOf(group.group_id).hidden).length
);

const conversations = computed(() => {
  const items = [
    {
      threadId: "companion",
      type: "companion",
      name: "小鱼",
      note: "C 伙伴 · 只做建议，成交需你确认",
      last: lastMessages.value.companion || null,
      created_at: "",
    },
    ...friends.value.map((friend) => ({
      threadId: friend.friend_id,
      type: "friend",
      kind: friend.kind,
      name: friend.name,
      note: friend.note || "",
      friend,
      last: lastMessages.value[friend.friend_id] || null,
      created_at: friend.created_at || "",
    })),
    ...groups.value.map((group) => ({
      threadId: group.group_id,
      type: "group",
      kind: "group",
      name: group.name,
      note: `${group.members?.length || 0} 位成员`,
      group,
      last: lastMessages.value[group.group_id] || null,
      created_at: group.created_at || "",
    })),
  ];
  const keyword = search.value.trim().toLowerCase();
  return items
    .filter((item) => (showHidden.value ? true : !prefOf(item.threadId).hidden))
    .filter((item) => !keyword || `${item.name} ${item.note}`.toLowerCase().includes(keyword))
    .sort((a, b) => {
      const pinnedA = prefOf(a.threadId).pinned ? 1 : 0;
      const pinnedB = prefOf(b.threadId).pinned ? 1 : 0;
      if (pinnedA !== pinnedB) return pinnedB - pinnedA;
      return String(itemTime(b)).localeCompare(String(itemTime(a)));
    });
});

const pendingRequests = computed(() => requests.value.filter((item) => item.status === "PENDING"));
const unreadNotices = computed(() => notices.value.filter((item) => item.status === "UNREAD"));

const contactLists = computed(() => {
  const keyword = search.value.trim().toLowerCase();
  const match = (value) => !keyword || String(value || "").toLowerCase().includes(keyword);
  return {
    friends: friends.value.filter((friend) => friend.kind !== "merchant" && match(`${friend.name} ${friend.note}`)),
    merchants: friends.value.filter((friend) => friend.kind === "merchant" && match(`${friend.name} ${friend.note}`)),
    groups: groups.value.filter((group) => match(`${group.name} ${group.members?.length || 0}`)),
  };
});

const visibleSuggestions = computed(() =>
  suggestions.value.filter(
    (item) =>
      !item.is_friend &&
      !ignoredSuggestions.value.has(String(item.merchant_id)) &&
      (!search.value.trim() || `${item.name} ${item.note}`.toLowerCase().includes(search.value.trim().toLowerCase()))
  )
);

const contactCount = computed(
  () => contactLists.value.friends.length + contactLists.value.merchants.length + contactLists.value.groups.length
);

async function loadPage() {
  loading.value = true;
  error.value = "";
  try {
    const [friendData, groupData, unreadData, prefData, requestData, noticeData] = await Promise.all([
      getJson("/api/c/friends"),
      getJson("/api/c/groups").catch(() => ({ groups: [] })),
      getJson("/api/c/threads/unread").catch(() => ({ threads: {} })),
      getJson("/api/c/conversation-prefs").catch(() => ({ prefs: [] })),
      getJson("/api/c/friend-requests?status=PENDING").catch(() => ({ requests: [] })),
      getJson("/api/c/group-notices").catch(() => ({ notices: [] })),
    ]);
    friends.value = Array.isArray(friendData?.friends) ? friendData.friends : [];
    groups.value = Array.isArray(groupData?.groups) ? groupData.groups : [];
    unread.value = unreadData?.threads && typeof unreadData.threads === "object" ? unreadData.threads : {};
    prefs.value = Object.fromEntries(
      (Array.isArray(prefData?.prefs) ? prefData.prefs : []).map((item) => [item.thread_id, item])
    );
    requests.value = Array.isArray(requestData?.requests) ? requestData.requests : [];
    notices.value = Array.isArray(noticeData?.notices) ? noticeData.notices : [];
    await loadLastMessages();
    await loadSuggestions();
  } catch (err) {
    error.value = err?.detail || err?.message || "联系人加载失败，请稍后重试";
  } finally {
    loading.value = false;
  }
}

async function refreshData() {
  if (refreshing.value) return;
  refreshing.value = true;
  await loadPage();
  refreshing.value = false;
}

async function loadLastMessages() {
  const tasks = [];
  for (const friend of friends.value) {
    tasks.push(
      getJson(`/api/c/friends/${encodeURIComponent(friend.friend_id)}/messages?limit=1`)
        .then((data) => {
          lastMessages.value = { ...lastMessages.value, [friend.friend_id]: data?.messages?.[0] || null };
        })
        .catch(() => {})
    );
  }
  for (const group of groups.value) {
    tasks.push(
      getJson(`/api/c/groups/${encodeURIComponent(group.group_id)}/messages?limit=1`)
        .then((data) => {
          lastMessages.value = { ...lastMessages.value, [group.group_id]: data?.messages?.[0] || null };
        })
        .catch(() => {})
    );
  }
  tasks.push(
    getJson("/api/c/app/messages?thread_id=companion&limit=1")
      .then((data) => {
        lastMessages.value = { ...lastMessages.value, companion: data?.messages?.[0] || null };
      })
      .catch(() => {})
  );
  await Promise.allSettled(tasks);
}

async function loadSuggestions() {
  suggestionError.value = "";
  try {
    const data = await getJson("/api/c/merchants/available");
    suggestions.value = Array.isArray(data?.merchants) ? data.merchants : [];
  } catch (err) {
    suggestions.value = [];
    suggestionError.value = err?.detail || err?.message || "推荐加载失败";
  }
}

async function addSuggestion(merchant) {
  if (!merchant || suggestionBusy.value) return;
  suggestionBusy.value = String(merchant.merchant_id);
  try {
    await postJson("/api/c/friends/merchants", { merchant_id: merchant.merchant_id });
    suggestions.value = suggestions.value.filter((item) => item.merchant_id !== merchant.merchant_id);
    await refreshData();
    toast(`已添加 ${merchant.name}`, "success");
  } catch (err) {
    toast(err?.detail || err?.message || "添加失败，请稍后重试", "error");
  } finally {
    suggestionBusy.value = "";
  }
}

function ignoreSuggestion(merchant) {
  ignoredSuggestions.value = new Set([...ignoredSuggestions.value, String(merchant.merchant_id)]);
  persistIgnoredSuggestions();
  toast("已忽略这个推荐", "success");
}

async function acceptRequest(request) {
  try {
    await postJson(`/api/c/friend-requests/${encodeURIComponent(request.request_id)}/accept`, {});
    requests.value = requests.value.filter((item) => item.request_id !== request.request_id);
    await refreshData();
    toast(`已添加 ${request.requester_name}`, "success");
  } catch (err) {
    toast(err?.detail || err?.message || "接受好友申请失败", "error");
  }
}

async function rejectRequest(request) {
  try {
    await postJson(`/api/c/friend-requests/${encodeURIComponent(request.request_id)}/reject`, {});
    requests.value = requests.value.filter((item) => item.request_id !== request.request_id);
    toast("已拒绝好友申请", "success");
  } catch (err) {
    toast(err?.detail || err?.message || "拒绝好友申请失败", "error");
  }
}

async function markNoticeRead(notice) {
  if (!notice || notice.status === "READ") return;
  try {
    const data = await postJson(`/api/c/group-notices/${encodeURIComponent(notice.notice_id)}/read`, {});
    notices.value = notices.value.map((item) =>
      item.notice_id === notice.notice_id ? { ...item, ...(data || {}), status: "READ" } : item
    );
  } catch (err) {
    toast(err?.detail || err?.message || "标记群通知失败", "error");
  }
}

async function markAllNoticesRead() {
  const unreadItems = notices.value.filter((item) => item.status === "UNREAD");
  for (const item of unreadItems) {
    await markNoticeRead(item);
  }
  toast("群通知已标记为已读", "success");
}

async function updatePref(threadId, patch, successText) {
  try {
    const data = await patchJson(`/api/c/conversation-prefs/${encodeURIComponent(threadId)}`, patch);
    prefs.value = { ...prefs.value, [threadId]: data };
    toast(successText, "success");
  } catch (err) {
    toast(err?.detail || err?.message || "会话设置保存失败", "error");
  }
}

async function markThreadRead(threadId) {
  if (!threadId) return;
  unread.value = { ...unread.value, [threadId]: 0 };
  try {
    await postJson(`/api/c/threads/${encodeURIComponent(threadId)}/read`, {});
  } catch {
    // 下一次进入会话或刷新时会校正
  }
}

function openConversation(item) {
  if (item.type === "companion") {
    router.push("/c/app");
    return;
  }
  actionItem.value = null;
  active.value = item;
  chatError.value = "";
  draft.value = "";
  messages.value = [];
  section.value = "conversations";
  markThreadRead(item.threadId);
  loadMessages(item);
  if (item.type === "friend") connectSocket(item.threadId);
  else closeSocket();
}

async function loadMessages(item) {
  messagesLoading.value = true;
  try {
    const endpoint =
      item.type === "group"
        ? `/api/c/groups/${encodeURIComponent(item.threadId)}/messages?limit=50`
        : `/api/c/friends/${encodeURIComponent(item.threadId)}/messages?limit=50`;
    const data = await getJson(endpoint);
    messages.value = Array.isArray(data?.messages) ? data.messages : [];
    scrollToBottom();
  } catch (err) {
    chatError.value = err?.detail || err?.message || "消息加载失败";
  } finally {
    messagesLoading.value = false;
  }
}

function closeChat() {
  active.value = null;
  messages.value = [];
  draft.value = "";
  chatError.value = "";
  closeSocket();
  refreshData();
}

function connectSocket(friendId) {
  closeSocket();
  try {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${window.location.host}/api/c/ws/chat/${encodeURIComponent(friendId)}`);
  } catch {
    socketState.value = "fallback";
    return;
  }
  socketState.value = "connecting";
  socket.onopen = () => {
    socketState.value = "online";
  };
  socket.onmessage = (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    if (payload.type === "chat") {
      for (const message of [payload.message, payload.reply, payload.companion_message]) {
        if (message && !messages.value.some((item) => item.message_id === message.message_id)) {
          messages.value.push(message);
        }
      }
      scrollToBottom();
    } else if (payload.type === "error") {
      chatError.value = payload.error?.message || "消息发送失败";
    }
  };
  socket.onerror = () => {
    socketState.value = "fallback";
  };
  socket.onclose = () => {
    if (socketState.value === "online") socketState.value = "fallback";
  };
}

function closeSocket() {
  if (socket) {
    socket.onclose = null;
    socket.close();
    socket = null;
  }
  socketState.value = "offline";
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    const el = document.getElementById("social-chat-scroll");
    if (el) el.scrollTop = el.scrollHeight;
  });
}

async function send() {
  const content = draft.value.trim();
  if (!content || !active.value || sending.value) return;
  sending.value = true;
  chatError.value = "";
  draft.value = "";
  try {
    if (active.value.type === "friend") {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ content }));
      } else {
        const data = await postJson(`/api/c/friends/${encodeURIComponent(active.value.threadId)}/messages`, {
          content,
        });
        for (const message of [data?.message, data?.reply, data?.companion_message]) {
          if (message) messages.value.push(message);
        }
        scrollToBottom();
      }
    } else {
      const data = await postJson(`/api/c/groups/${encodeURIComponent(active.value.threadId)}/messages`, {
        content,
      });
      if (data?.message) messages.value.push(data.message);
      for (const reply of data?.replies || []) messages.value.push(reply);
      scrollToBottom();
    }
  } catch (err) {
    chatError.value = err?.detail || err?.message || "消息发送失败";
    draft.value = content;
  } finally {
    sending.value = false;
  }
}

function onKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send();
  }
}

function openConversationMenu(item) {
  actionItem.value = item;
  actionType.value = "conversation";
}

function openContactMenu(friend) {
  actionItem.value = {
    threadId: friend.friend_id,
    type: "friend",
    kind: friend.kind,
    name: friend.name,
    note: friend.note,
    friend,
  };
  actionType.value = "contact";
}

async function removeFriend(friend) {
  if (!friend || !window.confirm(`删除好友「${friend.name}」？历史消息会保留。`)) return;
  try {
    await del(`/api/c/friends/${encodeURIComponent(friend.friend_id)}`);
    actionItem.value = null;
    await refreshData();
    toast("好友已删除", "success");
  } catch (err) {
    toast(err?.detail || err?.message || "删除好友失败", "error");
  }
}

function closeActionMenu() {
  actionItem.value = null;
}

function formatTime(value) {
  return String(value || "").replace("T", " ").slice(5, 16);
}

function senderName(message) {
  if (active.value?.type === "group") return message.sender_name || "群成员";
  if (String(message.sender_id || "").startsWith("buyer_")) return "我";
  return active.value?.name || "对方";
}

function isOwn(message) {
  return String(message.sender_id || "").startsWith("buyer_");
}

onMounted(async () => {
  await loadPage();
  unreadTimer = window.setInterval(() => {
    if (document.visibilityState !== "hidden" && !active.value) {
      getJson("/api/c/threads/unread")
        .then((data) => {
          if (data?.threads) unread.value = data.threads;
        })
        .catch(() => {});
    }
  }, 20000);
});

onBeforeUnmount(() => {
  closeSocket();
  if (unreadTimer) window.clearInterval(unreadTimer);
});
</script>

<template>
  <div class="social-qq" :class="{ 'is-chat': !!active }">
    <header class="social-qq-head">
      <div class="social-qq-heading">
        <button
          v-if="active"
          type="button"
          class="social-qq-back"
          aria-label="返回消息列表"
          @click="closeChat"
        >‹</button>
        <div>
          <p class="social-qq-kicker">{{ active ? "CHAT" : section === "contacts" ? "CONTACTS" : "MESSAGES" }}</p>
          <h2>{{ active ? active.name : section === "contacts" ? "联系人" : "消息" }}</h2>
        </div>
      </div>
      <button
        v-if="!active"
        type="button"
        class="social-qq-add"
        aria-label="添加好友"
        @click="section = 'contacts'; contactFilter = 'all'"
      >＋</button>
      <button v-else type="button" class="social-qq-more" aria-label="会话设置" @click="openConversationMenu(active)">⋯</button>
    </header>

    <div v-if="!active" class="social-qq-search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.2-3.2" />
      </svg>
      <input id="social-search-input" name="search" v-model="search" type="search" :placeholder="section === 'contacts' ? '搜索联系人或群聊' : '搜索会话'" aria-label="搜索" />
    </div>

    <div v-if="!active" class="social-qq-segment" role="tablist" aria-label="消息或联系人">
      <button
        type="button"
        role="tab"
        :aria-selected="section === 'conversations'"
        :class="{ active: section === 'conversations' }"
        @click="section = 'conversations'"
      >
        消息
        <span v-if="pendingRequests.length + unreadNotices.length" class="social-qq-badge">{{ pendingRequests.length + unreadNotices.length }}</span>
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="section === 'contacts'"
        :class="{ active: section === 'contacts' }"
        @click="section = 'contacts'"
      >
        联系人
        <span class="social-qq-count">{{ contactCount }}</span>
      </button>
    </div>

    <main v-if="!active" class="social-qq-body">
      <p v-if="loading" class="social-qq-state" role="status">正在加载…</p>
      <div v-else-if="error" class="social-qq-state is-error" role="alert">
        <strong>联系人暂时不可用</strong>
        <p>{{ error }}</p>
        <button type="button" @click="loadPage">重新加载</button>
      </div>

      <template v-else-if="section === 'conversations'">
        <div class="social-qq-subhead">
          <span>最近会话</span>
          <span class="social-qq-actions">
            <button v-if="hiddenThreads" type="button" class="social-qq-link" @click="showHidden = !showHidden">
              {{ showHidden ? "收起隐藏" : `显示隐藏 (${hiddenThreads})` }}
            </button>
            <button type="button" class="social-qq-link" :disabled="refreshing" @click="refreshData">
              {{ refreshing ? "刷新中…" : "刷新" }}
            </button>
          </span>
        </div>

        <div v-if="!conversations.length" class="social-qq-empty">
          <strong>还没有会话</strong>
          <p>{{ search ? "没有匹配的会话。" : "去联系人里找小鱼、好友或店宠聊两句。" }}</p>
          <button type="button" class="social-qq-primary" @click="section = 'contacts'">去联系人</button>
        </div>

        <button
          v-for="item in conversations"
          :key="item.threadId"
          type="button"
          class="social-conv-row"
          :class="{ pinned: prefOf(item.threadId).pinned }"
          @click="openConversation(item)"
          @contextmenu.prevent="openConversationMenu(item)"
        >
          <span class="social-avatar" :class="`is-${item.type}`">{{ initial(item.name) }}</span>
          <span class="social-conv-copy">
            <span class="social-conv-top">
              <strong>{{ item.name }}</strong>
              <small>{{ formatTime(item.last?.created_at) }}</small>
            </span>
            <span class="social-conv-bottom">
              <span>{{ lastPreview(item) }}</span>
              <span class="social-conv-flags">
                <span v-if="prefOf(item.threadId).pinned" class="social-flag">置顶</span>
                <span v-if="prefOf(item.threadId).muted" class="social-flag">免打扰</span>
                <span v-if="unreadOf(item.threadId)" class="social-unread">{{ unreadOf(item.threadId) > 99 ? "99+" : unreadOf(item.threadId) }}</span>
              </span>
            </span>
          </span>
          <span class="social-conv-more" role="button" tabindex="0" aria-label="会话操作" @click.stop="openConversationMenu(item)">⋯</span>
        </button>
      </template>

      <template v-else>
        <section v-if="visibleSuggestions.length" class="social-contact-section">
          <div class="social-contact-section-head">
            <strong>可能想认识的人</strong>
            <button type="button" class="social-qq-link" @click="loadSuggestions">换一批</button>
          </div>
          <div v-for="merchant in visibleSuggestions" :key="merchant.merchant_id" class="social-suggest-row">
            <span class="social-avatar is-merchant">{{ initial(merchant.name) }}</span>
            <span class="social-suggest-copy">
              <strong>{{ merchant.name }}</strong>
              <small>{{ merchant.note || "店宠 · 售前 / 售后 / 砍价" }}</small>
            </span>
            <button
              type="button"
              class="social-qq-outline"
              :disabled="suggestionBusy === merchant.merchant_id"
              @click="addSuggestion(merchant)"
            >{{ suggestionBusy === merchant.merchant_id ? "添加中…" : "添加" }}</button>
            <button type="button" class="social-suggest-close" aria-label="忽略推荐" @click="ignoreSuggestion(merchant)">×</button>
          </div>
        </section>
        <p v-else-if="suggestionError" class="social-qq-state is-error" role="alert">{{ suggestionError }}</p>

        <section class="social-contact-section social-contact-entries">
          <button type="button" class="social-entry-row" @click="requestsOpen = true">
            <span class="social-entry-icon">友</span>
            <span><strong>新朋友</strong><small>{{ pendingRequests.length ? `${pendingRequests.length} 条待处理` : "暂无新的好友申请" }}</small></span>
            <span v-if="pendingRequests.length" class="social-unread">{{ pendingRequests.length }}</span>
            <span class="social-chevron">›</span>
          </button>
          <button type="button" class="social-entry-row" @click="noticesOpen = true">
            <span class="social-entry-icon">群</span>
            <span><strong>群通知</strong><small>{{ unreadNotices.length ? `${unreadNotices.length} 条未读` : "暂无新的群通知" }}</small></span>
            <span v-if="unreadNotices.length" class="social-unread">{{ unreadNotices.length }}</span>
            <span class="social-chevron">›</span>
          </button>
        </section>

        <div class="social-contact-tabs" role="tablist" aria-label="联系人分类">
          <button
            v-for="filter in FILTERS"
            :key="filter.key"
            type="button"
            role="tab"
            :aria-selected="contactFilter === filter.key"
            :class="{ active: contactFilter === filter.key }"
            @click="contactFilter = filter.key"
          >{{ filter.label }}</button>
        </div>

        <section
          v-if="contactFilter === 'all' || contactFilter === 'merchant'"
          class="social-contact-section"
        >
          <div class="social-contact-section-head">
            <strong>店宠</strong>
            <span>{{ contactLists.merchants.length }}</span>
          </div>
          <button
            v-for="friend in contactLists.merchants"
            :key="friend.friend_id"
            type="button"
            class="social-contact-row"
            @click="openConversation({ threadId: friend.friend_id, type: 'friend', kind: friend.kind, name: friend.name, note: friend.note, friend })"
          >
            <span class="social-avatar is-merchant">{{ initial(friend.name) }}</span>
            <span class="social-contact-copy"><strong>{{ friend.name }}</strong><small>{{ friend.note || "店宠" }}</small></span>
            <button type="button" class="social-row-more" aria-label="好友操作" @click.stop="openContactMenu(friend)">⋯</button>
          </button>
          <p v-if="!contactLists.merchants.length" class="social-inline-empty">还没有店宠好友，去上面的推荐里添加。</p>
        </section>

        <section
          v-if="contactFilter === 'all' || contactFilter === 'friend'"
          class="social-contact-section"
        >
          <div class="social-contact-section-head">
            <strong>好友</strong>
            <span>{{ contactLists.friends.length }}</span>
          </div>
          <div
            v-for="friend in contactLists.friends"
            :key="friend.friend_id"
            class="social-contact-row"
            role="button"
            tabindex="0"
            @click="openConversation({ threadId: friend.friend_id, type: 'friend', kind: friend.kind, name: friend.name, note: friend.note, friend })"
            @keydown.enter="openConversation({ threadId: friend.friend_id, type: 'friend', kind: friend.kind, name: friend.name, note: friend.note, friend })"
          >
            <span class="social-avatar">{{ initial(friend.name) }}</span>
            <span class="social-contact-copy"><strong>{{ friend.name }}</strong><small>{{ friend.note || "好友" }}</small></span>
            <button type="button" class="social-row-more" aria-label="好友操作" @click.stop="openContactMenu(friend)">⋯</button>
          </div>
          <p v-if="!contactLists.friends.length" class="social-inline-empty">还没有好友。</p>
        </section>

        <section
          v-if="contactFilter === 'all' || contactFilter === 'group'"
          class="social-contact-section"
        >
          <div class="social-contact-section-head">
            <strong>群聊</strong>
            <span>{{ contactLists.groups.length }}</span>
          </div>
          <button
            v-for="group in contactLists.groups"
            :key="group.group_id"
            type="button"
            class="social-contact-row"
            @click="openConversation({ threadId: group.group_id, type: 'group', kind: 'group', name: group.name, note: `${group.members?.length || 0} 位成员`, group })"
          >
            <span class="social-avatar is-group">{{ initial(group.name) }}</span>
            <span class="social-contact-copy"><strong>{{ group.name }}</strong><small>{{ group.members?.length || 0 }} 位成员</small></span>
            <span class="social-chevron">›</span>
          </button>
          <p v-if="!contactLists.groups.length" class="social-inline-empty">还没有群聊。</p>
        </section>
      </template>
    </main>

    <section v-else class="social-chat" aria-label="聊天窗口">
      <div class="social-chat-subhead">
        <span>{{ active.type === "group" ? `群聊 · ${active.group?.members?.length || 0} 位成员` : active.kind === "merchant" ? "店宠单聊" : "好友单聊" }}</span>
        <span class="social-chat-state">
          <span v-if="active.type === 'friend'" class="socket-dot" :class="socketState" />
          {{ active.type === "friend" ? (socketState === "online" ? "实时连接" : "HTTP 回退") : "HTTP 发送" }}
        </span>
      </div>
      <div id="social-chat-scroll" class="social-chat-scroll" aria-live="polite">
        <p v-if="messagesLoading" class="social-qq-state" role="status">正在加载消息…</p>
        <p v-else-if="chatError" class="social-qq-state is-error" role="alert">{{ chatError }}</p>
        <p v-else-if="!messages.length" class="social-chat-empty">还没有消息，发一句试试。</p>
        <div
          v-for="message in messages"
          :key="message.message_id"
          class="social-message"
          :class="{ own: isOwn(message) }"
        >
          <small class="social-message-meta">{{ senderName(message) }} · {{ formatTime(message.created_at) }}</small>
          <div class="social-message-bubble">{{ message.content }}</div>
          <div v-if="message.metadata?.quote_id" class="social-quote">
            <span>结构化报价</span>
            <span v-for="policy in message.metadata.policy_refs || []" :key="policy.policy_id">{{ policy.title || policy.policy_id }}</span>
            <span v-for="product in message.metadata.product_refs || []" :key="product.product_id">{{ product.title || product.product_id }}</span>
            <RouterLink
              :to="{ path: '/c', query: { quote: message.metadata.quote_id, friend_id: active.threadId, merchant_id: message.metadata.merchant_id, merchant_name: message.metadata.merchant_name } }"
            >去商城确认</RouterLink>
          </div>
        </div>
      </div>
      <form class="social-composer" @submit.prevent="send">
        <textarea
          id="social-chat-input"
          name="message"
          v-model="draft"
          rows="1"
          :disabled="sending"
          placeholder="输入消息，Enter 发送"
          aria-label="输入消息"
          @keydown="onKeydown"
        />
        <button type="submit" :disabled="!draft.trim() || sending">{{ sending ? "发送中" : "发送" }}</button>
      </form>
    </section>

    <div v-if="requestsOpen" class="social-mask" @click.self="requestsOpen = false">
      <section class="social-sheet" role="dialog" aria-modal="true" aria-label="新朋友">
        <header class="social-sheet-head">
          <div><p class="social-qq-kicker">FRIEND REQUESTS</p><h3>新朋友</h3></div>
          <button type="button" aria-label="关闭" @click="requestsOpen = false">×</button>
        </header>
        <p v-if="!pendingRequests.length" class="social-sheet-empty">暂无新的好友申请。</p>
        <article v-for="request in pendingRequests" :key="request.request_id" class="social-request-row">
          <span class="social-avatar">{{ initial(request.requester_name) }}</span>
          <div><strong>{{ request.requester_name }}</strong><small>{{ request.message || request.note || "请求添加你为好友" }}</small></div>
          <div class="social-request-actions">
            <button type="button" class="social-qq-outline" @click="rejectRequest(request)">拒绝</button>
            <button type="button" class="social-qq-primary" @click="acceptRequest(request)">接受</button>
          </div>
        </article>
      </section>
    </div>

    <div v-if="noticesOpen" class="social-mask" @click.self="noticesOpen = false">
      <section class="social-sheet" role="dialog" aria-modal="true" aria-label="群通知">
        <header class="social-sheet-head">
          <div><p class="social-qq-kicker">GROUP NOTICES</p><h3>群通知</h3></div>
          <button type="button" aria-label="关闭" @click="noticesOpen = false">×</button>
        </header>
        <div v-if="notices.length" class="social-sheet-tools">
          <button type="button" class="social-qq-link" @click="markAllNoticesRead">全部标为已读</button>
        </div>
        <p v-if="!notices.length" class="social-sheet-empty">暂无群通知。</p>
        <button
          v-for="notice in notices"
          :key="notice.notice_id"
          type="button"
          class="social-notice-row"
          :class="{ unread: notice.status === 'UNREAD' }"
          @click="markNoticeRead(notice)"
        >
          <span class="social-notice-dot" :class="{ unread: notice.status === 'UNREAD' }" />
          <span><strong>{{ notice.title }}</strong><small>{{ notice.content || "群通知" }} · {{ formatTime(notice.created_at) }}</small></span>
        </button>
      </section>
    </div>

    <div v-if="actionItem" class="social-mask" @click.self="closeActionMenu">
      <section class="social-action-sheet" role="dialog" aria-modal="true" aria-label="操作">
        <header class="social-sheet-head">
          <div><p class="social-qq-kicker">ACTIONS</p><h3>{{ actionItem.name }}</h3></div>
          <button type="button" aria-label="关闭" @click="closeActionMenu">×</button>
        </header>
        <template v-if="actionType === 'conversation'">
          <button type="button" class="social-action-row" @click="updatePref(actionItem.threadId, { pinned: !prefOf(actionItem.threadId).pinned }, prefOf(actionItem.threadId).pinned ? '已取消置顶' : '已置顶会话'); closeActionMenu()">
            {{ prefOf(actionItem.threadId).pinned ? "取消置顶" : "置顶会话" }}
          </button>
          <button type="button" class="social-action-row" @click="updatePref(actionItem.threadId, { muted: !prefOf(actionItem.threadId).muted }, prefOf(actionItem.threadId).muted ? '已取消免打扰' : '已开启免打扰'); closeActionMenu()">
            {{ prefOf(actionItem.threadId).muted ? "取消免打扰" : "免打扰" }}
          </button>
          <button type="button" class="social-action-row" @click="markThreadRead(actionItem.threadId); toast('已标记为已读', 'success'); closeActionMenu()">标为已读</button>
          <button type="button" class="social-action-row" @click="updatePref(actionItem.threadId, { hidden: !prefOf(actionItem.threadId).hidden }, prefOf(actionItem.threadId).hidden ? '已恢复会话' : '已隐藏会话'); closeActionMenu()">
            {{ prefOf(actionItem.threadId).hidden ? "恢复会话" : "隐藏会话" }}
          </button>
        </template>
        <template v-else>
          <button type="button" class="social-action-row" @click="openConversation(actionItem); closeActionMenu()">发消息</button>
          <button type="button" class="social-action-row is-danger" @click="removeFriend(actionItem.friend || actionItem)">删除好友</button>
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.social-qq {
  display: flex;
  flex-direction: column;
  min-height: 0;
  color: var(--text);
}

.social-qq.is-chat {
  min-height: calc(100dvh - 190px);
}

.social-qq-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 2px 10px;
}

.social-qq-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.social-qq-heading h2 {
  margin: 0;
  font-size: 23px;
  letter-spacing: -0.02em;
}

.social-qq-kicker {
  margin: 0 0 3px;
  color: var(--primary);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.social-qq-back,
.social-qq-add,
.social-qq-more {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid var(--border);
  border-radius: 50%;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}

.social-qq-back {
  margin-left: -4px;
  font-size: 28px;
}

.social-qq-search {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 10px;
  padding: 0 11px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-2);
  color: var(--text-3);
}

.social-qq-search svg {
  width: 17px;
  height: 17px;
  flex: none;
}

.social-qq-search input {
  width: 100%;
  height: 38px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 16px;
}

.social-qq-segment {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
  padding: 4px;
  border-radius: 12px;
  background: var(--surface-2);
}

.social-qq-segment button {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 34px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--text-3);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.social-qq-segment button.active {
  background: var(--surface);
  color: var(--text);
  font-weight: 700;
  box-shadow: 0 1px 5px rgba(30, 27, 22, 0.08);
}

.social-qq-badge,
.social-qq-count {
  display: inline-grid;
  min-width: 17px;
  height: 17px;
  place-items: center;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}

.social-qq-count {
  background: var(--surface-3);
  color: var(--text-3);
}

.social-qq-body {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 9px;
  padding-bottom: 18px;
}

.social-qq-subhead,
.social-contact-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--text-3);
  font-size: 12px;
}

.social-qq-actions {
  display: flex;
  gap: 8px;
}

.social-qq-link {
  border: 0;
  background: transparent;
  color: var(--primary);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.social-qq-link:disabled {
  opacity: 0.5;
}

.social-qq-state {
  margin: 0;
  padding: 16px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 13px;
}

.social-qq-state.is-error {
  border-color: #e4b6a9;
  color: var(--primary-strong);
}

.social-qq-state p {
  margin: 6px 0 10px;
}

.social-qq-state button,
.social-qq-primary,
.social-qq-outline {
  min-height: 32px;
  padding: 0 11px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.social-qq-primary {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.social-qq-outline {
  flex: none;
  border-color: var(--primary);
  color: var(--primary);
}

.social-qq-empty {
  padding: 30px 16px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface);
  text-align: center;
}

.social-qq-empty strong {
  display: block;
  font-size: 16px;
}

.social-qq-empty p {
  margin: 6px 0 14px;
  color: var(--text-3);
  font-size: 12px;
}

.social-conv-row {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  padding: 10px 6px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.social-conv-row.pinned {
  background: color-mix(in srgb, var(--primary-soft) 30%, transparent);
}

.social-avatar {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  place-items: center;
  border-radius: 50%;
  background: var(--surface-3);
  color: var(--text-2);
  font-size: 16px;
  font-weight: 700;
}

.social-avatar.is-merchant {
  background: #e5f0ea;
  color: #2f7352;
}

.social-avatar.is-group {
  border-radius: 13px;
  background: #e8eaf8;
  color: #4c568b;
}

.social-conv-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}

.social-conv-top,
.social-conv-bottom {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.social-conv-top strong {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.social-conv-top small {
  flex: none;
  color: var(--text-3);
  font-size: 10px;
}

.social-conv-bottom > span:first-child {
  overflow: hidden;
  color: var(--text-3);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.social-conv-flags {
  display: flex;
  flex: none;
  align-items: center;
  gap: 4px;
}

.social-flag {
  color: var(--primary);
  font-size: 9px;
}

.social-unread {
  display: inline-grid;
  min-width: 17px;
  height: 17px;
  place-items: center;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}

.social-conv-more,
.social-row-more {
  display: grid;
  width: 28px;
  height: 28px;
  flex: none;
  place-items: center;
  border: 0;
  background: transparent;
  color: var(--text-3);
  font: inherit;
  cursor: pointer;
}

.social-contact-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 0 4px;
}

.social-contact-section-head {
  padding: 0 6px 4px;
}

.social-contact-section-head strong {
  color: var(--text-2);
  font-size: 12px;
  font-weight: 600;
}

.social-suggest-row,
.social-contact-row,
.social-entry-row {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  min-height: 54px;
  padding: 7px 6px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.social-suggest-copy,
.social-contact-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}

.social-contact-row > .social-contact-copy {
  overflow: hidden;
}

.social-suggest-copy strong,
.social-contact-copy strong,
.social-entry-row strong {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.social-suggest-copy small,
.social-contact-copy small,
.social-entry-row small {
  overflow: hidden;
  color: var(--text-3);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.social-suggest-close {
  border: 0;
  background: transparent;
  color: var(--text-3);
  font-size: 18px;
  cursor: pointer;
}

.social-contact-entries {
  gap: 0;
  border-top: 1px solid var(--border);
}

.social-entry-row > span:nth-child(2) {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}

.social-entry-icon {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  place-items: center;
  border-radius: 12px;
  background: var(--surface-2);
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
}

.social-chevron {
  flex: none;
  color: var(--text-3);
  font-size: 20px;
}

.social-contact-tabs {
  display: flex;
  gap: 5px;
  overflow-x: auto;
  padding: 8px 0 4px;
  scrollbar-width: none;
}

.social-contact-tabs button {
  flex: none;
  padding: 5px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-3);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.social-contact-tabs button.active {
  border-color: var(--primary);
  background: var(--primary-soft);
  color: var(--primary-strong);
  font-weight: 700;
}

.social-inline-empty {
  margin: 7px 6px;
  color: var(--text-3);
  font-size: 12px;
}

.social-chat {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
}

.social-qq.is-chat .social-chat {
  min-height: 0;
}

.social-chat-subhead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 2px 2px 7px;
  color: var(--text-3);
  font-size: 11px;
}

.social-chat-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.socket-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
}

.socket-dot.online {
  background: #3b9c70;
}

.socket-dot.fallback {
  background: #c68a36;
}

.social-chat-scroll {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  padding: 4px 2px 10px;
  overscroll-behavior: contain;
}

.social-chat-empty {
  margin: auto;
  color: var(--text-3);
  font-size: 12px;
}

.social-message {
  display: flex;
  max-width: 88%;
  flex-direction: column;
  align-self: flex-start;
  gap: 3px;
}

.social-message.own {
  align-self: flex-end;
  align-items: flex-end;
}

.social-message-meta {
  color: var(--text-3);
  font-size: 9px;
}

.social-message-bubble {
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.social-message.own .social-message-bubble {
  border-color: var(--text);
  background: var(--text);
  color: var(--surface);
}

.social-quote {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 6px 8px;
  border: 1px dashed var(--border);
  border-radius: 9px;
  color: var(--text-3);
  font-size: 10px;
}

.social-quote a {
  color: var(--primary);
  text-decoration: none;
}

.social-composer {
  display: flex;
  align-items: flex-end;
  gap: 7px;
  padding: 8px 0 2px;
  border-top: 1px solid var(--border);
}

.social-composer textarea {
  min-height: 38px;
  max-height: 110px;
  flex: 1;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 14px;
  outline: 0;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 16px;
  line-height: 1.5;
  resize: none;
}

.social-composer button {
  min-height: 38px;
  padding: 0 12px;
  border: 0;
  border-radius: 999px;
  background: var(--primary);
  color: #fff;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.social-composer button:disabled {
  opacity: 0.45;
}

.social-mask {
  position: fixed;
  z-index: 60;
  inset: 0;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  background: rgba(30, 27, 22, 0.4);
  padding: 14px;
}

.social-sheet,
.social-action-sheet {
  width: min(520px, 100%);
  max-height: 76vh;
  overflow-y: auto;
  padding: 16px;
  border-radius: 18px;
  background: var(--surface);
}

.social-sheet-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.social-sheet-head h3 {
  margin: 0;
  font-size: 19px;
}

.social-sheet-head > button {
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 19px;
  cursor: pointer;
}

.social-sheet-empty {
  margin: 18px 0;
  color: var(--text-3);
  font-size: 12px;
  text-align: center;
}

.social-sheet-tools {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 4px;
}

.social-request-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 0;
  border-bottom: 1px solid var(--border);
}

.social-request-row > div {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}

.social-request-row strong {
  font-size: 13px;
}

.social-request-row small {
  overflow: hidden;
  color: var(--text-3);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.social-request-actions {
  display: flex;
  flex: none;
  gap: 5px;
}

.social-notice-row {
  display: flex;
  width: 100%;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 0;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.social-notice-row > span:last-child {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.social-notice-row strong {
  font-size: 13px;
}

.social-notice-row small {
  color: var(--text-3);
  font-size: 11px;
}

.social-notice-dot {
  width: 7px;
  height: 7px;
  flex: none;
  margin-top: 5px;
  border-radius: 50%;
  background: transparent;
}

.social-notice-dot.unread {
  background: var(--primary);
}

.social-notice-row.unread strong {
  font-weight: 700;
}

.social-action-sheet {
  padding-bottom: 8px;
}

.social-action-row {
  display: block;
  width: 100%;
  min-height: 44px;
  padding: 0 4px;
  border: 0;
  border-bottom: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 14px;
  text-align: left;
  cursor: pointer;
}

.social-action-row:last-child {
  border-bottom: 0;
}

.social-action-row.is-danger {
  color: var(--primary-strong);
}

@media (min-width: 760px) {
  .social-qq-body {
    padding-bottom: 24px;
  }

  .social-conv-row,
  .social-contact-row,
  .social-suggest-row {
    padding-right: 2px;
    padding-left: 2px;
  }
}
</style>
