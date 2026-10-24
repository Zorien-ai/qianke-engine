# syntax=docker/dockerfile:1.7
# ============================================================================
# 千客引擎 · Vue 3 前端生产镜像（多阶段构建）
#
# 构建上下文是项目根目录（docker-compose 里 context: .），
# 所以 COPY 路径都带 web/ 前缀；最终只保留 Nginx 和 dist 静态文件。
# ============================================================================

# ---------- 阶段 1：构建 Vue ----------
FROM node:18-alpine AS build

WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存：代码改动不会重复 npm install
COPY web/package*.json ./
# 阿里云服务器使用国内 npm 镜像，避免 npm install 卡住
RUN npm config set registry https://registry.npmmirror.com \
    && npm install --no-audit --no-fund

# 再复制前端源码（node_modules / dist 由 .dockerignore 排除）
COPY web/ ./

# Vite 产物在 /app/dist；base 为 ./，适合挂载到 /v2/ 子路径
RUN npm run build


# ---------- 阶段 2：Nginx 托管 ----------
FROM nginx:alpine AS runtime

# nginx:alpine 自带 busybox wget，健康检查不再额外安装 curl
# （Alpine 源在国内也可能很慢，能省一步是一步）

# 项目根目录的 nginx.conf：静态站点 + 反向代理 + gzip + TLS
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 把构建产物放到 /usr/share/nginx/html/v2，与后端/前端的 /v2/ 路径一致
COPY --from=build /app/dist /usr/share/nginx/html/v2

EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
