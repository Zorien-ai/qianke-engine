<script setup>
/**
 * 官网 Landing Page（`/v2/#/home`，公开可匿名访问）。
 *
 * 极简高级风（参考 DeepSeek / Linear 的减法）：全站只有
 *   Hero（居中大标题 + 一句副标题 + 两个按钮，Canvas 星云全幅背景）
 *   → 三张大图 + 三行标题
 *   → 两对「大字报」
 *   → 一句私有化 Slogan + 一个按钮
 *   → 极简 Footer。
 * 所有解释性长文案都去掉了，产品细节留给 /docs。
 *
 * 纯 Vue 3 + 手写 CSS，不引第三方库/远程字体；滚动淡入用 IntersectionObserver
 * 自定义指令 v-reveal（24px / 0.9s / cubic-bezier(.22,.61,.36,1)，可错峰）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { store } from "../store";
import HeroNebula from "../components/landing/HeroNebula.vue";
import "../styles/landing.css";

const shotModules = import.meta.glob("../assets/shots/*.png", { eager: true, import: "default" });
const shot = (name) => shotModules[`../assets/shots/${name}.png`] || "";

const isAuthed = computed(() => !!store.authenticated);

/* ---------- Hero 三阶段氛围（Canvas 内部渲染，无图例文字） ---------- */
const PHASE_MS = 2600;
function prefersReducedMotion() {
  return !!(
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}
const reducedMotion = ref(prefersReducedMotion());
const phase = ref(reducedMotion.value ? 2 : 0);

let phaseTimer = null;
let motionQuery = null;

function clearPhaseTimer() {
  if (phaseTimer) {
    clearInterval(phaseTimer);
    phaseTimer = null;
  }
}

function startPhaseLoop() {
  clearPhaseTimer();
  const reduce = prefersReducedMotion();
  reducedMotion.value = !!reduce;
  if (reduce) {
    phase.value = 2;
    return;
  }
  phase.value = 0;
  phaseTimer = setInterval(() => {
    phase.value = (phase.value + 1) % 3;
  }, PHASE_MS);
}

function onMotionChange() {
  startPhaseLoop();
}

/* ---------- 顶部导航：Hero 内透明亮色 / 滚出后浅色吸顶 ---------- */
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

/* ---------- 页内锚点：hash 路由下不能用 href="#id"，并补偿吸顶导航 ---------- */
function scrollTo(selector) {
  const node = document.querySelector(selector);
  if (!node) return;
  const top = node.getBoundingClientRect().top + window.scrollY - navHeight() - 10;
  window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
}

/* ---------- 滚动淡入上浮（24px / 0.9s / cubic-bezier(.22,.61,.36,1)） ---------- */
const vReveal = {
  mounted(el) {
    el.classList.add("reveal");
    if (typeof window === "undefined") return;
    const reduce = prefersReducedMotion();
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

/* ---------- 页面内容：三张图只配一行标题 ---------- */
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

onMounted(() => {
  motionQuery =
    typeof window !== "undefined" && window.matchMedia
      ? window.matchMedia("(prefers-reduced-motion: reduce)")
      : null;
  if (motionQuery) {
    if (motionQuery.addEventListener) motionQuery.addEventListener("change", onMotionChange);
    else if (motionQuery.addListener) motionQuery.addListener(onMotionChange);
  }
  startPhaseLoop();
  window.addEventListener("scroll", updateNavState, { passive: true });
  window.addEventListener("resize", updateNavState);
  updateNavState();
  document.title = "用户画像 RAG · 无需 SQL 的 AI 用户画像助理";
});

onBeforeUnmount(() => {
  clearPhaseTimer();
  if (motionQuery) {
    if (motionQuery.removeEventListener) motionQuery.removeEventListener("change", onMotionChange);
    else if (motionQuery.removeListener) motionQuery.removeListener(onMotionChange);
  }
  window.removeEventListener("scroll", updateNavState);
  window.removeEventListener("resize", updateNavState);
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
      <!-- ============ Hero：全屏居中，Canvas 星云全幅背景 ============ -->
      <section ref="heroRef" class="l-hero">
        <div class="l-hero-bg" aria-hidden="true">
          <HeroNebula :phase="phase" :reduced-motion="reducedMotion" full-bleed />
        </div>

        <div class="l-hero-content">
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

        <!-- Hero 底部 → 第二屏白底：200~260px 呼吸过渡（暖白渐变 + 暖金光弧 + 网格淡出） -->
        <div class="l-hero-fade" aria-hidden="true">
          <span class="l-hero-grid-fade" />
        </div>

        <button class="l-scroll-hint" type="button" aria-label="向下滚动" @click="scrollTo('#product')">
          <span aria-hidden="true" />
        </button>
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
