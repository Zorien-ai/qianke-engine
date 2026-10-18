<script setup>
/**
 * Hero 右侧暗黑粒子星云（原生 Canvas，无第三方依赖）。
 *
 * 一张 canvas 画：慢速漂移的粒子星座 + 细线连接 + 中心暖金光核（呼吸）+ 阶段特效
 * （阶段1 向心流星 / 阶段2 冲击波 + 闪光 / 阶段3 三条发光贝塞尔曲线 + 流动光点）。
 * DOM 覆盖层负责 CSV 胶囊、玻璃拟态画像卡与 flash。
 *
 * 性能与生命周期：
 *   - 单 rAF 循环、dt 钳制 48ms、DPR 上限 1.75；
 *   - ResizeObserver 自适应，粒子数按面积在 70~130 间调整（小屏进一步下调）；
 *   - IntersectionObserver + visibilitychange：不可见/离开视口暂停；
 *   - prefers-reduced-motion：只画一帧静态（星云 + 曲线 + 卡片），不跑循环；
 *   - 卸载 cancelAnimationFrame、断开两个 observer、移除监听、清空引用。
 */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps({
  // 0 散落 / 1 爆发 / 2 吐出
  phase: { type: Number, default: 0 },
  reducedMotion: { type: Boolean, default: false },
  // 全幅背景模式：Canvas 铺满 Hero，作为文字后的背景层；模式内中心更暗、卡片贴角
  fullBleed: { type: Boolean, default: false },
});

const wrapRef = ref(null);
const canvasRef = ref(null);

const CHIPS = [
  // 四象限入场 + 错峰，避免向心途中叠成一坨
  { file: "orders.csv", meta: "user_id · amount", x: -32, y: -27, delay: 0 },
  { file: "用户表.csv", meta: "member_level · city", x: 31, y: -30, delay: 80 },
  { file: "rules.md", meta: "高价值客户 · 流失预警", x: -33, y: 25, delay: 160 },
  { file: "trade_2024.csv", meta: "order_id · pay_time", x: 32, y: 28, delay: 240 },
];

const CARDS = [
  {
    avatar: "高",
    name: "高价值客户",
    tags: ["高客单", "美妆偏好"],
    tx: -6,
    ty: -4,
    delay: "0ms",
    accent: "#f5b35a",
  },
  {
    avatar: "复",
    name: "复购用户",
    tags: ["近 30 天活跃", "母婴"],
    tx: 8,
    ty: -2,
    delay: "110ms",
    accent: "#7dd3c0",
  },
  {
    avatar: "预",
    name: "流失预警",
    tags: ["待召回", "沉睡用户"],
    tx: 0,
    ty: 10,
    delay: "220ms",
    accent: "#b9a6ff",
  },
];

const TAU = Math.PI * 2;
const CORE_COLOR = "245, 179, 90"; // 暖金
const MAX_DPR = 1.75;
const MAX_DT = 48;

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
let frameCount = 0;
let phaseStart = 0;
let currentPhase = props.phase;
let reduce = props.reducedMotion;

let resizeObserver = null;
let intersectionObserver = null;

