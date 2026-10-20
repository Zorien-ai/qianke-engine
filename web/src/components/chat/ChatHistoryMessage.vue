<script setup>
/**
 * 历史消息：只读渲染已落库的一轮问答。
 * 来源已由服务端按当前权限裁剪；这里不再做权限判断。
 */
import { computed } from "vue";
import { renderMarkdown } from "../../lib/markdown";

const props = defineProps({
  message: { type: Object, required: true },
  canSources: { type: Boolean, default: false },
});

const isUser = computed(() => props.message.role === "user");
const answerHtml = computed(() =>
  isUser.value
    ? ""
    : renderMarkdown(props.message.content || "", {
        cite: (n) => (props.canSources ? `<span class="cite">[来源${n}]</span>` : null),
      })
);
const sources = computed(() => (props.canSources ? props.message.sources || [] : []));
const routeLabel = computed(() => {
  const map = {
    rag: "RAG 检索问答",
    chitchat: "闲聊",
    error: "检索不可用",
    sql: "结构化查询",
  };
  const route = props.message.route;
  return map[route] || (route ? String(route).toUpperCase() : "回答");
});
</script>

<template>
  <div class="history-message" :class="isUser ? 'is-user' : 'is-assistant'">
    <div v-if="isUser" class="history-user-bubble">{{ message.content }}</div>
    <section v-else class="history-answer-card">
      <header class="history-answer-head">
        <span class="badge is-primary">{{ routeLabel }}</span>
        <span v-if="message.status === 'error'" class="badge is-error">失败</span>
        <span class="history-time">{{ message.created_at ? message.created_at.slice(0, 16).replace("T", " ") : "" }}</span>
      </header>
      <div v-if="message.rewritten_question" class="history-rewrite">
        <span>结合上下文理解为</span>
        <b>{{ message.rewritten_question }}</b>
      </div>
      <div class="history-answer-body" v-html="answerHtml" />
      <details v-if="sources.length" class="history-sources">
        <summary>数据来源 · {{ sources.length }} 条</summary>
        <div v-for="source in sources" :key="source.index" class="history-source">
          <span class="history-source-index">[来源{{ source.index }}]</span>
          <span>{{ source.source || "未知来源" }}</span>
          <p v-if="source.text">{{ source.text }}</p>
        </div>
      </details>
    </section>
  </div>
</template>

<style scoped>
.history-message { margin: 18px 0 0; }
.history-message.is-user { display: flex; justify-content: flex-end; }
.history-user-bubble {
  max-width: min(78%, 720px);
  padding: 11px 15px;
  border-radius: 16px 16px 4px 16px;
  background: var(--primary-soft);
  color: var(--text);
  font-size: 13.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.history-answer-card {
  padding: 16px 18px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
.history-answer-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.history-time { margin-left: auto; color: var(--muted); font-size: 10.5px; }
.history-rewrite {
  display: flex;
  align-items: baseline;
  gap: 7px;
  flex-wrap: wrap;
  margin-top: 10px;
  padding: 8px 10px;
  border: 1px dashed color-mix(in srgb, var(--primary) 26%, var(--border));
  border-radius: 8px;
  color: var(--muted);
  font-size: 11.5px;
}
.history-rewrite b { color: var(--text-2); font-weight: 600; }
.history-answer-body {
  margin-top: 10px;
  color: var(--text);
  font-size: 13.5px;
  line-height: 1.8;
  word-break: break-word;
}
.history-answer-body :deep(p) { margin: 0 0 10px; }
.history-answer-body :deep(p:last-child) { margin-bottom: 0; }
.history-answer-body :deep(.cite) {
  margin-left: 2px;
  padding: 0 3px;
  border-radius: 3px;
  background: var(--primary-soft);
  color: var(--primary);
  font-size: 10px;
}
.history-sources {
  margin-top: 12px;
  border-top: 1px solid var(--border);
  padding-top: 10px;
  color: var(--muted);
  font-size: 11.5px;
}
.history-sources summary { cursor: pointer; color: var(--primary); }
.history-source {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 8px;
  color: var(--text-2);
}
.history-source-index { color: var(--primary); font-family: var(--font-mono, monospace); font-size: 10px; }
.history-source p { margin: 3px 0 0; color: var(--muted); line-height: 1.55; }
</style>
