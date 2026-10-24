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
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    TZ=Asia/Shanghai

# psycopg2 / 模型依赖需要的系统库：
#   build-essential  某些包需要源码编译（无 wheel 时）
#   libpq-dev        PostgreSQL 头文件（psycopg2 编译兜底）
#   curl             容器健康检查
#   libgomp1         PyTorch/NumPy 的 OpenMP 运行库
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ca-certificates \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

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
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# ---------- 启动命令 ----------
# 2 核 4G 的硬性上限：最多 2 个 uvicorn worker。
# 云端必须设置 MODEL_API_BASE，embedding/rerank 走远程服务，
# 因此每个 worker 只保留轻量 HTTP 客户端，不再各加载一份本地模型。
CMD ["uvicorn", "rag_demo.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
