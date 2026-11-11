<template>
  <div class="c-shell-wrap">
    <div class="c-shell-frame">
      <header class="c-shell-top">
        <RouterLink class="c-shell-back" to="/c/app" aria-label="返回对话">←</RouterLink>
        <strong>{{ title }}</strong>
        <RouterLink class="c-shell-home" to="/c/app">对话</RouterLink>
      </header>

      <main class="c-shell-body">
        <slot />
      </main>

      <nav class="c-shell-tabs" aria-label="C 端主导航">
        <RouterLink
          v-for="tab in tabs"
          :key="tab.key"
          :to="tab.to"
          class="c-shell-tab"
          :class="{ 'is-active': isActive(tab) }"
        >
          <span class="c-shell-tab-icon" v-html="tab.icon" />
          <span>{{ tab.label }}</span>
        </RouterLink>
      </nav>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { RouterLink, useRoute } from "vue-router";

const route = useRoute();
const title = computed(() => route.meta?.title || "千客");
const tabs = [
  { key: "chat", label: "聊", to: "/c/app", icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg>' },
  { key: "shop", label: "逛", to: "/c", icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>' },
  { key: "orders", label: "订单", to: "/c/orders", icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h9l4 4v16H6z"/><path d="M14 2v5h5"/><path d="M9 12h6M9 16h6"/></svg>' },
  { key: "messages", label: "消息", to: "/c/social", icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.5 9.4 9.4 0 0 1-3.2-.6L4 21l1.6-4.8A8.4 8.4 0 0 1 12.5 3 8.4 8.4 0 0 1 21 11.5z"/></svg>' },
];
const activePath = computed(() => route.path);
function isActive(tab) {
  if (tab.key === "shop") return activePath.value === "/c";
  return activePath.value === tab.to;
}
</script>

<style>
.c-shell-wrap {
  min-height: 100vh;
  padding: 20px;
  background: #ece8df;
  color: #1e1b16;
  box-sizing: border-box;
}

.c-shell-frame {
  --bg: #f7f3ea;
  --surface: #fffdf8;
  --surface-2: #f7f3ea;
  --surface-3: #efe7da;
  --border: #e4dccd;
  --text: #1e1b16;
  --text-2: #6b6258;
  --text-3: #8a7f72;
  --muted: #8a7f72;
  --primary: #d95f3b;
  --primary-soft: #f6e3da;
  --primary-strong: #b4492f;
  --radius: 14px;
  --radius-xs: 9px;
  --shadow-sm: none;
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 560px;
  height: calc(100vh - 40px);
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid rgba(30, 27, 22, 0.1);
  border-radius: 26px;
  background: var(--surface);
  box-shadow: 0 22px 60px rgba(30, 27, 22, 0.16);
}

.c-shell-top {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: none;
  min-height: 48px;
  padding: 0 14px;
  border-bottom: 1px solid var(--border);
  background: rgba(255, 253, 248, 0.92);
  backdrop-filter: blur(12px);
  font-size: 13px;
}

.c-shell-top strong {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
  font-family: Georgia, "Noto Serif SC", "Songti SC", serif;
  font-size: 15px;
  font-weight: 600;
}

.c-shell-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  color: var(--text-2);
  font-size: 18px;
  text-decoration: none;
}

.c-shell-back:hover,
.c-shell-home:hover {
  background: var(--bg-soft);
  color: var(--text);
}

.c-shell-home {
  color: var(--text-3);
  font-size: 11px;
  text-decoration: none;
}

.c-shell-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px 26px;
  background: var(--bg);
}

.c-shell-body .shop-page,
.c-shell-body .orders-page,
.c-shell-body .social-page {
  max-width: none;
  padding: 0;
}

.c-shell-frame .c-shell-body .shop-grid,
.c-shell-frame .c-shell-body .social-shell {
  grid-template-columns: 1fr !important;
}

.c-shell-body .social-shell {
  min-height: 0;
}

.c-shell-tabs {
  display: flex;
  flex: none;
  align-items: stretch;
  border-top: 1px solid var(--border);
  background: rgba(255, 253, 248, 0.96);
  backdrop-filter: blur(12px);
  padding: 5px 6px calc(5px + env(safe-area-inset-bottom));
}

.c-shell-tab {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 5px 0;
  border-radius: 10px;
  color: var(--text-3);
  font-size: 10px;
  text-decoration: none;
}

.c-shell-tab.is-active {
  color: var(--primary);
  background: var(--primary-soft);
  font-weight: 700;
}

.c-shell-tab-icon {
  display: inline-flex;
  width: 20px;
  height: 20px;
}

.c-shell-tab-icon svg {
  width: 20px;
  height: 20px;
}

@media (max-width: 640px) {
  .c-shell-wrap {
    padding: 0;
    background: var(--surface);
  }

  .c-shell-frame {
    height: 100vh;
    height: 100dvh;
    max-width: none;
    border: 0;
    border-radius: 0;
    box-shadow: none;
  }

  .c-shell-body .social-shell {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  .c-shell-body .friend-panel {
    flex: none;
    max-height: 118px;
    overflow: hidden;
  }

  .c-shell-body .friend-list {
    display: flex;
    overflow-x: auto;
  }

  .c-shell-body .chat-panel {
    width: 100%;
    min-width: 0;
  }

  .c-shell-body .message-scroll {
    min-height: 0;
    max-height: none;
    padding: 12px;
  }

  .c-shell-body .message-row {
    max-width: 88%;
  }

  .c-shell-body .message-bubble {
    max-width: 100%;
    overflow-wrap: anywhere;
  }
}
</style>
