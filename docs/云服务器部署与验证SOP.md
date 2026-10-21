# 千客引擎 · 云服务器部署与验证 SOP

> 目标机器：Ubuntu 22.04，2 核 4G  
> 架构：`db`（PostgreSQL + pgvector） + `backend`（FastAPI） + `frontend`（Nginx/Vue）  
> 适用版本：当前 `vip` 分支，2026-10-21

---

## 0. 先看：上线前必须确认的 4 个关键项

这部分比命令更重要。当前仓库直接部署会遇到的限制：

1. **Python 版本不是 3.11**
   - `pyproject.toml` 要求 `>=3.12,<3.13`
   - 因此 `Dockerfile` 使用 `python:3.12-slim`
   - 如果你强制用 3.11，需要改 `pyproject.toml` 并重新跑完整测试，不能只改基础镜像

2. **远程 BGE 已接入，但必须配置环境变量**
   - `config.py` / `hybrid_retriever.py` / `reranker.py` 已支持 `MODEL_API_BASE`
   - 设置后 embedding 走 `POST {BASE}/v1/embeddings`，rerank 走 `POST {BASE}/v1/rerank`
   - 云端轻量镜像不再安装 torch / sentence-transformers / transformers
   - 不设置 `MODEL_API_BASE` 时仍会回退本地 BGE；云端镜像没有 torch，回退会失败
   - **.env 必须配置：**

     ```dotenv
     MODEL_API_BASE=https://你的模型服务地址
     MODEL_API_KEY=你的模型服务密钥
     ```

3. **数据库不是单库结构**
   - `vec_db`：demo / 评测基线
   - `vec_db_user`：用户上传数据
   - `vec_db_test`：首跑测试库
   - `rag_auth`：账号、会话、Token 钱包等控制面
   - 已额外提供 `deploy/initdb/01-databases.sql`，首次启动自动创建这些库

4. **Docker 构建依赖与本地不同**
   - `pyproject.toml` 的 torch 是 Windows CUDA wheel（`wheels/*.whl`），Linux 无法安装
   - `Dockerfile` 已删除 torch / sentence-transformers / transformers 等本地模型依赖
   - API 容器只保留远程模型 HTTP 客户端，镜像会显著变小

> 结论：**远程模型适配已完成；上线前只需确认 `MODEL_API_BASE` / `MODEL_API_KEY` 和证书/数据。**

---

## 1. 本地准备 `.env`

### 1.1 复制模板

```bash
cp .env.example .env
```

### 1.2 必改字段

打开 `.env`，至少修改：

```dotenv
# LLM
DEEPSEEK_API_KEY=sk-你的真实key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-flash

# 远程模型服务（云端必填）
MODEL_API_BASE=https://你的模型服务地址
MODEL_API_KEY=你的模型服务密钥
MODEL_API_TIMEOUT=60
MODEL_API_BATCH_SIZE=32
MODEL_API_EMBEDDING_MODEL=bge-m3
MODEL_API_RERANK_MODEL=bge-reranker-v2-m3

# 数据库（和 docker-compose.yml 的 POSTGRES_PASSWORD 必须一致）
POSTGRES_USER=postgres
POSTGRES_PASSWORD=换成强密码
POSTGRES_DB=vec_db

# 账号库
RAG_AUTH_PG_DB=rag_auth
RAG_AUTH_PG_USER=postgres
RAG_AUTH_PG_PASSWORD=和POSTGRES_PASSWORD一致

# 管理员初始密码（首次启动写入数据库，之后改这里无效）
RAG_ADMIN_USER=admin
RAG_ADMIN_PASSWORD=换成强密码

# Text2SQL 只读账号（由应用自动创建）
RAG_SQL_READONLY_USER=sql_reader
RAG_SQL_READONLY_PASSWORD=换成强密码

# 生产禁用
RAG_ALLOW_HEADER_AUTH=0
```

### 1.3 确认 `.env` 没有被 Git 跟踪

```bash
git check-ignore -v .env
# 应输出 .gitignore 命中
git status --short | grep '\.env' || true
```

> `.env`、`.pem`、`.key` 已在 `.gitignore` 中。不要把真实密码、API Key 发给任何人，也不要提交到 Git。

---

## 2. 把代码传到服务器

### 方案 A：私有 Git 仓库（推荐）

在本地：

```bash
git add .
git commit -m "deploy: add docker production files"
git push origin vip
```

