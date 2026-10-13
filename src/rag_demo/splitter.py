#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : splitter.py
@Function: 切分策略 —— 按来源类型分派，统一返回 List[Document]

对应流程图「离线导入」的切分环节：

    文档分析与清洗 → ◆切分策略
                      ├─ 文档类型切分   （Markdown → 标题切分 + 长度切分）
                      └─ 数据表类型切分 （一行用户 = 一个 Document）
                                        ↓
                              均返回 List[Document] 对象

统一契约的价值不在于「整齐」，而在于 **metadata 能跟着走**：
此前切分产物是裸字符串，标题、来源这些结构信息只能靠拼进正文带出去；
改成 Document 后，语义内容留在正文、结构信息留在 metadata，各归各位。

metadata 字段（分两个阶段，范围不同）：

    ── 切分产物（Document.metadata，内存里的临时载体）──
    source / doc_type / dept / sensitivity / headers / chunk_index / user_id
    ＋结构化字段（age / city / member_level / …）

    带上结构化字段是为了让 Document **自包含**——入库时一个对象就能取齐所有列，
    不必再回查 DataFrame。这些字段落库后会拆成独立列，不会冗余进 jsonb，
    因此不产生任何运行时开销。

    ── 入库后（数据库）──
    结构化字段 → 独立列（供 Text2SQL 聚合）
    dept / sensitivity → 独立列（供检索过滤）
    其余 → metadata jsonb
"""
import logging

import pandas as pd
from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

logger = logging.getLogger(__name__)

# 切分策略名（与流程图里的两个分支对应）
DOC_TYPE_WIKI = "wiki"        # 文档类型切分
DOC_TYPE_PROFILE = "profile"  # 数据表类型切分

# 与既有入库口径保持一致，避免改动影响检索侧的过滤条件
DEPT_PROFILE = "sales"
DEPT_WIKI = "all"
SENSITIVITY_DEFAULT = 1

# 两段式切分的参数（沿用改造前的取值）
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
    """
    文档类型切分：Markdown → 标题切分 → 长度切分

    两段式的原因：
        只用标题切 -> 会产出超长 chunk，可能顶破模型输入上限
        只用长度切 -> 会从句子中间劈开，且丢掉标题层级
        先按语义边界切、再按长度兜底，两者都避开

    标题会**同时**出现在正文和 metadata 里，这不是冗余：
        正文里的标题 -> 参与向量化与 BM25 打分（检索「会员等级」这类词要能匹配上）
        metadata 里的 -> 供展示、过滤、Parent Document 合并使用
    """
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


def split_profile_documents(profiles: pd.DataFrame) -> list[Document]:
    """
    数据表类型切分：一行用户 = 一个 Document

    粒度取「用户」这一行，不再往下拆：
        画像文本本就是按 user_id 聚合出来的，再切碎会破坏
        「一个用户一条画像」的完整性，也会失去单用户查询的能力
        （「U2765 是什么用户」这类问题需要整条画像）。

    metadata 带全部结构化字段，理由见模块 docstring —— 让 Document 自包含。
    """
    documents: list[Document] = []

    for row in profiles.to_dict("records"):
        documents.append(
            Document(
                page_content=row["profile_text"],
                metadata={
                    "source": "user_profile",
                    "doc_type": DOC_TYPE_PROFILE,
                    "dept": DEPT_PROFILE,
                    "sensitivity": SENSITIVITY_DEFAULT,
                    "user_id": row["user_id"],
                    # ---- 以下结构化字段入库时拆成独立列，供 Text2SQL ----
                    "age": row["age"],
                    "gender": row["gender"],
                    "city": row["city"],
                    "member_level": row["member_level"],
                    "order_count": row["order_count"],
                    "total_amount": row["total_amount"],
                    "avg_amount": row["avg_amount"],
                    "top_category": row["top_category"],
                    "days_since_last_buy": row["days_since_last_buy"],
                    "platforms": row["platforms"],
                },
            )
        )

    return documents


def split(strategy: str, payload: dict) -> list[Document]:
    """
    切分策略分派（对应流程图里的菱形）

    参数:
        strategy: DOC_TYPE_WIKI（文档类型切分）
                  DOC_TYPE_PROFILE（数据表类型切分）
        payload : wiki    -> {"text": str, "doc_name": str}
                  profile -> {"profiles": pd.DataFrame}

    返回:
        List[Document]，两条策略出口结构一致
    """
    if strategy == DOC_TYPE_WIKI:
        return split_wiki_documents(payload["text"], payload["doc_name"])

    if strategy == DOC_TYPE_PROFILE:
        return split_profile_documents(payload["profiles"])

    raise ValueError(f"未知切分策略: {strategy}")
