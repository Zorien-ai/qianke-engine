import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";
import { initTheme } from "./theme";
import { installI18n } from "./i18n";
import "./styles/main.css";

initTheme();
installI18n();

createApp(App).use(router).mount("#app");
