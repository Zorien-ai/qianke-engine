#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Function: 给老库回填 wiki_vectors.parent_key / parent_text（不重算向量、不动 id）

为什么需要这个脚本
------------------
父块是 M4 才加的列。老库里的 chunk 没有 `parent_key` / `parent_text`，
`WIKI_PARENT_MODE=section` 会静默退回「整篇文档全文扩展」——功能没坏，但章节粒度
用不上。

直接重跑 `ingest_docs.py` 当然可以，代价是：TRUNCATE 整表、重新 encode 全部文档、
`wiki_vectors.id` 全部变化，于是 `search_index.corpus_id`（`wiki:<id>`）全部失配，
必须再重建一次索引。只是为了补两列元数据，这个代价太大。

本脚本的做法：用**同一个切分器**把原文再切一遍，把结果对回已有行：
    1. 优先按 `chunk_text` 精确匹配（同一份文档、同一个切分器，正常都能对上）
    2. 对不上（历史版本切分差异）且两边条数一致，按该文档内的 id 顺序与
       chunk_index 顺序对齐
    3. 仍对不上的行保持原样并在结果里报告，不猜

默认 **dry-run**，只打印将要改多少行；加 `--apply` 才写库。

不做的事
--------
不回填 `metadata.images`：图片需要原文目录里的图片文件 + OSS 凭证，属于「重新入库
素材」而不是「补元数据」。图片请走一次正常入库（重建或增量）。

用法
----
    uv run python src/rag_demo/tools/backfill_parents.py                # 预演
    uv run python src/rag_demo/tools/backfill_parents.py --apply        # 写库
    uv run python src/rag_demo/tools/backfill_parents.py --doc 用户分析报告模板.md
"""
import argparse
import logging
import os
import sys

from rag_demo.config import DEFAULT_DATASET, DOCS_DIR
from rag_demo.db.connection import get_conn, reset_dataset, use_dataset
from rag_demo.db.schema import read_index_meta
from rag_demo.splitter import DOC_TYPE_WIKI, split

logger = logging.getLogger("backfill_parents")


def _doc_dir() -> str:
    try:
        return read_index_meta("doc_source_dir") or DOCS_DIR
    except Exception as e:  # noqa: BLE001 读不到就用默认目录
        logger.warning("读取 doc_source_dir 失败，退回 %s: %s", DOCS_DIR, e)
        return DOCS_DIR


def _rows_of(cur, doc_name: str) -> list[tuple[int, str]]:
    cur.execute(
        "SELECT id, chunk_text FROM wiki_vectors WHERE doc_name = %s ORDER BY id",
        (doc_name,),
    )
    return [(int(r[0]), r[1] or "") for r in cur.fetchall()]


def _build_updates(rows, documents) -> tuple[list[tuple], int]:
    """
    返回 ([(parent_key, parent_text, id)], 无法匹配的行数)

    先精确匹配正文，再按顺序兜底：两种方式都不会给同一行写两个不同的父块。
    """
    by_text: dict[str, list[dict]] = {}
    for doc in documents:
        by_text.setdefault(doc.page_content, []).append(doc.metadata)

    matched: dict[int, dict] = {}
    for row_id, text in rows:
        bucket = by_text.get(text)
        if bucket:
            matched[row_id] = bucket.pop(0)

    if len(matched) < len(rows) and len(rows) == len(documents):
        # 历史切分差异：条数一致时顺序仍然可比（写入顺序 == chunk_index 顺序）
        matched = {row_id: documents[i].metadata for i, (row_id, _) in enumerate(rows)}

    updates = [
        (meta.get("parent_key"), meta.get("parent_text"), row_id)
        for row_id, meta in matched.items()
        if meta.get("parent_key") is not None
    ]
    return updates, len(rows) - len(updates)


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 wiki_vectors 的父块列")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认只预演）")
    parser.add_argument("--doc", default="", help="只处理指定文档名")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="数据集名，默认 demo")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    token = use_dataset(args.dataset)
    conn = get_conn()
    cur = conn.cursor()
    try:
        sql = "SELECT doc_name, count(*) FROM wiki_vectors"
        params: tuple = ()
        if args.doc:
            sql += " WHERE doc_name = %s"
            params = (args.doc,)
        sql += " GROUP BY doc_name ORDER BY doc_name"
        cur.execute(sql, params)
        docs = cur.fetchall()
        if not docs:
            print("没有可处理的文档（表为空或文档名不存在）。")
            return 0

        base = _doc_dir()
        print(f"数据集 {args.dataset} / 原文目录 {base}")
        print(f"待处理 {len(docs)} 篇文档，共 {sum(int(c) for _, c in docs)} 个 chunk\n")

        planned = 0
        unmatched = 0
        missing_files: list[str] = []
        for doc_name, total in docs:
            path = os.path.join(base, doc_name)
            if not os.path.isfile(path):
                fallback = os.path.join(DOCS_DIR, doc_name)
                if os.path.isfile(fallback):
                    path = fallback
                else:
                    missing_files.append(doc_name)
                    print(f"[跳过] {doc_name}: 找不到原文（{path}）")
                    continue

            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
            documents = split(DOC_TYPE_WIKI, {"text": text, "doc_name": doc_name})
            rows = _rows_of(cur, doc_name)
            updates, miss = _build_updates(rows, documents)
            planned += len(updates)
            unmatched += miss
            print(
                f"[{'更新' if args.apply else '预演'}] {doc_name}: "
                f"chunk {len(rows)}，可回填 {len(updates)}，未匹配 {miss}"
            )

            if args.apply and updates:
                cur.executemany(
                    "UPDATE wiki_vectors SET parent_key = %s, parent_text = %s WHERE id = %s",
                    updates,
                )

        if args.apply:
            conn.commit()
            print(f"\n已提交：{planned} 行写入父块。")
        else:
            print(f"\n预演结果：将更新 {planned} 行；加 --apply 生效。")

        if unmatched:
            print(f"⚠ {unmatched} 行无法匹配到父块（保持原样），建议对该文档重新入库。")
        if missing_files:
            print(f"⚠ {len(missing_files)} 篇文档缺原文，未处理：{', '.join(missing_files)}")
        return 0
    finally:
        cur.close()
        reset_dataset(token)


if __name__ == "__main__":
    sys.exit(main())
