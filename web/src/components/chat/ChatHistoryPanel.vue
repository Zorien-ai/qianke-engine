<script setup>
/**
 * 对话历史会话栏（桌面固定，移动端抽屉）。
 * 只负责展示与交互，接口调用统一由 Chat.vue 处理。
 */
import { computed, nextTick, ref } from "vue";

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: "" },
  loading: { type: Boolean, default: false },
  open: { type: Boolean, default: false },
});

const emit = defineEmits(["new", "select", "rename", "delete", "close"]);

const editingId = ref("");
const editingTitle = ref("");
const editInput = ref(null);

function timeLabel(value) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
}

function startRename(session) {
  editingId.value = session.id;
  editingTitle.value = session.title || "新对话";
  nextTick(() => {
    const el = Array.isArray(editInput.value) ? editInput.value[0] : editInput.value;
    el?.focus?.();
    el?.select?.();
  });
}

function cancelRename() {
  editingId.value = "";
  editingTitle.value = "";
}

function commitRename() {
  const id = editingId.value;
  const title = editingTitle.value.trim();
  if (id && title) emit("rename", { id, title });
  cancelRename();
}

function onRenameKey(event) {
  if (event.key === "Enter") commitRename();
  if (event.key === "Escape") cancelRename();
}

const hasSessions = computed(() => props.sessions.length > 0);
</script>

<template>
  <aside class="chat-history-panel" :class="{ 'is-open': open }" aria-label="历史会话">
    <header class="history-head">
      <div>
        <div class="history-kicker">CONVERSATIONS</div>
        <strong>历史会话</strong>
      </div>
      <button type="button" class="icon-btn history-close" aria-label="关闭历史会话" @click="$emit('close')">
        ×
      </button>
    </header>

    <button type="button" class="new-chat-btn" @click="$emit('new')">
      <span aria-hidden="true">＋</span>
      新对话
    </button>

    <div v-if="loading" class="history-list">
      <div v-for="i in 5" :key="i" class="skeleton history-skeleton" />
    </div>

    <div v-else-if="!hasSessions" class="history-empty">
      <div class="history-empty-icon">◌</div>
      <p>还没有历史会话</p>
      <span>发出第一条问题后自动保存</span>
    </div>

    <nav v-else class="history-list" aria-label="会话列表">
      <div
        v-for="session in sessions"
        :key="session.id"
        class="history-item"
        :class="{ 'is-active': session.id === activeId }"
      >
        <template v-if="editingId === session.id">
          <input
            ref="editInput"
            v-model="editingTitle"
            class="history-rename"
            maxlength="80"
            aria-label="会话标题"
            @keydown="onRenameKey"
            @blur="commitRename"
          />
        </template>
        <template v-else>
          <button
            type="button"
            class="history-main"
            :title="session.title"
            @click="$emit('select', session.id)"
            @dblclick="startRename(session)"
          >
            <span class="history-title">{{ session.title || "新对话" }}</span>
            <span class="history-meta">
              {{ session.message_count || 0 }} 条 · {{ timeLabel(session.updated_at) }}
            </span>
          </button>
          <span class="history-actions">
            <button type="button" class="history-action" title="重命名" @click.stop="startRename(session)">✎</button>
            <button type="button" class="history-action is-danger" title="删除" @click.stop="$emit('delete', session.id)">×</button>
          </span>
        </template>
      </div>
    </nav>

    <footer class="history-foot">历史会话按账号私有保存</footer>
  </aside>
  <div v-if="open" class="history-backdrop" @click="$emit('close')" />
</template>

<style scoped>
.chat-history-panel {
  display: flex;
  flex-direction: column;
  width: 252px;
  flex: 0 0 252px;
  min-height: 420px;
  align-self: stretch;
  padding: 4px 10px 8px;
  border-right: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface) 48%, transparent);
}
.history-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 6px 12px;
}
.history-kicker {
  color: var(--muted);
  font-family: var(--font-mono, monospace);
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
}
.history-head strong { display: block; margin-top: 2px; font-size: 14px; }
.history-close { display: none; font-size: 20px; line-height: 1; }
.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  width: 100%;
  padding: 9px 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
  color: var(--text-2);
  font: inherit;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color .16s, color .16s, background .16s;
}
.new-chat-btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-soft); }
.history-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-height: 0;
  margin-top: 12px;
  overflow-y: auto;
  scrollbar-width: thin;
}
.history-skeleton { height: 44px; border-radius: 8px; }
.history-item {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 42px;
  border-radius: 8px;
}
.history-item:hover { background: var(--surface-2); }
.history-item.is-active { background: var(--primary-soft); }
.history-main {
  flex: 1;
  min-width: 0;
  padding: 7px 8px;
  border: 0;
  background: transparent;
  color: var(--text-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.history-item.is-active .history-main { color: var(--primary); }
.history-title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  font-weight: 600;
}
.history-meta { display: block; margin-top: 2px; color: var(--muted); font-size: 10px; }
.history-actions {
  display: flex;
  gap: 1px;
  padding-right: 3px;
  opacity: 0;
  transition: opacity .15s;
}
.history-item:hover .history-actions, .history-item.is-active .history-actions { opacity: 1; }
.history-action {
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--muted);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.history-action:hover { background: var(--surface-3); color: var(--text); }
.history-action.is-danger:hover { color: var(--danger); }
.history-rename {
  width: calc(100% - 10px);
  margin: 5px;
  padding: 6px 7px;
  border: 1px solid var(--primary);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 12px;
  outline: none;
}
.history-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 42px 8px;
  color: var(--muted);
  text-align: center;
}
.history-empty-icon { font-size: 26px; opacity: .5; }
.history-empty p { margin: 0; color: var(--text-2); font-size: 12px; }
.history-empty span { font-size: 10.5px; }
.history-foot {
  margin-top: auto;
  padding: 14px 6px 2px;
  color: var(--muted);
  font-size: 10px;
  line-height: 1.5;
}
.history-backdrop { display: none; }
@media (max-width: 900px) {
  .chat-history-panel {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 80;
    width: min(300px, 84vw);
    min-height: 100vh;
    padding-top: 14px;
    background: var(--surface);
    box-shadow: 18px 0 60px rgba(0, 0, 0, .22);
    transform: translateX(-102%);
    transition: transform .24s ease;
  }
  .chat-history-panel.is-open { transform: translateX(0); }
  .history-close { display: grid; }
  .history-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 79;
    background: rgba(8, 10, 14, .34);
    backdrop-filter: blur(2px);
  }
}
</style>
