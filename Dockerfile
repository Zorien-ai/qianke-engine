# syntax=docker/dockerfile:1.7
# ============================================================================
# 千客引擎 · FastAPI 后端生产镜像
#
# 部署假设：
#   1. 云端 2 核 4G Ubuntu 22.04；
#   2. Web / DB / API 在云端，BGE 模型通过内网或外网模型服务调用；
#   3. 数据库由 docker-compose.yml 的 db 容器提供。
#
# 重要说明：
#   - 项目 pyproject.toml 要求 Python >=3.12,<3.13，因此这里使用
#     python:3.12-slim，而不是 3.11-slim；3.11 会在依赖解析和运行期
#     直接失败（项目已声明 Python 版本下限）。
#   - 本地开发把 torch 锁成了 Windows CUDA wheel（wheels/*.whl），
#     Linux Docker 不能安装该 wheel。这里用 PyPI CPU wheel，保证镜像
#     可以在 Linux 构建；生产环境建议把 BGE 推理放到独立模型服务。
#   - 不要在这个镜像里 COPY models/、wheels/、.env、data/ 和日志：
#     它们要么很大，要么是运行期数据/密钥。模型和数据通过 volume 或
#     外部服务提供。
# ============================================================================

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS runtime

# ---------- 基础环境 ----------
# 阿里云服务器走国内 PyPI 镜像，避免 pip 长时间卡在 pypi.org
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    TZ=Asia/Shanghai \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

# 不安装 apt 系统依赖：
#   - psycopg2-binary 自带 libpq，不需要 libpq-dev；
#   - 云端不装 torch，因此不需要 build-essential / libgomp1；
#   - 健康检查改用 Python 标准库，不再依赖 curl。
# 这样可以避开 Debian apt 源在国内构建时长时间卡住的问题。
WORKDIR /app

# ---------- 安装 Python 依赖 ----------
# 云端 API 不安装 torch / sentence-transformers / transformers / accelerate /
# FlagEmbedding / HuggingFace 模型依赖：embedding 与 rerank 全部通过
# MODEL_API_BASE 调用远程模型服务（见 retrieval/remote_models.py）。
#
# 这里不用 uv.lock：lock 内固定的是 Windows CUDA torch wheel，Linux 无法安装，
# 而且云端 API 根本不需要本地模型。
RUN pip install --upgrade pip \
    && pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "psycopg2-binary>=2.9" \
        "pgvector>=0.3" \
        "openai>=1.40" \
        "argon2-cffi>=23.1" \
        "python-multipart>=0.0.9" \
        "pandas>=2.2" \
        "numpy>=1.26" \
        "jieba>=0.42" \
        "rank-bm25>=0.2" \
        "langchain-core>=0.3" \
        "langchain-text-splitters>=0.3" \
        "alibabacloud-oss-v2>=1.0"

# ---------- 复制源码 ----------
# 只复制运行必需内容；web/dist 由 Nginx 前端容器托管，不需要进后端镜像。
COPY src /app/src
COPY scripts /app/scripts
COPY pyproject.toml /app/pyproject.toml

# ---------- 运行期目录 ----------
# data / var / logs / models 在 compose 中通过 volume 提供，避免镜像携带业务数据。
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/data /app/var /app/logs /app/models \
    && chown -R app:app /app
USER app

EXPOSE 8000

# 健康检查：DB 已就绪、应用已启动才返回 {"status":"ok"}
# 使用 Python 标准库，避免依赖 curl / apt。
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

# ---------- 启动命令 ----------
# 2 核 4G：使用 1 个 uvicorn worker 更稳。
# 原因：uvicorn 每个 worker 都会执行一次 lifespan，而 auth.init() 会在启动时
# 并发创建/更新账号库；2 个 worker 同时初始化曾触发 PostgreSQL DeadlockDetected。
# 远程模型模式下单个 worker 足够支撑演示，也避免启动竞态。
CMD ["uvicorn", "rag_demo.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