在服务器：

```bash
sudo mkdir -p /opt && cd /opt
sudo git clone <你的私有仓库地址> qianke-engine
cd qianke-engine
```

> 不要把 `.env`、`certs/`、模型权重提交到仓库；它们只在服务器上准备。

### 方案 B：rsync / scp

```bash
# 本地执行，排除密钥、模型和构建产物
rsync -avz --exclude='.git' --exclude='.env' --exclude='.venv' \
  --exclude='wheels' --exclude='models' --exclude='web/node_modules' \
  --exclude='web/dist' ./ user@SERVER:/opt/qianke-engine/
```

---

## 3. 服务器安装 Docker

Ubuntu 22.04：

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu jammy stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker
```

验证：

```bash
docker --version
docker compose version
```

> 旧版命令是 `docker-compose`，新版是 `docker compose`；下文使用新版。  
> 如果你机器只有旧版，把命令替换为 `docker-compose`。

---

## 4. 准备证书（443 必需）

`nginx.conf` 的 443 server 使用：

```text
/etc/nginx/certs/fullchain.pem
/etc/nginx/certs/privkey.pem
```

compose 会把宿主机的 `./certs` 挂载到该目录。

### 4.1 正式环境

用你已有的域名证书，或使用 certbot：

```bash
sudo apt install -y certbot
# 先暂停任何占用 80 端口的服务，再申请
sudo certbot certonly --standalone -d your-domain.com

sudo mkdir -p certs
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem certs/
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem certs/
sudo chown -R $USER:$USER certs
```

### 4.2 仅用于联调：自签证书

```bash
mkdir -p certs
openssl req -x509 -nodes -days 30 -newkey rsa:2048 \
  -keyout certs/privkey.pem \
  -out certs/fullchain.pem \
  -subj "/CN=your-server-ip"
```

> 自签证书浏览器会提示不安全，只用于内网联调。正式对外前换成正式证书。

---

## 5. 初始化数据库与数据

### 5.1 首次启动数据库

```bash
cd /opt/qianke-engine
docker compose up -d db
docker compose ps
# 等待 STATUS 显示 healthy
```

首次启动时 `deploy/initdb/01-databases.sql` 会自动创建：

- `vec_db`
- `vec_db_user`
- `vec_db_test`
- `rag_auth`
- 各库的 `vector` 扩展

### 5.2 迁移已有 demo 数据（如果服务器需要演示数据）

在本地/旧服务器导出：

```bash
pg_dump -Fc -h localhost -U postgres -d vec_db -f vec_db.dump
```

上传到服务器：

```bash
scp vec_db.dump user@SERVER:/opt/qianke-engine/
```

恢复：

```bash
docker compose exec -T db pg_restore \
  -U postgres -d vec_db --clean --if-exists < vec_db.dump
```

> 如果只需要空库，跳过这一步；但页面会没有画像/文档数据。  
> 账号库 `rag_auth` 如需保留历史用户，也按同样方式导出/恢复。

---

## 6. 一键启动

```bash
cd /opt/qianke-engine
docker compose up -d --build
```

首次构建时间较长（Node 构建 + Python 依赖 + torch CPU wheel），不要中途 Ctrl+C。

查看状态：

```bash
docker compose ps
```

期望：

```text
qianke-db         healthy
qianke-backend    healthy
qianke-frontend   healthy
```

如果 `backend` 一直是 `starting`，看日志：

```bash
docker compose logs -f backend
```

---

## 7. 验证

### 7.1 容器状态

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 frontend
```

### 7.2 健康检查

```bash
# Nginx
curl -k https://127.0.0.1/healthz

# 后端健康（走 Nginx 代理）
curl -k https://127.0.0.1/health

# 前端首页
curl -k -I https://127.0.0.1/v2/
```

浏览器访问：

```text
https://你的域名/v2/
```

自签证书环境请先接受浏览器安全提示。

### 7.3 接口冒烟

```bash
# 登录页/身份接口应能返回 401 或 JSON，而不是 502
curl -k https://127.0.0.1/whoami

# SSE 不要被代理缓冲
curl -k -N -X POST https://127.0.0.1/qa/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"你好"}'
```

### 7.4 远程模型连通性

在服务器上直接测模型服务，不要在只看容器健康状态：

