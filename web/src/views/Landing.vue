<script setup>
/**
 * 官网 Landing Page（`/v2/#/home`，公开可匿名访问）。
 *
 * task-12：首屏改为左右 50/50 的「七秒叙事动画」——
 *   0–2s   暗金星云呼吸 → 中央毛玻璃搜索框浮现 + 打字机逐字输入
 *   2–4.5s 搜索框收缩吸入中心，AI 高亮 + 数据标签飞过
 *   4.5–6s 粒子重组为玻璃结果卡（演示数据）
 *   6–7s   星云恢复呼吸，左侧标题/副标题/按钮 stagger 登场
 * 结束后固定最终态，不循环；刷新重放。
 * 时间轴由 Vue 状态机 + setTimeout 驱动；页面隐藏时暂停、回来按已用时间续播；
 * onBeforeUnmount 清理所有 timer；prefers-reduced-motion 直接最终静态排版（无 timer）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { postJson } from "../api";
import { refreshWhoami, store, toast } from "../store";
import HeroNebula from "../components/landing/HeroNebula.vue";
import LanguageToggle from "../components/LanguageToggle.vue";
import ThemeToggle from "../components/ThemeToggle.vue";
import Logo from "../components/Logo.vue";
import wechatQr from "../assets/wechat-qr.png";
import "../styles/landing.css";

const shotModules = import.meta.glob("../assets/shots/*.png", { eager: true, import: "default" });
const shot = (name) => shotModules[`../assets/shots/${name}.png`] || "";

const router = useRouter();
const isAuthed = computed(() => !!store.authenticated);
const demoStarting = ref(false);

async function startDemo() {
  if (demoStarting.value) return;
  demoStarting.value = true;
  try {
    await postJson("/api/auth/demo-login", {});
    await refreshWhoami();
    toast("已进入演示体验模式（只读）", "info", 3200);
    await router.push("/chat");
  } catch (e) {
    toast((e && (e.detail || e.message)) || "演示体验暂不可用，请稍后再试", "error", 5200);
  } finally {
    demoStarting.value = false;
  }
}

/* ==================== 官网 CTA 弹窗（文档 / 私有化部署） ==================== */
const GITHUB_URL = "https://github.com/Zorien-ai/qianke-engine";
const CONTACT_EMAIL = "contact@qianke-engine.com";
const TERMINAL_COMMAND = `git clone ${GITHUB_URL}.git
cd qianke-engine
docker-compose up -d`;
const docsOpen = ref(false);
const deployOpen = ref(false);
const copied = ref(false);
let copyTimer = null;
let bodyOverflow = "";
let bodyLocked = false;

function closeModals() {
  docsOpen.value = false;
  deployOpen.value = false;
}

function onModalKeydown(event) {
  if (event.key === "Escape") closeModals();
}

async function copyTerminalCommand() {
  try {
    await navigator.clipboard.writeText(TERMINAL_COMMAND);
    copied.value = true;
    if (copyTimer) clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      copied.value = false;
    }, 1600);
  } catch (err) {
    /* 剪贴板被浏览器禁用时静默降级：终端代码仍可直接选中复制 */
  }
}

watch([docsOpen, deployOpen], ([docs, deploy]) => {
  const open = docs || deploy;
  // 不能把「原 overflow 是否为空」当作锁状态：Landing 原本通常就是 ""，
  // 一旦用它判断，关闭时条件永远不成立，页面会永久停在 overflow:hidden。
  if (open && !bodyLocked) {
    bodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    bodyLocked = true;
  } else if (!open && bodyLocked) {
    document.body.style.overflow = bodyOverflow;
    bodyOverflow = "";
    bodyLocked = false;
  }
});


