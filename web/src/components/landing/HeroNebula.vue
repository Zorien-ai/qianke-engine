<script setup>
/**
 * Hero 叙事 Canvas（task-12，原生 Canvas，无第三方依赖）。
 *
 * 只负责背景星云与粒子：DOF 星云、中心光核呼吸/漂移、阶段2 的爆亮与高亮粒子；
 * 搜索框 / 数据标签 / 结果卡全部由 Landing.vue 用 DOM + CSS 玻璃拟态渲染，文字更清晰。
 *
 * props.stage：search → absorb → result → final（时间轴由 Landing.vue 状态机驱动）
 *   - search：缓慢呼吸，部分粒子被点亮；
 *   - absorb：中心瞬间爆亮（AI 思考），少量粒子高亮并向中心收；
 *   - result：高亮粒子向外发射、回落，星云逐渐恢复；
 *   - final：稳定呼吸态（不循环重播）。
 * 保留：单 rAF、dt 钳制、DPR 上限 1.75、低比例渲染、离屏暂停、reduced-motion 单帧静态、卸载清理。
 */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps({
  stage: { type: String, default: "search" },
  reducedMotion: { type: Boolean, default: false },
});

const wrapRef = ref(null);
const canvasRef = ref(null);

const TAU = Math.PI * 2;
const WARM = "245, 179, 90";
const BG = "5, 5, 6";
const MAX_DPR = 1.75;
const MAX_DT = 48;
const FULL_RENDER_SCALE = 0.56;

let canvas = null;
let ctx = null;
let wrap = null;

let width = 0;
let height = 0;
let dpr = 1;
let particles = [];
let highlights = [];
let running = false;
let visible = true;
let rafId = 0;
let lastTs = 0;
let lastDt = 16;
let frameCount = 0;
let stageStart = 0;
let startedAt = 0;
let currentStage = props.stage;
let reduce = props.reducedMotion;

let resizeObserver = null;
let intersectionObserver = null;
let visHandler = null;

const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
const rand = (min, max) => min + Math.random() * (max - min);
const easeOut = (p) => 1 - Math.pow(1 - clamp(p, 0, 1), 3);

/* ---------- 焦点位置：Canvas 只存在于右列舞台内，中心就是舞台中心 ---------- */
function focusPoint() {
  return { x: width * 0.5, y: height * 0.5 };
}

/* ---------- 粒子 / 景深 ---------- */
function particleCount() {
  const area = width * height;
  return clamp(Math.round(area / 30000), 34, 54);
}

function initParticles() {
  const count = particleCount();
  particles = [];
  for (let i = 0; i < count; i++) {
    const depth = Math.pow(Math.random(), 1.7);
    const speed = 0.004 + depth * 0.02;
    const angle = rand(0, TAU);
    particles.push({
      x: rand(0, width),
      y: rand(0, height),
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      depth,
      r: 0.5 + depth * 2.1,
      star: depth > 0.6 && Math.random() < 0.24,
      halo: depth > 0.6,
      twinkle: rand(0, TAU),
      twinkleSpeed: rand(0.0005, 0.0016),
    });
  }
  pickHighlights();
}

function pickHighlights() {
  const pool = particles.filter((p) => p.depth > 0.5);
  highlights = [];
  const used = new Set();
  const want = Math.min(7, pool.length);
  while (highlights.length < want && used.size < pool.length) {
    const idx = Math.floor(Math.random() * pool.length);
    if (used.has(idx)) continue;
    used.add(idx);
    highlights.push(pool[idx]);
  }
}

/* ---------- 尺寸 ---------- */
function resize() {
  if (!wrap || !canvas) return;
  const nextW = wrap.clientWidth;
  const nextH = wrap.clientHeight;
  if (!nextW || !nextH) return;
  const baseDpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
  const nextScale = baseDpr * FULL_RENDER_SCALE;
  if (ctx && nextW === width && nextH === height && nextScale === dpr) return;
  width = nextW;
  height = nextH;
  dpr = nextScale;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  initParticles();
  if (reduce) drawStatic();
  else if (running) draw(performance.now());
}