```bash
set -a
source .env
set +a

curl -fsS -X POST "${MODEL_API_BASE}/v1/embeddings" \
  -H "Authorization: Bearer ${MODEL_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"input":["你好"],"model":"bge-m3"}' | head -c 300

curl -fsS -X POST "${MODEL_API_BASE}/v1/rerank" \
  -H "Authorization: Bearer ${MODEL_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"query":"高价值用户定义","documents":["近90天消费排名前20%","今天天气很好"],"model":"bge-reranker-v2-m3"}' | head -c 300
```

然后在容器里确认：

```bash
docker compose exec backend python -c \
  "from rag_demo.config import USE_REMOTE_MODEL, MODEL_API_BASE; print(USE_REMOTE_MODEL, MODEL_API_BASE)"
```

应输出 `True https://...`。如果输出 `False`，检查 `.env` 是否被 compose 注入。

### 7.5 内存安全

```bash
docker stats --no-stream
```

重点看：

- `qianke-backend` 是否接近 `2GiB`
- `qianke-db` 是否接近 `1GiB`
- 整机是否开始使用 swap

持续观察：

```bash
docker stats
```

如果 backend 接近 2G：

1. 立刻停止压测
2. `docker compose logs -f backend` 看是否在加载本地模型
3. 按第 0 节把模型移到独立服务
4. 临时把 `Dockerfile` 的 `--workers 2` 改为 `--workers 1`，但这不是长期方案

### 7.5 日志

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f db
```

应用日志同时写入宿主机：

```text
./logs/rag_demo.log
```

---

## 8. 常用运维

### 更新代码

```bash
cd /opt/qianke-engine
git pull
docker compose up -d --build
docker compose ps
```

### 重启

```bash
docker compose restart backend frontend
```

### 停止（保留数据）

```bash
docker compose down
```

> 绝对不要在生产执行 `docker compose down -v`，它会删除 `pgdata` 数据卷。

### 备份数据库

```bash
docker compose exec -T db pg_dump -U postgres -d vec_db -Fc > backup-$(date +%F).dump
docker compose exec -T db pg_dump -U postgres -d rag_auth -Fc > auth-$(date +%F).dump
```

### 查看端口/防火墙

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

不要开放 5432、8000。

---

## 9. Nginx 的关键行为（排错用）

- `/v2/`：Vue 静态资源，`try_files` 回退到 `/v2/index.html`
- `/api/`：KB、wizard、marketing、monitor、billing 等
- `/qa`、`/qa/stream`：普通问答与 SSE；流式关闭了 proxy buffering
- `/auth/`、`/whoami`、`/login`：登录与会话
- `/admin/`：管理端页面/接口
- `/health`、`/healthz`：健康检查

如果页面能打开、接口 502：

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 frontend
```

如果刷新页面 404：

```bash
# 确认静态目录存在
docker compose exec frontend ls /usr/share/nginx/html/v2
# 检查 nginx 配置
docker compose exec frontend nginx -t
```

---

## 10. 上线前检查清单

- [ ] `.env` 没有提交 Git
- [ ] `POSTGRES_PASSWORD`、`RAG_ADMIN_PASSWORD`、`RAG_SQL_READONLY_PASSWORD` 已改强密码
- [ ] `DEEPSEEK_API_KEY` 只存在于服务器 `.env`
- [ ] 证书是正式证书，不是自签
- [ ] `docker compose ps` 三个服务均 healthy
- [ ] `https://域名/v2/` 可打开
- [ ] 登录、提问、流式回答、上传、知识库页面可用
- [ ] `docker stats` 下 backend/db 不超限、没有 OOM
- [ ] `docker compose down -v` 已明确禁止在生产执行
- [ ] `MODEL_API_BASE` / `MODEL_API_KEY` 已配置
- [ ] 远程 embedding / rerank 接口可访问
- [ ] 已备份 `pgdata` 与 `.env`

---

## 11. 文件清单

- `Dockerfile`：FastAPI 后端镜像
- `web/Dockerfile`：Vue 多阶段构建 + Nginx
- `nginx.conf`：静态托管、API/SSE 代理、gzip、TLS
- `docker-compose.yml`：db / backend / frontend、资源限制、网络、卷
- `deploy/initdb/01-databases.sql`：首次初始化多数据库与 pgvector
- `.dockerignore`：避免把密钥、模型、数据库卷、node_modules 打进构建上下文
- `docker-compose.dev.yml`：原来的“只起 PostgreSQL”本地开发编排备份
