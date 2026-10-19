/**
 * 轻量中英文切换。
 *
 * 为什么采用字典 + DOM 文案翻译层：
 * - 现有页面数量多、中文文案分散，逐条改模板成本高且容易漏；
 * - 这里只翻译「静态 UI 文案」，不翻译 AI 回答、原文、RAG 切片等业务内容；
 * - 默认中文；用户切换后持久化到 localStorage。
 *
 * 约束：新增 UI 文案时把中文放进 i18n-en.json 字典即可；技术内容/动态数据保持原文。
 */
import { ref } from "vue";
import en from "./i18n-en.json";

export const LOCALE_KEY = "qianke-locale";
export const locale = ref("zh");

const TEXT_ORIGINALS = new WeakMap();
const ATTR_ORIGINALS = new WeakMap();
const TEXT_NODES = new Set();
const ATTR_ELEMENTS = new Set();
const CJK = /[\u4e00-\u9fff]/;
const SPACE = /\s+/g;
const EXCLUDE_SELECTOR = [
  ".answer-body",
  ".raw-reader",
  ".chunk-text",
  ".source-text",
  ".sql-table",
  ".markdown",
  ".eval-template",
  ".eval-detail pre",
  ".history-error",
  "pre",
  "code",
  "textarea",
  "script",
  "style",
  "svg",
  "[data-no-i18n]",
].join(",");
const ATTRS = ["placeholder", "title", "aria-label", "aria-description", "alt"];
let observer = null;
let headObserver = null;
let titleOriginal = "";

