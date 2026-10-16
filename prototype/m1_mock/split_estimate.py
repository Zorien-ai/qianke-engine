#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : split_estimate.py
@Function: 切分逻辑的**冻结副本** —— 只服务冻结快照里的「预估分块数」

来源：src/rag_demo/splitter.py::split_wiki_documents（2026-10-16 复制，逐行照抄）
口径：两段式切分 —— 先按 Markdown 标题切，再按长度兜底；参数与入库口径一致
      （chunk_size=400 / overlap=40 / 分隔符有序）。

为什么不直接 import 真实切分器：
    快照的「独立」必须连依赖一起独立。只要还 import 一次 rag_demo.*，
    M2 重构那个模块时（改签名、换依赖、或只是 import 期间抛错）就能把
    8001 的测试环境打挂——而测试者并不知道我们在改后端。

为什么可以接受口径漂移：
    这里的结果只用于界面上的「预估分块数」，不参与真实入库。M2 若调整了
    真实切分参数，这个数字可能与真实流水线不一致，但最多影响一句提示的准确性，
    不会让任何测试者卡住。真要对齐时，重新复制一份即可（这就是快照的代价与用法）。

⚠ 不要为了「保持同步」而修改本文件：快照的价值在于稳定，不在于最新。
"""

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

# 与 rag_demo.splitter 的取值一致（照抄时的原值）
DOC_TYPE_WIKI = "wiki"
DEPT_WIKI = "all"
SENSITIVITY_DEFAULT = 1

_MD_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]
_CHUNK_SIZE = 400
_CHUNK_OVERLAP = 40
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]

# 切分器无状态，模块级建一次即可
_MD_SPLITTER = MarkdownHeaderTextSplitter(headers_to_split_on=_MD_HEADERS)
_CHAR_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=_CHUNK_SIZE,
    chunk_overlap=_CHUNK_OVERLAP,
    separators=_SEPARATORS,
)


def split_wiki_documents(text: str, doc_name: str) -> list[Document]:
    """文档类型切分：Markdown → 标题切分 → 长度切分（与 splitter.py 同实现）"""
    documents: list[Document] = []

    for md_chunk in _MD_SPLITTER.split_text(text):
        headers = {k: v for k, v in md_chunk.metadata.items() if v}

        # 标题拼回正文开头：MarkdownHeaderTextSplitter 只把标题放进 metadata，
        # 正文里没有，题目语义会在向量化时丢失。
        header_str = " ".join(f"{k}: {v}" for k, v in headers.items())
        body = (
            f"{header_str}\n{md_chunk.page_content}"
            if header_str
            else md_chunk.page_content
        )

        for piece in _CHAR_SPLITTER.split_text(body):
            documents.append(
                Document(
                    page_content=piece,
                    metadata={
                        "source": doc_name,
                        "doc_type": DOC_TYPE_WIKI,
                        "dept": DEPT_WIKI,
                        "sensitivity": SENSITIVITY_DEFAULT,
                        "headers": headers,
                        "chunk_index": len(documents),
                    },
                )
            )

    return documents