function rand(min, max) {
  return min + Math.random() * (max - min);
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

/* ---------- 初始化 / 自适应 ---------- */
function particleCount() {
  const area = width * height;
  let count;
  if (props.fullBleed) {
    // 全幅背景：像素多，粒子上限收到 110，移动端再降一档
    count = clamp(Math.round(area / 12000), 70, 110);
  } else {
    count = clamp(Math.round(area / 3500), 70, 130);
  }
  if (width < 480) count = Math.min(count, props.fullBleed ? 52 : 62);
  return count;
}

function initParticles() {
  const count = particleCount();
  particles = [];
  for (let i = 0; i < count; i++) {
    const star = Math.random() < 0.14;
    particles.push({
      x: rand(0, width),
      y: rand(0, height),
      vx: rand(-0.011, 0.011),
      vy: rand(-0.011, 0.011),
      r: star ? rand(1.3, 2.1) : rand(0.6, 1.4),
      star,
      twinkle: rand(0, TAU),
      twinkleSpeed: rand(0.0006, 0.0018),
    });
  }
}

function resize() {
  if (!wrap || !canvas) return;
  const nextW = wrap.clientWidth;
  const nextH = wrap.clientHeight;
  if (!nextW || !nextH) return;
  const nextDpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
  // 全幅背景铺满整屏时，按 0.78 渲染再拉伸（软一点但省一半以上像素，帧率更稳）
  const renderScale = props.fullBleed ? 0.78 : 1;
  const nextScale = nextDpr * renderScale;
  // ResizeObserver 首次回调会和 onMounted 的 resize 重复，尺寸没变就不重排/重画
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

/* ---------- 绘制工具 ---------- */
function drawCore(t) {
  const full = props.fullBleed;
  const pulse = 0.85 + 0.15 * Math.sin(t * 0.0021);
  const since = t - phaseStart;
  const burst = currentPhase === 1 ? 1 + 0.45 * Math.max(0, 1 - since / 650) : 1;
  const cx = width / 2;
  const cy = height * 0.5;
  const coreR =
    Math.min(width, height) * (full ? 0.052 : 0.072) * pulse * (full ? 1 : burst);

  // 外层暖光（全幅背景模式下中心压暗，保证文字可读）
  const outerR = Math.min(coreR * (full ? 4.2 : 5.2), Math.min(width, height) * (full ? 0.42 : 0.58));
  let g = ctx.createRadialGradient(cx, cy, 0, cx, cy, outerR);
  g.addColorStop(0, `rgba(255, 238, 205, ${(full ? 0.24 : 0.42) * (full ? 1 : burst)})`);
  g.addColorStop(0.32, `rgba(${CORE_COLOR}, ${full ? 0.13 : 0.18})`);
  g.addColorStop(1, `rgba(${CORE_COLOR}, 0)`);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, outerR, 0, TAU);
  ctx.fill();

  // 旋转的细弧线（增强科技感）
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(t * 0.00018);
  ctx.strokeStyle = `rgba(${CORE_COLOR}, ${full ? 0.16 : 0.22})`;
  ctx.lineWidth = 1;
  for (let k = 0; k < 3; k++) {
    ctx.beginPath();
    ctx.arc(0, 0, coreR * (1.7 + k * 0.42), k * 1.9, k * 1.9 + 1.15);
    ctx.stroke();
  }
  ctx.restore();

  // 高亮光核
  const g2 = ctx.createRadialGradient(cx, cy, 0, cx, cy, coreR);
  g2.addColorStop(0, "rgba(255, 255, 255, 1)");
  g2.addColorStop(0.28, "rgba(255, 246, 228, 0.98)");
  g2.addColorStop(0.62, `rgba(${CORE_COLOR}, 0.9)`);
  g2.addColorStop(1, `rgba(${CORE_COLOR}, 0)`);
  ctx.fillStyle = g2;
  ctx.beginPath();
  ctx.arc(cx, cy, coreR, 0, TAU);
  ctx.fill();
}

function drawParticleNetwork(t) {
  const full = props.fullBleed;
  const threshold = Math.min(width, height) * (full ? 0.17 : 0.22);
  const cx = width / 2;
  const cy = height * 0.5;

  // 细线连接：按亮度分 4 桶批量描边（逐条 stroke 在整屏画布上太贵）
  const lineBuckets = [[], [], [], []];
  for (let i = 0; i < particles.length; i++) {
    const a = particles[i];
    for (let j = i + 1; j < particles.length; j++) {
      const b = particles[j];
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const d2 = dx * dx + dy * dy;
      if (d2 > threshold * threshold) continue;
      const k = 1 - Math.sqrt(d2) / threshold;
      const bucket = Math.min(3, Math.floor(k * 4));
      lineBuckets[bucket].push(a.x, a.y, b.x, b.y);
    }
  }
  const lineAlpha = full ? [0.05, 0.1, 0.15, 0.2] : [0.06, 0.12, 0.18, 0.24];
  ctx.lineWidth = 0.7;
  lineBuckets.forEach((pts, idx) => {
    if (!pts.length) return;
    ctx.strokeStyle = `rgba(${CORE_COLOR}, ${lineAlpha[idx]})`;
    ctx.beginPath();
    for (let k = 0; k < pts.length; k += 4) {
      ctx.moveTo(pts[k], pts[k + 1]);
      ctx.lineTo(pts[k + 2], pts[k + 3]);
    }
    ctx.stroke();
  });

  // 粒子本体：按 twinkle 亮度分 4 桶批量 fill；星点单独带十字光
  const dotBuckets = [[], [], [], []];
  const stars = [];
  for (const p of particles) {
    if (p.star) {
      stars.push(p);
      continue;
    }
    const twinkle = 0.55 + 0.45 * Math.sin(t * p.twinkleSpeed + p.twinkle);
    const bucket = Math.min(3, Math.floor(twinkle * 4));
    dotBuckets[bucket].push(p);
  }
  const dotAlpha = full ? [0.16, 0.24, 0.32, 0.4] : [0.18, 0.28, 0.38, 0.48];
  dotBuckets.forEach((list, idx) => {
    if (!list.length) return;
    ctx.fillStyle = `rgba(${CORE_COLOR}, ${dotAlpha[idx]})`;
    ctx.beginPath();
    for (const p of list) {
      ctx.moveTo(p.x + p.r, p.y);
      ctx.arc(p.x, p.y, p.r, 0, TAU);
    }
    ctx.fill();
  });
  if (stars.length) {
    ctx.beginPath();
    for (const p of stars) {
      const tw = 0.55 + 0.45 * Math.sin(t * p.twinkleSpeed + p.twinkle);
      const r = p.r * (1 + tw * 0.2);
      ctx.moveTo(p.x + r, p.y);
      ctx.arc(p.x, p.y, r, 0, TAU);
      ctx.moveTo(p.x - p.r * 3.4, p.y);
      ctx.lineTo(p.x + p.r * 3.4, p.y);
      ctx.moveTo(p.x, p.y - p.r * 3.4);
      ctx.lineTo(p.x, p.y + p.r * 3.4);
    }
    ctx.fillStyle = "rgba(255, 250, 240, 0.72)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 250, 240, 0.2)";
    ctx.lineWidth = 0.8;
    ctx.stroke();
  }

  // 中心附近留白：把光核区域压暗一点点，让核心更突出
  const hole = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.min(width, height) * 0.075);
  hole.addColorStop(0, "rgba(5, 6, 10, 0.55)");
  hole.addColorStop(1, "rgba(5, 6, 10, 0)");
  ctx.fillStyle = hole;
  ctx.beginPath();
  ctx.arc(cx, cy, Math.min(width, height) * 0.075, 0, TAU);
  ctx.fill();
}

