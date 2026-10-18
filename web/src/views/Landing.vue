<script setup>
/**
 * 官网 Landing Page（`/v2/#/home`，公开、可匿名访问）。
 *
 * 纯 Vue 3 + 手写 CSS，不引第三方动画库、不用远程字体：
 *   - 暖白营销页配色（#F9F9F8 / 深炭黑标题 / 灰蓝正文）+ 衬线标题栈；
 *   - Hero 右侧三阶段循环叙事：散落 CSV → 吸入发光 AI 大脑 → 吐出带彩色标签的画像卡片；
 *     阶段由 JS 定时切换，动效全交给 CSS transition/keyframes；卸载清定时器；
 *     prefers-reduced-motion 下静态停在阶段 3（生成画像）。
 *   - 滚动触达淡入上浮用 IntersectionObserver 自定义指令 v-reveal（reduced-motion 直接显示）。
 *   - 真实场景截图使用 import.meta.glob 引用：截图未就位时不炸构建，页面显示占位框；
 *     图片就位后重新 build 即可自动替换。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { store } from "../store";
import "../styles/landing.css";

/* 真实截图：Lead 产图前不存在也不会让构建失败（glob 为空时回退占位框） */
const shotModules = import.meta.glob("../assets/shots/*.png", { eager: true, import: "default" });
const shot = (name) => shotModules[`../assets/shots/${name}.png`] || "";

const isAuthed = computed(() => !!store.authenticated);

/* ---------- Hero 三阶段循环动画 ---------- */
const PHASE_KEYS = ["scatter", "absorb", "emit"];
const PHASE_LEGEND = ["上传交易表", "AI 理解业务", "生成可问画像"];
const PHASE_MS = 2600;

const phase = ref(0);
const phaseKey = computed(() => PHASE_KEYS[phase.value]);

let phaseTimer = null;
let motionQuery = null;

const dataPoints = [
  { file: "orders.csv", fields: "user_id · amount · city", x: -172, y: -118, delay: 0 },
  { file: "用户表.csv", fields: "member_level · gender", x: 152, y: -142, delay: 90 },
  { file: "rules.md", fields: "高价值客户 · 流失预警", x: -188, y: 78, delay: 170 },
  { file: "trade_2024.csv", fields: "order_id · pay_time", x: 158, y: 112, delay: 250 },
  { file: "会员规则.md", fields: "# 标签定义", x: -86, y: -186, delay: 130 },
  { file: "goods.csv", fields: "category · price", x: 54, y: 176, delay: 210 },
];

const profileCards = [
  {
    avatar: "高",
    name: "高价值客户",
    tags: ["高客单", "美妆偏好"],
    tx: -148,
    ty: -84,
    delay: 0,
    accent: "#B45309",
  },
  {
    avatar: "复",
    name: "复购用户",
    tags: ["近 30 天活跃", "母婴"],
    tx: 142,
    ty: -62,
    delay: 110,
    accent: "#2F6F5E",
  },
  {
    avatar: "预",
    name: "流失预警",
    tags: ["待召回", "沉睡用户"],
    tx: -28,
    ty: 128,
    delay: 210,
    accent: "#6D5AA8",
  },
];

function clearPhaseTimer() {
  if (phaseTimer) {
    clearInterval(phaseTimer);
    phaseTimer = null;
  }
}

function startPhaseLoop() {
  clearPhaseTimer();
  const reduce =
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) {
    // 降低动效：静态展示阶段 3（生成画像）
    phase.value = 2;
    return;
  }
  phase.value = 0;
  phaseTimer = setInterval(() => {
    phase.value = (phase.value + 1) % PHASE_KEYS.length;
  }, PHASE_MS);
}

function onMotionChange() {
  startPhaseLoop();
}