/* ==================== 对话式叙事时间轴（task-15，约 8.2s） ==================== */
const QUESTION = "找出最近一个月高客单的美妆女性用户";
const TYPE_MS = 80;
const TYPING_START_MS = 120;
const BASE_EVENTS = [
  { at: 1600, stage: "send" },
  { at: 2400, stage: "process" },
  { at: 4400, stage: "cards" },
  { at: 6000, stage: "return" },
  { at: 7000, stage: "final" },
  { at: 8200, stage: "done" },
];
const FALLBACK_USERS = [
  {
    uid: "U7380",
    gender: "女",
    age: 25,
    member_level: "白银",
    order_count: 4,
    avg_amount: 3105.37,
    top_category: "美妆",
    city: "成都",
    days_since_last_buy: 29,
  },
  {
    uid: "U6126",
    gender: "女",
    age: 30,
    member_level: "普通",
    order_count: 4,
    avg_amount: 2453.93,
    top_category: "美妆",
    city: "广州",
    days_since_last_buy: 13,
  },
  {
    uid: "U4911",
    gender: "女",
    age: 35,
    member_level: "普通",
    order_count: 2,
    avg_amount: 2244.6,
    top_category: "美妆",
    city: "广州",
    days_since_last_buy: 24,
  },
  {
    uid: "U3790",
    gender: "女",
    age: 30,
    member_level: "普通",
    order_count: 2,
    avg_amount: 1780.99,
    top_category: "美妆",
    city: "成都",
    days_since_last_buy: 1,
  },
];

