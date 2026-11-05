# -*- coding: utf-8 -*-
"""RRF k 参数化的契约测试（不连库、不调模型）。

覆盖三件事，对应「k 可参数化」改造的三个风险点：
1. `rrf_fusion` 的默认值必须仍是 60，显式传入的 k 必须真的参与打分（且能改变排序）；
2. 运行时覆盖 `set_rrf_k` 必须能被 `hybrid_search` 感知，且 `set_rrf_k(None)` 能恢复默认；
3. `answer_cache` 的键必须包含 rrf_k，否则换 k 会命中旧 k 的缓存。
"""
import os

import pytest

from rag_demo.cache import AnswerCache
from rag_demo.retrieval import hybrid_retriever as hr


@pytest.fixture(autouse=True)
def _restore_runtime_k():
    """任何用例都不许把全局 k 残留到下一个用例/下一次实验。"""
    yield
    hr.set_rrf_k(None)


def test_default_rrf_k_matches_config():
    # 默认值来自 config.RRF_K；仓库默认必须是 60（除非部署侧用 RAG_RRF_K 显式覆盖）
    assert hr.get_rrf_k() == hr.RRF_K
    assert isinstance(hr.RRF_K, int) and hr.RRF_K >= 1
    if "RAG_RRF_K" not in os.environ:
        assert hr.RRF_K == 60


def test_rrf_fusion_default_score_uses_config_k():
    fused = hr.rrf_fusion([[{"id": "a", "source": "s"}]], top_n=5)
    assert fused[0]["rrf_score"] == pytest.approx(1 / (hr.RRF_K + 0 + 1))


def test_rrf_fusion_explicit_k_changes_scores():
    one = hr.rrf_fusion([[{"id": "a", "source": "s"}]], k=10, top_n=5)
    two = hr.rrf_fusion([[{"id": "a", "source": "s"}]], k=100, top_n=5)
    assert one[0]["rrf_score"] > two[0]["rrf_score"]  # k 越大，名次权重越平


def _flip_order_lists():
    """构造两组名次，使「单路第 1 名」与「两路都靠前」的优劣随 k 反转。

    x: 一路第 1、另一路第 30（0-based rank 0 / 29）——靠单路头部；
    y: 两路都是第 10（rank 9 / 9）——靠多路共识。
    k 小时 x 的头部优势更大，k 大时 y 的共识优势胜出。
    """
    list_a = [{"id": "x", "source": "s"}] + [
        {"id": f"a{i}", "source": "s"} for i in range(1, 9)
    ] + [{"id": "y", "source": "s"}]
    list_b = (
        [{"id": f"b{i}", "source": "s"} for i in range(1, 10)]
        + [{"id": "y", "source": "s"}]
        + [{"id": f"c{i}", "source": "s"} for i in range(1, 20)]
        + [{"id": "x", "source": "s"}]
    )
    return [list_a, list_b]


def test_rrf_fusion_k_can_flip_order():
    lists = _flip_order_lists()
    small = hr.rrf_fusion(lists, k=10, top_n=5)
    large = hr.rrf_fusion(lists, k=100, top_n=5)
    assert small[0]["id"] == "x"
    assert large[0]["id"] == "y"


def test_set_rrf_k_roundtrip_and_validation():
    hr.set_rrf_k(10)
    assert hr.get_rrf_k() == 10
    hr.set_rrf_k(None)
    assert hr.get_rrf_k() == hr.RRF_K
    with pytest.raises(ValueError):
        hr.set_rrf_k(0)
    with pytest.raises(ValueError):
        hr.set_rrf_k(-5)
    # 类型严格：字符串 / 浮点 / bool 一律拒绝，避免实验传错值静默截断
    with pytest.raises(TypeError):
        hr.set_rrf_k("7")
    with pytest.raises(TypeError):
        hr.set_rrf_k(7.9)
    with pytest.raises(TypeError):
        hr.set_rrf_k(True)


def test_hybrid_search_uses_runtime_k(monkeypatch):
    seen = {}
    real_fusion = hr.rrf_fusion

    def spy(result_lists, k=hr.RRF_K, top_n=hr.TOP_K_RRF):
        seen["k"] = k
        return real_fusion(result_lists, k=k, top_n=top_n)

    monkeypatch.setattr(hr, "vector_search",
                        lambda query, top_k, dept=None: [
                            {"id": "v", "source": "user_profile", "score": 0.9}
                        ])
    monkeypatch.setattr(hr, "keyword_search",
                        lambda query, top_k, mode=None, rrf_k=None: [
                            {"id": "k", "source": "tag_definitions.md", "score": 1.0}
                        ])
    monkeypatch.setattr(hr, "attach_wiki_meta", lambda items: items)
    monkeypatch.setattr(hr, "rrf_fusion", spy)

    hr.set_rrf_k(7)
    hr.hybrid_search("k 覆盖是否生效", top_k=5)
    assert seen["k"] == 7

    hr.set_rrf_k(None)
    hr.hybrid_search("k 覆盖是否生效", top_k=5)
    assert seen["k"] == hr.RRF_K


def test_hybrid_search_explicit_rrf_k_beats_runtime(monkeypatch):
    """显式传入 rrf_k 时以显式值为准（消融脚本可以不依赖全局状态）。"""
    seen = {}
    real_fusion = hr.rrf_fusion

    def spy(result_lists, k=hr.RRF_K, top_n=hr.TOP_K_RRF):
        seen["k"] = k
        return real_fusion(result_lists, k=k, top_n=top_n)

    monkeypatch.setattr(hr, "vector_search", lambda query, top_k, dept=None: [])
    monkeypatch.setattr(hr, "keyword_search",
                        lambda query, top_k, mode=None, rrf_k=None: [])
    monkeypatch.setattr(hr, "attach_wiki_meta", lambda items: items)
    monkeypatch.setattr(hr, "rrf_fusion", spy)

    hr.set_rrf_k(60)
    hr.hybrid_search("q", top_k=5, rrf_k=17)
    assert seen["k"] == 17


def test_answer_cache_key_includes_rrf_k():
    base = AnswerCache.make_key("高价值用户怎么定义", dataset="demo")
    assert base == AnswerCache.make_key("高价值用户怎么定义", dataset="demo", rrf_k=hr.RRF_K)
    assert base != AnswerCache.make_key("高价值用户怎么定义", dataset="demo", rrf_k=hr.RRF_K + 1)
