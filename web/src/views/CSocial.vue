<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { getJson, postJson } from "../api";

const friends = ref([]);
const selected = ref(null);
const messages = ref([]);
const loading = ref(true);
const error = ref("");
const draft = ref("");
const sending = ref(false);
const socketState = ref("offline");
let ws = null;

const selectedName = computed(() => selected.value?.name || "选择好友");

function isOwn(message) {
  return message.sender_id && message.sender_id.startsWith("buyer_");
}

function connectSocket(friendId) {
  closeSocket();
  if (!friendId) return;
  try {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${scheme}://${window.location.host}/api/c/ws/chat/${friendId}`);
  } catch {
    socketState.value = "fallback";
    return;
  }
  socketState.value = "connecting";
  ws.onopen = () => {
    socketState.value = "online";
  };
  ws.onmessage = (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    if (payload.type === "chat") {
      if (payload.message) messages.value.push(payload.message);
      if (payload.reply) messages.value.push(payload.reply);
      scrollToBottom();
    } else if (payload.type === "error") {
      error.value = payload.error?.message || "消息发送失败";
    }
  };
  ws.onerror = () => {
    socketState.value = "fallback";
  };
  ws.onclose = () => {
    if (socketState.value === "online") socketState.value = "fallback";
  };
}

function closeSocket() {
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
  socketState.value = "offline";
}

async function loadMessages(friendId) {
  messages.value = [];
  try {
    const data = await getJson(`/api/c/friends/${encodeURIComponent(friendId)}/messages?limit=50`);
    messages.value = data?.messages || [];
    scrollToBottom();
  } catch (e) {
    error.value = e?.detail || e?.message || "消息加载失败";
  }
}

async function selectFriend(friend) {
  selected.value = friend;
  error.value = "";
  await loadMessages(friend.friend_id);
  connectSocket(friend.friend_id);
}

async function loadFriends() {
  loading.value = true;
  error.value = "";
  try {
    const data = await getJson("/api/c/friends");
    friends.value = data?.friends || [];
    const merchant = friends.value.find((item) => item.kind === "merchant") || friends.value[0];
    if (merchant) await selectFriend(merchant);
  } catch (e) {
    error.value = e?.detail || e?.message || "好友列表加载失败";
  } finally {
    loading.value = false;
  }
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    const el = document.getElementById("c-chat-scroll");
    if (el) el.scrollTop = el.scrollHeight;
  });
}

async function send() {
  const content = draft.value.trim();
  if (!content || !selected.value || sending.value) return;
  sending.value = true;
  error.value = "";
  draft.value = "";
  try {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ content }));
      return;
    }
    const result = await postJson(
      `/api/c/friends/${encodeURIComponent(selected.value.friend_id)}/messages`,
      { content }
    );
    if (result.message) messages.value.push(result.message);
    if (result.reply) messages.value.push(result.reply);
    scrollToBottom();
  } catch (e) {
    error.value = e?.detail || e?.message || "消息发送失败";
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

onMounted(loadFriends);
onBeforeUnmount(closeSocket);
</script>

<template>
  <div class="social-page">
    <header class="social-head">
      <div>
        <p class="social-kicker">C-END · IM</p>
        <h2>社交消息</h2>
        <p class="social-subtitle">
          IM 社交壳 MVP：好友、单聊、店宠 @ 唤醒。店宠由独立 B 端 Agent 回复，商品库当前仍是 mock。
        </p>
      </div>
      <span class="connection" role="status">
        <span class="connection-dot" :class="socketState" />
        {{ socketState === "online" ? "实时连接" : socketState === "connecting" ? "连接中" : "HTTP 回退" }}
      </span>
    </header>

    <p v-if="error" class="social-error" role="alert">{{ error }}</p>

    <section class="social-shell">
      <aside class="friend-panel" aria-label="好友列表">
        <div class="friend-head">
          <h3>好友</h3>
          <span>{{ friends.length }}</span>
        </div>
        <p v-if="loading" class="state-line" role="status">正在加载好友…</p>
        <div v-else class="friend-list">
          <button
            v-for="friend in friends"
            :key="friend.friend_id"
            class="friend-row"
            :class="{ active: selected?.friend_id === friend.friend_id }"
            type="button"
            :aria-current="selected?.friend_id === friend.friend_id ? 'true' : undefined"
            @click="selectFriend(friend)"
          >
            <span class="friend-mark">{{ friend.name.slice(0, 1) }}</span>
            <span class="friend-copy">
              <strong>{{ friend.name }}</strong>
              <small>{{ friend.note }}</small>
            </span>
            <span v-if="friend.kind === 'merchant'" class="friend-tag">店宠</span>
          </button>
        </div>
      </aside>

      <section class="chat-panel" aria-label="聊天窗口">
        <div class="chat-head">
          <div>
            <h3>{{ selectedName }}</h3>
            <p>{{ selected?.kind === "merchant" ? "按 @店宠 唤醒；越界消息由代码闸门拦截" : "好友单聊" }}</p>
          </div>
          <span class="chat-meta">mock IM</span>
        </div>

        <div id="c-chat-scroll" class="message-scroll" aria-live="polite">
          <p v-if="!messages.length" class="empty-line">还没有消息，发一句试试。</p>
          <div
            v-for="message in messages"
            :key="message.message_id"
            class="message-row"
            :class="{ own: isOwn(message) }"
          >
            <div class="message-meta">
              {{ isOwn(message) ? "我" : selectedName }} · {{ message.created_at?.slice(11, 19) }}
            </div>
            <div class="message-bubble">{{ message.content }}</div>
          </div>
        </div>

        <form class="composer" @submit.prevent="send">
          <label class="sr-only" for="c-message-input">输入消息</label>
          <textarea
            id="c-message-input"
            v-model="draft"
            rows="2"
            :disabled="!selected || sending"
            placeholder="输入消息；Enter 发送，Shift+Enter 换行"
            @keydown="onKeydown"
          />
          <button class="send-btn" type="submit" :disabled="!draft.trim() || !selected || sending">
            {{ sending ? "发送中…" : "发送" }}
          </button>
        </form>
      </section>
    </section>
  </div>
</template>

<style scoped>
.social-page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 8px 0 40px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.social-head {
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

.social-kicker {
  margin: 0 0 6px;
  color: var(--primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.social-head h2 {
  font-size: 24px;
}

.social-subtitle {
  max-width: 670px;
  margin-top: 7px;
  color: var(--text-2);
  font-size: 13px;
}

.connection {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--muted);
  font-size: 11px;
  white-space: nowrap;
}

.connection-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--muted);
}

.connection-dot.online { background: var(--success); }
.connection-dot.connecting { background: var(--warn); }

.social-error {
  padding: 9px 11px;
  border: 1px solid var(--danger);
  border-radius: var(--radius-xs);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 12px;
}

.social-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  min-height: 580px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}