function prefersReducedMotion() {
  return !!(
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const reducedMotion = ref(prefersReducedMotion());
const stage = ref("typing");
const typed = ref("");
const copyVisible = ref(false);

/* ==================== demo 用户数据（匿名只读接口，失败静默降级） ==================== */
const DEFAULT_LABELS = ["女 / 28 岁", "客单价 1200", "偏好美妆"];
const DEFAULT_QUERY = { matched: 2341, avg_amount: 1540, age_min: 25, age_max: 35 };
const demoData = ref(null);

const demoUsers = computed(() => (Array.isArray(demoData.value?.users) ? demoData.value.users : []));
const demoMatchedUsers = computed(() =>
  Array.isArray(demoData.value?.matched_users) ? demoData.value.matched_users : []
);
const demoLabels = computed(() => {
  const labels = demoData.value?.labels;
  return Array.isArray(labels) && labels.length ? labels.slice(0, 3) : DEFAULT_LABELS;
});
const demoQuery = computed(() => demoData.value?.query || DEFAULT_QUERY);
const totalProfiles = computed(() =>
  Number.isFinite(demoData.value?.total_profiles) ? demoData.value.total_profiles : null
);

function formatInt(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return Math.round(n).toLocaleString("zh-CN");
}

const matchedDisplay = computed(() => formatInt(demoQuery.value.matched));
const avgAmountDisplay = computed(() => formatInt(Math.floor(Number(demoQuery.value.avg_amount))));
const ageRangeDisplay = computed(
  () => `${demoQuery.value.age_min ?? 25}-${demoQuery.value.age_max ?? 35}`
);
const totalProfilesDisplay = computed(() =>
  totalProfiles.value == null ? "" : formatInt(totalProfiles.value)
);
const legendText = computed(() =>
  totalProfiles.value == null
    ? "每个光点，都是一位 demo 用户"
    : `每个光点，都是一位 demo 用户 · 共 ${totalProfilesDisplay.value} 位`
);

/* 4 张用户卡：优先 matched_users（任务要求取前 4），不足用 users 兜底，仍不足用静默 fallback */
const storyCards = computed(() => {
  const pool = [];
  const seen = new Set();
  const push = (u) => {
    if (!u || !u.uid || seen.has(u.uid)) return;
    seen.add(u.uid);
    pool.push(u);
  };
  demoMatchedUsers.value.forEach((u) => {
    if (pool.length < 4) push(u);
  });
  demoUsers.value.forEach((u) => {
    if (pool.length < 4) push(u);
  });
  FALLBACK_USERS.forEach((u) => {
    if (pool.length < 4) push(u);
  });
  return pool.slice(0, 4);
});

function formatCardAmount(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return Math.round(n).toLocaleString("zh-CN");
}

function genderSymbol(gender) {
  if (gender === "女") return "♀";
  if (gender === "男") return "♂";
  return "·";
}

const answerVisible = computed(() => stage.value === "return" || stage.value === "final");
const humanMessageVisible = computed(() =>
  ["process", "cards", "return", "final"].includes(stage.value)
);
const cardsMounted = computed(() =>
  stage.value === "cards" || stage.value === "return" || stage.value === "final"
);
const cardsSettled = computed(() => stage.value === "final");
const nebulaStage = computed(() => {
  if (stage.value === "typing" || stage.value === "send") return "search";
  if (stage.value === "process") return "absorb";
  return "final";
});

async function fetchDemoUsers() {
  try {
    const res = await fetch("/api/public/demo/users?limit=400", {
      headers: { accept: "application/json" },
      credentials: "same-origin",
    });
    if (!res.ok) return;
    const data = await res.json();
    if (data && Array.isArray(data.users) && data.users.length) {
      demoData.value = data;
    }
  } catch (err) {
    /* 静默降级：接口不可用时保持现有硬编码文案 */
  }
}

let storyStart = 0;
let pausedTotal = 0;
let pausedAt = 0;
let typingTimer = null;
let debugTimer = null;
let timers = [];
let storyDone = ref(false);
let timelineEvents = BASE_EVENTS.slice();

function clearStoryTimers() {
  timers.forEach((id) => clearTimeout(id));
  timers = [];
  if (typingTimer) {
    clearInterval(typingTimer);
    typingTimer = null;
  }
}

function elapsedMs() {
  if (!storyStart) return 0;
  const paused = pausedAt ? performance.now() - pausedAt : 0;
  return performance.now() - storyStart - pausedTotal - paused;
}

function syncDebug() {
  const e = Math.max(0, elapsedMs() / 1000);
  window.__heroStoryDebug = {
    phase: stage.value,
    elapsed: Number(e.toFixed(2)),
    cards: cardsMounted.value ? 4 : 0,
  };
}

function startTyping() {
  if (typingTimer) clearInterval(typingTimer);
  // 用「已用时间」反推打字进度，而不是逐次累加：SwiftShader 下主线程被渲染占用时也不会漏字
  typingTimer = setInterval(() => {
    const since = elapsedMs() - TYPING_START_MS;
    const len = Math.max(0, Math.min(QUESTION.length, Math.floor(since / TYPE_MS) + 1));
    if (typed.value.length !== len) typed.value = QUESTION.slice(0, len);
    if (len >= QUESTION.length) {
      clearInterval(typingTimer);
      typingTimer = null;
    }
  }, 45);
}

function applyStage(next) {
  if (next === "done") {
    storyDone.value = true;
    copyVisible.value = true;
    clearStoryTimers();
    stage.value = "final";
    syncDebug();
    return;
  }
  stage.value = next;
  if (next === "final") copyVisible.value = true;
  syncDebug();
}

function scheduleFrom(elapsed) {
  clearStoryTimers();
  // 打字机：120ms 后开始（1.6s 时应有完整问题）
  if (stage.value === "typing" && typed.value.length < QUESTION.length) {
    const delay = Math.max(0, TYPING_START_MS - elapsed);
    timers.push(
      setTimeout(() => {
        startTyping();
      }, delay)
    );
  }
  for (const ev of timelineEvents) {
    if (ev.at <= elapsed) continue;
    timers.push(
      setTimeout(() => {
        applyStage(ev.stage);
      }, ev.at - elapsed)
    );
  }
}

/* 发送按钮：typing 阶段点击可提前发送；done 后点击重播整段 */
function onSendClick() {
  if (storyDone.value) {
    replayStory();
    return;
  }
  if (stage.value !== "typing") return;
  const anchor = elapsedMs();
  typed.value = QUESTION;
  clearStoryTimers();
  timelineEvents = [
    { at: anchor, stage: "send" },
    { at: anchor + 800, stage: "process" },
    { at: anchor + 2800, stage: "cards" },
    { at: anchor + 4400, stage: "return" },
    { at: anchor + 5400, stage: "final" },
    { at: anchor + 6600, stage: "done" },
  ];
  applyStage("send");
  scheduleFrom(anchor + 1);
}

function replayStory() {
  clearStoryTimers();
  storyStart = performance.now();
  pausedTotal = 0;
  pausedAt = 0;
  typed.value = "";
  copyVisible.value = false;
  storyDone.value = false;
  stage.value = "typing";
  timelineEvents = BASE_EVENTS.slice();
  if (reducedMotion.value) {
    finishStatic();
    return;
  }
  scheduleFrom(0);
  syncDebug();
}

/* QA 冻结钩子：截图验收时冻结时间轴 + CSS 动画 + Canvas rAF，保证时间点准确 */
function freezeStoryForQa() {
  if (!storyStart) return;
  if (!pausedAt) {
    pausedAt = performance.now();
    clearStoryTimers();
  }
  try {
    document.getAnimations().forEach((anim) => {
      try {
        anim.pause();
      } catch (e) {
        /* ignore */
      }
    });
  } catch (e) {
    /* ignore */
  }
  if (typeof window.__nebulaPause === "function") window.__nebulaPause();
}

function resumeStoryForQa() {
  if (!pausedAt) return;
  pausedTotal += performance.now() - pausedAt;
  pausedAt = 0;
  try {
    document.getAnimations().forEach((anim) => {
      try {
        anim.play();
      } catch (e) {
        /* ignore */
      }
    });
  } catch (e) {
    /* ignore */
  }
  if (typeof window.__nebulaResume === "function") window.__nebulaResume();
  if (!storyDone.value) scheduleFrom(elapsedMs());
}

function onVisibilityChange() {
  if (reducedMotion.value || storyDone.value) return;
  if (document.hidden) {
    if (!pausedAt) {
      pausedAt = performance.now();
      clearStoryTimers();
    }
  } else if (pausedAt) {
    pausedTotal += performance.now() - pausedAt;
    pausedAt = 0;
    const elapsed = elapsedMs();
    const passed = timelineEvents.filter((ev) => ev.at <= elapsed);
    if (passed.length) {
      const last = passed[passed.length - 1];
      applyStage(last.stage === "done" ? "final" : last.stage);
      if (last.stage === "done") {
        storyDone.value = true;
        clearStoryTimers();
        return;
      }
    }
    scheduleFrom(elapsed);
  }
}

function finishStatic() {
  storyDone.value = true;
  stage.value = "final";
  typed.value = QUESTION;
  copyVisible.value = true;
  window.__heroStoryDebug = { phase: "final", elapsed: 0, cards: 4 };
}

function startStory() {
  storyStart = performance.now();
  pausedTotal = 0;
  pausedAt = 0;
  stage.value = "typing";
  typed.value = "";
  copyVisible.value = false;
  storyDone.value = false;
  timelineEvents = BASE_EVENTS.slice();

  if (reducedMotion.value) {
    finishStatic();
    return;
  }

  scheduleFrom(0);
  debugTimer = setInterval(syncDebug, 100);
  syncDebug();
  document.addEventListener("visibilitychange", onVisibilityChange);
}

/* ==================== 顶部导航 / 锚点 ==================== */
const navScrolled = ref(false);
const navDark = ref(true);
const heroRef = ref(null);
// 舞台 DOM 传给 HeroNebula：悬停画像 tooltip 要 Teleport 到这一层，
// 否则 .nebula 的 z-index:0 stacking context 会让它被结果卡（z-index:4）盖住
const heroStageEl = ref(null);

function navHeight() {
  return window.innerWidth <= 900 ? 62 : 68;
}
function updateNavState() {
  const y = window.scrollY || 0;
  navScrolled.value = y > 10;
  const hero = heroRef.value;
  if (!hero) {
    navDark.value = false;
    return;
  }
  navDark.value = hero.getBoundingClientRect().bottom > navHeight() + 10;
}
function scrollTo(selector) {
  const node = document.querySelector(selector);
  if (!node) return;
  const top = node.getBoundingClientRect().top + window.scrollY - navHeight() - 10;
  window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
}

/* ==================== 滚动淡入 ==================== */
const vReveal = {
  mounted(el) {
    el.classList.add("reveal");
    if (typeof window === "undefined") return;
    const reduce =
      window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) {
      el.classList.add("is-visible");
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.18, rootMargin: "0px 0px -8% 0px" }
    );
    io.observe(el);
    el.__revealObserver = io;
  },
  unmounted(el) {
    if (el.__revealObserver) el.__revealObserver.disconnect();
  },
};

