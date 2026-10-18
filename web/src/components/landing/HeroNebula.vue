<script setup>
/**
 * Hero 叙事星云（task-13 终极特效版）。
 *
 * 渲染优先级：
 *   1) WebGL / Three.js：3D 粒子云（1200~2000 颗、近大远小、additive、正弦扰动）+ 中心泛光 sprite
 *      + UnrealBloomPass 强泛光 + ~250 颗 kNN 密集网络连线（LineSegments additive）+ 缓慢自转；
 *   2) WebGL 不可用时降级 Canvas2D：大 radial gradient 光晕 + lighter 叠加 + 正弦扰动粒子 + 密集连线。
 *
 * 阶段（由 Landing.vue 的 7s 时间轴驱动）：search → absorb → result → final。
 *   absorb：Bloom ×~3 爆闪 0.15~0.25s + 一次性闪光环 + 粒子轻微向内收。
 * 生命周期：页面隐藏/离屏暂停；卸载 dispose geometry/material/texture/renderer 与 rAF；reduced-motion 只渲染单帧。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";

const props = defineProps({
  stage: { type: String, default: "search" },
  reducedMotion: { type: Boolean, default: false },
  users: { type: Array, default: () => [] },
  matchedUsers: { type: Array, default: () => [] },
  // 舞台 DOM（Landing.vue 传入），用于把 tooltip Teleport 到结果卡之上
  tooltipTarget: { type: Object, default: null },
});

const wrapRef = ref(null);
const tooltip = ref(null);

const TAU = Math.PI * 2;
const MAX_DT = 48;
const BLOOM_BASE = 0.55;
const WEBGL_RENDER_SCALE = 0.6;
const FALLBACK_SCALE = 0.62;
const PARTICLE_COUNT = 1600;
const LINK_COUNT = 280;

let wrap = null;
let canvas = null;
let mode = "webgl"; // webgl | canvas2d
let running = false;
let visible = true;
let reduce = props.reducedMotion;
let currentStage = props.stage;
let rafId = 0;
let lastTs = 0;
let frameCount = 0;
let stageStart = 0;
let absorbStart = -1;
let hiddenAt = 0;

let renderer = null;
let composer = null;
let bloomPass = null;
let scene = null;
let camera = null;
let cloud = null;
let points = null;
let linkLines = null;
let coreSprite = null;
let outerSprite = null;
let flashRing = null;
let coreTex = null;
let coreMat = null;
let outerMat = null;
let flashMat = null;
let pointsGeom = null;
let pointsMat = null;
let linkGeom = null;
let linkMat = null;
let basePositions = null;
let linkPairs = null;
let linkPositions = null;

let ctx2d = null;
let fallbackParticles = [];
let fallbackPairs = [];
let spriteTex2d = null;

/* 交互：每颗粒子 = 一位 demo 用户（users[i % users.length]） */
let stageEl = null;
let pointerIn = false;
let pointerX = 0;
let pointerY = 0;
let pointerDirty = false;
let hoveredIndex = -1;
let pinnedIndex = -1;
let lastRenderTs = 0;
let basePhases = null;

const _hitVec = new THREE.Vector3();
let pointerMoveHandler = null;
let pointerLeaveHandler = null;
let pointerDownHandler = null;

let resizeObserver = null;
let intersectionObserver = null;
let visHandler = null;
let disposed = false;
let runStartedAt = 0;
let fpsChecked = 0;

/* 自适应画质档位：SwiftShader/低端 GPU 自动降分辨率，真机保持高画质 */
const WebGLQuality = { level: 0, scale: WEBGL_RENDER_SCALE, bloomScale: 0.5 };

const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
const rand = (min, max) => min + Math.random() * (max - min);
const easeOut = (p) => 1 - Math.pow(1 - clamp(p, 0, 1), 3);

/* ---------------- 工具：纹理 ---------------- */
function makeGlowTexture(inner = "rgba(255,255,255,1)", mid = "rgba(255,214,150,0.5)") {
  const size = 256;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0, inner);
  grad.addColorStop(0.25, mid);
  grad.addColorStop(0.55, "rgba(245,179,90,0.18)");
  grad.addColorStop(1, "rgba(245,179,90,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return tex;
}

