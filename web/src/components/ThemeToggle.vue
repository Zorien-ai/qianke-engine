<script setup>
/**
 * 主题分段控件：浅色 / 深色 / 跟随系统。
 * 与语言切换使用同一套分段控件视觉；data-no-i18n 避免文案翻译层改写控件。
 */
import { computed } from "vue";
import { locale } from "../i18n";
import { store } from "../store";
import { setThemeMode } from "../theme";

const ICONS = {
  light:
    '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  dark: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  system:
    '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
};
const options = [
  { value: "light", zh: "浅色", en: "Light" },
  { value: "dark", zh: "深色", en: "Dark" },
  { value: "system", zh: "跟随系统", en: "System" },
];
const current = computed(() => store.themeMode || "system");

function labelFor(option) {
  return locale.value === "en" ? option.en : option.zh;
}
</script>

<template>
  <div class="theme-switch" data-no-i18n role="group" aria-label="Theme / 主题">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      class="theme-option"
      :class="{ 'is-active': current === option.value }"
      :aria-pressed="current === option.value"
      :title="labelFor(option)"
      :aria-label="labelFor(option)"
      @click="setThemeMode(option.value)"
    >
      <span
        class="theme-icon"
        v-html="`<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'>${ICONS[option.value]}</svg>`"
      />
    </button>
  </div>
</template>

<style scoped>
.theme-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--border, rgba(148, 163, 184, 0.34));
  border-radius: 10px;
  background: var(--surface-2, rgba(148, 163, 184, 0.1));
  white-space: nowrap;
}
.theme-option {
  width: 27px;
  height: 25px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--muted, #64748b);
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}
.theme-option:hover { color: var(--text-2, #334155); }
.theme-option.is-active {
  color: var(--primary, #4f46e5);
  border-color: color-mix(in srgb, var(--primary, #4f46e5) 26%, var(--border, #e2e8f0));
  background: var(--primary-soft, rgba(91, 91, 214, 0.1));
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
}
.theme-icon { width: 14px; height: 14px; display: grid; place-items: center; }
.theme-icon :deep(svg) { width: 14px; height: 14px; }
</style>