/* ---------- 页内锚点（hash 路由下不能用 href="#id"） ---------- */
function scrollTo(selector) {
  const node = document.querySelector(selector);
  if (node && node.scrollIntoView) {
    node.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

/* ---------- 顶部导航：滚动后加一层阴影 ---------- */
const navScrolled = ref(false);
function onWindowScroll() {
  navScrolled.value = window.scrollY > 10;
}

/* ---------- 滚动触达淡入上浮 ---------- */
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
      { threshold: 0.14, rootMargin: "0px 0px -6% 0px" }
    );
    io.observe(el);
    el.__revealObserver = io;
  },
  unmounted(el) {
    if (el.__revealObserver) el.__revealObserver.disconnect();
  },
};

/* ---------- 页面内容 ---------- */
const navLinks = [
  { label: "真实场景", target: "#scenes" },
  { label: "产品能力", target: "#features" },
  { label: "私有化部署", target: "#contact" },
];

const scenes = [
  {
    key: "setup",
    index: "01",
    tag: "数据导入",
    url: "/v2/#/setup",
    img: shot("setup"),
    alt: "数据导入向导：拖拽上传 CSV 与规则文档",
    title: "拖拽上传，告别繁琐配置。",
    desc: "交易表与规则文档直接拖进浏览器，字段自动识别、确认即可构建。不用建表、不用写配置，示例数据还能一键跑通流程。",
    points: ["CSV / Markdown 双区拖拽，多文件可追加", "字段自动识别，关键字段手动确认", "示例数据一键填满，先跑通再换真数据"],
    // 1440x900 真机截图（向下滚过 260px）：两块拖拽卡片的范围
    highlightStyle: { top: "45.5%", left: "21.5%", width: "73.3%", height: "19.3%" },
    highlightLabel: "拖拽上传",
  },
  {
    key: "chat",
    index: "02",
    tag: "AI 对话",
    url: "/v2/#/chat",
    img: shot("chat"),
    alt: "AI 对话页：流式回答与可溯源的引用来源",
    title: "每一个答案，都有源可溯。",
    desc: "用中文直接问，回答流式生成；正文里的引用标记指向来源卡片——是用户画像，还是哪篇规则文档的哪一段，点开就能核对。",
    points: ["运营用中文提问，不用学 SQL", "正文 [来源N] 与来源列表一一对应", "画像与文档两路召回，答案有依据"],
    // 「数据来源」卡片区（含 [来源N] 标签与命中检索式）
    highlightStyle: { top: "57.8%", left: "21.5%", width: "73.3%", height: "33.3%" },
    highlightLabel: "引用来源 · 逐条可溯源",
  },
  {
    key: "kb",
    index: "03",
    tag: "知识库",
    url: "/v2/#/kb",
    img: shot("kb"),
    alt: "知识库页：数据状态与构建进度",
    title: "增量更新，让数据常新。",
    desc: "新增文件走增量构建，只处理变化的部分，已有用户画像不受影响；数据状态与构建进度一眼可见，过期了会提醒你重建。",
    points: ["新增文件增量更新，不必全量重跑", "数据状态与文档矩阵一屏看清", "构建进度可离开页面，回来自动恢复"],
    // 绿色数据状态条（已就绪，可随时提问 + 进度条）
    highlightStyle: { top: "33.3%", left: "20.2%", width: "76.5%", height: "10%" },
    highlightLabel: "数据状态 · 常新",
  },
];

const features = [
  {
    icon: "🔥",
    title: "拒绝排期，随问随答。",
    desc: "运营的问题不用再排队等数据组：用中文直接问，几秒拿到带来源的答案，把时间还给业务判断。",
  },
  {
    icon: "🧠",
    title: "双轨召回，既懂数据又懂业务。",
    desc: "结构化用户画像与文档知识两路召回、精排融合，人群问题与规则问题走同一个入口。",
  },
  {
    icon: "🛡️",
    title: "绝对私有化，数据绝不外传。",
    desc: "支持内网私有化部署，数据与模型调用都留在企业自己的环境里，不把交易数据交给第三方。",
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
  window.addEventListener("scroll", onWindowScroll, { passive: true });
  onWindowScroll();
  document.title = "用户画像 RAG · 让你的电商数据，听懂中国话";
});

