<script setup>
/**
 * 千客引擎品牌 Logo。
 * 纯 SVG 绘制：深黑圆角底座 + 4 个金色数据点菱形阵列 + 细连线。
 * 悬停时四个点产生极其克制的呼吸光晕；尺寸由 size 控制，任意缩放保持清晰。
 */
import { computed, useId } from "vue";

const props = defineProps({
  size: { type: Number, default: 32 },
  showText: { type: Boolean, default: true },
  text: { type: String, default: "千客引擎" },
});

const gradientId = `qk-logo-border-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
const boxStyle = computed(() => ({ "--logo-size": `${props.size}px` }));
const dots = [
  { cx: 16, cy: 8.4, delay: "0s" },
  { cx: 23.6, cy: 16, delay: "0.18s" },
  { cx: 16, cy: 23.6, delay: "0.36s" },
  { cx: 8.4, cy: 16, delay: "0.54s" },
];
</script>

<template>
  <div class="qk-logo" :class="{ 'has-text': showText }" :style="boxStyle">
    <svg
      class="qk-logo-mark"
      :width="size"
      :height="size"
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      :role="showText ? undefined : 'img'"
      :aria-label="showText ? undefined : text"
      :aria-hidden="showText ? 'true' : undefined"
    >
      <rect x="1" y="1" width="30" height="30" rx="8.6" fill="#09090C" />
      <rect
        x="1.45"
        y="1.45"
        width="29.1"
        height="29.1"
        rx="8.15"
        :stroke="`url(#${gradientId})`"
        stroke-width="0.9"
      />
      <path
        d="M16 8.4L23.6 16L16 23.6L8.4 16Z"
        stroke="#F59E0B"
        stroke-opacity="0.42"
        stroke-width="0.55"
        stroke-linejoin="round"
      />
      <g class="qk-logo-dots">
        <g v-for="(dot, i) in dots" :key="i">
          <circle
            class="qk-logo-halo"
            :cx="dot.cx"
            :cy="dot.cy"
            r="3.5"
            fill="#F59E0B"
            :style="{ animationDelay: dot.delay }"
          />
          <circle
            class="qk-logo-dot"
            :cx="dot.cx"
            :cy="dot.cy"
            r="1.48"
            fill="#F59E0B"
            :style="{ animationDelay: dot.delay }"
          />
        </g>
      </g>
      <defs>
        <linearGradient :id="gradientId" x1="2" y1="2" x2="30" y2="30" gradientUnits="userSpaceOnUse">
          <stop stop-color="#F59E0B" stop-opacity="0.28" />
          <stop offset="1" stop-color="#F59E0B" stop-opacity="0.05" />
        </linearGradient>
      </defs>
    </svg>
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
  overflow: visible;
  filter: drop-shadow(0 4px 10px rgba(0, 0, 0, 0.28));
}
.qk-logo-text {
  color: var(--text, #111827);
  font-size: calc(var(--logo-size) * 0.42);
  font-weight: 800;
  letter-spacing: 0.01em;
  white-space: nowrap;
}
.qk-logo-halo {
  opacity: 0;
  transform-box: fill-box;
  transform-origin: center;
  pointer-events: none;
  transition: opacity 0.2s ease;
}
.qk-logo:hover .qk-logo-halo {
  animation: qk-logo-breathe 2.2s ease-in-out infinite;
}
.qk-logo:hover .qk-logo-dot {
  animation: qk-logo-dot-breathe 2.2s ease-in-out infinite;
}
.qk-logo-dot {
  transform-box: fill-box;
  transform-origin: center;
}
@keyframes qk-logo-dot-breathe {
  0%, 100% { filter: drop-shadow(0 0 0 rgba(245, 158, 11, 0)); transform: scale(1); }
  50% { filter: drop-shadow(0 0 2px rgba(245, 158, 11, 0.7)); transform: scale(1.045); }
}
@keyframes qk-logo-breathe {
  0%, 100% { opacity: 0; transform: scale(0.8); }
  50% { opacity: 0.16; transform: scale(1.08); }
}
@media (prefers-reduced-motion: reduce) {
  .qk-logo:hover .qk-logo-halo,
  .qk-logo:hover .qk-logo-dot { animation: none; }
}
</style>