// 少数由后端/状态插值拼出来的 UI 句子单独覆盖；不要用“全量短语替换”，
// 否则会把企业名、人名、业务数据一起换成中英混杂。
const OVERRIDES = {
  "上传 QA 题库": "Upload QA Question Bank",
  "用户画像": "User Profiles",
  "已就绪，可随时提问": "Ready to ask questions anytime",
  "数据与检索索引一致，可以直接提问": "Data and search index are consistent; you can ask questions directly.",
  "当前以": "Currently signed in as",
  "历史表为空，显示最近一次构建": "History table is empty; showing the latest build.",
  "历史表为空，按当前索引构建时间回填": "History table is empty; backfilled from the current index build time.",
  "已启用登录：身份来自账号，请求头不再生效。企业账号审核通过后会生成企业库与邀请码；员工用邀请码加入企业。":
    "Login is enabled: identity comes from the account, and request headers no longer take effect. After an enterprise account is approved, its database and invite code are generated; employees join with the invite code.",
};
const DICT = { ...en, ...OVERRIDES };
const GREETINGS = {
  夜深了: "Good evening",
  早上好: "Good morning",
  下午好: "Good afternoon",
  晚上好: "Good evening",
};
const PATTERNS = [
  [
    /^(夜深了|早上好|下午好|晚上好)，$/,
    (m) => `${GREETINGS[m[1]] || "Hello"}, `,
  ],
  [
    /^(夜深了|早上好|下午好|晚上好)，(.+?)，$/,
    (m) => `${GREETINGS[m[1]] || "Hello"}, ${m[2]}, `,
  ],
  [/^，今天想了解什么？$/, () => ". What would you like to know today?"],
  [/^当前以\s*$/, () => "Currently signed in as "],
  [/^\s*身份登录（$/, () => " ("],
  [/^身份登录（(.+?)），\s*可用等级$/, (m) => ` (${m[1]}), available level `],
  [/^），\s*可用等级\s*$/, () => "), available level "],
  [/^。能看到的范围由账号等级决定，\s*$/, () => ". What you can see is determined by your account level; "],
  [/^页面只渲染你被允许使用的能力。$/, () => "the page only renders the capabilities you are allowed to use."],
  [/^可用 · (.+)$/, (m) => `Available · ${DICT[m[1]] || m[1]}`],
  [/^未开通 · (.+)$/, (m) => `Not enabled · ${DICT[m[1]] || m[1]}`],
  [/^可用 ·\s*$/, () => "Available · "],
  [/^未开通 ·\s*$/, () => "Not enabled · "],
  [
    /^(夜深了|早上好|下午好|晚上好)，(.+?)，今天想了解什么？$/,
    (m) => `${GREETINGS[m[1]] || "Hello"}, ${m[2]}. What would you like to know today?`,
  ],
  [
    /^当前以 (.+?) 身份登录（(.+?)），\s*可用等级 (.+?)。能看到的范围由账号等级决定，\s*页面只渲染你被允许使用的能力。$/,
    (m) =>
      `Currently signed in as ${m[1]} (${m[2]}), available level ${m[3]}. What you can see is determined by your account level; the page only renders the capabilities you are allowed to use.`,
  ],
  [/^(\d+)\s*篇\s*·\s*(\d+)\s*切片\s*·\s*(\d+)\s*画像$/, (m) =>
    `${m[1]} ${m[1] === "1" ? "document" : "documents"} · ${m[2]} ${m[2] === "1" ? "chunk" : "chunks"} · ${m[3]} ${m[3] === "1" ? "profile" : "profiles"}`],
  [/^1 篇文档$/, () => "1 document"],
  [/^1 个切片$/, () => "1 chunk"],
  [/^1 条记录$/, () => "1 record"],
  [/^1 位用户$/, () => "1 user"],
  [
    /^第 (\d+) \/ (\d+) 页 · 共 ([\d,]+) 位$/,
    (m) => `Page ${m[1]} / ${m[2]} · ${m[3]} total`,
  ],
  [/^共 (\d+) 篇$/, (m) => `${m[1]} documents`],
  [/^([\d,]+) 个切片$/, (m) => `${m[1]} chunks`],
  [/^(\d+) 篇文档$/, (m) => `${m[1]} documents`],
  [/^(\d+) 切片$/, (m) => `${m[1]} chunks`],
  [/^([\d,]+) 字符$/, (m) => `${m[1]} chars`],
  [/^(\d+) 条记录$/, (m) => `${m[1]} records`],
  [/^([\d.]+) 秒$/, (m) => `${m[1]}s`],
  [/^共 ([\d,]+) 个切片$/, (m) => `${m[1]} chunks`],
  [/^已上传：(\d+) 题$/, (m) => `Uploaded: ${m[1]} questions`],
  [
    /^每个光点，都是一位 demo 用户 · 共 ([\d,]+) 位$/,
    (m) => `Each light dot is a demo user · ${m[1]} total`,
  ],
  [/^(\d+) 个题库$/, (m) => `${m[1]} question sets`],
  [/^裁判：(.+)$/, (m) => `Judge: ${m[1]}`],
  [/^题库：(.+?) · 耗时 ([\d.]+)s?$/, (m) => `Question set: ${m[1]} · ${m[2]}s`],
  [/^(\d+) \/ (\d+) 题成功判定$/, (m) => `${m[1]} / ${m[2]} judged successfully`],
  [/^(\d+) 题 · 裁判异常 (\d+)$/, (m) => `${m[1]} questions · judge errors ${m[2]}`],
  [/^(\d+) 题有期望来源$/, (m) => `${m[1]} questions with expected sources`],
  [/^期望来源：(.+)$/, (m) => `Expected sources: ${m[1]}`],
  [/^正常 (\d+) · 待审核 (\d+)$/, (m) => `Active ${m[1]} · Pending ${m[2]}`],
  [/^· 停用 (\d+)$/, (m) => `· Disabled ${m[1]}`],
  [/^(\d+) 位用户$/, (m) => `${m[1]} users`],
  [/^当前账号的有效等级：(.+)$/, (m) => `Current effective level: ${m[1]}`],
  [/^切换到(浅色|深色)$/, (m) => `Switch to ${m[1] === "深色" ? "dark" : "light"} mode`],
];

function normalize(value) {
  return String(value || "").replace(/\u00a0/g, " ").replace(SPACE, " ").trim();
}

function englishFor(text) {
  const key = normalize(text);
  return DICT[key] || "";
}

function patternFor(text) {
  for (const [regex, replace] of PATTERNS) {
    const match = text.match(regex);
    if (match) return replace(match);
  }
  return "";
}

function isBlocked(element) {
  if (!element) return true;
  if (element.nodeType === 3) element = element.parentElement;
  if (!element || !element.closest) return true;
  return !!element.closest(EXCLUDE_SELECTOR);
}