.friend-panel {
  border-right: 1px solid var(--border);
  background: var(--surface-2);
}

.friend-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 16px;
  border-bottom: 1px solid var(--border);
}

.friend-head h3 {
  font-size: 14px;
}

.friend-head span {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
}

.friend-list {
  padding: 6px;
}

.friend-row {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 10px 9px;
  border: 0;
  border-radius: var(--radius-xs);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.friend-row:hover {
  background: var(--surface-3);
}

.friend-row.active {
  background: var(--primary-soft);
}

.friend-mark {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 50%;
  background: var(--surface);
  color: var(--text-2);
  font-weight: 700;
}

.friend-row.active .friend-mark {
  background: var(--primary);
  color: #fff;
}

.friend-copy {
  min-width: 0;
  flex: 1;
}

.friend-copy strong,
.friend-copy small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.friend-copy strong {
  font-size: 12px;
}

.friend-copy small {
  margin-top: 2px;
  color: var(--muted);
  font-size: 10px;
}

.friend-tag {
  flex: 0 0 auto;
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--surface);
  color: var(--text-2);
  font-size: 9px;
}

.chat-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.chat-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 15px 18px;
  border-bottom: 1px solid var(--border);
}

.chat-head h3 {
  font-size: 15px;
}

.chat-head p {
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
}

.chat-meta {
  color: var(--muted);
  font-family: var(--mono);
  font-size: 10px;
}

.message-scroll {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  min-height: 380px;
  max-height: 520px;
  overflow-y: auto;
  padding: 16px 18px;
  background: var(--surface);
}

.message-row {
  max-width: 76%;
  align-self: flex-start;
}

.message-row.own {
  align-self: flex-end;
  text-align: right;
}

.message-meta {
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 10px;
}

.message-bubble {
  display: inline-block;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.55;
  text-align: left;
  white-space: pre-wrap;
}

.message-row.own .message-bubble {
  border-color: var(--primary);
  background: var(--primary);
  color: #fff;
}

.empty-line {
  margin: auto;
  color: var(--muted);
  font-size: 12px;
}

.composer {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}

.composer textarea {
  min-height: 48px;
  flex: 1;
  resize: vertical;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface-2);
  color: var(--text);
  font: inherit;
  font-size: 12px;
}

.composer textarea:focus {
  outline: 2px solid var(--primary);
  outline-offset: 1px;
}

.send-btn {
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid var(--primary);
  border-radius: var(--radius-xs);
  background: var(--primary);
  color: #fff;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.send-btn:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

@media (max-width: 760px) {
  .social-shell {
    grid-template-columns: 1fr;
  }

  .friend-panel {
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }

  .friend-list {
    display: flex;
    overflow-x: auto;
    gap: 4px;
  }

  .friend-row {
    min-width: 180px;
  }

  .message-row {
    max-width: 88%;
  }

  .social-head {
    flex-direction: column;
  }
}
</style>
