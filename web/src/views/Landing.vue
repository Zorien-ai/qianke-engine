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
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { store } from "../store";
import HeroNebula from "../components/landing/HeroNebula.vue";
import "../styles/landing.css";

const shotModules = import.meta.glob("../assets/shots/*.png", { eager: true, import: "default" });
const shot = (name) => shotModules[`../assets/shots/${name}.png`] || "";

const isAuthed = computed(() => !!store.authenticated);

/* ==================== 七秒叙事时间轴 ==================== */
const QUESTION = "找出最近一个月高客单的美妆女性用户";
const TYPE_MS = 35;
const EVENTS = [
  { at: 2000, stage: "absorb" },
  { at: 4500, stage: "result" },
  { at: 6000, stage: "final" },
  { at: 7000, stage: "done" },
];

function prefersReducedMotion() {
  return !!(
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

const reducedMotion = ref(prefersReducedMotion());
const stage = ref("search");
const typed = ref("");
const copyVisible = ref(false);

let storyStart = 0;
let pausedTotal = 0;
let pausedAt = 0;
let typingTimer = null;
let debugTimer = null;
let timers = [];
let storyDone = false;

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
    cards: stage.value === "result" || stage.value === "final" || storyDone ? 1 : 0,
  };
}

function startTyping() {
  if (typingTimer) clearInterval(typingTimer);
  typingTimer = setInterval(() => {
    if (typed.value.length >= QUESTION.length) {
      clearInterval(typingTimer);
      typingTimer = null;
      return;
    }
    typed.value = QUESTION.slice(0, typed.value.length + 1);
  }, TYPE_MS);
}

function applyStage(next) {
  if (next === "done") {
    storyDone = true;
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
  // 打字机：等 800ms 再开始，保证 1.2s 截图时仍在逐字输入
  if (stage.value === "search" && typed.value.length < QUESTION.length) {
    const delay = Math.max(0, 800 - elapsed);
    timers.push(
      setTimeout(() => {
        startTyping();
      }, delay)
    );
  }
  for (const ev of EVENTS) {
    if (ev.at <= elapsed) continue;
    timers.push(
      setTimeout(() => {
        applyStage(ev.stage);
      }, ev.at - elapsed)
    );
  }
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
  if (!storyDone) scheduleFrom(elapsedMs());
}

function onVisibilityChange() {
  if (reducedMotion.value || storyDone) return;
  if (document.hidden) {
    if (!pausedAt) {
      pausedAt = performance.now();
      clearStoryTimers();
    }
  } else if (pausedAt) {
    pausedTotal += performance.now() - pausedAt;
    pausedAt = 0;
    const elapsed = elapsedMs();
    const passed = EVENTS.filter((ev) => ev.at <= elapsed);
    if (passed.length) {
      const last = passed[passed.length - 1];
      applyStage(last.stage === "done" ? "final" : last.stage);
      if (last.stage === "done") {
        storyDone = true;
        clearStoryTimers();
        return;
      }
    }
    scheduleFrom(elapsed);
  }
}

function startStory() {
  storyStart = performance.now();
  pausedTotal = 0;
  pausedAt = 0;
  stage.value = "search";
  typed.value = "";
  copyVisible.value = false;
  storyDone = false;

  if (reducedMotion.value) {
    stage.value = "final";
    typed.value = QUESTION;
    copyVisible.value = true;
    window.__heroStoryDebug = { phase: "final", elapsed: 0, cards: 1 };
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
  storySafetyTimer = setTimeout(beginStory, 1800);
  if (reducedMotion.value) beginStory();
  window.addEventListener("scroll", updateNavState, { passive: true });
  window.addEventListener("resize", updateNavState);
  updateNavState();
  window.__heroFreeze = freezeStoryForQa;
  window.__heroResume = resumeStoryForQa;
  document.title = "用户画像 RAG · 让你的电商数据，听懂中国话";
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
  delete window.__heroFreeze;
  delete window.__heroResume;
});
</script>

<template>
  <div class="landing">
    <!-- ============ 极简导航（Hero 上透明亮色，滚出后浅色吸顶） ============ -->
    <header class="l-nav" :class="{ 'is-dark': navDark, 'is-scrolled': navScrolled }">
      <div class="l-shell l-nav-inner">
        <RouterLink to="/home" class="l-brand" aria-label="用户画像 RAG 官网首页">
          <span class="l-logo">R</span>
          <span class="l-brand-text"><b>用户画像 RAG</b></span>
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
          <a href="/docs" target="_blank" rel="noopener" class="l-nav-link l-nav-doc">文档</a>
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
            :class="{ 'is-in': copyVisible, 'is-shifted': stage === 'result' || stage === 'final' }"
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
              <a v-else href="/login" class="l-btn l-btn-primary l-btn-lg">免费体验 Demo</a>
              <a href="/docs" target="_blank" rel="noopener" class="l-btn l-btn-ghost l-btn-lg">
                查看文档
              </a>
            </div>
          </div>

          <!-- 右：叙事舞台（Canvas 星云只在这个 50% 列内播放 + DOM 玻璃拟态） -->
          <div class="l-hero-stage">
            <HeroNebula :stage="stage" :reduced-motion="reducedMotion" />
            <!-- Phase 1：毛玻璃搜索框 + 打字机 -->
            <div class="story-search" :class="`is-stage-${stage}`" aria-hidden="true">
              <span class="story-search-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
                  <circle cx="11" cy="11" r="6.5" />
                  <path d="m16 16 4.5 4.5" />
                </svg>
              </span>
              <span class="story-search-text">{{ typed }}<i class="story-caret" /></span>
            </div>

            <!-- Phase 2：从粒子处飘散的数据标签 -->
            <div v-if="stage === 'absorb'" class="story-labels" aria-hidden="true">
              <span class="story-label story-label-1">女 / 28 岁</span>
              <span class="story-label story-label-2">客单价 1200</span>
              <span class="story-label story-label-3">偏好美妆</span>
            </div>

            <!-- Phase 3：晶莹玻璃结果卡（演示内容） -->
            <div
              v-if="stage === 'result' || stage === 'final'"
              class="story-result"
              :class="{ 'is-in': stage === 'result' || stage === 'final' }"
              aria-hidden="true"
            >
              <span class="story-result-badge">演示</span>
              <p class="story-result-title">已匹配 <b>2,341</b> 位用户</p>
              <p class="story-result-body">核心特征：25-35 岁，客单价均值 <b>1540</b> 元。</p>
              <span class="story-result-glow" aria-hidden="true" />
            </div>
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
          <a href="/docs" target="_blank" rel="noopener" class="l-btn l-btn-primary l-btn-lg">
            预约部署
          </a>
        </div>
      </section>
    </main>

    <!-- ============ Footer ============ -->
    <footer class="l-footer">
      <div class="l-shell l-footer-inner">
        <span class="l-footer-brand">© 2026 用户画像 RAG</span>
        <nav class="l-footer-links" aria-label="页脚链接">
          <a href="/docs" target="_blank" rel="noopener">产品文档</a>
          <a v-if="!isAuthed" href="/login">登录</a>
          <RouterLink v-else to="/">进入工作台</RouterLink>
        </nav>
      </div>
    </footer>
  </div>
</template>