/* ==================== 页面内容 ==================== */
const navLinks = [
  { label: "产品", target: "#product" },
  { label: "安全", target: "#security" },
];

const scenes = [
  {
    key: "setup",
    index: "01",
    url: "/v2/#/setup",
    img: shot("setup"),
    alt: "数据导入：拖拽上传 CSV 与规则文档",
    title: "拖拽上传，即插即用。",
    highlightStyle: { top: "45.5%", left: "21.5%", width: "73.3%", height: "19.3%" },
    highlightLabel: "拖拽上传",
  },
  {
    key: "chat",
    index: "02",
    url: "/v2/#/chat",
    img: shot("chat"),
    alt: "AI 对话：双轨检索与可溯源引用",
    title: "双轨检索，有据可查。",
    highlightStyle: { top: "57.8%", left: "21.5%", width: "73.3%", height: "33.3%" },
    highlightLabel: "引用来源 · 逐条可溯源",
  },
  {
    key: "kb",
    index: "03",
    url: "/v2/#/kb",
    img: shot("kb"),
    alt: "知识库：增量更新与数据状态",
    title: "增量更新，秒级响应。",
    highlightStyle: { top: "33.3%", left: "20.2%", width: "76.5%", height: "10%" },
    highlightLabel: "数据状态 · 常新",
  },
];