function drawMeteors(dt) {
  // 阶段1：从边缘向中心汇聚的流星拖尾
  const cx = width / 2;
  const cy = height * 0.5;
  for (const m of meteors) {
    m.age += dt;
    const p = clamp(m.age / m.duration, 0, 1);
    const ease = p * p * (3 - 2 * p);
    const x = m.sx + (cx - m.sx) * ease;
    const y = m.sy + (cy - m.sy) * ease;
    const tailP = clamp(ease - 0.16, 0, 1);
    const tx = m.sx + (cx - m.sx) * tailP;
    const ty = m.sy + (cy - m.sy) * tailP;
    const alpha = Math.sin(Math.PI * p) * 0.85;
    const grad = ctx.createLinearGradient(tx, ty, x, y);
    grad.addColorStop(0, `rgba(${CORE_COLOR}, 0)`);
    grad.addColorStop(1, `rgba(255, 244, 222, ${alpha})`);
    ctx.strokeStyle = grad;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(x, y);
    ctx.stroke();
    ctx.fillStyle = `rgba(255, 250, 240, ${alpha})`;
    ctx.beginPath();
    ctx.arc(x, y, 1.7, 0, TAU);
    ctx.fill();
  }
  meteors = meteors.filter((m) => m.age < m.duration);
}

