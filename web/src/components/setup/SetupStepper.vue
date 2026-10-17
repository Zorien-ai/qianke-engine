<script setup>
/**
 * 四步向导的步骤条：
 * - 当前步骤高亮 pill 用绝对定位的 indicator 平滑滑动（transform + cubic-bezier）；
 * - 下方连线按当前进度填充，宽度带过渡；
 * - 每步是一个真实 button，可键盘聚焦；只能跳到"已经到达过"的步骤。
 */
import { computed } from "vue";

const props = defineProps({
  steps: { type: Array, required: true },
  current: { type: Number, default: 1 },
  maxStep: { type: Number, default: 1 },
  disabled: { type: Boolean, default: false },
});

const emit = defineEmits(["select"]);

const activeIndex = computed(() =>
  Math.max(0, Math.min(props.steps.length - 1, props.current - 1))
);

const indicatorStyle = computed(() => ({
  width: `calc(100% / ${props.steps.length})`,
  transform: `translateX(${activeIndex.value * 100}%)`,
}));

const linePercent = computed(() => {
  if (props.steps.length <= 1) return 0;
  return (activeIndex.value / (props.steps.length - 1)) * 100;
});

function select(index) {
  const target = index + 1;
  if (props.disabled) return;
  if (target > props.maxStep) return;
  emit("select", target);
}
</script>

<template>
  <div class="setup-stepper" :class="{ 'is-disabled': disabled }">
    <div class="stepper-track" :style="{ '--step-count': steps.length }">
      <div class="stepper-line">
        <i :style="{ width: `${linePercent}%` }" />
      </div>
      <div class="stepper-indicator" :style="indicatorStyle" />

      <button
        v-for="(s, i) in steps"
        :key="s.key || i"
        type="button"
        class="stepper-item"
        :class="{
          'is-active': current === i + 1,
          'is-done': i + 1 < current,
          'is-reachable': i + 1 <= maxStep,
          'is-locked': i + 1 > maxStep,
        }"
        :disabled="disabled || i + 1 > maxStep"
        :aria-current="current === i + 1 ? 'step' : undefined"
        :title="i + 1 > maxStep ? '完成前面的步骤后才能到达' : s.title"
        @click="select(i)"
      >
        <span class="stepper-num">
          <svg
            v-if="i + 1 < current"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <span v-else-if="current === i + 1" class="stepper-dot" />
          <span v-else>{{ i + 1 }}</span>
        </span>
        <span class="stepper-text">
          <b>{{ s.title }}</b>
          <small>{{ s.desc }}</small>
        </span>
      </button>
    </div>
  </div>
</template>