function translateTextNode(node) {
  if (locale.value !== "en" || !node || node.nodeType !== 3) return;
  const raw = node.nodeValue || "";
  if (!CJK.test(raw) || isBlocked(node.parentElement)) return;
  const trimmed = raw.trim();
  const translated = patternFor(trimmed) || englishFor(trimmed);
  if (!translated) return;
  const leading = raw.match(/^\s*/)?.[0] || "";
  const trailing = raw.match(/\s*$/)?.[0] || "";
  const next = leading + translated + trailing;
  if (next === raw) return;
  if (!TEXT_ORIGINALS.has(node)) TEXT_ORIGINALS.set(node, raw);
  TEXT_NODES.add(node);
  node.nodeValue = next;
}

function translateAttrs(element) {
  if (locale.value !== "en" || !element || element.nodeType !== 1 || isBlocked(element)) return;
  for (const name of ATTRS) {
    const raw = element.getAttribute(name);
    if (!raw || !CJK.test(raw)) continue;
    const translated = patternFor(raw) || englishFor(raw);
    if (!translated) continue;
    let saved = ATTR_ORIGINALS.get(element);
    if (!saved) {
      saved = {};
      ATTR_ORIGINALS.set(element, saved);
    }
    if (!(name in saved)) saved[name] = raw;
    ATTR_ELEMENTS.add(element);
    element.setAttribute(name, translated);
  }
}

function scan(root) {
  if (!root || locale.value !== "en") return;
  if (root.nodeType === 3) {
    translateTextNode(root);
    return;
  }
  if (!(root instanceof Element)) return;
  if (root.matches(EXCLUDE_SELECTOR)) return;
  translateAttrs(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode(node) {
      if (node.nodeType === 1 && node.matches(EXCLUDE_SELECTOR)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let node;
  while ((node = walker.nextNode())) {
    if (node.nodeType === 3) translateTextNode(node);
    else translateAttrs(node);
  }
}

function restore() {
  for (const node of TEXT_NODES) {
    const original = TEXT_ORIGINALS.get(node);
    if (original !== undefined) node.nodeValue = original;
  }
  for (const element of ATTR_ELEMENTS) {
    const saved = ATTR_ORIGINALS.get(element) || {};
    for (const [name, value] of Object.entries(saved)) element.setAttribute(name, value);
  }
  TEXT_NODES.clear();
  ATTR_ELEMENTS.clear();
}

function applyLocale() {
  document.documentElement.lang = locale.value === "en" ? "en" : "zh-CN";
  if (observer) {
    observer.disconnect();
    observer = null;
  }
  if (headObserver) {
    headObserver.disconnect();
    headObserver = null;
  }
  if (locale.value === "zh") {
    restore();
    if (titleOriginal) document.title = titleOriginal;
    return;
  }
  translateTitle();
  headObserver = new MutationObserver(translateTitle);
  headObserver.observe(document.head, { subtree: true, childList: true, characterData: true });
  scan(document.body);
  observer = new MutationObserver((mutations) => {
    if (locale.value !== "en") return;
    for (const mutation of mutations) {
      if (mutation.type === "characterData") translateTextNode(mutation.target);
      else if (mutation.type === "attributes") translateAttrs(mutation.target);
      else for (const node of mutation.addedNodes) scan(node);
    }
  });
  observer.observe(document.body, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRS,
  });
}

function translateTitle() {
  if (locale.value !== "en") return;
  const raw = document.title || "";
  if (!CJK.test(raw)) return;
  const translated = englishFor(raw) || patternFor(raw);
  if (!translated) return;
  titleOriginal = raw;
  document.title = translated;
}

export function setLocale(value, persist = true) {
  const next = value === "en" ? "en" : "zh";
  locale.value = next;
  if (persist) {
    try {
      localStorage.setItem(LOCALE_KEY, next);
    } catch {
      /* 忽略隐私模式 */
    }
  }
  applyLocale();
}

export function toggleLocale() {
  setLocale(locale.value === "zh" ? "en" : "zh");
}

export function installI18n() {
  let saved = "zh";
  try {
    const raw = localStorage.getItem(LOCALE_KEY);
    if (raw === "en" || raw === "zh") saved = raw;
  } catch {
    /* 默认中文 */
  }
  locale.value = saved;
  document.documentElement.lang = saved === "en" ? "en" : "zh-CN";
  if (saved === "en") scan(document.body);
  if (saved === "en") applyLocale();
  else observer = null;
}

export function t(key) {
  if (locale.value !== "en") return key;
  return englishFor(key) || key;
}
