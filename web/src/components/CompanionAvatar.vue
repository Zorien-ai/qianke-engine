<template>
  <button
    ref="host"
    type="button"
    class="companion-avatar"
    :style="{ width: `${size}px`, height: `${size}px` }"
    :aria-label="label"\n    :data-state="state"
    :title="label"
    @click="handlePoke"
  >
    <span class="companion-avatar-fallback" aria-hidden="true">
      {{ fallback }}
    </span>
  </button>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps({
  size: { type: Number, default: 34 },
  state: { type: String, default: "idle" },
  follow: { type: Boolean, default: true },
  fallback: { type: String, default: "小" },
  label: { type: String, default: "和小鱼互动" },
});
const emit = defineEmits(["poke"]);
const host = ref(null);
let bot = null;
let cancelled = false;

onMounted(async () => {
  try {
    const [player, recipes] = await Promise.all([
      import("../vendor/grokbot/grok-player.js"),
      import("../vendor/grokbot/grok-recipes.json"),
    ]);
    if (cancelled || !host.value) return;
    bot = player.createGrokBot(host.value, {
      size: props.size,
      state: props.state,
      data: recipes.default,
      seed: 7,
      follow: props.follow,
      theme: {
        ink: [0.12, 0.105, 0.086],
        spot: [0.85, 0.37, 0.23],
        cutout: true,
      },
    });
    bot.ready?.catch(() => {});
  } catch (error) {
    console.warn("[companion-avatar] GrokBot 加载失败", error);
  }
});

watch(
  () => props.state,
  (value) => {
    bot?.setState(value || "idle");
  },
);

onBeforeUnmount(() => {
  cancelled = true;
  bot?.destroy();
  bot = null;
});

function handlePoke() {
  bot?.poke("bounce");
  bot?.blink();
  emit("poke");
}
</script>

<style scoped>
.companion-avatar {
  position: relative;
  display: inline-grid;
  flex: none;
  place-items: center;
  overflow: hidden;
  padding: 0;
  border: 1px solid var(--c-line, #e4dccd);
  border-radius: 50%;
  background: var(--c-bg-soft, #fffdf8);
  color: var(--c-text-2, #6b6258);
  cursor: pointer;
}

.companion-avatar:hover {
  border-color: var(--c-accent, #d95f3b);
}

.companion-avatar:focus-visible {
  outline: 2px solid var(--c-accent, #d95f3b);
  outline-offset: 2px;
}

.companion-avatar-fallback {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 11px;
  pointer-events: none;
}

.companion-avatar :deep(svg) {
  position: relative;
  z-index: 1;
  display: block;
  width: 100%;
  height: 100%;
}
</style>


