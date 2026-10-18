<script setup>
/**
 * Hero 暗夜星云背景（原生 Canvas，无第三方依赖）。
 *
 * 质感要点（task-11）：
 *   - 深空微渐变上的景深粒子：近景大 + 柔和 bokeh 光晕，远景小/暗/锐利；
 *   - 连线只发生在近景少数粒子之间，更细更淡，不再“蜘蛛网”；
 *   - Ambient Glow 单独用低分辨率 canvas + CSS 缓慢漂移（暖金 + 极淡冷色），不占每帧预算；
 *   - 三阶段氛围：向心流星 → 爆发冲击波 → 中心向外发柔和能量光带（无任何卡片 DOM）；
 *   - 单 rAF、dt 钳制、DPR 上限 1.75、全幅模式低缩放渲染后拉伸，ResizeObserver 自适应；
 *   - 离屏/后台暂停，prefers-reduced-motion 只画一帧静态，卸载完整清理。
 */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps({
  // 0 散落 / 1 爆发 / 2 能量释放
  phase: { type: Number, default: 0 },
  reducedMotion: { type: Boolean, default: false },
  fullBleed: { type: Boolean, default: true },
});

const wrapRef = ref(null);
const canvasRef = ref(null);

const TAU = Math.PI * 2;
const WARM = "245, 179, 90";
const COOL = "148, 176, 214";
const BG = "7, 7, 11";
const MAX_DPR = 1.75;
const MAX_DT = 48;
const FULL_RENDER_SCALE = 0.46;

let canvas = null;
let ctx = null;
let wrap = null;

let width = 0;
let height = 0;
let dpr = 1;
let particles = [];
let meteors = [];
let shockwaves = [];
let running = false;
let visible = true;
let rafId = 0;
let lastTs = 0;
let lastDt = 16;
let frameCount = 0;
let phaseStart = 0;
let startedAt = 0;
let meteorTimer = 0;
let currentPhase = props.phase;
let reduce = props.reducedMotion;

let resizeObserver = null;
let intersectionObserver = null;
let visHandler = null;

const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
const rand = (min, max) => min + Math.random() * (max - min);

/* ---------- 粒子 / 景深 ---------- */
function particleCount() {
  const area = width * height;
  if (props.fullBleed) return clamp(Math.round(area / 32000), 40, 56);
  return clamp(Math.round(area / 3500), 70, 130);
}

function initParticles() {
  const count = particleCount();
  particles = [];
  for (let i = 0; i < count; i++) {
    // depth：0 远景 / 1 近景；指数让远景更多、近景更少
    const depth = Math.pow(Math.random(), 1.7);
    const speed = 0.004 + depth * 0.02;
    const angle = rand(0, TAU);
    const star = depth > 0.55 && Math.random() < 0.22;
    particles.push({
      x: rand(0, width),
      y: rand(0, height),
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      depth,
      r: 0.5 + depth * 2.1 + (star ? 0.5 : 0),
      star,
      halo: depth > 0.6 && !star,
      twinkle: rand(0, TAU),
      twinkleSpeed: rand(0.0005, 0.0016),
    });
  }
}

