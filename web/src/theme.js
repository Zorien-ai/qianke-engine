/** 深浅色主题：默认跟随系统，手动切换后记在 localStorage。 */
import { store } from "./store";

const KEY = "rag-v2-theme";

export function initTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem(KEY);
  } catch {
    /* 隐私模式下 localStorage 可能不可用 */
  }
  const prefersDark =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  store.theme = saved === "light" || saved === "dark" ? saved : prefersDark ? "dark" : "light";
  applyTheme();
}

export function toggleTheme() {
  store.theme = store.theme === "dark" ? "light" : "dark";
  try {
    localStorage.setItem(KEY, store.theme);
  } catch {
    /* 忽略 */
  }
  applyTheme();
}

function applyTheme() {
  document.documentElement.dataset.theme = store.theme;
}
