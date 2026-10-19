<script setup>
/**
 * 中英文切换：分段式控件，默认中文，切换后持久化。
 * 根节点 data-no-i18n，避免文案翻译层把「中文 / English」改掉。
 */
import { locale, setLocale } from "../i18n";

const options = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
];
</script>

<template>
  <div
    class="lang-switch"
    data-no-i18n
    role="group"
    aria-label="Language / 语言"
  >
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      class="lang-option"
      :class="{ 'is-active': locale === option.value }"
      :aria-pressed="locale === option.value"
      @click="setLocale(option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<style scoped>
.lang-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--border, rgba(148, 163, 184, 0.34));
  border-radius: 10px;
  background: var(--surface-2, rgba(148, 163, 184, 0.1));
  white-space: nowrap;
}
.lang-option {
  height: 25px;
  padding: 0 9px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--muted, #64748b);
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}
.lang-option:hover {
  color: var(--text-2, #334155);
}
.lang-option.is-active {
  color: var(--primary, #4f46e5);
  border-color: color-mix(in srgb, var(--primary, #4f46e5) 26%, var(--border, #e2e8f0));
  background: var(--primary-soft, rgba(91, 91, 214, 0.1));
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
}
</style>
