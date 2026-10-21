# -*- coding: utf-8 -*-
"""远程 BGE 客户端协议测试（不访问真实网络）。"""
import numpy as np

from rag_demo.retrieval import remote_models


def test_remote_embedding_batch_and_single(monkeypatch):
    calls = []

    def fake_post(path, payload):
        calls.append((path, payload))
        return {
            "data": [
                {"index": i, "embedding": [float(i), 1.0]}
                for i, _ in enumerate(payload["input"])
            ]
        }

    monkeypatch.setattr(remote_models, "_post", fake_post)
    emb = remote_models.RemoteEmbedding()
    single = emb.encode("a")
    assert isinstance(single, np.ndarray)
    assert single.shape == (2,)
    batch = emb.encode(["a", "b"])
    assert batch.shape == (2, 2)
    assert calls[0][0] == "/v1/embeddings"


def test_remote_rerank_maps_index_order(monkeypatch):
    def fake_post(path, payload):
        assert path == "/v1/rerank"
        assert payload["documents"] == ["doc-a", "doc-b"]
        # 故意逆序返回，验证按 index 对齐而不是按响应顺序
        return {
            "results": [
                {"index": 1, "relevance_score": 0.1},
                {"index": 0, "relevance_score": 0.9},
            ]
        }

    monkeypatch.setattr(remote_models, "_post", fake_post)
    scores = remote_models.RemoteReranker().predict([("q", "doc-a"), ("q", "doc-b")])
    assert list(scores) == [0.9, 0.1]


def test_remote_endpoint_does_not_duplicate_v1(monkeypatch):
    seen = []
    monkeypatch.setattr(remote_models, "MODEL_API_BASE", "https://example.test/v1")
    monkeypatch.setattr(remote_models, "MODEL_API_KEY", "test-key")
    monkeypatch.setattr(remote_models, "MODEL_API_TIMEOUT", 5)
    monkeypatch.setattr(remote_models, "MODEL_API_BATCH_SIZE", 8)

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"data":[{"index":0,"embedding":[1,2]}]}'

    def fake_urlopen(req, timeout):
        seen.append(req.full_url)
        assert req.headers.get("Authorization") == "Bearer test-key"
        return FakeResponse()

    monkeypatch.setattr(remote_models.urllib.request, "urlopen", fake_urlopen)
    remote_models.RemoteEmbedding().encode("hello")
    assert seen == ["https://example.test/v1/embeddings"]
