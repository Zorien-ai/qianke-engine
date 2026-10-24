# -*- coding: utf-8 -*-
"""search_index 构建时的稀疏编码降级测试。

背景：云端轻量镜像不安装 FlagEmbedding，KEYWORD_RETRIEVER 默认 bm25。
旧实现无条件调用 encode_sparse，导致上传构建在最后一步「建立检索索引」失败。
"""
from rag_demo.tools import build_search_index as bsi


def test_bm25_mode_skips_sparse_encoding(monkeypatch):
    called = {"value": False}

    def fake_encode(texts):
        called["value"] = True
        return [{"1": 0.5}] * len(texts)

    monkeypatch.setattr(bsi, "KEYWORD_RETRIEVER", "bm25")
    monkeypatch.setattr(bsi, "encode_sparse", fake_encode)

    assert bsi._encode_sparse_or_none(["画像文本", "文档文本"]) == [None, None]
    assert called["value"] is False


def test_sparse_mode_without_flagembedding_falls_back_to_bm25(monkeypatch):
    called = {"value": False}

    def fake_encode(texts):
        called["value"] = True
        return [{"1": 0.5}] * len(texts)

    monkeypatch.setattr(bsi, "KEYWORD_RETRIEVER", "both")
    monkeypatch.setattr(bsi.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(bsi, "encode_sparse", fake_encode)

    assert bsi._encode_sparse_or_none(["画像文本"]) == [None]
    assert called["value"] is False


def test_sparse_mode_with_flagembedding_encodes(monkeypatch):
    monkeypatch.setattr(bsi, "KEYWORD_RETRIEVER", "sparse")
    monkeypatch.setattr(bsi.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(
        bsi, "encode_sparse", lambda texts: [{"1": 0.25} for _ in texts]
    )

    assert bsi._encode_sparse_or_none(["a", "b"]) == [{"1": 0.25}, {"1": 0.25}]