/* ---------- 尺寸 ---------- */
function resize() {
  if (!wrap || !canvas) return;
  const nextW = wrap.clientWidth;
  const nextH = wrap.clientHeight;
  if (!nextW || !nextH) return;
  const baseDpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
  const nextScale = baseDpr * (props.fullBleed ? FULL_RENDER_SCALE : 1);
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

/* ---------- 粒子网络（DOF） ---------- */
function drawParticleNetwork(t) {
  const threshold = Math.min(width, height) * (props.fullBleed ? 0.1 : 0.14);

  // 连线：只有双方都偏近景时才连，数量少、更细更淡
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
  const lineAlpha = [0.03, 0.06, 0.11];
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

  // 粒子：远景小而暗且锐利；近景大 + 柔和 bokeh 光晕
  const far = [];
  const mid = [];
  const near = [];
  const nearHalo = [];
  const starDots = [];
  for (const p of particles) {
    if (p.star) {
      starDots.push(p);
    } else if (p.depth < 0.35) {
      far.push(p);
    } else if (p.depth < 0.62) {
      mid.push(p);
    } else {
      near.push(p);
      if (p.halo) nearHalo.push(p);
    }
  }

  // bokeh：两层低透明度大圆近似柔光晕（批量绘制，不用渐变/滤镜）
  if (nearHalo.length) {
    ctx.fillStyle = "rgba(255, 214, 160, 0.045)";
    ctx.beginPath();
    for (const p of nearHalo) {
      const r = p.r * 3.6;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
    ctx.fillStyle = "rgba(255, 222, 175, 0.08)";
    ctx.beginPath();
    for (const p of nearHalo) {
      const r = p.r * 2.1;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
  }

  if (far.length) {
    ctx.fillStyle = `rgba(${WARM}, 0.24)`;
    ctx.beginPath();
    for (const p of far) {
      const r = p.r * 0.7;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
  }
  if (mid.length) {
    ctx.fillStyle = `rgba(${WARM}, 0.4)`;
    ctx.beginPath();
    for (const p of mid) {
      const r = p.r * 0.95;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
  }
  if (near.length) {
    ctx.fillStyle = "rgba(255, 240, 214, 0.78)";
    ctx.beginPath();
    for (const p of near) {
      const r = p.r;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
    }
    ctx.fill();
  }
  if (starDots.length) {
    ctx.beginPath();
    for (const p of starDots) {
      const r = p.r;
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
      ctx.moveTo(p.x - r * 3, p.y);
      ctx.lineTo(p.x + r * 3, p.y);
      ctx.moveTo(p.x, p.y - r * 3);
      ctx.lineTo(p.x, p.y + r * 3);
    }
    ctx.fillStyle = "rgba(255, 250, 240, 0.7)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 250, 240, 0.16)";
    ctx.lineWidth = 0.7;
    ctx.stroke();
  }
}

/* ---------- 中心光核（呼吸 + 极缓慢漂移） ---------- */
function drawCore(t) {
  const pulse = 0.86 + 0.14 * Math.sin(t * 0.0019);
  const since = t - phaseStart;
  const burst = currentPhase === 1 ? 1 + 0.35 * Math.max(0, 1 - since / 700) : 1;
  // Ambient Glow 的“缓慢漂移”揉进光核中心，不再额外加一层全屏图层
  const cx = width / 2 + Math.sin(t * 0.00009) * width * 0.018;
  const cy = height * 0.5 + Math.cos(t * 0.00012) * height * 0.014;
  const coreR = Math.min(width, height) * 0.05 * pulse * burst;

  const outerR = Math.min(width, height) * 0.22 * (0.9 + 0.1 * pulse) * burst;
  // 窄屏把大范围光晕再压淡，避免整块暖光糊在字后面
  const narrow = width < 480 ? 0.5 : 1;
  let g = ctx.createRadialGradient(cx, cy, 0, cx, cy, outerR);
  g.addColorStop(0, `rgba(255, 240, 214, ${0.2 * burst * narrow})`);
  g.addColorStop(0.3, `rgba(${WARM}, ${0.09 * narrow})`);
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

/* ---------- 阶段1：向心流星 ---------- */
function drawMeteors(dt) {
  const cx = width / 2;
  const cy = height * 0.5;
  for (const m of meteors) {
    m.age += dt;
    const p = clamp(m.age / m.duration, 0, 1);
    const ease = p * p * (3 - 2 * p);
    const x = m.sx + (cx - m.sx) * ease * 0.9;
    const y = m.sy + (cy - m.sy) * ease * 0.9;
    const tailP = clamp(ease - 0.14, 0, 1);
    const tx = m.sx + (cx - m.sx) * tailP * 0.9;
    const ty = m.sy + (cy - m.sy) * tailP * 0.9;
    const alpha = Math.sin(Math.PI * p) * 0.42;
    const grad = ctx.createLinearGradient(tx, ty, x, y);
    grad.addColorStop(0, `rgba(${WARM}, 0)`);
    grad.addColorStop(1, `rgba(255, 244, 222, ${alpha})`);
    ctx.strokeStyle = grad;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(x, y);
    ctx.stroke();
    ctx.fillStyle = `rgba(255, 250, 240, ${alpha * 0.9})`;
    ctx.beginPath();
    ctx.arc(x, y, 1.4, 0, TAU);
    ctx.fill();
  }
  meteors = meteors.filter((m) => m.age < m.duration);
}

/* ---------- 阶段2：爆发冲击波 + 微 flash ---------- */
function drawShockwaves(dt) {
  const cx = width / 2;
  const cy = height * 0.5;
  const base = Math.min(width, height);
  for (const w of shockwaves) {
    w.age += dt;
    if (w.age < 0) continue;
    const p = clamp(w.age / w.duration, 0, 1);
    const alpha = (1 - p) * 0.34;
    if (alpha <= 0.01) continue;
    ctx.strokeStyle = `rgba(${WARM}, ${alpha})`;
    ctx.lineWidth = 2 * (1 - p) + 0.5;
    ctx.beginPath();
    ctx.arc(cx, cy, base * (0.05 + p * 0.46), 0, TAU);
    ctx.stroke();
    ctx.strokeStyle = `rgba(255, 250, 240, ${alpha * 0.4})`;
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    ctx.arc(cx, cy, base * (0.045 + p * 0.4), 0, TAU);
    ctx.stroke();
  }
  shockwaves = shockwaves.filter((w) => w.age < w.duration);
}

function drawFlash(t) {
  if (currentPhase !== 1 || reduce) return;
  const since = t - phaseStart;
  if (since > 650) return;
  const alpha = Math.max(0, 1 - since / 650) * 0.2;
  const cx = width / 2;
  const cy = height * 0.5;
  const r = Math.min(width, height) * 0.3;
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
  g.addColorStop(0, `rgba(255, 252, 244, ${alpha})`);
  g.addColorStop(0.5, `rgba(${WARM}, ${alpha * 0.3})`);
  g.addColorStop(1, `rgba(${WARM}, 0)`);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, TAU);
  ctx.fill();
}

/* ---------- 阶段3：中心向外发柔和能量光带 ---------- */
function drawEnergyBands(t) {
  if (currentPhase !== 2 && !reduce) return;
  const since = reduce ? 1200 : t - phaseStart;
  const fadeIn = clamp(since / 520, 0, 1);
  const fadeOut = currentPhase === 2 ? 1 - clamp((since - 2150) / 520, 0, 1) : 1;
  const fade = fadeIn * fadeOut;
  if (fade <= 0.01) return;

  const cx = width / 2;
  const cy = height * 0.5;
  const base = Math.min(width, height);
  const rot = t * 0.000055;
  for (let i = 0; i < 3; i++) {
    const angle = rot + i * (TAU / 3) + 0.4;
    const len = base * (0.34 + i * 0.03);
    const end = { x: cx + Math.cos(angle) * len, y: cy + Math.sin(angle) * len * 0.82 };
    const mid = {
      x: cx + Math.cos(angle + 0.32) * len * 0.55,
      y: cy + Math.sin(angle + 0.32) * len * 0.55,
    };
    const g = ctx.createLinearGradient(cx, cy, end.x, end.y);
    g.addColorStop(0, `rgba(${WARM}, ${0.18 * fade})`);
    g.addColorStop(0.55, `rgba(255, 236, 205, ${0.12 * fade})`);
    g.addColorStop(1, `rgba(${WARM}, 0)`);
    ctx.strokeStyle = g;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.quadraticCurveTo(mid.x, mid.y, end.x, end.y);
    // 两层即可：宽柔光 + 细亮线（少画一层大面积描边，帧率更稳）
    ctx.lineWidth = 13;
    ctx.globalAlpha = 0.42;
    ctx.stroke();
    ctx.lineWidth = 2.2;
    ctx.globalAlpha = 1;
    ctx.stroke();

    // 沿线向外流动的光点
    if (!reduce) {
      for (let k = 0; k < 2; k++) {
        const f = (t * 0.00032 + i * 0.19 + k * 0.5) % 1;
        const mt = 1 - f;
        const px = mt * mt * cx + 2 * mt * f * mid.x + f * f * end.x;
        const py = mt * mt * cy + 2 * mt * f * mid.y + f * f * end.y;
        const a = Math.sin(Math.PI * f) * 0.75;
        ctx.fillStyle = `rgba(255, 248, 232, ${a})`;
        ctx.beginPath();
        ctx.arc(px, py, 1.8, 0, TAU);
        ctx.fill();
      }
    }
  }
  ctx.globalAlpha = 1;
}

/* ---------- 中心压暗（保证文字可读，颜色跟深空底一致） ---------- */
function drawScrim() {
  const cx = width / 2;
  const cy = height * 0.48;
  const r = Math.max(width * 0.6, height * 0.62);
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
  g.addColorStop(0, `rgba(${BG}, 0.52)`);
  g.addColorStop(0.52, `rgba(${BG}, 0.24)`);
  g.addColorStop(1, `rgba(${BG}, 0)`);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, TAU);
  ctx.fill();
}

/* ---------- 单帧绘制 ---------- */
function draw(t) {
  if (!ctx || !width || !height) return;
  ctx.clearRect(0, 0, width, height);
  drawParticleNetwork(t);
  drawCore(t);
  drawScrim();
  if (currentPhase === 0) drawMeteors(lastDt);
  drawShockwaves(lastDt);
  drawFlash(t);
  drawEnergyBands(t);
  frameCount++;
  if (window.__nebulaDebug) {
    window.__nebulaDebug.frames = frameCount;
    window.__nebulaDebug.phase = currentPhase;
    window.__nebulaDebug.particles = particles.length;
    window.__nebulaDebug.running = running;
  }
}

/* ---------- 模拟 ---------- */
function simulate(dt) {
  const cx = width / 2;
  const cy = height * 0.5;
  const pull = currentPhase === 0 ? 0.00002 : 0;
  for (const p of particles) {
    if (pull) {
      p.vx += (cx - p.x) * pull * dt * 0.02;
      p.vy += (cy - p.y) * pull * dt * 0.02;
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

  if (currentPhase === 0 && !reduce) {
    meteorTimer += dt;
    if (meteorTimer > 260) {
      meteorTimer = 0;
      const angle = rand(0, TAU);
      const radius = Math.max(width, height) * rand(0.5, 0.7);
      meteors.push({
        sx: cx + Math.cos(angle) * radius,
        sy: cy + Math.sin(angle) * radius,
        age: 0,
        duration: rand(1000, 1500),
      });
    }
  }
}

/* ---------- rAF ----------
   自适应画布帧率：GPU 环境画满 60fps；软件渲染/低端机若单帧绘制超过 ~11ms，
   就隔帧绘制（约 30fps 星云背景），让页面 rAF 仍保持 60fps，不拖垮整页。 */
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

/* ---------- reduced-motion：只画一帧 ---------- */
function drawStatic() {
  if (!ctx || !width || !height) return;
  currentPhase = 2;
  initParticles();
  ctx.clearRect(0, 0, width, height);
  drawParticleNetwork(0);
  drawCore(0);
  drawEnergyBands(0);
  drawScrim();
  frameCount++;
  if (window.__nebulaDebug) {
    window.__nebulaDebug.frames = frameCount;
    window.__nebulaDebug.phase = currentPhase;
    window.__nebulaDebug.particles = particles.length;
    window.__nebulaDebug.running = false;
    window.__nebulaDebug.static = true;
  }
}

/* ---------- 挂载 / 监听 ---------- */
onMounted(() => {
  wrap = wrapRef.value;
  canvas = canvasRef.value;
  if (!wrap || !canvas) return;
  currentPhase = props.phase;
  reduce = props.reducedMotion;
  phaseStart = performance.now();
  window.__nebulaDebug = {
    frames: 0,
    phase: currentPhase,
    particles: 0,
    running: false,
    static: false,
    dpr: 1,
  };

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

  if (window.__nebulaDebug) {
    window.__nebulaDebug.dpr = dpr;
    window.__nebulaDebug.canvases = document.querySelectorAll("canvas.nebula-canvas").length;
  }
});

watch(
  () => props.phase,
  (next) => {
    currentPhase = next;
    phaseStart = performance.now();
    if (next === 1) {
      shockwaves = [
        { age: 0, duration: 950 },
        { age: -180, duration: 1100 },
      ];
    }
    if (next === 0) {
      meteors = [];
      meteorTimer = 0;
    }
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
      currentPhase = props.phase;
      phaseStart = performance.now();
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
  meteors = [];
  shockwaves = [];
  ctx = null;
  canvas = null;
  wrap = null;
  window.__nebulaDebug = null;
});
</script>

<template>
  <div ref="wrapRef" class="nebula" :data-phase="phase">
    <canvas ref="canvasRef" class="nebula-canvas" aria-hidden="true" />
  </div>
</template>
