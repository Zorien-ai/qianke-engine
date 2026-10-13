#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : cache.py
@Function: 问答结果缓存（LRU + TTL，线程安全）

为什么需要
----------
实测一次问答 9~17s，其中 **92~96% 花在 LLM 生成**。而 demo 场景的提问高度重复
（反复试同一批评测题、调参数后重问同一问题），命中缓存可直接把响应压到毫秒级。

键的设计
--------
缓存键包含 question + dept + 检索模式。**必须带检索模式**，否则切换
BM25 / 稀疏向量后会拿到另一套策略的结果，看起来像「策略没生效」。

失效策略
--------
- TTL：默认 1 小时。库里画像和文档会随 ingest 更新，缓存不宜永久有效。
- 容量：LRU 上限 256 条，超出淘汰最久未用的。
- 手动：`clear()` 供数据更新后清空。
"""
import hashlib
import threading
import time
from collections import OrderedDict

DEFAULT_MAXSIZE = 256
DEFAULT_TTL = 3600  # 秒


class AnswerCache:
    """线程安全的 LRU + TTL 缓存"""

    def __init__(self, maxsize: int = DEFAULT_MAXSIZE, ttl: int = DEFAULT_TTL):
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(question: str, dept: str | None = None, keyword_mode: str | None = None) -> str:
        """
        生成缓存键

        显式拼接三个维度再哈希，避免不同参数组合互相覆盖。
        """
        raw = f"{question.strip()}|{dept or '-'}|{keyword_mode or '-'}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                self._misses += 1
                return None

            expire_at, value = item
            if expire_at < now:  # 已过期
                del self._store[key]
                self._misses += 1
                return None

            self._store.move_to_end(key)  # 标记为最近使用
            self._hits += 1
            return value

    def set(self, key: str, value: dict) -> None:
        with self._lock:
            self._store[key] = (time.time() + self._ttl, value)
            self._store.move_to_end(key)
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)  # 淘汰最久未用

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._store),
                "maxsize": self._maxsize,
                "ttl": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total * 100, 1) if total else 0.0,
            }


# 进程级单例
answer_cache = AnswerCache()
