/* Login page language switch: same localStorage key as the Vue app, default Chinese. */
(function () {
  "use strict";
  var KEY = "qianke-locale";
  var locale = "zh";
  try {
    locale = localStorage.getItem(KEY) === "en" ? "en" : "zh";
  } catch (e) {
    locale = "zh";
  }
  var dict = {};
  var dictReady = false;
  var dictPromise = null;
  var textOriginal = new WeakMap();
  var attrOriginal = new WeakMap();
  var textNodes = new Set();
  var attrEls = new Set();
  var observer = null;
  var titleOriginal = "";
  var CJK = /[\u4e00-\u9fff]/;
  var SPACE = /\s+/g;
  var ATTRS = ["placeholder", "title", "aria-label", "alt"];
  var EXCLUDE = "script,style,textarea,pre,code,[data-no-i18n]";

  function norm(v) {
    return String(v || "").replace(/\u00a0/g, " ").replace(SPACE, " ").trim();
  }
  function resolve(v) {
    var key = norm(v);
    return dict[key] || "";
  }
  function blocked(el) {
    if (!el) return true;
    if (el.nodeType === 3) el = el.parentElement;
    return !el || !el.closest || !!el.closest(EXCLUDE);
  }
  function translateText(node) {
    if (locale !== "en" || !node || node.nodeType !== 3) return;
    var raw = node.nodeValue || "";
    if (!CJK.test(raw) || blocked(node.parentElement)) return;
    var translated = resolve(raw);
    if (!translated) return;
    var lead = (raw.match(/^\s*/) || [""])[0];
    var tail = (raw.match(/\s*$/) || [""])[0];
    var next = lead + translated + tail;
    if (next === raw) return;
    if (!textOriginal.has(node)) textOriginal.set(node, raw);
    textNodes.add(node);
    node.nodeValue = next;
  }
  function translateAttrs(el) {
    if (locale !== "en" || !el || el.nodeType !== 1 || blocked(el)) return;
    ATTRS.forEach(function (name) {
      var raw = el.getAttribute(name);
      if (!raw || !CJK.test(raw)) return;
      var translated = resolve(raw);
      if (!translated) return;
      var saved = attrOriginal.get(el);
      if (!saved) { saved = {}; attrOriginal.set(el, saved); }
      if (!(name in saved)) saved[name] = raw;
      attrEls.add(el);
      el.setAttribute(name, translated);
    });
  }
  function scan(root) {
    if (locale !== "en" || !root) return;
    if (root.nodeType === 3) { translateText(root); return; }
    if (root.nodeType !== 1 || root.matches(EXCLUDE)) return;
    translateAttrs(root);
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: function (node) {
        if (node.nodeType === 1 && node.matches(EXCLUDE)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    var node;
    while ((node = walker.nextNode())) {
      if (node.nodeType === 3) translateText(node); else translateAttrs(node);
    }
  }
  function restore() {
    textNodes.forEach(function (node) {
      var original = textOriginal.get(node);
      if (original !== undefined) node.nodeValue = original;
    });
    attrEls.forEach(function (el) {
      var saved = attrOriginal.get(el) || {};
      Object.keys(saved).forEach(function (name) { el.setAttribute(name, saved[name]); });
    });
    textNodes.clear();
    attrEls.clear();
  }
  function translateTitle() {
    if (locale !== "en") {
      if (titleOriginal) document.title = titleOriginal;
      return;
    }
    var raw = document.title || "";
    var translated = resolve(raw);
    if (!translated) return;
    titleOriginal = raw;
    document.title = translated;
  }
  function apply() {
    document.documentElement.lang = locale === "en" ? "en" : "zh-CN";
    if (observer) { observer.disconnect(); observer = null; }
    if (locale === "zh") { restore(); translateTitle(); return; }
    translateTitle();
    scan(document.body);
    observer = new MutationObserver(function (mutations) {
      if (locale !== "en") return;
      mutations.forEach(function (m) {
        if (m.type === "characterData") translateText(m.target);
        else if (m.type === "attributes") translateAttrs(m.target);
        else m.addedNodes.forEach(function (n) { scan(n); });
      });
    });
    observer.observe(document.body, {
      subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS,
    });
  }
  function ensureDict() {
    if (dictReady) return Promise.resolve(dict);
    if (!dictPromise) {
      dictPromise = fetch("/static/login-en.json", { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : {}; })
        .then(function (data) {
          dict = data || {};
          dictReady = true;
          return dict;
        })
        .catch(function () {
          dictPromise = null;
          return {};
        });
    }
    return dictPromise;
  }
  function updateSwitch(root) {
    if (!root) return;
    root.querySelectorAll("[data-lang]").forEach(function (button) {
      var active = button.getAttribute("data-lang") === locale;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }
  function setLocale(next) {
    locale = next === "en" ? "en" : "zh";
    try { localStorage.setItem(KEY, locale); } catch (e) { /* ignore */ }
    updateSwitch(document.getElementById("lang-switch"));
    if (locale === "en") {
      // 默认中文进入时字典还没请求；首次切英文必须按需加载，否则只会高亮按钮、正文仍是中文。
      ensureDict().then(function () {
        if (locale === "en") apply();
      });
    } else {
      apply();
    }
  }
  function init(root) {
    if (root) {
      updateSwitch(root);
      root.querySelectorAll("[data-lang]").forEach(function (button) {
        button.addEventListener("click", function () {
          setLocale(button.getAttribute("data-lang"));
        });
      });
    }
    if (locale === "en") {
      ensureDict().then(function () {
        if (locale === "en") apply();
      });
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { init(document.getElementById("lang-switch")); });
  } else {
    init(document.getElementById("lang-switch"));
  }
})();