let motionQuery = null;
let storyStarted = false;
let storySafetyTimer = null;
let storyBeginHandler = null;
function onMotionChange() {
  const reduce = prefersReducedMotion();
  if (reduce === reducedMotion.value) return;
  reducedMotion.value = reduce;
  clearStoryTimers();
  if (debugTimer) {
    clearInterval(debugTimer);
    debugTimer = null;
  }
  document.removeEventListener("visibilitychange", onVisibilityChange);
  if (reduce) {
    stage.value = "final";
    typed.value = QUESTION;
    copyVisible.value = true;
    window.__heroStoryDebug = { phase: "final", elapsed: 0, cards: 1 };
  } else {
    startStory();
  }
}

onMounted(() => {
  motionQuery =
    typeof window !== "undefined" && window.matchMedia
      ? window.matchMedia("(prefers-reduced-motion: reduce)")
      : null;
  if (motionQuery) {
    if (motionQuery.addEventListener) motionQuery.addEventListener("change", onMotionChange);
    else if (motionQuery.addListener) motionQuery.addListener(onMotionChange);
  }
  fetchDemoUsers();
  // 等 WebGL 星云初始化完成再启动 7s 时间轴，避免 shader 编译阻塞把打字/分镜时间点挤在一起
  const beginStory = () => {
    if (storyStarted) return;
    storyStarted = true;
    if (storySafetyTimer) {
      clearTimeout(storySafetyTimer);
      storySafetyTimer = null;
    }
    startStory();
  };
  window.addEventListener("hero-nebula-ready", beginStory, { once: true });
  storyBeginHandler = beginStory;
  storySafetyTimer = setTimeout(beginStory, 4000);
  if (reducedMotion.value) beginStory();
  window.addEventListener("scroll", updateNavState, { passive: true });
  window.addEventListener("resize", updateNavState);
  window.addEventListener("keydown", onModalKeydown);
  updateNavState();
  window.__heroFreeze = freezeStoryForQa;
  window.__heroResume = resumeStoryForQa;
  document.title = "千客引擎 · 让你的电商数据，听懂中国话";
});

onBeforeUnmount(() => {
  clearStoryTimers();
  if (storySafetyTimer) {
    clearTimeout(storySafetyTimer);
    storySafetyTimer = null;
  }
  if (storyBeginHandler) {
    window.removeEventListener("hero-nebula-ready", storyBeginHandler);
    storyBeginHandler = null;
  }
  if (debugTimer) {
    clearInterval(debugTimer);
    debugTimer = null;
  }
  document.removeEventListener("visibilitychange", onVisibilityChange);
  if (motionQuery) {
    if (motionQuery.removeEventListener) motionQuery.removeEventListener("change", onMotionChange);
    else if (motionQuery.removeListener) motionQuery.removeListener(onMotionChange);
  }
  window.removeEventListener("scroll", updateNavState);
  window.removeEventListener("resize", updateNavState);
  window.removeEventListener("keydown", onModalKeydown);
  if (copyTimer) {
    clearTimeout(copyTimer);
    copyTimer = null;
  }
  if (bodyLocked) {
    document.body.style.overflow = bodyOverflow;
    bodyOverflow = "";
    bodyLocked = false;
  }
  delete window.__heroFreeze;
  delete window.__heroResume;
});
</script>

