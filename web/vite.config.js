import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

/**
 * 部署形态：后端起在 8000，构建产物挂到 http://127.0.0.1:8000/v2/。
 *
 * - base: './'        —— 产物里的资源用相对路径引用，/v2/ 子路径下才找得到；
 * - outDir: 'dist'    —— 后端 main.py 约定的目录（契约 F：web/dist）；
 * - 手写 CSS，不引 UI 库 —— 依赖只有 vue + vue-router。
 *
 * 路由用 hash（createWebHashHistory）：/v2/ 是静态挂载，没有服务端 fallback，
 * 刷新 /v2/chat 会 404，所以路径必须留在 # 后面。
 */
export default defineConfig({
  base: "./",
  plugins: [vue()],
  build: {
    outDir: "dist",
    assetsDir: "assets",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      // 多入口：保留现有 SPA 主入口，新增独立 B 端商家工作台（/v2/b.html）
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        b: fileURLToPath(new URL("./b.html", import.meta.url)),
      },
    },
  },
  server: {
    port: 5173,
    // 本地开发时把接口代理到后端（构建产物由后端自托管，不依赖这里）
    proxy: {
      "/whoami": "http://127.0.0.1:8000",
      "/stats": "http://127.0.0.1:8000",
      "/qa": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
      "/admin": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
      "/login": "http://127.0.0.1:8000",
    },
  },
});
