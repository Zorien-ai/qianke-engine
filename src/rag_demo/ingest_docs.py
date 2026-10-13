#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : ingest_docs.py
@Function: 将 data/docs 下的 Markdown 文档切分、向量化，写入 wiki_vectors

切分走 splitter.split(DOC_TYPE_WIKI, ...)，与数据表来源共用同一套
「切分策略 → List[Document]」契约。
"""
import json
import os

from sentence_transformers import SentenceTransformer

from rag_demo.config import DOCS_DIR, MODEL_PATH, SEARCH_INDEX_TABLE
from rag_demo.db.connection import close_conn, get_conn
from rag_demo.splitter import DOC_TYPE_WIKI, split

print("正在加载 bge-m3 模型...")
model = SentenceTransformer(MODEL_PATH) if os.path.exists(MODEL_PATH) \
        else SentenceTransformer("BAAI/bge-m3")

print("正在连接数据库...")
conn = get_conn()
cur = conn.cursor()

# 补 metadata 列以对齐 user_profile_vectors，用于存放切分阶段的结构信息
# （标题路径 / 块序位 / 来源类型）。原先这些信息在切分后被丢掉了。
cur.execute("ALTER TABLE wiki_vectors ADD COLUMN IF NOT EXISTS metadata JSONB")

# 清空旧数据，避免重复导入
cur.execute("TRUNCATE wiki_vectors RESTART IDENTITY;")
conn.commit()

total_chunks = 0
for filename in sorted(os.listdir(DOCS_DIR)):
    if not filename.endswith(".md"):
        continue
    with open(os.path.join(DOCS_DIR, filename), "r", encoding="utf-8") as f:
        text = f.read()

    documents = split(DOC_TYPE_WIKI, {"text": text, "doc_name": filename})
    if not documents:
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
    print(f"[OK] {filename}: 导入 {len(documents)} 个分块")

cur.close()
close_conn()
print(f"\n所有文档已入库，共 {total_chunks} 个分块")
print(
    f"\n[注意] 文档分块已变化，检索索引 {SEARCH_INDEX_TABLE} 需要重建，"
    f"否则检索将使用旧索引：\n"
    f"    uv run python src/rag_demo/tools/build_search_index.py"
)
