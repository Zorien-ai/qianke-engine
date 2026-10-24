# -*- coding: utf-8 -*-
"""缓存键数据版本回归测试。"""
from rag_demo.cache import AnswerCache


def test_cache_key_changes_with_data_version():
    kwargs = dict(dataset="test", history_key="", data_version="build:2026-10-24 11:00:00")
    first = AnswerCache.make_key("上海的黑卡流失用户有哪些", **kwargs)
    second = AnswerCache.make_key(
        "上海的黑卡流失用户有哪些",
        dataset="test",
        history_key="",
        data_version="build:2026-10-24 11:05:00",
    )
    assert first != second


def test_cache_key_same_question_same_version_is_stable():
    one = AnswerCache.make_key("上海的黑卡流失用户有哪些", dataset="test", data_version="v1")
    two = AnswerCache.make_key("上海的黑卡流失用户有哪些", dataset="test", data_version="v1")
    assert one == two
