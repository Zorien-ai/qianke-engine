import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";
import { initTheme } from "./theme";
import { installI18n } from "./i18n";
import "./styles/main.css";

initTheme();
installI18n();

createApp(App).use(router).mount("#app");

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    const swUrl = new URL("sw.js", window.location.href);
    navigator.serviceWorker
      .register(swUrl, { scope: new URL("./", window.location.href).pathname })
      .catch(() => {
        // PWA 注册失败不影响主应用。
      });
  });
}
