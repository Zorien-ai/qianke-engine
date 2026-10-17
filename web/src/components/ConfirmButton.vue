<script setup>
/**
 * 二次确认按钮：第一次点击进入"确认"态，5 秒内再点才 emit("confirm")。
 * 比 window.confirm 轻，也避免误点破坏性操作。
 */
import { onBeforeUnmount, ref } from "vue";

const props = defineProps({
  label: { type: String, required: true },
  confirmText: { type: String, default: "确认？" },
  kind: { type: String, default: "ghost" }, // ghost | danger | primary
  disabled: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
});
const emit = defineEmits(["confirm"]);

const armed = ref(false);
let timer = null;

function onClick() {
  if (props.disabled || props.busy) return;
  if (!armed.value) {
    armed.value = true;
    clearTimeout(timer);
    timer = setTimeout(() => (armed.value = false), 5000);
    return;
  }
  clearTimeout(timer);
  armed.value = false;
  emit("confirm");
}

onBeforeUnmount(() => clearTimeout(timer));
</script>

<template>
  <button
    type="button"
    class="btn"
    :class="[kind === 'danger' ? 'btn-danger' : kind === 'primary' ? 'btn-primary' : 'btn-ghost', { 'is-armed': armed }]"
    :disabled="disabled || busy"
    @click="onClick"
  >
    <span v-if="busy" class="spinner spinner-sm" />
    {{ busy ? "处理中…" : armed ? confirmText : label }}
  </button>
</template>
