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
  collapsed: { type: Boolean, default: false },
});

const emit = defineEmits(["new", "select", "rename", "delete", "close", "toggle"]);

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
const dockSessions = computed(() => props.sessions.slice(0, 8));

const DOT_COLORS = ["#8b8cf6", "#5aa9e6", "#54b8a7", "#e6a15a", "#d77ca8", "#8f9bb3", "#78b86b", "#b58de0"];

function dotColor(session) {
  const key = String(session.id || session.title || "");
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  return DOT_COLORS[hash % DOT_COLORS.length];
}
</script>

<template>
  <aside
    class="chat-history-panel"
    :class="{ 'is-open': open, 'is-collapsed': collapsed }"
    aria-label="历史会话"
  >
    <template v-if="!collapsed">
      <header class="history-head">
        <strong>历史会话</strong>
        <div class="history-head-actions">
          <button
            type="button"
            class="history-toggle"
            aria-label="收起历史会话"
            aria-expanded="true"
            title="收起历史会话"
            @click="$emit('toggle')"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="4" width="18" height="16" rx="2" />
              <path d="M8 4v16" />
            </svg>
          </button>
          <button type="button" class="icon-btn history-close" aria-label="关闭历史会话" @click="$emit('close')">
            ×
          </button>
        </div>
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
    </template>

    <template v-else>
      <div class="history-dock">
        <button
          type="button"
          class="history-toggle dock-toggle"
          aria-label="展开历史会话"
          aria-expanded="false"
          title="展开历史会话"
          @click="$emit('toggle')"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M8 4v16" />
          </svg>
        </button>

        <button
          type="button"
          class="new-chat-btn is-rail"
          title="新建对话"
          aria-label="新建对话"
          @click="$emit('new')"
        >
          <span aria-hidden="true">＋</span>
        </button>

        <div v-if="dockSessions.length" class="history-dots" aria-label="最近会话">
          <button
            v-for="session in dockSessions"
            :key="session.id"
            type="button"
            class="history-dot"
            :class="{ 'is-active': session.id === activeId }"
            :style="{ '--dot-color': dotColor(session) }"
            :aria-label="`${session.title || '新对话'}，${session.message_count || 0} 条`"
            @click="$emit('select', session.id)"
          >
            <span class="history-dot-mark" aria-hidden="true"></span>
            <span class="history-dot-tooltip">
              <b>{{ session.title || "新对话" }}</b>
              <span>{{ session.message_count || 0 }} 条 · {{ timeLabel(session.updated_at) }}</span>
            </span>
          </button>
        </div>
      </div>
    </template>
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
  transition: width .22s ease, flex-basis .22s ease, padding .22s ease;
}
.history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 6px 12px;
}
.history-head strong { font-size: 15px; letter-spacing: -0.01em; }
.history-head-actions { display: flex; align-items: center; gap: 2px; }
.history-toggle,
.history-close {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  transition: background .15s, color .15s, border-color .15s;
}
.history-toggle svg { width: 17px; height: 17px; }
.history-toggle:hover,
.history-close:hover {
  border-color: var(--border);
  background: var(--surface-2);
  color: var(--primary);
}
.history-close { display: none; font-size: 20px; line-height: 1; }
.chat-history-panel.is-collapsed {
  /* 参与 flex 布局，不再用负 left 悬在内容左侧：
     负偏移会落到 App 侧边栏下面，表现为历史记录栏被裁掉/缩进错位。 */
  position: relative;
  top: auto;
  left: auto;
  z-index: 12;
  width: 44px;
  flex: 0 0 44px;
  min-height: 0;
  height: auto;
  align-self: flex-start;
  padding: 0;
  border-right: 0;
  background: transparent;
}
.history-dock {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  width: 44px;
  padding: 7px 5px 8px;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: color-mix(in srgb, var(--surface) 96%, transparent);
  box-shadow: 0 10px 30px -16px rgba(15, 23, 42, 0.38);
}
.dock-toggle { flex: 0 0 auto; border-radius: 12px; }
.history-dots {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  width: 100%;
}
.history-dot {
  position: relative;
  display: grid;
  place-items: center;
  width: 30px;
  height: 17px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
}
.history-dot:hover,
.history-dot:focus-visible { background: var(--surface-2); outline: none; }
.history-dot-mark {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--dot-color, var(--muted));
  opacity: .8;
  transition: transform .15s ease, opacity .15s ease, box-shadow .15s ease;
}
.history-dot:hover .history-dot-mark,
.history-dot:focus-visible .history-dot-mark { opacity: 1; transform: scale(1.12); }
.history-dot.is-active .history-dot-mark {
  width: 11px;
  height: 11px;
  opacity: 1;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--dot-color, var(--primary)) 22%, transparent);
}
.history-dot-tooltip {
  position: absolute;
  left: 32px;
  top: 50%;
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 154px;
  max-width: 240px;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: 0 10px 30px -12px rgba(15, 23, 42, .3);
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transform: translateY(-50%) translateX(-3px);
  transition: opacity .14s ease, transform .14s ease, visibility .14s;
}
.history-dot-tooltip b {
  overflow: hidden;
  color: var(--text);
  font-size: 11.5px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-dot-tooltip span { color: var(--muted); font-size: 10.5px; white-space: nowrap; }
.history-dot:hover .history-dot-tooltip,
.history-dot:focus-visible .history-dot-tooltip {
  opacity: 1;
  visibility: visible;
  transform: translateY(-50%) translateX(0);
}
.new-chat-btn.is-rail {
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  padding: 0;
  border-radius: 10px;
  font-size: 17px;
  line-height: 1;
}
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
  min-height: 46px;
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
  font-size: 13px;
  font-weight: 600;
}
.history-meta {
  display: block;
  margin-top: 3px;
  color: var(--text-2);
  opacity: 0.72;
  font-size: 11.5px;
}
.history-actions {
  position: absolute;
  right: 2px;
  top: 50%;
  display: flex;
  gap: 2px;
  padding-left: 10px;
  border-radius: 0 8px 8px 0;
  background: linear-gradient(90deg, transparent, var(--surface-2) 28%);
  opacity: 0;
  pointer-events: none;
  transform: translateY(-50%);
  transition: opacity .15s;
}
.history-item.is-active .history-actions {
  background: linear-gradient(90deg, transparent, var(--primary-soft) 28%);
}
.history-item:hover .history-actions,
.history-item:focus-within .history-actions { opacity: 1; pointer-events: auto; }
.history-action {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-2);
  font: inherit;
  font-size: 15px;
  line-height: 1;
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
  .chat-history-panel.is-collapsed { display: none; }
  .history-close { display: grid; }
  .history-toggle { display: none; }
  .history-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 79;
    background: rgba(8, 10, 14, .34);
    backdrop-filter: blur(2px);
  }
}
@media (hover: none) {
  .history-item.is-active .history-actions { opacity: 1; }
}
</style>
