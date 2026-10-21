<script setup>
/**
 * 千客引擎最终版 Logo。
 * 使用已去白底的透明 PNG；旁边可显示加粗品牌名。
 */
import logoUrl from "../assets/logo.png";

const props = defineProps({
  size: { type: Number, default: 32 },
  showText: { type: Boolean, default: true },
  text: { type: String, default: "千客引擎" },
});
</script>

<template>
  <div class="qk-logo" :class="{ 'has-text': showText }" :style="{ '--logo-size': `${size}px` }">
    <img
      class="qk-logo-mark"
      :src="logoUrl"
      :width="size"
      :height="size"
      alt="千客引擎 Logo"
      draggable="false"
    />
    <span v-if="showText" class="qk-logo-text">{{ text }}</span>
  </div>
</template>

<style scoped>
.qk-logo {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  line-height: 1;
  user-select: none;
}
.qk-logo-mark {
  display: block;
  flex: 0 0 auto;
  width: var(--logo-size);
  height: var(--logo-size);
  object-fit: contain;
  border-radius: 22%;
  filter: drop-shadow(0 3px 8px rgba(0, 0, 0, 0.18));
  transition: transform 0.2s ease, filter 0.2s ease;
}
.qk-logo:hover .qk-logo-mark {
  transform: scale(1.035);
  filter: drop-shadow(0 5px 14px rgba(0, 0, 0, 0.24));
}
.qk-logo-text {
  color: var(--text, #111827);
  font-size: calc(var(--logo-size) * 0.43);
  font-weight: 800;
  letter-spacing: 0.01em;
  white-space: nowrap;
}
@media (prefers-reduced-motion: reduce) {
  .qk-logo-mark { transition: none; }
  .qk-logo:hover .qk-logo-mark { transform: none; }
}
</style>