function makePointTexture() {
  const size = 128;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(255,246,230,0.9)");
  grad.addColorStop(0.7, "rgba(255,220,175,0.25)");
  grad.addColorStop(1, "rgba(255,220,175,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/* ---------------- Three.js 粒子云 ---------------- */
const vertexShader = /* glsl */ `
  attribute float aSize;
  attribute float aPhase;
  attribute float aTwinkle;
  attribute vec3 aColor;
  uniform float uTime;
  uniform float uPixelRatio;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec3 p = position;
    float t = uTime;
    p.x += sin(t * 0.55 + aPhase) * 0.24;
    p.y += cos(t * 0.47 + aPhase * 1.7) * 0.2;
    p.z += sin(t * 0.4 + aPhase * 0.7) * 0.18;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_PointSize = aSize * uPixelRatio * (36.0 / max(0.6, -mv.z));
    gl_Position = projectionMatrix * mv;
    vColor = aColor;
    vAlpha = 0.62 + 0.38 * sin(t * aTwinkle + aPhase);
  }
`;

const fragmentShader = /* glsl */ `
  uniform float uOpacity;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - vec2(0.5));
    // 收紧光点核心：泛光压低后每一颗要能看清，而不是糊成一团光
    float a = smoothstep(0.5, 0.08, d);
    a = pow(a, 2.6);
    gl_FragColor = vec4(vColor, a * uOpacity * vAlpha);
  }
`;

function buildCloudData() {
  const count = PARTICLE_COUNT;
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const phases = new Float32Array(count);
  const twinkles = new Float32Array(count);

  for (let i = 0; i < count; i++) {
    const r = 1.2 + Math.pow(Math.random(), 0.56) * 3.2;
    const theta = Math.random() * TAU;
    const phi = Math.acos(rand(-1, 1)) * 0.82;
    const spiral = r * 0.55;
    const x = Math.cos(theta + spiral) * r * Math.sin(phi);
    const z = Math.sin(theta + spiral) * r * Math.sin(phi);
    const y = Math.cos(phi) * r * 0.58;
    positions[i * 3] = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = z;

    const depth = clamp((r - 1.2) / 3.2, 0, 1);
    sizes[i] = 0.42 + (1 - depth) * 0.5 + Math.pow(Math.random(), 2.2) * 0.35;

    const kind = Math.random();
    let cr;
    let cg;
    let cb;
    if (kind < 0.68) {
      cr = 1;
      cg = rand(0.86, 0.96);
      cb = rand(0.72, 0.86);
    } else if (kind < 0.9) {
      cr = 1;
      cg = rand(0.62, 0.78);
      cb = rand(0.28, 0.46);
    } else {
      cr = rand(0.55, 0.75);
      cg = rand(0.72, 0.86);
      cb = rand(0.92, 1);
    }
    colors[i * 3] = cr;
    colors[i * 3 + 1] = cg;
    colors[i * 3 + 2] = cb;
    phases[i] = rand(0, TAU);
    twinkles[i] = rand(0.4, 1.5);
  }

  // kNN 连线：~250 颗，每颗连最近 2~3 颗（总线段 ~550）
  const linkable = [];
  for (let i = 0; i < count; i++) {
    const x = positions[i * 3];
    const y = positions[i * 3 + 1];
    const z = positions[i * 3 + 2];
    const r = Math.sqrt(x * x + y * y + z * z);
    if (r < 3.9) linkable.push(i);
  }
  const picked = [];
  const step = Math.max(1, Math.floor(linkable.length / LINK_COUNT));
  for (let i = 0; i < linkable.length && picked.length < LINK_COUNT; i += step) {
    picked.push(linkable[i]);
  }
  const pairs = [];
  for (const i of picked) {
    const ax = positions[i * 3];
    const ay = positions[i * 3 + 1];
    const az = positions[i * 3 + 2];
    const dists = [];
    for (const j of picked) {
      if (j === i) continue;
      const dx = ax - positions[j * 3];
      const dy = ay - positions[j * 3];
      const dz = az - positions[j * 3];
      dists.push({ j, d: Math.sqrt(dx * dx + dy * dy + dz * dz) });
    }
    dists.sort((a, b) => a.d - b.d);
    const need = 2;
    for (let k = 0; k < Math.min(need, dists.length); k++) {
      pairs.push([i, dists[k].j]);
    }
  }
  return { positions, colors, sizes, phases, twinkles, pairs };
}

function initWebGL() {
  renderer = new THREE.WebGLRenderer({
    antialias: false,
    alpha: false,
    powerPreference: "high-performance",
    preserveDrawingBuffer: false,
  });
  renderer.setClearColor(0x050506, 1);
  renderer.setPixelRatio(1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  canvas = renderer.domElement;
  canvas.className = "nebula-canvas";
  canvas.setAttribute("aria-hidden", "true");
  wrap.appendChild(canvas);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x050506);
  camera = new THREE.PerspectiveCamera(58, 1, 0.1, 100);
  camera.position.set(0, 0, 7.2);

  cloud = new THREE.Group();
  scene.add(cloud);

  const data = buildCloudData();
  basePositions = data.positions;
  basePhases = data.phases;
  pointsGeom = new THREE.BufferGeometry();
  pointsGeom.setAttribute("position", new THREE.BufferAttribute(data.positions, 3));
  pointsGeom.setAttribute("aColor", new THREE.BufferAttribute(data.colors, 3));
  pointsGeom.setAttribute("aSize", new THREE.BufferAttribute(data.sizes, 1));
  pointsGeom.setAttribute("aPhase", new THREE.BufferAttribute(data.phases, 1));
  pointsGeom.setAttribute("aTwinkle", new THREE.BufferAttribute(data.twinkles, 1));

  const pointTex = makePointTexture();
  pointsMat = new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
      uOpacity: { value: 0.82 },
      uMap: { value: pointTex },
    },
    vertexShader,
    fragmentShader,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  points = new THREE.Points(pointsGeom, pointsMat);
  cloud.add(points);

  // 密集网络连线
  linkPairs = data.pairs;
  linkPositions = new Float32Array(linkPairs.length * 2 * 3);
  linkGeom = new THREE.BufferGeometry();
  linkGeom.setAttribute("position", new THREE.BufferAttribute(linkPositions, 3));
  linkMat = new THREE.LineBasicMaterial({
    color: 0xf5c07a,
    transparent: true,
    opacity: 0.085,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  linkLines = new THREE.LineSegments(linkGeom, linkMat);
  cloud.add(linkLines);

  // 中心强泛光 sprite（两层）
  coreTex = makeGlowTexture();
  coreMat = new THREE.SpriteMaterial({
    map: coreTex,
    color: 0xffe2b4,
    transparent: true,
    opacity: 0.45,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  coreSprite = new THREE.Sprite(coreMat);
  coreSprite.scale.set(0.95, 0.95, 1);
  coreSprite.position.set(0, -0.5, 0);
  scene.add(coreSprite);

  outerMat = new THREE.SpriteMaterial({
    map: coreTex,
    color: 0xf5b35a,
    transparent: true,
    opacity: 0.1,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  outerSprite = new THREE.Sprite(outerMat);
  outerSprite.scale.set(2.2, 2.2, 1);
  outerSprite.position.set(0, -0.55, -0.1);
  scene.add(outerSprite);

  // 体积雾感：两片超低透明度的大 sprite，让云有「星云」而不是纯线框
  // （泛光压低后雾也要更轻，否则又会糊成一片）
  for (const [x, y, z, s, op] of [
    [-1.4, 0.6, -1.8, 7.2, 0.022],
    [1.5, -0.9, -2.4, 8.6, 0.018],
  ]) {
    const hazeMat = new THREE.SpriteMaterial({
      map: coreTex,
      color: 0xf0b46a,
      transparent: true,
      opacity: op,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const haze = new THREE.Sprite(hazeMat);
    haze.position.set(x, y, z);
    haze.scale.set(s, s * 0.8, 1);
    scene.add(haze);
  }

  // 一次性闪光环
  flashMat = new THREE.MeshBasicMaterial({
    color: 0xffe3b8,
    transparent: true,
    opacity: 0,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  flashRing = new THREE.Mesh(new THREE.RingGeometry(0.985, 1.0, 96), flashMat);
  flashRing.position.z = 0.1;
  scene.add(flashRing);

  composer = new EffectComposer(renderer);
  composer.setPixelRatio(1);
  composer.addPass(new RenderPass(scene, camera));
  const size = currentSize();
  bloomPass = new UnrealBloomPass(
    new THREE.Vector2(Math.max(64, size.w * WEBGL_RENDER_SCALE * 0.45), Math.max(64, size.h * WEBGL_RENDER_SCALE * 0.45)),
    BLOOM_BASE,
    0.42,
    0.3
  );
  composer.addPass(bloomPass);
  composer.addPass(new OutputPass());

  setSize();
  mode = "webgl";
  updateDebug();
}

/* ---------------- 尺寸 ---------------- */
function currentSize() {
  const w = wrap ? wrap.clientWidth : 0;
  const h = wrap ? wrap.clientHeight : 0;
  return { w: Math.max(1, w), h: Math.max(1, h) };
}

function setSize() {
  if (!wrap) return;
  const { w, h } = currentSize();
  if (mode === "webgl" && renderer) {
    const rw = Math.max(160, Math.round(w * WebGLQuality.scale));
    const rh = Math.max(160, Math.round(h * WebGLQuality.scale));
    renderer.setSize(rw, rh, false);
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    if (camera) {
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
    if (composer) composer.setSize(rw, rh);
    if (bloomPass) {
      bloomPass.setSize(
        Math.round(rw * WebGLQuality.bloomScale),
        Math.round(rh * WebGLQuality.bloomScale)
      );
    }
    if (pointsMat) pointsMat.uniforms.uPixelRatio.value = (w * WebGLQuality.scale) / w;
  } else if (mode === "canvas2d" && ctx2d) {
    const rw = Math.max(160, Math.round(w * FALLBACK_SCALE));
    const rh = Math.max(160, Math.round(h * FALLBACK_SCALE));
    canvas.width = rw;
    canvas.height = rh;
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    initFallbackParticles();
  }
}

function applyQuality(level) {
  if (mode !== "webgl" || WebGLQuality.level === level) return;
  WebGLQuality.level = level;
  if (level >= 2) {
    WebGLQuality.scale = 0.42;
    WebGLQuality.bloomScale = 0.3;
  } else if (level === 1) {
    WebGLQuality.scale = 0.5;
    WebGLQuality.bloomScale = 0.38;
  }
  setSize();
  updateDebug();
}

/* ---------------- 每帧 ---------------- */
function updateLinks(time) {
  if (!linkGeom || !linkPairs) return;
  const pos = linkPositions;
  for (let p = 0; p < linkPairs.length; p++) {
    const pair = linkPairs[p];
    for (let s = 0; s < 2; s++) {
      const i = pair[s];
      const bx = basePositions[i * 3];
      const by = basePositions[i * 3 + 1];
      const bz = basePositions[i * 3 + 2];
      const phase = i * 0.37;
      const x = bx + Math.sin(time * 0.55 + phase) * 0.24;
      const y = by + Math.cos(time * 0.47 + phase * 1.7) * 0.2;
      const z = bz + Math.sin(time * 0.4 + phase * 0.7) * 0.18;
      const o = (p * 2 + s) * 3;
      pos[o] = x;
      pos[o + 1] = y;
      pos[o + 2] = z;
    }
  }
  linkGeom.attributes.position.needsUpdate = true;
}

function renderFrame(ts) {
  const time = ts / 1000;
  if (pointsMat) pointsMat.uniforms.uTime.value = time;
  if (cloud) {
    cloud.rotation.y = time * 0.055;
    cloud.rotation.x = Math.sin(time * 0.12) * 0.06;
  }
  updateLinks(time);

  const since = absorbStart >= 0 ? ts - absorbStart : Infinity;
  const absorbPulse = absorbStart >= 0 && since < 700 ? 1 - clamp(since / 700, 0, 1) : 0;
  let bloomBoost = absorbPulse * 0.18;
  if (absorbStart >= 0 && since < 220) {
    bloomBoost = BLOOM_BASE * 1.8 * (1 - clamp(since / 220, 0, 1));
  }

  if (coreSprite) {
    const pulse = 1 + Math.sin(time * 1.9) * 0.05 + absorbPulse * 0.45;
    coreSprite.scale.set(0.95 * pulse, 0.95 * pulse, 1);
    coreMat.opacity = 0.45 + absorbPulse * 0.12;
  }
  if (outerSprite) {
    outerSprite.scale.set(2.2 + absorbPulse * 1.4, 2.2 + absorbPulse * 1.4, 1);
    outerMat.opacity = 0.1 + absorbPulse * 0.1;
  }
  if (pointsMat) pointsMat.uniforms.uOpacity.value = 0.82 + absorbPulse * 0.08;
  if (linkMat) linkMat.opacity = 0.085 + absorbPulse * 0.06;
  if (bloomPass) bloomPass.strength = BLOOM_BASE + bloomBoost;

  if (flashRing && flashMat) {
    if (absorbStart >= 0 && since < 700) {
      const p = easeOut(clamp(since / 700, 0, 1));
      const s = 0.5 + p * 4.6;
      flashRing.scale.set(s, s, 1);
      flashMat.opacity = 0.28 * (1 - p);
    } else {
      flashMat.opacity = 0;
    }
  }

  if (composer) composer.render();
  frameCount++;
  lastRenderTs = ts;
  updateInteraction(ts / 1000);
  updateDebug();
}

/* ---------------- 星云节点 ↔ demo 用户交互 ---------------- */
const userAt = (index) => {
  const list = props.users;
  if (!list || !list.length) return null;
  return list[index % list.length] || null;
};

function moneyText(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "–";
  return Math.round(n).toLocaleString("zh-CN");
}

function projectParticle(index, timeSec) {
  if (!cloud || !camera || !basePositions) return null;
  const i3 = index * 3;
  const phase = basePhases ? basePhases[index] : index * 0.37;
  const t = timeSec;
  const x = basePositions[i3] + Math.sin(t * 0.55 + phase) * 0.24;
  const y = basePositions[i3 + 1] + Math.cos(t * 0.47 + phase * 1.7) * 0.2;
  const z = basePositions[i3 + 2] + Math.sin(t * 0.4 + phase * 0.7) * 0.18;
  _hitVec.set(x, y, z);
  cloud.updateMatrixWorld(true);
  _hitVec.applyMatrix4(cloud.matrixWorld);
  _hitVec.project(camera);
  if (_hitVec.z > 1 || _hitVec.z < -1) return null;
  const w = wrap ? wrap.clientWidth : 0;
  const h = wrap ? wrap.clientHeight : 0;
  return {
    x: (_hitVec.x * 0.5 + 0.5) * w,
    y: (-_hitVec.y * 0.5 + 0.5) * h,
    z: _hitVec.z,
  };
}

// 命中测试：14px 内最近的粒子；WebGL 做 3D 投影，Canvas2D 用动态屏幕坐标
function hitTest(px, py, timeSec) {
  if (!props.users.length) return -1;
  const r2 = 14 * 14;
  let best = -1;
  let bestD = r2;
  if (mode === "webgl") {
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const p = projectParticle(i, timeSec);
      if (!p) continue;
      const dx = p.x - px;
      const dy = p.y - py;
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
  } else {
    const cw = canvas ? canvas.width : 1;
    const ch = canvas ? canvas.height : 1;
    const w = wrap ? wrap.clientWidth : 1;
    const h = wrap ? wrap.clientHeight : 1;
    for (let i = 0; i < fallbackParticles.length; i++) {
      const q = fallbackParticles[i];
      const sx = ((q.x + Math.sin(timeSec * 0.55 + q.phase) * 8) / cw) * w;
      const sy = ((q.y + Math.cos(timeSec * 0.47 + q.phase * 1.7) * 7) / ch) * h;
      const dx = sx - px;
      const dy = sy - py;
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
  }
  return best;
}

function tooltipLines(user) {
  const lines = [];
  const row1 = [];
  if (Number.isFinite(Number(user.avg_amount))) row1.push(`客单价 ¥${moneyText(user.avg_amount)}`);
  if (user.order_count != null) row1.push(`${user.order_count} 单`);
  if (user.top_category) row1.push(`偏好${user.top_category}`);
  if (row1.length) lines.push(row1.join(" · "));
  const row2 = [];
  if (user.city) row2.push(user.city);
  if (user.days_since_last_buy != null) row2.push(`最近购买 ${user.days_since_last_buy} 天前`);
  if (row2.length) lines.push(row2.join(" · "));
  return lines;
}

function setTooltip(index, pinned, timeSec) {
  const user = userAt(index);
  if (!user) {
    tooltip.value = null;
    return;
  }
  const pos = mode === "webgl" ? projectParticle(index, timeSec) : null;
  let sx = 0;
  let sy = 0;
  if (pos) {
    sx = pos.x;
    sy = pos.y;
  } else if (mode === "canvas2d" && canvas && wrap) {
    const q = fallbackParticles[index];
    if (q) {
      sx = ((q.x + Math.sin(timeSec * 0.55 + q.phase) * 8) / canvas.width) * wrap.clientWidth;
      sy = ((q.y + Math.cos(timeSec * 0.47 + q.phase * 1.7) * 7) / canvas.height) * wrap.clientHeight;
    }
  }
  tooltip.value = {
    user,
    pinned,
    index,
    x: sx,
    y: sy,
    meta: [user.gender, Number.isFinite(Number(user.age)) ? `${user.age} 岁` : "", user.member_level]
      .filter(Boolean)
      .join(" · "),
    lines: tooltipLines(user),
  };
}

function updateInteraction(timeSec) {
  if (!wrap) return;
  if (!props.users.length) {
    if (tooltip.value) tooltip.value = null;
    return;
  }
  if (pinnedIndex >= 0) {
    setTooltip(pinnedIndex, true, timeSec);
    return;
  }
  if (!pointerIn) {
    if (tooltip.value) tooltip.value = null;
    wrap.style.cursor = "default";
    return;
  }
  if (pointerDirty) {
    pointerDirty = false;
    const idx = hitTest(pointerX, pointerY, timeSec);
    hoveredIndex = idx;
    if (idx >= 0) {
      setTooltip(idx, false, timeSec);
      wrap.style.cursor = "pointer";
    } else {
      tooltip.value = null;
      wrap.style.cursor = "default";
    }
  } else if (hoveredIndex >= 0) {
    setTooltip(hoveredIndex, false, timeSec);
  }
}

function syncInteractionStatic() {
  if (!props.users.length) return;
  const timeSec = 0;
  if (pinnedIndex >= 0) {
    setTooltip(pinnedIndex, true, timeSec);
    return;
  }
  if (!pointerIn) {
    tooltip.value = null;
    if (wrap) wrap.style.cursor = "default";
    return;
  }
  const idx = hitTest(pointerX, pointerY, timeSec);
  hoveredIndex = idx;
  if (idx >= 0) {
    setTooltip(idx, false, timeSec);
    if (wrap) wrap.style.cursor = "pointer";
  } else {
    tooltip.value = null;
    if (wrap) wrap.style.cursor = "default";
  }
}

const tooltipStyle = computed(() => {
  const t = tooltip.value;
  if (!t) return {};
  const w = wrap ? wrap.clientWidth : 0;
  const h = wrap ? wrap.clientHeight : 0;
  const estW = 252;
  const estH = 104;
  let left = t.x + 16;
  let top = t.y - 22;
  if (left + estW > w - 8) left = Math.max(8, t.x - 16 - estW);
  if (top < 8) top = t.y + 18;
  if (top + estH > h - 8) top = Math.max(8, h - estH - 8);
  return { left: `${Math.round(left)}px`, top: `${Math.round(top)}px` };
});

function onPointerMove(e) {
  const rect = stageEl ? stageEl.getBoundingClientRect() : wrap.getBoundingClientRect();
  pointerX = e.clientX - rect.left;
  pointerY = e.clientY - rect.top;
  pointerIn = true;
  pointerDirty = true;
  if (!running) syncInteractionStatic();
}

function onPointerLeave() {
  pointerIn = false;
  pointerDirty = false;
  hoveredIndex = -1;
  if (pinnedIndex < 0) tooltip.value = null;
  if (wrap) wrap.style.cursor = "default";
}

function onPointerDown(e) {
  if (!props.users.length) return;
  const rect = stageEl ? stageEl.getBoundingClientRect() : wrap.getBoundingClientRect();
  const px = e.clientX - rect.left;
  const py = e.clientY - rect.top;
  const timeSec = running ? lastRenderTs / 1000 : 0;
  // 优先使用当前 hover 命中的粒子：截图/逐帧之间云会缓慢自转，避免 click 时重新投影落空
  let idx = hoveredIndex >= 0 ? hoveredIndex : hitTest(px, py, timeSec);
  if (idx >= 0) {
    pinnedIndex = pinnedIndex === idx ? -1 : idx;
    hoveredIndex = idx;
    pointerIn = true;
    if (pinnedIndex >= 0) setTooltip(pinnedIndex, true, timeSec);
    else setTooltip(idx, false, timeSec);
  } else {
    pinnedIndex = -1;
    tooltip.value = null;
  }
  if (!running) syncInteractionStatic();
}

/* ---------------- Canvas2D 降级 ---------------- */
function initFallbackCanvas() {
  canvas = document.createElement("canvas");
  canvas.className = "nebula-canvas";
  canvas.setAttribute("aria-hidden", "true");
  wrap.appendChild(canvas);
  ctx2d = canvas.getContext("2d");
  spriteTex2d = makePointTexture().image;
  mode = "canvas2d";
  initFallbackParticles();
  setSize();
  updateDebug();
}

function initFallbackParticles() {
  const w = canvas ? canvas.width : 800;
  const h = canvas ? canvas.height : 600;
  const count = 1200;
  const particles = [];
  for (let i = 0; i < count; i++) {
    const a = Math.random() * TAU;
    const r = Math.pow(Math.random(), 0.55) * Math.min(w, h) * 0.46;
    const x = w / 2 + Math.cos(a) * r;
    const y = h / 2 + Math.sin(a) * r * 0.78;
    const depth = Math.pow(Math.random(), 1.6);
    particles.push({
      x,
      y,
      r: 0.6 + depth * 2.4,
      phase: rand(0, TAU),
      twinkle: rand(0.5, 1.6),
      warm: Math.random() < 0.82,
      depth,
    });
  }
  fallbackParticles = particles;
  const pairs = [];
  const maxD = Math.min(w, h) * 0.075;
  for (let i = 0; i < particles.length && pairs.length < 900; i += 4) {
    const a = particles[i];
    let best = -1;
    let bestD = Infinity;
    let best2 = -1;
    let best2D = Infinity;
    for (let j = 0; j < particles.length; j += 3) {
      if (j === i) continue;
      const b = particles[j];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (d < bestD) {
        best2 = best;
        best2D = bestD;
        best = j;
        bestD = d;
      } else if (d < best2D) {
        best2 = j;
        best2D = d;
      }
    }
    if (best >= 0 && bestD < maxD) pairs.push([i, best]);
    if (best2 >= 0 && best2D < maxD) pairs.push([i, best2]);
  }
  fallbackPairs = pairs;
}

function renderFallback(ts) {
  const time = ts / 1000;
  const w = canvas.width;
  const h = canvas.height;
  const since = absorbStart >= 0 ? ts - absorbStart : Infinity;
  const absorbPulse = absorbStart >= 0 && since < 700 ? 1 - clamp(since / 700, 0, 1) : 0;

  ctx2d.globalCompositeOperation = "source-over";
  ctx2d.clearRect(0, 0, w, h);
  ctx2d.globalCompositeOperation = "lighter";

  const cx = w * 0.5;
  const cy = h * 0.5;
  const glowR = Math.min(w, h) * (0.34 + absorbPulse * 0.1);
  const g = ctx2d.createRadialGradient(cx, cy, 0, cx, cy, glowR);
  g.addColorStop(0, `rgba(255,248,232,${0.9 + absorbPulse * 0.1})`);
  g.addColorStop(0.2, "rgba(255,226,180,0.5)");
  g.addColorStop(0.5, "rgba(245,179,90,0.14)");
  g.addColorStop(1, "rgba(245,179,90,0)");
  ctx2d.fillStyle = g;
  ctx2d.beginPath();
  ctx2d.arc(cx, cy, glowR, 0, TAU);
  ctx2d.fill();

  ctx2d.strokeStyle = `rgba(245,192,122,${0.14 + absorbPulse * 0.1})`;
  ctx2d.lineWidth = 0.7;
  ctx2d.beginPath();
  for (const [i, j] of fallbackPairs) {
    const a = fallbackParticles[i];
    const b = fallbackParticles[j];
    const ax = a.x + Math.sin(time * 0.55 + a.phase) * 8;
    const ay = a.y + Math.cos(time * 0.47 + a.phase * 1.7) * 7;
    const bx = b.x + Math.sin(time * 0.55 + b.phase) * 8;
    const by = b.y + Math.cos(time * 0.47 + b.phase * 1.7) * 7;
    ctx2d.moveTo(ax, ay);
    ctx2d.lineTo(bx, by);
  }
  ctx2d.stroke();

  for (const p of fallbackParticles) {
    const x = p.x + Math.sin(time * 0.55 + p.phase) * 8;
    const y = p.y + Math.cos(time * 0.47 + p.phase * 1.7) * 7;
    const tw = 0.65 + 0.35 * Math.sin(time * p.twinkle * 1.8 + p.phase);
    const size = p.r * 7 * (0.7 + p.depth * 0.7);
    ctx2d.globalAlpha = tw * (0.5 + p.depth * 0.4);
    ctx2d.drawImage(spriteTex2d, x - size / 2, y - size / 2, size, size);
  }
  ctx2d.globalAlpha = 1;
  frameCount++;
  lastRenderTs = ts;
  updateInteraction(ts / 1000);
  updateDebug();
}

/* ---------------- 调试 ---------------- */
function updateDebug() {
  window.__nebulaDebug = {
    mode,
    frames: frameCount,
    running,
    particles: mode === "webgl" ? PARTICLE_COUNT : fallbackParticles.length,
    links: mode === "webgl" ? (linkPairs ? linkPairs.length : 0) : fallbackPairs.length,
    bloom: bloomPass ? Number(bloomPass.strength.toFixed(2)) : null,
    dpr: renderer ? renderer.getPixelRatio() : 1,
    hovered: hoveredIndex >= 0 ? userAt(hoveredIndex)?.uid || null : null,
    pinned: pinnedIndex >= 0 ? userAt(pinnedIndex)?.uid || null : null,
    quality: {
      renderScale: WebGLQuality.scale,
      bloomScale: WebGLQuality.bloomScale,
      level: WebGLQuality.level,
    },
  };
}

/* ---------------- 主循环 ---------------- */
let drawCost = 0;
function loop(ts) {
  if (!running) return;
  rafId = requestAnimationFrame(loop);
  const dt = lastTs ? Math.min(MAX_DT, ts - lastTs) : 16;
  lastTs = ts;
  const t0 = performance.now();
  if (mode === "webgl") renderFrame(ts);
  else renderFallback(ts);
  const cost = performance.now() - t0;
  drawCost = drawCost ? drawCost * 0.92 + cost * 0.08 : cost;
  void dt;

  // 低端/SwiftShader 自动降级：先降分辨率，再降 Bloom 分辨率（真机不会触发）
  const runMs = ts - runStartedAt;
  if (mode === "webgl" && runMs > 2200 && runMs - fpsChecked > 2500) {
    fpsChecked = runMs;
    const fps = frameCount / (runMs / 1000);
    if (fps < 32 && WebGLQuality.level === 0) applyQuality(1);
    else if (fps < 24 && WebGLQuality.level === 1) applyQuality(2);
  }
}

function start() {
  if (reduce || running) return;
  if (mode === "webgl" && !composer) return;
  if (mode === "canvas2d" && !ctx2d) return;
  running = true;
  runStartedAt = performance.now();
  lastTs = 0;
  rafId = requestAnimationFrame(loop);
  updateDebug();
}

function stop() {
  running = false;
  if (rafId) cancelAnimationFrame(rafId);
  rafId = 0;
  updateDebug();
}

function renderStatic() {
  if (mode === "webgl" && composer) {
    absorbStart = -1;
    if (bloomPass) bloomPass.strength = BLOOM_BASE;
    renderFrame(0);
  } else if (mode === "canvas2d" && ctx2d) {
    absorbStart = -1;
    renderFallback(0);
  }
}

/* ---------------- 生命周期 ---------------- */
function disposeWebGL() {
  if (composer) {
    composer.passes.forEach((pass) => {
      if (pass && typeof pass.dispose === "function") pass.dispose();
    });
    composer.dispose();
    composer = null;
  }
  if (scene) {
    scene.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
        for (const m of mats) {
          for (const key of Object.keys(m)) {
            const v = m[key];
            if (v && v.isTexture) v.dispose();
          }
          m.dispose();
        }
      }
    });
    scene.clear();
    scene = null;
  }
  if (renderer) {
    try {
      renderer.dispose();
      renderer.forceContextLoss();
    } catch (e) {
      /* ignore */
    }
    renderer = null;
  }
  if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
  points = null;
  pointsGeom = null;
  pointsMat = null;
  linkLines = null;
  linkGeom = null;
  linkMat = null;
  coreSprite = null;
  outerSprite = null;
  flashRing = null;
  coreMat = null;
  outerMat = null;
  flashMat = null;
  bloomPass = null;
  camera = null;
  cloud = null;
  basePositions = null;
  linkPairs = null;
  linkPositions = null;
  coreTex = null;
  canvas = null;
}

function disposeFallback() {
  if (canvas && canvas.parentNode) canvas.parentNode.removeChild(canvas);
  canvas = null;
  ctx2d = null;
  fallbackParticles = [];
  fallbackPairs = [];
  spriteTex2d = null;
}

function tryStart() {
  try {
    initWebGL();
  } catch (err) {
    mode = "canvas2d";
    disposeWebGL();
    initFallbackCanvas();
  }
  if (reduce) {
    stop();
    renderStatic();
  } else {
    start();
  }
  window.dispatchEvent(new Event("hero-nebula-ready"));
}

function onVisibility() {
  if (document.hidden) {
    if (running) {
      hiddenAt = performance.now();
      stop();
    }
  } else if (visible && !running && !reduce) {
    start();
    if (hiddenAt) hiddenAt = 0;
  }
}

function onResize() {
  setSize();
  if (reduce) renderStatic();
}

onMounted(() => {
  wrap = wrapRef.value;
  if (!wrap) return;
  currentStage = props.stage;
  reduce = props.reducedMotion;
  stageStart = performance.now();
  if (reduce) absorbStart = -1;

  // 延后一帧初始化 WebGL，避免阻塞 Landing 的 7s 时间轴启动（SwiftShader 下 shader 编译较慢）
  setTimeout(() => {
    if (!disposed) tryStart();
  }, 0);

  if (typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(() => onResize());
    resizeObserver.observe(wrap);
  }
  if (typeof IntersectionObserver !== "undefined") {
    intersectionObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          visible = entry.isIntersecting;
          if (visible && !reduce) start();
          else if (!visible) stop();
        });
      },
      { threshold: 0.05 }
    );
    intersectionObserver.observe(wrap);
  }
  visHandler = onVisibility;
  document.addEventListener("visibilitychange", visHandler);

  // 交互：悬停 / 点击 pin（只读；卸载时移除）
  stageEl = wrap.parentElement || wrap;
  pointerMoveHandler = onPointerMove;
  pointerLeaveHandler = onPointerLeave;
  pointerDownHandler = onPointerDown;
  stageEl.addEventListener("pointermove", pointerMoveHandler, { passive: true });
  stageEl.addEventListener("pointerleave", pointerLeaveHandler, { passive: true });
  stageEl.addEventListener("pointerdown", pointerDownHandler);
  stageEl.addEventListener("pointercancel", pointerLeaveHandler, { passive: true });

  // QA 冻结钩子：截图验收时暂停 rAF，保留最后一帧
  window.__nebulaPause = () => {
    stop();
  };
  window.__nebulaResume = () => {
    if (visible && !reduce) start();
  };
});

watch(
  () => props.stage,
  (next) => {
    currentStage = next;
    stageStart = performance.now();
    if (next === "absorb") absorbStart = performance.now();
    if (next === "final") absorbStart = -1;
    if (reduce) renderStatic();
    updateDebug();
  }
);

watch(
  () => props.reducedMotion,
  (next) => {
    reduce = next;
    if (next) {
      stop();
      renderStatic();
    } else {
      start();
    }
  }
);

onBeforeUnmount(() => {
  disposed = true;
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
  if (mode === "webgl") disposeWebGL();
  else disposeFallback();
  if (stageEl) {
    if (pointerMoveHandler) stageEl.removeEventListener("pointermove", pointerMoveHandler);
    if (pointerLeaveHandler) {
      stageEl.removeEventListener("pointerleave", pointerLeaveHandler);
      stageEl.removeEventListener("pointercancel", pointerLeaveHandler);
    }
    if (pointerDownHandler) stageEl.removeEventListener("pointerdown", pointerDownHandler);
  }
  stageEl = null;
  pointerMoveHandler = null;
  pointerLeaveHandler = null;
  pointerDownHandler = null;
  tooltip.value = null;
  hoveredIndex = -1;
  pinnedIndex = -1;
  window.__nebulaDebug = null;
  delete window.__nebulaPause;
  delete window.__nebulaResume;
});
</script>

<template>
  <div ref="wrapRef" class="nebula" :data-stage="stage">
    <!--
      tooltip 必须挂到舞台（.l-hero-stage）这一层：
      它原本在 .nebula 内，而 .nebula 的 stacking context 是 z-index:0，
      z-index:8 也压不过 z-index:4 的结果卡，悬停时画像会被卡片盖住。
      Landing.vue 把舞台元素作为 tooltipTarget 传进来。
    -->
    <Teleport v-if="tooltip && tooltipTarget" :to="tooltipTarget">
      <div
        class="nebula-tooltip"
        :class="{ 'is-pinned': tooltip.pinned }"
        :style="tooltipStyle"
        role="status"
        aria-live="polite"
      >
        <div class="nebula-tooltip-head">
          <i class="nebula-tooltip-dot" />
          <b>Demo 用户 {{ tooltip.user.uid }}</b>
          <span class="nebula-tooltip-meta">{{ tooltip.meta }}</span>
        </div>
        <p v-for="(line, i) in tooltip.lines" :key="i" class="nebula-tooltip-line">{{ line }}</p>
        <span v-if="tooltip.pinned" class="nebula-tooltip-pin">已固定 · 点击空白取消</span>
      </div>
    </Teleport>
  </div>
</template>
