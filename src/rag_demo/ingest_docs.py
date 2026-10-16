#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : ingest_docs.py
@Function: Markdown 文档 → 切分 → 向量化 → 写入 wiki_vectors

切分走 splitter.split(DOC_TYPE_WIKI, ...)，与数据表来源共用同一套
「切分策略 → List[Document]」契约。

两种用法（M2 改造点）
--------------------
改造前这个文件**没有函数**，加载模型 / 连库 / TRUNCATE / 写库全在模块顶层，
于是 `import rag_demo.ingest_docs` 就等于「清空并重写知识库」——
服务里想复用它的切分与写库逻辑，一 import 就把库清了，不可控。
现在拆成 load_doc_texts + ingest_documents 两个函数，脚本用法保持不变。

· 脚本（扫 data/docs，与改造前行为一致）：
      uv run python src/rag_demo/ingest_docs.py
· 服务内调用（M2 用户上传的 .md 走这条）：
      ingest_documents([("a.md", text), ...], model=<检索侧单例>)

为什么 model 要能从外面传进来：检索侧已有 bge-m3 单例
（retrieval.hybrid_retriever.get_model），服务进程里再 new 一个会翻倍占显存
（config 里已警示 fp32 双模型约 4.4GB）。脚本没有别的模型在手，才自己加载。
"""
import json
import logging
import os
from typing import Callable

from sentence_transformers import SentenceTransformer

from rag_demo.config import DOCS_DIR, MODEL_PATH, SEARCH_INDEX_TABLE
from rag_demo.db.connection import close_conn, get_conn
from rag_demo.splitter import DOC_TYPE_WIKI, split

logger = logging.getLogger(__name__)

# 进度回调：(已完成文档数, 文档总数, 当前文件名)
ProgressFn = Callable[[int, int, str], None]


def load_doc_texts(docs_dir: str = DOCS_DIR) -> list[tuple[str, str]]:
    """
    读取目录下所有 .md → [(文件名, 正文)]

    按文件名排序：顺序稳定，重跑结果才可复现（指纹比对依赖这一点）。
    读不出来的单个文件只跳过并告警，不让它带崩整批——
    用户上传的一堆文档里有一篇编码坏了，不该导致前 9 篇都白导。
    """
    items: list[tuple[str, str]] = []
    for filename in sorted(os.listdir(docs_dir)):
        if not filename.endswith(".md"):
            continue
        path = os.path.join(docs_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                items.append((filename, f.read()))
        except Exception as e:  # noqa: BLE001
            logger.warning("跳过无法读取的文档 %s: %s: %s", filename, type(e).__name__, e)
    return items


def ingest_documents(
    docs: list[tuple[str, str]],
    model: SentenceTransformer | None = None,
    progress: ProgressFn | None = None,
) -> dict:
    """
    切分 + 向量化 + 写入 wiki_vectors（**全量覆盖**：先 TRUNCATE 再写）

    docs: [(文件名, 正文)]。正文已由调用方解码好——M2 的上传接口在收到文件时
          就已经按 utf-8/GBK 判过编码了，这里不再猜。
    model: 不传则自行加载（脚本路径）；服务路径必须传检索侧单例，避免重复占显存。
    progress: 每篇文档完成后回调一次，供构建任务的进度条使用。

    返回 {"docs": 成功导入的文档数, "chunks": 总块数}

    注意这里**不关连接**：服务与脚本共用 db.connection 的进程级单例，
    函数内 close_conn() 会把别的线程正在用的连接一起关掉（改造前 main() 结尾就是这么干的）。
    连接的生命周期由调用方负责。
    """
    if not docs:
        # 空输入直接拦下，不能走到 TRUNCATE——那会把已有知识库清空还不报错。
        # 改造前脚本没有这道闸，DOCS_DIR 为空时会静默清库。
        raise ValueError("没有可导入的 .md 文档")

    if model is None:
        logger.info("正在加载 bge-m3 模型...")
        model = SentenceTransformer(MODEL_PATH) if os.path.exists(MODEL_PATH) \
            else SentenceTransformer("BAAI/bge-m3")

    conn = get_conn()
    cur = conn.cursor()
    try:
        # 补 metadata 列以对齐 user_profile_vectors，用于存放切分阶段的结构信息
        # （标题路径 / 块序位 / 来源类型）。原先这些信息在切分后被丢掉了。
        cur.execute("ALTER TABLE wiki_vectors ADD COLUMN IF NOT EXISTS metadata JSONB")

        # 清空旧数据，避免重复导入
        cur.execute("TRUNCATE wiki_vectors RESTART IDENTITY;")
        conn.commit()

        total_chunks = 0
        imported = 0
        total = len(docs)
        for i, (filename, text) in enumerate(docs, 1):
            documents = split(DOC_TYPE_WIKI, {"text": text, "doc_name": filename})
            if not documents:
                logger.warning("[跳过] %s: 切分后没有内容", filename)
                if progress:
                    progress(i, total, filename)
                continue

            vecs = model.encode(
                [d.page_content for d in documents], batch_size=16, show_progress_bar=False
            )
            for doc, vec in zip(documents, vecs):
                meta = doc.metadata
                cur.execute(
                    """INSERT INTO wiki_vectors
                       (doc_name, chunk_text, embedding, dept, sensitivity, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        meta["source"],
                        doc.page_content,
                        vec,
                        meta["dept"],
                        meta["sensitivity"],
                        json.dumps({
                            "doc_type": meta["doc_type"],
                            "headers": meta["headers"],
                            "chunk_index": meta["chunk_index"],
                        }, ensure_ascii=False),
                    )
                )
            conn.commit()
            total_chunks += len(documents)
            imported += 1
            logger.info("[OK] %s: 导入 %d 个分块", filename, len(documents))
            if progress:
                progress(i, total, filename)
    finally:
        cur.close()

    return {"docs": imported, "chunks": total_chunks}


def main() -> None:
    """脚本入口：扫 data/docs 全量重建（与改造前行为一致）"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    logger.info("正在连接数据库...")
    docs = load_doc_texts()
    if not docs:
        logger.error("data/docs 下没有 .md 文档，已中止（不会清空 wiki_vectors）")
        return

    result = ingest_documents(docs)
    logger.info("所有文档已入库，共 %d 个分块（%d 篇）", result["chunks"], result["docs"])

    close_conn()
    logger.warning(
        "文档分块已变化，检索索引 %s 需要重建，否则检索将使用旧索引：\n"
        "    uv run python src/rag_demo/tools/build_search_index.py",
        SEARCH_INDEX_TABLE,
    )


if __name__ == "__main__":
    main()
