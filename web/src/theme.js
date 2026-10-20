/** 深浅色主题：支持浅色 / 深色 / 跟随系统，默认跟随系统。 */
import { store } from "./store";

const KEY = "rag-v2-theme";
let media = null;

function systemPrefersDark() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

function resolveTheme(mode) {
  if (mode === "system") return systemPrefersDark() ? "dark" : "light";
  return mode === "dark" ? "dark" : "light";
}

export function initTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem(KEY);
  } catch {
    /* 隐私模式下 localStorage 可能不可用 */
  }
  store.themeMode = saved === "light" || saved === "dark" || saved === "system" ? saved : "system";
  applyTheme();

  if (typeof window !== "undefined" && typeof window.matchMedia === "function") {
    media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (store.themeMode === "system") applyTheme();
    };
    if (media.addEventListener) media.addEventListener("change", onChange);
    else if (media.addListener) media.addListener(onChange);
  }
}

export function setThemeMode(mode) {
  store.themeMode = mode === "light" || mode === "dark" || mode === "system" ? mode : "system";
  try {
    localStorage.setItem(KEY, store.themeMode);
  } catch {
    /* 忽略 */
  }
  applyTheme();
}

/** 兼容旧调用：浅色 ↔ 深色切换。 */
export function toggleTheme() {
  setThemeMode(store.theme === "dark" ? "light" : "dark");
}

function applyTheme() {
  store.theme = resolveTheme(store.themeMode);
  document.documentElement.dataset.theme = store.theme;
}
