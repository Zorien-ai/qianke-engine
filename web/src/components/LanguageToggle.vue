<script setup>
/**
 * 中英文切换按钮：默认中文，点击切换并持久化。
 * data-no-i18n 保证切换按钮自身不被文案翻译层改写。
 */
import { computed } from "vue";
import { locale, toggleLocale } from "../i18n";

const label = computed(() => (locale.value === "zh" ? "EN" : "中文"));
const title = computed(() => (locale.value === "zh" ? "Switch to English" : "切换为中文"));
</script>

<template>
  <button
    type="button"
    class="lang-toggle"
    data-no-i18n
    :title="title"
    :aria-label="title"
    @click="toggleLocale"
  >
    {{ label }}
  </button>
</template>

<style scoped>
.lang-toggle {
  min-width: 40px;
  height: 30px;
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border, rgba(148, 163, 184, 0.34));
  border-radius: 8px;
  background: var(--surface-2, rgba(148, 163, 184, 0.1));
  color: var(--text-2, #475569);
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.03em;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}
.lang-toggle:hover {
  color: var(--primary, #6d5dfc);
  border-color: var(--primary, #6d5dfc);
  background: var(--primary-soft, rgba(109, 93, 252, 0.1));
}
</style>