onBeforeUnmount(() => {
  clearPhaseTimer();
  if (motionQuery) {
    if (motionQuery.removeEventListener) motionQuery.removeEventListener("change", onMotionChange);
    else if (motionQuery.removeListener) motionQuery.removeListener(onMotionChange);
  }
  window.removeEventListener("scroll", onWindowScroll);
});
</script>

<template>
  <div class="landing">
    <!-- ============ 顶部极简导航（吸顶） ============ -->
    <header class="l-nav" :class="{ 'is-scrolled': navScrolled }">
      <div class="l-shell l-nav-inner">
        <RouterLink to="/home" class="l-brand" aria-label="用户画像 RAG 官网首页">
          <span class="l-logo">R</span>
          <span class="l-brand-text">
            <b>用户画像 RAG</b>
            <small>电商数据智能助理</small>
          </span>
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
          <a href="/docs" target="_blank" rel="noopener" class="l-nav-link l-nav-doc">查看文档</a>
          <a v-if="!isAuthed" href="/login" class="l-nav-login">登录</a>
          <RouterLink v-else to="/" class="l-btn l-btn-primary l-btn-sm">进入工作台</RouterLink>
        </div>
      </div>
    </header>

    <main>
      <!-- ============ Hero ============ -->
      <section class="l-hero">
        <div class="l-shell l-hero-grid">
          <div class="l-hero-copy">
            <span class="l-eyebrow"><i aria-hidden="true" />电商运营的 AI 数据助理</span>
            <h1 class="l-title">
              让你的电商数据，<br />
              <em>听懂中国话。</em>
            </h1>
            <p class="l-lead">
              无需懂 SQL，无需养分析师。上传交易表，3 分钟构建你的专属 AI 业务助理。
            </p>
            <div class="l-hero-actions">
              <RouterLink v-if="isAuthed" to="/" class="l-btn l-btn-primary l-btn-lg">
                进入工作台 <span aria-hidden="true">→</span>
              </RouterLink>
              <a v-else href="/login" class="l-btn l-btn-primary l-btn-lg">
                免费体验 Demo <span aria-hidden="true">→</span>
              </a>
              <button type="button" class="l-btn l-btn-ghost l-btn-lg" @click="scrollTo('#contact')">
                预约私有化部署
              </button>
            </div>
            <ul class="l-hero-facts">
              <li>不用写 SQL</li>
              <li>答案带来源</li>
              <li>支持私有化部署</li>
            </ul>
          </div>

          <!-- 三阶段循环叙事动画（纯 CSS/Vue） -->
          <div class="l-hero-visual" aria-hidden="true">
            <div class="l-stage" :data-phase="phaseKey">
              <div class="l-stage-scene">
                <div class="l-brain">
                  <span class="l-brain-ring l-ring-1" />
                  <span class="l-brain-ring l-ring-2" />
                  <span class="l-brain-core">AI</span>
                </div>

                <span
                  v-for="p in dataPoints"
                  :key="p.file"
                  class="l-datachip"
                  :style="{ '--x': `${p.x}px`, '--y': `${p.y}px`, '--delay': `${p.delay}ms` }"
                >
                  <span class="l-datachip-file">{{ p.file }}</span>
                  <span class="l-datachip-fields">{{ p.fields }}</span>
                </span>

                <article
                  v-for="c in profileCards"
                  :key="c.name"
                  class="l-profile-card"
                  :style="{
                    '--tx': `${c.tx}px`,
                    '--ty': `${c.ty}px`,
                    '--delay': `${c.delay}ms`,
                    '--accent': c.accent,
                  }"
                >
                  <span class="l-profile-avatar">{{ c.avatar }}</span>
                  <span class="l-profile-body">
                    <span class="l-profile-name">{{ c.name }}</span>
                    <span class="l-profile-tags">
                      <span v-for="tag in c.tags" :key="tag">{{ tag }}</span>
                    </span>
                  </span>
                </article>
              </div>
            </div>
            <div class="l-phase-legend">
              <span
                v-for="(label, i) in PHASE_LEGEND"
                :key="label"
                class="l-phase-item"
                :class="{ 'is-active': phase === i }"
              >
                <i aria-hidden="true" />{{ label }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 真实场景 ============ -->
      <section id="scenes" class="l-section l-scenes">
        <div class="l-shell">
          <header class="l-section-head" v-reveal>
            <span class="l-eyebrow"><i aria-hidden="true" />真实场景</span>
            <h2 class="l-h2">专为电商运营打造的<br class="l-br-mobile" />桌面工作台</h2>
            <p class="l-section-lead">
              不是又一个聊天框。从导入、问答到知识库维护，完整流程跑在浏览器里，每一步都看得见。
            </p>
          </header>

          <div class="l-scene-list">
            <article
              v-for="(scene, i) in scenes"
              :key="scene.key"
              class="l-scene"
              :class="{ 'is-reverse': i % 2 === 1 }"
            >
              <div class="l-scene-media" v-reveal>
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
                      <span class="l-shot-placeholder-tag">{{ scene.tag }} · 真机截图</span>
                      <span class="l-shot-placeholder-hint">素材准备中，镜像构建后自动替换</span>
                    </div>
                    <div class="l-highlight" :style="scene.highlightStyle">
                      <span class="l-highlight-label">{{ scene.highlightLabel }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div class="l-scene-copy" v-reveal>
                <span class="l-scene-index">{{ scene.index }} / {{ scene.tag }}</span>
                <h3 class="l-h3">{{ scene.title }}</h3>
                <p class="l-body">{{ scene.desc }}</p>
                <ul class="l-points">
                  <li v-for="point in scene.points" :key="point">{{ point }}</li>
                </ul>
              </div>
            </article>
          </div>
        </div>
      </section>

      <!-- ============ 产品能力 ============ -->
      <section id="features" class="l-section l-features">
        <div class="l-shell">
          <header class="l-section-head" v-reveal>
            <span class="l-eyebrow"><i aria-hidden="true" />产品能力</span>
            <h2 class="l-h2">运营真正用得上的三件事</h2>
            <p class="l-section-lead">先把问题答对，再把数据管好，最后把数据留在自己手里。</p>
          </header>

          <div class="l-card-grid">
            <article v-for="feature in features" :key="feature.title" class="l-feature-card" v-reveal>
              <span class="l-feature-icon" aria-hidden="true">{{ feature.icon }}</span>
              <h3 class="l-h3">{{ feature.title }}</h3>
              <p class="l-body">{{ feature.desc }}</p>
            </article>
          </div>
        </div>
      </section>

      <!-- ============ 私有化部署 / 联系 ============ -->
      <section id="contact" class="l-section l-contact">
        <div class="l-shell">
          <div class="l-contact-card" v-reveal>
            <div class="l-contact-copy">
              <span class="l-eyebrow"><i aria-hidden="true" />私有化部署</span>
              <h2 class="l-h2">想把它放在你自己的服务器上？</h2>
              <p class="l-body">
                支持 Docker 内网部署，数据与模型都留在企业自己的环境里。准备好一份交易表，就可以安排一次内网演示。
              </p>
            </div>
            <div class="l-contact-actions">
              <RouterLink v-if="isAuthed" to="/" class="l-btn l-btn-primary">进入工作台</RouterLink>
              <a v-else href="/login" class="l-btn l-btn-primary">登录体验</a>
              <a href="/docs" target="_blank" rel="noopener" class="l-btn l-btn-ghost">查看部署文档</a>
            </div>
          </div>
        </div>
      </section>
    </main>

    <!-- ============ Footer ============ -->
    <footer class="l-footer">
      <div class="l-shell l-footer-inner">
        <span class="l-footer-brand">
          <span class="l-logo l-logo-sm">R</span>
          © 2026 用户画像 RAG
        </span>
        <nav class="l-footer-links" aria-label="页脚链接">
          <a href="/docs" target="_blank" rel="noopener">产品文档</a>
          <a v-if="!isAuthed" href="/login">登录</a>
          <RouterLink v-else to="/">进入工作台</RouterLink>
          <RouterLink :to="{ path: '/home', hash: '' }">官网首页</RouterLink>
        </nav>
      </div>
    </footer>
  </div>
</template>