function drawShockwaves(dt) {
  const cx = width / 2;
  const cy = height * 0.5;
  const base = Math.min(width, height);
  for (const w of shockwaves) {
    w.age += dt;
    if (w.age < 0) continue;
    const p = clamp(w.age / w.duration, 0, 1);
    const alpha = (1 - p) * (props.fullBleed ? 0.4 : 0.55);
    if (alpha <= 0.01) continue;
    ctx.strokeStyle = `rgba(${CORE_COLOR}, ${alpha})`;
    ctx.lineWidth = 2.4 * (1 - p) + 0.6;
    ctx.beginPath();
    ctx.arc(cx, cy, base * (0.06 + p * 0.52), 0, TAU);
    ctx.stroke();
    ctx.strokeStyle = `rgba(255, 250, 240, ${alpha * 0.5})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, base * (0.05 + p * 0.46), 0, TAU);
    ctx.stroke();
  }
  shockwaves = shockwaves.filter((w) => w.age < w.duration);
}

function cubicPoint(p0, p1, p2, p3, t) {
  const mt = 1 - t;
  return {
    x: mt * mt * mt * p0.x + 3 * mt * mt * t * p1.x + 3 * mt * t * t * p2.x + t * t * t * p3.x,
    y: mt * mt * mt * p0.y + 3 * mt * mt * t * p1.y + 3 * mt * t * t * p2.y + t * t * t * p3.y,
  };
}

function curveTargets() {
  // 与 CSS 里 .nebula-card-N 的锚点保持一致（全幅 / ≤900 / ≤640 有各自的重排）
  if (props.fullBleed) {
    return [
      { x: width * 0.12, y: height * 0.72 },
      { x: width * 0.88, y: height * 0.68 },
      { x: width * 0.84, y: height * 0.22 },
    ];
  }
  const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
  if (vw <= 640) {
    return [
      { x: width * 0.27, y: height * 0.3 },
      { x: width * 0.72, y: height * 0.22 },
      { x: width * 0.5, y: height * 0.8 },
    ];
  }
  if (vw <= 900) {
    return [
      { x: width * 0.2, y: height * 0.28 },
      { x: width * 0.8, y: height * 0.24 },
      { x: width * 0.5, y: height * 0.8 },
    ];
  }
  return [
    { x: width * 0.17, y: height * 0.27 },
    { x: width * 0.83, y: height * 0.24 },
    { x: width * 0.51, y: height * 0.79 },
  ];
}

function drawEmitCurves(t) {
  if (currentPhase !== 2 && !reduce) return;
  // 全幅模式下小屏不显示画像卡，曲线也一起省略
  if (
    props.fullBleed &&
    typeof window !== "undefined" &&
    window.innerWidth < 1100 &&
    !reduce
  ) {
    return;
  }
  const since = t - phaseStart;
  const progress = reduce ? 1 : clamp(since / 700, 0, 1);
  const cx = width / 2;
  const cy = height * 0.5;
  const targets = curveTargets();

  targets.forEach((target, i) => {
    const p0 = { x: cx, y: cy };
    const p3 = target;
    const p1 = { x: cx + (p3.x - cx) * 0.42, y: cy + (p3.y - cy) * 0.02 };
    const p2 = { x: p3.x - (p3.x - cx) * 0.2, y: p3.y + (p3.y - cy) * 0.32 };
    const alpha = (props.fullBleed ? 0.68 : 0.55) * progress;

    ctx.save();
    ctx.strokeStyle = `rgba(${CORE_COLOR}, ${alpha * 0.35})`;
    ctx.lineWidth = 4;
    ctx.beginPath();
    for (let s = 0; s <= 1.001; s += 0.05) {
      const pt = cubicPoint(p0, p1, p2, p3, s);
      if (s === 0) ctx.moveTo(pt.x, pt.y);
      else ctx.lineTo(pt.x, pt.y);
    }
    ctx.stroke();
    ctx.strokeStyle = `rgba(255, 246, 226, ${alpha})`;
    ctx.lineWidth = 1.4;
    ctx.stroke();
    ctx.restore();

    // 沿线流动光点
    if (!reduce) {
      for (let k = 0; k < 2; k++) {
        const tt = (t * 0.00042 + i * 0.17 + k * 0.5) % 1;
        const pt = cubicPoint(p0, p1, p2, p3, tt);
        const dotAlpha = Math.sin(Math.PI * tt) * 0.9;
        ctx.fillStyle = `rgba(255, 248, 232, ${dotAlpha})`;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 2.4, 0, TAU);
        ctx.fill();
        ctx.fillStyle = `rgba(${CORE_COLOR}, ${dotAlpha * 0.35})`;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 6.5, 0, TAU);
        ctx.fill();
      }
    }
  });
}

function drawFlash(t) {
  if (currentPhase !== 1 || reduce) return;
  const since = t - phaseStart;
  if (since > 700) return;
  const alpha = Math.max(0, 1 - since / 700) * (props.fullBleed ? 0.3 : 0.42);
  const cx = width / 2;
  const cy = height * 0.5;
  const flashR = Math.min(width, height) * (props.fullBleed ? 0.36 : 0.44);
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, flashR);
  g.addColorStop(0, `rgba(255, 252, 244, ${alpha})`);
  g.addColorStop(0.45, `rgba(${CORE_COLOR}, ${alpha * 0.3})`);
  g.addColorStop(1, `rgba(${CORE_COLOR}, 0)`);
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, flashR, 0, TAU);
  ctx.fill();
}

function drawFullScrim() {
  if (!props.fullBleed) return;
  // 中心压暗融进画布，省掉一层全屏 DOM 渐变合成（软件渲染下明显更省帧）
  const cx = width / 2;
  const cy = height * 0.46;
  const r = Math.max(width * 0.62, height * 0.62);
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
  g.addColorStop(0, "rgba(5, 6, 10, 0.58)");
  g.addColorStop(0.55, "rgba(5, 6, 10, 0.22)");
  g.addColorStop(1, "rgba(5, 6, 10, 0)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, TAU);
  ctx.fill();
  // 底部渐隐，衔接到下方暖白内容区
  const lg = ctx.createLinearGradient(0, height * 0.8, 0, height);
  lg.addColorStop(0, "rgba(5, 6, 10, 0)");
  lg.addColorStop(1, "rgba(5, 6, 10, 0.9)");
  ctx.fillStyle = lg;
  ctx.fillRect(0, height * 0.8, width, height * 0.2);
}

function draw(t) {
  if (!ctx || !width || !height) return;
  ctx.clearRect(0, 0, width, height);
  drawParticleNetwork(t);
  drawCore(t);
  if (currentPhase === 0) drawMeteors(lastDt);
  drawShockwaves(lastDt);
  drawFlash(t);
  drawEmitCurves(t);
  drawFullScrim();
  frameCount++;
  if (window.__nebulaDebug) {
    window.__nebulaDebug.frames = frameCount;
    window.__nebulaDebug.phase = currentPhase;
    window.__nebulaDebug.particles = particles.length;
    window.__nebulaDebug.running = running;
  }
}

/* ---------- 主循环 ---------- */
let lastDt = 16;

function simulate(dt, t) {
  const cx = width / 2;
  const cy = height * 0.5;
  const pull = currentPhase === 0 ? 0.000028 : 0;
  const burstBoost = currentPhase === 1 ? 1.9 : 1;

  for (const p of particles) {
    if (pull) {
      p.vx += (cx - p.x) * pull * dt * 0.02;
      p.vy += (cy - p.y) * pull * dt * 0.02;
    }
    p.x += p.vx * dt * burstBoost;
    p.y += p.vy * dt * burstBoost;
    // 轻微阻尼 + 限速，避免越聚越快
    p.vx *= 0.999;
    p.vy *= 0.999;
    const speed = Math.hypot(p.vx, p.vy);
    if (speed > 0.05) {
      p.vx = (p.vx / speed) * 0.05;
      p.vy = (p.vy / speed) * 0.05;
    }
    if (p.x < -12) p.x = width + 12;
    if (p.x > width + 12) p.x = -12;
    if (p.y < -12) p.y = height + 12;
    if (p.y > height + 12) p.y = -12;
  }

  // 阶段1：周期生成向心流星
  if (currentPhase === 0 && !reduce) {
    meteorTimer += dt;
    if (meteorTimer > 170) {
      meteorTimer = 0;
      const angle = rand(0, TAU);
      const radius = Math.max(width, height) * rand(0.5, 0.72);
      meteors.push({
        sx: cx + Math.cos(angle) * radius,
        sy: cy + Math.sin(angle) * radius,
        age: 0,
        duration: rand(880, 1350),
      });
    }
  }
}

let meteorTimer = 0;

function loop(ts) {
  if (!running) return;
  rafId = requestAnimationFrame(loop);
  const dt = lastTs ? Math.min(MAX_DT, ts - lastTs) : 16;
  lastTs = ts;
  lastDt = dt;
  const t = ts - startedAt;
  simulate(dt, t);
  draw(t);
}

let startedAt = 0;

function start() {
  if (reduce || running || !ctx) return;
  running = true;
  lastTs = 0;
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

/* ---------- 降低动效：只画一帧 ---------- */
function drawStatic() {
  if (!ctx || !width || !height) return;
  currentPhase = 2;
  // 静态星云：固定种子式刷新一次粒子位置
  initParticles();
  ctx.clearRect(0, 0, width, height);
  drawParticleNetwork(0);
  drawCore(0);
  drawEmitCurves(0);
  drawFullScrim();
  frameCount++;
  if (window.__nebulaDebug) {
    window.__nebulaDebug.frames = frameCount;
    window.__nebulaDebug.phase = currentPhase;
    window.__nebulaDebug.particles = particles.length;
    window.__nebulaDebug.running = false;
    window.__nebulaDebug.static = true;
  }
}

/* ---------- 生命周期 ---------- */
let visHandler = null;

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

  if (reduce) {
    // resize() 里已经按 reduce 画过静态一帧，这里不再重复画
  } else {
    start();
  }

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
        { age: -170, duration: 1050 },
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
  <div ref="wrapRef" class="nebula" :class="[`is-phase-${phase}`, { 'is-full': fullBleed }]">
    <canvas ref="canvasRef" class="nebula-canvas" aria-hidden="true" />

    <div class="nebula-overlay" aria-hidden="true">
      <!-- 阶段1：向心汇聚的 CSV 胶囊（全幅背景模式只用 Canvas 氛围，不铺文字胶囊） -->
      <template v-if="!fullBleed">
        <span
          v-for="chip in CHIPS"
          :key="chip.file"
          class="nebula-chip"
          :style="{
            '--x': `${chip.x}cqw`,
            '--y': `${chip.y}cqw`,
            '--x-mid': `${(chip.x * 0.82).toFixed(1)}cqw`,
            '--y-mid': `${(chip.y * 0.82).toFixed(1)}cqw`,
            '--x-late': `${(chip.x * 0.38).toFixed(1)}cqw`,
            '--y-late': `${(chip.y * 0.38).toFixed(1)}cqw`,
            '--delay': `${chip.delay}ms`,
          }"
        >
          <span class="nebula-chip-file">{{ chip.file }}</span>
          <span class="nebula-chip-meta">{{ chip.meta }}</span>
        </span>
      </template>

      <!-- 阶段2：一次白金光 flash -->
      <span v-if="phase === 1" class="nebula-flash" />

      <!-- 阶段3：三张玻璃拟态画像卡（位置在 CSS，移动端可重排） -->
      <article
        v-for="(card, i) in CARDS"
        :key="card.name"
        class="nebula-card"
        :class="`nebula-card-${i + 1}`"
        :style="{
          '--tw': `${card.tx}px`,
          '--th': `${card.ty}px`,
          '--delay': card.delay,
          '--accent': card.accent,
        }"
      >
        <span class="nebula-card-avatar">{{ card.avatar }}</span>
        <span class="nebula-card-body">
          <span class="nebula-card-name">{{ card.name }}</span>
          <span class="nebula-card-tags">
            <span v-for="tag in card.tags" :key="tag">{{ tag }}</span>
          </span>
        </span>
      </article>
    </div>
  </div>
</template>
