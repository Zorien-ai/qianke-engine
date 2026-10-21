# -*- coding: utf-8 -*-
"""远程 BGE 模型客户端（OpenAI-compatible embeddings + rerank）。

生产环境不把 BGE-M3 / reranker 放进 2C4G API 容器，而是通过 Cloudflare Tunnel
等通道调用独立模型服务。这里只依赖标准库 urllib，避免额外安装 requests。

环境变量：
    MODEL_API_BASE=https://xxx.trycloudflare.com
    MODEL_API_KEY=...
    MODEL_API_TIMEOUT=60
    MODEL_API_BATCH_SIZE=32
    MODEL_API_EMBEDDING_MODEL=bge-m3
    MODEL_API_RERANK_MODEL=bge-reranker-v2-m3

接口约定：
    POST {BASE}/v1/embeddings
        {"input": ["..."], "model": "bge-m3"}
    POST {BASE}/v1/rerank
        {"query": "...", "documents": ["..."], "model": "bge-reranker-v2-m3"}

兼容常见返回：
    embeddings: {"data":[{"index":0,"embedding":[...]}]} / {"embeddings":[[...]]}
    rerank:     {"results":[{"index":0,"relevance_score":0.9}]} /
                {"data":[{"index":0,"score":0.9}]} / {"scores":[...]} / [0.9, ...]
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

import numpy as np

from rag_demo.config import (
    MODEL_API_BASE,
    MODEL_API_BATCH_SIZE,
    MODEL_API_EMBEDDING_MODEL,
    MODEL_API_KEY,
    MODEL_API_RERANK_MODEL,
    MODEL_API_TIMEOUT,
)

logger = logging.getLogger(__name__)


class RemoteModelError(RuntimeError):
    """远程模型服务不可用/返回格式不符合约定。"""


def remote_enabled() -> bool:
    return bool(MODEL_API_BASE)


def _url(path: str) -> str:
    """base 允许写成 .../v1 或裸域名，两种都兼容。"""
    base = MODEL_API_BASE.rstrip("/")
    if base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]  # 去掉重复的 /v1
    return base + path


def _post(path: str, payload: dict) -> object:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "qianke-engine/remote-model-client",
    }
    if MODEL_API_KEY:
        headers["Authorization"] = f"Bearer {MODEL_API_KEY}"

    last_error: Exception | None = None
    for attempt in range(1, 3):
        req = urllib.request.Request(_url(path), data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=MODEL_API_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            # 不把 Authorization 或完整响应体写进日志，避免密钥泄漏
            detail = exc.read().decode("utf-8", errors="replace")[:300] if exc.fp else ""
            last_error = RemoteModelError(
                f"远程模型接口 HTTP {exc.code} path={path} detail={detail}"
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = RemoteModelError(
                f"远程模型接口调用失败 path={path}: {type(exc).__name__}: {exc}"
            )
        if attempt < 2:
            logger.warning("远程模型调用失败，重试第 %s 次: %s", attempt + 1, last_error)
            continue
    raise last_error or RemoteModelError(f"远程模型接口失败 path={path}")


def _as_embedding_list(payload: object) -> list[list[float]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            ordered = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                if "embedding" in item:
                    ordered.append((item.get("index", len(ordered)), item["embedding"]))
            if ordered:
                ordered.sort(key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0)
                return [[float(v) for v in item] for _, item in ordered]
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list):
            return [[float(v) for v in item] for item in embeddings]
        if isinstance(payload.get("embedding"), list):
            return [[float(v) for v in payload["embedding"]]]
    raise RemoteModelError("远程 embeddings 返回格式无法解析")


def _parse_rerank(payload: object, expected: int) -> list[float]:
    scores = [0.0] * expected

    def put(index, value):
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return
        if 0 <= idx < expected:
            scores[idx] = float(value)

    if isinstance(payload, list):
        for i, value in enumerate(payload[:expected]):
            scores[i] = float(value)
        return scores
    if isinstance(payload, dict):
        results = payload.get("results") or payload.get("data")
        if isinstance(results, list):
            for pos, item in enumerate(results[:expected]):
                if isinstance(item, dict):
                    idx = item.get("index", pos)
                    value = (
                        item.get("relevance_score")
                        if item.get("relevance_score") is not None
                        else item.get("score", item.get("rerank_score", 0.0))
                    )
                    put(idx, value)
                else:
                    put(pos, item)
            return scores
        raw_scores = payload.get("scores") or payload.get("rerank_scores")
        if isinstance(raw_scores, list):
            for i, value in enumerate(raw_scores[:expected]):
                scores[i] = float(value)
            return scores
    raise RemoteModelError("远程 rerank 返回格式无法解析")


class RemoteEmbedding:
    """给 hybrid_retriever / ingest 使用的 SentenceTransformer 兼容包装。"""

    def encode(self, sentences, batch_size=None, show_progress_bar=False, **kwargs):
        single = isinstance(sentences, str)
        texts = [sentences] if single else [str(x) for x in sentences]
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        chunk_size = max(1, int(batch_size or MODEL_API_BATCH_SIZE))
        vectors: list[list[float]] = []
        for start in range(0, len(texts), chunk_size):
            chunk = texts[start:start + chunk_size]
            payload = {
                "input": chunk,
                "model": MODEL_API_EMBEDDING_MODEL,
            }
            result = _post("/v1/embeddings", payload)
            vectors.extend(_as_embedding_list(result))

        if len(vectors) != len(texts):
            raise RemoteModelError(
                f"远程 embeddings 数量不匹配: 期望 {len(texts)} 得到 {len(vectors)}"
            )
        arr = np.asarray(vectors, dtype=np.float32)
        return arr[0] if single else arr

    def get_sentence_embedding_dimension(self):
        return None


class RemoteReranker:
    """给 reranker.rerank 使用的 CrossEncoder 兼容包装。"""

    def predict(self, pairs, **kwargs):
        pairs = list(pairs or [])
        if not pairs:
            return []
        query = pairs[0][0]
        documents = [str(p[1]) for p in pairs]
        payload = {
            "query": query,
            "documents": documents,
            "model": MODEL_API_RERANK_MODEL,
        }
        result = _post("/v1/rerank", payload)
        scores = _parse_rerank(result, len(documents))
        return np.asarray(scores, dtype=np.float32)