/* ---------- 星云粒子（DOF） ---------- */
function drawParticleNetwork(t) {
  const threshold = Math.min(width, height) * 0.1;

  const lineBuckets = [[], [], []];
  for (let i = 0; i < particles.length; i++) {
    const a = particles[i];
    if (a.depth < 0.58) continue;
    for (let j = i + 1; j < particles.length; j++) {
      const b = particles[j];
      if (b.depth < 0.58) continue;
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const d2 = dx * dx + dy * dy;
      if (d2 > threshold * threshold) continue;
      const k = 1 - Math.sqrt(d2) / threshold;
      const bucket = Math.min(2, Math.floor(k * 3));
      lineBuckets[bucket].push(a.x, a.y, b.x, b.y);
    }
  }
  const lineAlpha = [0.03, 0.06, 0.1];
  ctx.lineWidth = 0.65;
  lineBuckets.forEach((pts, idx) => {
    if (!pts.length) return;
    ctx.strokeStyle = `rgba(${WARM}, ${lineAlpha[idx]})`;
    ctx.beginPath();
    for (let k = 0; k < pts.length; k += 4) {
      ctx.moveTo(pts[k], pts[k + 1]);
      ctx.lineTo(pts[k + 2], pts[k + 3]);
    }
    ctx.stroke();
  });

  const far = [];
  const mid = [];
  const near = [];
  const halo = [];
  const stars = [];
  for (const p of particles) {
    if (p.star) stars.push(p);
    else if (p.depth < 0.35) far.push(p);
    else if (p.depth < 0.62) mid.push(p);
    else {
      near.push(p);
      if (p.halo) halo.push(p);
    }
  }

  if (halo.length) {
    ctx.fillStyle = "rgba(255, 214, 160, 0.045)";
    ctx.beginPath();
    for (const p of halo) {
      const r = p.r * 3.4;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
    ctx.fillStyle = "rgba(255, 222, 175, 0.08)";
    ctx.beginPath();
    for (const p of halo) {
      const r = p.r * 2;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
  }
  if (far.length) {
    ctx.fillStyle = `rgba(${WARM}, 0.22)`;
    ctx.beginPath();
    for (const p of far) {
      const r = p.r * 0.7;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
  }
  if (mid.length) {
    ctx.fillStyle = `rgba(${WARM}, 0.38)`;
    ctx.beginPath();
    for (const p of mid) {
      const r = p.r * 0.95;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
  }
  if (near.length) {
    ctx.fillStyle = "rgba(255, 240, 214, 0.75)";
    ctx.beginPath();
    for (const p of near) {
      const r = p.r;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
  }
  if (stars.length) {
    ctx.beginPath();
    for (const p of stars) {
      const r = p.r;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
      ctx.moveTo(p.x - r * 3, p.y);
      ctx.lineTo(p.x + r * 3, p.y);
      ctx.moveTo(p.x, p.y - r * 3);
      ctx.lineTo(p.x, p.y + r * 3);
    }
    ctx.fillStyle = "rgba(255, 250, 240, 0.68)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 250, 240, 0.16)";
    ctx.lineWidth = 0.7;
    ctx.stroke();
  }
}

/* ---------- 高亮粒子（absorb/result 阶段） ---------- */
function drawHighlights(t) {
  if (!highlights.length) return;
  const since = t - stageStart;
  const focus = focusPoint();
  let pull = 0;
  let glow = 0;
  if (currentStage === "absorb") {
    const p = clamp(since / 900, 0, 1);
    pull = 0.4 * easeOut(p);
    glow = 0.7 + 0.7 * Math.sin(p * Math.PI);
  } else if (currentStage === "result") {
    const p = clamp(since / 1500, 0, 1);
    pull = -0.28 * easeOut(p);
    glow = 1 - 0.45 * p;
  } else if (currentStage === "final") {
    glow = Math.max(0, 0.3 * (1 - clamp(since / 1400, 0, 1)));
  } else {
    glow = 0.22;
  }
  if (glow <= 0.02) return;

  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  for (const p of highlights) {
    const dx = focus.x - p.x;
    const dy = focus.y - p.y;
    const x = p.x + dx * pull;
    const y = p.y + dy * pull;
    const r = 2 + glow * 2.4;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r * 7);
    g.addColorStop(0, `rgba(255, 250, 235, ${0.85 * glow})`);
    g.addColorStop(0.2, `rgba(255, 214, 150, ${0.5 * glow})`);
    g.addColorStop(1, "rgba(245, 179, 90, 0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r * 7, 0, TAU);
    ctx.fill();
    ctx.fillStyle = `rgba(255, 252, 240, ${0.95 * glow})`;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.fill();
  }
  ctx.restore();
}

/* ---------- 中心光核 ---------- */
function drawCore(t) {
  const focus = focusPoint();
  const pulse = 0.86 + 0.14 * Math.sin(t * 0.0019);
  const since = t - stageStart;
  let burst = 1;
  if (currentStage === "absorb") {
    burst = 1.35 + 1.0 * (1 - easeOut(clamp(since / 900, 0, 1)));
  } else if (currentStage === "result") {
    burst = 0.95;
  }
  const cx = focus.x + Math.sin(t * 0.00009) * width * 0.012;
  const cy = focus.y + Math.cos(t * 0.00012) * height * 0.01;
  const coreR = Math.min(width, height) * 0.042 * pulse * burst;

  const outerR = Math.min(width, height) * 0.2 * (0.92 + 0.08 * pulse) * burst;
  let g = ctx.createRadialGradient(cx, cy, 0, cx, cy, outerR);
  g.addColorStop(0, `rgba(255, 240, 214, ${Math.min(0.5, 0.2 * burst)})`);
  g.addColorStop(0.3, `rgba(${WARM}, 0.09)`);
  g.addColorStop(1, `rgba(${WARM}, 0)`);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, outerR, 0, TAU);
  ctx.fill();

  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(t * 0.00014);
  ctx.strokeStyle = `rgba(${WARM}, 0.14)`;
  ctx.lineWidth = 0.8;
  for (let k = 0; k < 2; k++) {
    ctx.beginPath();
    ctx.arc(0, 0, coreR * (2.1 + k * 1.05), k * 2.4, k * 2.4 + 1.1);
    ctx.stroke();
  }
  ctx.restore();

  const g2 = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
  g2.addColorStop(0, "rgba(255, 255, 255, 1)");
  g2.addColorStop(0.3, "rgba(255, 246, 228, 0.95)");
  g2.addColorStop(0.66, `rgba(${WARM}, 0.8)`);
  g2.addColorStop(1, `rgba(${WARM}, 0)`);
  ctx.fillStyle = g2;
  ctx.beginPath();
  ctx.arc(cx, cy, coreR, 0, TAU);
  ctx.fill();
}

/* ---------- absorb 阶段中心爆亮（一次性 flash） ---------- */
function drawFlash(t) {
  if (currentStage !== "absorb" || reduce) return;
  const since = t - stageStart;
  if (since > 900) return;
  const alpha = Math.max(0, 1 - since / 900) * 0.34;
  const focus = focusPoint();
  const r = Math.min(width, height) * 0.3;
  const g = ctx.createRadialGradient(focus.x, focus.y, 0, focus.x, focus.y, r);
  g.addColorStop(0, `rgba(255, 252, 244, ${alpha})`);
  g.addColorStop(0.45, `rgba(${WARM}, ${alpha * 0.3})`);
  g.addColorStop(1, `rgba(${WARM}, 0)`);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(focus.x, focus.y, r, 0, TAU);
  ctx.fill();
}

/* ---------- 单帧绘制 ---------- */
function draw(t) {
  if (!ctx || !width || !height) return;
  ctx.clearRect(0, 0, width, height);
  drawParticleNetwork(t);
  drawCore(t);
  drawHighlights(t);
  drawFlash(t);
  frameCount++;
  if (window.__nebulaDebug) {
    window.__nebulaDebug.frames = frameCount;
    window.__nebulaDebug.particles = particles.length;
    window.__nebulaDebug.running = running;
    window.__nebulaDebug.dpr = dpr;
  }
}

/* ---------- 模拟 ---------- */
function simulate(dt) {
  const focus = focusPoint();
  const pull = currentStage === "absorb" ? 0.000045 : 0;
  for (const p of particles) {
    if (pull) {
      p.vx += (focus.x - p.x) * pull * dt * 0.02;
      p.vy += (focus.y - p.y) * pull * dt * 0.02;
    }
    p.x += p.vx * dt;
    p.y += p.vy * dt;
    const speed = Math.hypot(p.vx, p.vy);
    const maxSpeed = 0.004 + p.depth * 0.02;
    if (speed > maxSpeed) {
      p.vx = (p.vx / speed) * maxSpeed;
      p.vy = (p.vy / speed) * maxSpeed;
    }
    if (p.x < -16) p.x = width + 16;
    if (p.x > width + 16) p.x = -16;
    if (p.y < -16) p.y = height + 16;
    if (p.y > height + 16) p.y = -16;
  }
}

/* ---------- rAF（自适应：软件渲染时自动隔帧，页面 rAF 保持顺滑） ---------- */
let drawAccum = 0;
let drawCost = 0;

function loop(ts) {
  if (!running) return;
  rafId = requestAnimationFrame(loop);
  const dt = lastTs ? Math.min(MAX_DT, ts - lastTs) : 16;
  lastTs = ts;
  drawAccum += dt;
  const minInterval = drawCost > 11 ? 30 : 0;
  if (drawAccum < minInterval) return;
  const step = Math.min(MAX_DT, drawAccum);
  drawAccum = 0;
  lastDt = step;
  simulate(step);
  const t0 = performance.now();
  draw(ts - startedAt);
  const cost = performance.now() - t0;
  drawCost = drawCost ? drawCost * 0.9 + cost * 0.1 : cost;
}

function start() {
  if (reduce || running || !ctx) return;
  running = true;
  lastTs = 0;
  drawAccum = 0;
  drawCost = 0;
  startedAt = performance.now();
  if (window.__nebulaDebug) window.__nebulaDebug.running = true;
  rafId = requestAnimationFrame(loop);
}

function stop() {
  running = false;
  if (rafId) cancelAnimationFrame(rafId);
  rafId = 0;
  if (window.__nebulaDebug) window.__nebulaDebug.running = false;
}

/* ---------- reduced-motion：只画一帧静态 ---------- */
function drawStatic() {
  if (!ctx || !width || !height) return;
  initParticles();
  ctx.clearRect(0, 0, width, height);
  drawParticleNetwork(0);
  drawCore(0);
  frameCount++;
  if (window.__nebulaDebug) {
    window.__nebulaDebug.frames = frameCount;
    window.__nebulaDebug.particles = particles.length;
    window.__nebulaDebug.running = false;
    window.__nebulaDebug.static = true;
    window.__nebulaDebug.dpr = dpr;
  }
}

/* ---------- 生命周期 ---------- */
onMounted(() => {
  wrap = wrapRef.value;
  canvas = canvasRef.value;
  if (!wrap || !canvas) return;
  currentStage = props.stage;
  reduce = props.reducedMotion;
  stageStart = performance.now();
  window.__nebulaDebug = { frames: 0, particles: 0, running: false, static: false, dpr: 1 };

  resize();

  if (typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(() => resize());
    resizeObserver.observe(wrap);
  }
  if (typeof IntersectionObserver !== "undefined") {
    intersectionObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          visible = entry.isIntersecting;
          if (visible) start();
          else stop();
        });
      },
      { threshold: 0.05 }
    );
    intersectionObserver.observe(wrap);
  }
  visHandler = () => {
    if (document.hidden) stop();
    else if (visible) start();
  };
  document.addEventListener("visibilitychange", visHandler);

  if (reduce) drawStatic();
  else start();
});

watch(
  () => props.stage,
  (next) => {
    currentStage = next;
    stageStart = performance.now();
    if (next === "absorb") pickHighlights();
    if (reduce) drawStatic();
  }
);

watch(
  () => props.reducedMotion,
  (next) => {
    reduce = next;
    if (next) {
      stop();
      drawStatic();
    } else {
      start();
    }
  }
);

onBeforeUnmount(() => {
  stop();
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  if (intersectionObserver) {
    intersectionObserver.disconnect();
    intersectionObserver = null;
  }
  if (visHandler) {
    document.removeEventListener("visibilitychange", visHandler);
    visHandler = null;
  }
  particles = [];
  highlights = [];
  ctx = null;
  canvas = null;
  wrap = null;
  window.__nebulaDebug = null;
});
</script>

<template>
  <div ref="wrapRef" class="nebula" :data-stage="stage">
    <canvas ref="canvasRef" class="nebula-canvas" aria-hidden="true" />
  </div>
</template>
