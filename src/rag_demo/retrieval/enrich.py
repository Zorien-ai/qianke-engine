#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Function: 检索候选补全（父块 / 图片）

为什么单独一次批量查询，而不是让每路召回自己 SELECT
--------------------------------------------------
BM25 走的是 `search_index`（内存 / 独立表），那里没有 parent 与 metadata；
只有 `wiki_vectors` 才有。两路 RRF 融合后再按 id 批量回表一次，
既不让 BM25 多存一份冗余字段，也避免「每种召回各写一条 JOIN」的分叉。

只读、不提交：与 vector_search 一致，查询结束必须 rollback 释放
AccessShareLock（否则会堵住 ingest 的 ALTER TABLE）。
"""
import json
import logging

from rag_demo.db.connection import get_conn

logger = logging.getLogger(__name__)


def _wiki_id(item: dict) -> int | None:
    cid = str(item.get("id") or "")
    if not cid.startswith("wiki:"):
        return None
    try:
        return int(cid.split(":", 1)[1])
    except ValueError:
        return None


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}
    return {}


def attach_wiki_meta(candidates: list[dict]) -> list[dict]:
    """
    给 wiki 候选补 `parent_key` / `parent_text` / `images`

    失败时原样返回（记 warning）：补全只是增强，不该让整次检索变成
    「检索不可用」——那会把一个装饰性问题升级成答不出话。
    """
    if not candidates:
        return candidates

    ids: list[int] = []
    for c in candidates:
        wid = _wiki_id(c)
        if wid is not None:
            ids.append(wid)
    if not ids:
        return candidates

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, parent_key, parent_text, metadata FROM wiki_vectors "
            "WHERE id = ANY(%s)",
            (ids,),
        )
        rows = {int(r[0]): r for r in cur.fetchall()}
    except Exception as e:  # noqa: BLE001 补全失败只降级
        logger.warning("检索候选补全父块/图片失败: %s: %s", type(e).__name__, e)
        return candidates
    finally:
        conn.rollback()
        cur.close()

    for c in candidates:
        wid = _wiki_id(c)
        row = rows.get(wid) if wid is not None else None
        if row is None:
            continue
        c["parent_key"] = row[1] or ""
        c["parent_text"] = row[2] or ""
        images = _as_dict(row[3]).get("images") or []
        if images:
            c["images"] = [
                img for img in images
                if isinstance(img, dict) and (img.get("key") or img.get("url"))
            ]
    return candidates
