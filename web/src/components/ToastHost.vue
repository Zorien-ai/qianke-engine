<script setup>
/**
 * 轻提示：右下角浮层，由 store.toast() 推入，自动消失。
 * 错误提示停留更久、可手动点掉。
 */
import { store } from "../store";

const ICONS = { info: "i", success: "✓", error: "!", warn: "!" };
</script>

<template>
  <div class="toast-host" aria-live="polite">
    <transition-group name="toast">
      <div
        v-for="t in store.toasts"
        :key="t.id"
        class="toast"
        :class="`is-${t.type}`"
        @click="store.toasts.splice(store.toasts.indexOf(t), 1)"
      >
        <span class="toast-icon">{{ ICONS[t.type] || "i" }}</span>
        <span class="toast-text">{{ t.message }}</span>
      </div>
    </transition-group>
  </div>
</template>
