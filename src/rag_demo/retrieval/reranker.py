#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : reranker.py
@Function: bge-reranker-v2-m3 精排
"""
import logging
import os

from sentence_transformers import CrossEncoder

from rag_demo.config import (
    DEVICE,
    DOCS_DIR,
    DTYPE,
    RERANKER_PATH,
    WIKI_EXPAND_FULLTEXT,
    WIKI_MAX_CHARS,
    WIKI_MIN_SCORE,
    WIKI_PARENT_MODE,
    is_doc_source,
)

logger = logging.getLogger(__name__)

_reranker = None

# 文档原文目录缓存：按数据集分键（demo 在 data/docs，用户上传在 data/uploads/<id>/）
_doc_dir_cache: dict[str, str] = {}


def _doc_base_dir() -> str:
    """
    文档原文目录：优先用导入时记下的路径，读不到再退回 DOCS_DIR

    改前这里写死 `DOCS_DIR`（data/docs）。M2 用户上传的文档落在
    `data/uploads/<id>/` 下，扩展必然找不到——不是报错，是**静默退化**：
    只打一条 warning，用户的 WIKI_EXPAND_FULLTEXT 等于被关掉。
    目录属于数据布局，不属于系统常量。
    """
    try:
        from rag_demo.db.connection import current_dataset
        from rag_demo.db.schema import read_index_meta

        dataset = current_dataset()
        if dataset not in _doc_dir_cache:
            _doc_dir_cache[dataset] = read_index_meta("doc_source_dir") or DOCS_DIR
        return _doc_dir_cache[dataset]
    except Exception as e:  # noqa: BLE001 读不到就退回默认目录，不影响主链路
        logger.debug("读取文档原文目录失败，退回 DOCS_DIR: %s", e)
        return DOCS_DIR


def get_reranker():
    global _reranker
    if _reranker is None:
        if os.path.exists(RERANKER_PATH):
            logger.info(f"正在加载本地 bge-reranker-v2-m3（device={DEVICE}, dtype={DTYPE}）...")
            _reranker = CrossEncoder(
                str(RERANKER_PATH),
                device=DEVICE,
                model_kwargs={"dtype": DTYPE},
            )
        else:
            logger.warning("本地未找到 bge-reranker-v2-m3，从 HuggingFace 加载（首次会下载）...")
            _reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device=DEVICE)
    return _reranker


def rerank(query, candidates, top_k=5):
    """对候选列表精排，返回 Top-K"""
    if not candidates:
        return []
    reranker = get_reranker()
    pairs = [(query, c["text"]) for c in candidates]
    scores = reranker.predict(pairs)
    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)
    return sorted(candidates, key=lambda x: -x["rerank_score"])[:top_k]


# TODO(perf): [P2] wiki 全文扩展会放大上下文，实测 11.0s → 15.1s（+16%）。
#             可调小 WIKI_MAX_CHARS、或只扩展被多次命中的文档。
#             注意：此机制解决了「chunk 粒度错配」问题（DA-01 靠它才能列出全部标签），
#             属正向改进而非缺陷，只是有成本，不可简单移除。详见 bug/性能隐患台账.md
def _expand_to_parent(items, mode=WIKI_PARENT_MODE, max_chars=WIKI_MAX_CHARS):
    """
    父块回填：把命中的 wiki chunk 换成它所属的**章节**（或整篇）正文。

    动机：chunk 级 rerank 分数无法支撑文档级取舍——例如 DA-01「哪些标签跟美妆相关」
    需要 tag_definitions.md 里的**全部**标签定义，而其中任一 chunk 单独看都答不了
    这个问题（rerank 只给 0.001，见 bug/10.11 问题 5）。

    两种粒度：
        section 用入库时写好的 parent_text（一个标题章节，切分器已截到 1600 字）
        doc     旧行为：读磁盘原文全文，截到 WIKI_MAX_CHARS
    去重键也跟着变：章节级按 parent_key 收敛，整篇级按 source 收敛——
    否则同一篇文档的两个章节会被当成重复条目丢掉一个。
    保留原 chunk 的 rerank_score 用于排序，附加 expand_scope 便于排查。
    """
    if mode == "off":
        return items

    expanded = []
    seen = set()
    for c in items:
        use_section = mode == "section" and bool(c.get("parent_text"))
        dedupe_key = (c.get("parent_key") or c["source"]) if use_section else c["source"]
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        if use_section:
            text = c["parent_text"]
            scope = "section"
            if len(text) > max_chars:
                # 章节一般不超过 max_chars；超长时仍按同一上限截断，避免上下文失控
                text = text[:max_chars] + "……"
        else:
            path = os.path.join(_doc_base_dir(), c["source"])
            if not os.path.exists(path):
                logger.warning(f"Parent Document 扩展失败，找不到源文件: {path}")
                expanded.append(c)
                continue
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            scope = "doc"
            if len(text) > max_chars:
                text = text[:max_chars] + "……"

        expanded.append({**c, "text": text, "expanded": True, "expand_scope": scope})
    return expanded


def rerank_by_source(query, candidates, top_k_profile=3, top_k_wiki=2,
                     min_wiki_score=WIKI_MIN_SCORE, expand_fulltext=WIKI_EXPAND_FULLTEXT,
                     parent_mode: str | None = None):
    """
    分来源精排：
    - 画像类（user_profile）：取 Top-N
    - 文档类（*.md）：取 Top-M，可选回填父块（章节 / 整篇，见 config.WIKI_PARENT_MODE）
    - 合并后按 rerank_score 重排

    注意：wiki 名额是「上限」而非「强制填满」。检索池里的 wiki 可能全都不相关，
    硬塞会浪费 token 并干扰生成（详见 bug/10.11 问题 5）。
    实测分数参考（sigmoid 后）：强相关 ≈ 0.8，明确无关 ≈ 0.005。
    """
    profiles = [c for c in candidates if not is_doc_source(c["source"])]
    wikis = [c for c in candidates if is_doc_source(c["source"])]

    reranked_profiles = rerank(query, profiles, top_k=top_k_profile) if profiles else []

    reranked_wikis = []
    if wikis:
        reranked_wikis = [
            c
            for c in rerank(query, wikis, top_k=top_k_wiki)
            if c.get("rerank_score", 0) >= min_wiki_score
        ]
        if reranked_wikis:
            mode = parent_mode or WIKI_PARENT_MODE
            reranked_wikis = _expand_to_parent(
                reranked_wikis, mode=mode if expand_fulltext else "off"
            )

    combined = reranked_profiles + reranked_wikis
    combined.sort(key=lambda x: -x.get("rerank_score", 0))
    return combined