<template>
  <div class="landing">
    <!-- ============ 极简导航（Hero 上透明亮色，滚出后浅色吸顶） ============ -->
    <header class="l-nav" :class="{ 'is-dark': navDark, 'is-scrolled': navScrolled }">
      <div class="l-shell l-nav-inner">
        <RouterLink to="/home" class="l-brand" aria-label="千客引擎（Qianke Engine）官网首页">
          <Logo :size="30" :show-text="false" class="l-logo-slot" />
          <span class="l-brand-text"><b>千客引擎</b></span>
        </RouterLink>

        <nav class="l-nav-links" aria-label="页面导航">
          <button
            v-for="link in navLinks"
            :key="link.target"
            type="button"
            class="l-nav-link"
            @click="scrollTo(link.target)"
          >
            {{ link.label }}
          </button>
        </nav>

        <div class="l-nav-actions">
          <ThemeToggle class="l-nav-theme" />
          <LanguageToggle class="l-nav-lang" />
          <a href="/docs" target="_blank" rel="noopener" class="l-nav-link l-nav-doc" @click.prevent="docsOpen = true">文档</a>
          <a v-if="!isAuthed" href="/login" class="l-nav-login">登录</a>
          <RouterLink v-else to="/" class="l-btn l-btn-primary l-btn-sm">进入工作台</RouterLink>
        </div>
      </div>
    </header>

    <main>
      <!-- ============ Hero：左右 50/50 + 七秒叙事动画 ============ -->
      <section ref="heroRef" class="l-hero">
        <div class="l-shell l-hero-split">
          <!-- 左：文案（初始隐藏，6s 后 stagger 登场；result 起轻微左移视差） -->
          <div
            class="l-hero-copy"
            :class="{
              'is-in': copyVisible,
              'is-shifted': stage === 'return' || stage === 'final',
            }"
          >
            <h1 class="l-hero-title">
              让你的电商数据，<br />
              <span>听懂中国话。</span>
            </h1>
            <p class="l-hero-sub">无需 SQL 的 AI 用户画像助理</p>
            <div class="l-hero-actions">
              <RouterLink v-if="isAuthed" to="/" class="l-btn l-btn-primary l-btn-lg">
                进入工作台
              </RouterLink>
              <button
                v-else
                type="button"
                class="l-btn l-btn-primary l-btn-lg"
                :disabled="demoStarting"
                @click="startDemo"
              >
                {{ demoStarting ? "正在进入体验…" : "免费体验 Demo" }}
              </button>
              <button type="button" class="l-btn l-btn-ghost l-btn-lg" @click="docsOpen = true">
                查看文档
              </button>
            </div>
          </div>

          <!-- 右：对话式叙事舞台（星云 + 输入/发送 + 用户卡 + 返回答案） -->
          <div ref="heroStageEl" class="l-hero-stage">
            <HeroNebula
              :stage="nebulaStage"
              :reduced-motion="reducedMotion"
              :users="demoUsers"
              :matched-users="demoMatchedUsers"
              :tooltip-target="heroStageEl"
            />

            <!-- Phase 1：顶部「你」的毛玻璃输入框 + 圆形发送按钮 -->
            <div class="chat-dock" :class="{ 'is-sent': stage !== 'typing' }">
              <div class="chat-input" aria-hidden="true">
                <span class="chat-avatar">你</span>
                <span class="chat-text">{{ typed }}<i class="chat-caret" /></span>
              </div>
              <span v-if="storyDone" class="chat-replay-hint">重播演示</span>
              <button
                type="button"
                class="chat-send"
                :class="{
                  'is-firing': stage === 'send',
                  'is-replay': storyDone,
                  'is-hidden': ['process', 'cards', 'return', 'final'].includes(stage) && !storyDone,
                }"
                :aria-label="storyDone ? '重播演示' : '发送问题'"
                :title="storyDone ? '重播演示' : '发送'"
                @click="onSendClick"
              >
                <svg v-if="!storyDone" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 19V5" />
                  <path d="m5 12 7-7 7 7" />
                </svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 12a9 9 0 1 1-3.5-7.1" />
                  <path d="M21 3v6h-6" />
                </svg>
                <span class="chat-send-ripple" aria-hidden="true" />
              </button>
            </div>

            <!-- 发送落地后：顶部保留「你」的问题气泡，形成「你问 → 千客答」的对话结构 -->
            <div v-if="humanMessageVisible" class="human-msg" aria-hidden="true">
              <span class="chat-avatar">你</span>
              <span class="human-bubble">{{ QUESTION }}</span>
            </div>

            <!-- Phase 2：问题胶囊沿弧线飞向星云中心（同一条消息的克隆） -->
            <div v-if="stage === 'send'" class="chat-capsule" aria-hidden="true">
              {{ QUESTION }}<i class="chat-capsule-tail" />
            </div>

            <!-- Phase 3：星云处理中 -->
            <div v-if="stage === 'process'" class="process-row" aria-hidden="true">
              <span>星云处理中</span>
              <i></i><i></i><i></i>
            </div>

            <!-- Phase 4：星云吐出 4 张 demo 用户画像卡 -->
            <div v-if="cardsMounted" class="user-cards" :class="{ 'is-settled': cardsSettled }" aria-hidden="true">
              <div
                v-for="(user, i) in storyCards"
                :key="user.uid + i"
                class="u-card"
                :class="{ 'is-final': cardsSettled }"
              >
                <span class="u-avatar">{{ genderSymbol(user.gender) }}</span>
                <span class="u-info">
                  <b class="u-uid">{{ user.uid }}</b>
                  <span class="u-meta">{{ user.gender }} · {{ user.age }} 岁</span>
                  <span class="u-amount">客单价 ¥{{ formatCardAmount(user.avg_amount) }}</span>
                  <span class="u-tag">{{ user.member_level }}<template v-if="user.top_category"> · 偏好{{ user.top_category }}</template></span>
                </span>
              </div>
              <span class="u-card-more">共 4 位 demo 用户</span>
            </div>

            <!-- Phase 5：返回胶囊沿弧线飞向答案槽 -->
            <div v-if="stage === 'return'" class="return-pill" aria-hidden="true">
              返回<i class="return-tail" /><i class="return-spark" />
            </div>

            <!-- Phase 5/6：星云返回的答案卡（真实 demo 统计） -->
            <div
              v-if="answerVisible"
              class="story-result answer-card"
              :class="{ 'is-in': answerVisible }"
              aria-hidden="true"
            >
              <div class="answer-head">
                <span class="story-result-role">千客</span>
                <span class="story-result-badge">演示</span>
              </div>
              <p class="story-result-title">已匹配 <b>{{ matchedDisplay }}</b> 位用户</p>
              <p class="story-result-body">
                核心特征：{{ ageRangeDisplay }} 岁，客单价均值 <b>{{ avgAmountDisplay }}</b> 元。
              </p>
              <span class="story-result-glow" aria-hidden="true" />
            </div>

            <!-- 图例：让「一颗光点 = 一位 demo 用户」这件事一眼看懂 -->
            <p class="l-hero-legend">
              <i class="l-hero-legend-dot" />
              {{ legendText }}
              <span class="l-hero-legend-hint">悬停 / 点击查看画像</span>
            </p>
          </div>
        </div>
      </section>

      <!-- ============ 产品：三张大图 + 三行标题 ============ -->
      <section id="product" class="l-showcase">
        <div class="l-shell l-showcase-list">
          <article
            v-for="(scene, i) in scenes"
            :key="scene.key"
            class="l-show-row"
            :class="{ 'is-reverse': i % 2 === 1 }"
          >
            <div class="l-show-media" v-reveal>
              <div class="l-mac">
                <div class="l-mac-bar">
                  <span class="l-mac-dots"><i /><i /><i /></span>
                  <span class="l-mac-url">{{ scene.url }}</span>
                  <span class="l-mac-dots l-mac-dots-end"><i /><i /><i /></span>
                </div>
                <div class="l-mac-body">
                  <img
                    v-if="scene.img"
                    class="l-shot"
                    :src="scene.img"
                    :alt="scene.alt"
                    loading="lazy"
                    decoding="async"
                  />
                  <div v-else class="l-shot-placeholder">
                    <span class="l-shot-placeholder-tag">真机截图</span>
                  </div>
                  <div class="l-highlight" :style="scene.highlightStyle">
                    <span class="l-highlight-label">{{ scene.highlightLabel }}</span>
                  </div>
                </div>
              </div>
            </div>

            <h2 class="l-show-title" v-reveal :style="{ '--reveal-delay': '140ms' }">
              <span class="l-show-index">{{ scene.index }}</span>
              <span>{{ scene.title }}</span>
            </h2>
          </article>
        </div>
      </section>

      <!-- ============ 痛点：两对大字报 ============ -->
      <section id="pain" class="l-pain">
        <div class="l-shell l-pain-list">
          <div class="l-pain-item" v-reveal>
            <p class="l-pain-q">懂技术的太贵？</p>
            <p class="l-pain-a">招个分析师，<br class="l-br-mobile" />不如直接问 AI。</p>
          </div>
          <div class="l-pain-item is-reverse" v-reveal :style="{ '--reveal-delay': '160ms' }">
            <p class="l-pain-q">传统 BI 太难用？</p>
            <p class="l-pain-a">别让运营对着复杂的<br class="l-br-mobile" />报表发呆。</p>
          </div>
        </div>
      </section>

      <!-- ============ 私有化：一句 Slogan + 一个按钮 ============ -->
      <section id="security" class="l-private">
        <div class="l-shell l-private-inner" v-reveal>
          <h2 class="l-private-slogan">100% 私有化，数据绝不外传。</h2>
          <button type="button" class="l-btn l-btn-primary l-btn-lg" @click="deployOpen = true">
            预约私有化部署
          </button>
        </div>
      </section>
    </main>

    <!-- ============ Footer ============ -->
    <footer class="l-footer">
      <div class="l-shell l-footer-inner">
        <span class="l-footer-brand">© 2026 千客引擎</span>
        <nav class="l-footer-links" aria-label="页脚链接">
          <a href="/docs" target="_blank" rel="noopener">产品文档</a>
          <a v-if="!isAuthed" href="/login">登录</a>
          <RouterLink v-else to="/">进入工作台</RouterLink>
        </nav>
      </div>
    </footer>
    <!-- ============ 官网 CTA：开发者文档 / 私有化部署 ============ -->
    <Teleport to="body">
      <Transition name="l-modal">
        <div v-if="docsOpen" class="l-modal" role="presentation" @click.self="docsOpen = false">
          <section
            class="l-modal-panel l-doc-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="l-doc-title"
            @click.stop
          >
            <button type="button" class="l-modal-close" aria-label="关闭文档弹窗" @click="docsOpen = false">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
            <p class="l-modal-kicker">OPEN SOURCE · DEVELOPER DOCS</p>
            <h2 id="l-doc-title" class="l-modal-title">千客引擎：开发者文档</h2>
            <p class="l-modal-lead">
              从源码到部署，一条命令把千客引擎跑起来。开源、可私有化，数据始终留在你自己的基础设施里。
            </p>
            <a class="l-github-cta" :href="GITHUB_URL" target="_blank" rel="noopener">
              <svg class="l-github-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 .5C5.7.5.7 5.6.7 11.9c0 5 3.2 9.3 7.7 10.8.6.1.8-.3.8-.6v-2.1c-3.1.7-3.8-1.3-3.8-1.3-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.1.1 1.7 1.2 1.7 1.2 1 1.7 2.6 1.2 3.3.9.1-.7.4-1.2.7-1.5-2.5-.3-5.1-1.3-5.1-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.6 5.4-5.1 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6 4.5-1.5 7.7-5.8 7.7-10.8C23.3 5.6 18.3.5 12 .5Z" />
              </svg>
              <span>🚀 前往 GitHub 仓库查看完整源码与部署指南</span>
              <svg class="l-github-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </a>
            <div class="l-terminal">
              <div class="l-terminal-bar">
                <span class="l-terminal-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                <span class="l-terminal-title">快速开始</span>
                <button type="button" class="l-terminal-copy" @click="copyTerminalCommand">
                  {{ copied ? "已复制" : "复制" }}
                </button>
              </div>
              <pre><code>{{ TERMINAL_COMMAND }}</code></pre>
            </div>
            <p class="l-modal-foot">Apache-2.0 · 支持完全离线 / 内网部署</p>
          </section>
        </div>
      </Transition>
    </Teleport>

    <Teleport to="body">
      <Transition name="l-modal">
        <div v-if="deployOpen" class="l-modal" role="presentation" @click.self="deployOpen = false">
          <section
            class="l-modal-panel l-deploy-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="l-deploy-title"
            @click.stop
          >
            <button type="button" class="l-modal-close" aria-label="关闭私有化部署弹窗" @click="deployOpen = false">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
            <p class="l-modal-kicker">PRIVATE DEPLOYMENT · 1:1</p>
            <h2 id="l-deploy-title" class="l-modal-title">获取 100% 私有化部署方案</h2>
            <p class="l-modal-lead">
              千客引擎支持完全内网部署，数据不出门。添加开发者，获取一对一部署指导。
            </p>
            <div class="l-qr-card">
              <div class="l-qr-frame">
                <img :src="wechatQr" alt="千客引擎开发者微信二维码" />
              </div>
              <p class="l-qr-caption">扫码添加开发者微信</p>
              <span class="l-qr-hint">备注「私有化部署」优先通过</span>
            </div>
            <a class="l-modal-mail" :href="`mailto:${CONTACT_EMAIL}`">
              或发送邮件至 {{ CONTACT_EMAIL }}
            </a>
          </section>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
