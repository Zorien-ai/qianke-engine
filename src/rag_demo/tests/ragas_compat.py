#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : ragas_compat.py
@Function: ragas 在本项目环境下的两处适配（LangChain 1.x 垫片 + DeepSeek/本地 embedding 包装）

必须在 `import ragas` **之前** import 本模块。

安装方式（未写进 pyproject.toml，原因见下）：
    uv pip install ragas

    刻意不写进 pyproject：ragas 0.4.3 会把 openai 从 3.26 降到 3.3.0、
    rich 从 15 降到 14.3.4（torch 不受影响）。这会改 uv.lock，
    影响主链路的依赖解析——而 ragas 只用于离线评测，不参与服务运行时。
    要用评测时手动装即可；实测 openai 3.3.0 下项目现有 LLM 调用正常。

    ⚠️ 安装时若有服务在跑（uvicorn）会因文件占用失败，先停服务。

适配一：LangChain 1.x 缺失模块垫片
----------------------------------
ragas 0.4.3 仍按 LangChain 0.3 时代的路径去 import 一批 chat model 类
（`langchain_community.chat_models.vertexai` 等），这些模块在 LangChain 1.x
里已被移除或拆成独立包。本项目只用 `LangchainLLMWrapper(ChatOpenAI)`，
那些类一个都不会用到——注册同名占位模块让 import 通过即可。

这属于 ragas 与 LangChain 1.x 的版本错配，不是本项目的缺陷；
ragas 跟进后（或在 LangChain 0.3 环境下）此垫片可删。

适配二：DeepSeek + 本地 bge-m3
------------------------------
- LLM：DeepSeek 是 OpenAI 兼容接口，用 ChatOpenAI 指 base_url 即可。
  但必须显式禁用思考模式——ragas 自己发起调用，不会走项目的
  `chat_completion`（那里统一加了 thinking disabled），
  不禁用的话每次 judge 都带一长段推理，又慢又容易把输出格式带歪。
- Embeddings：AnswerRelevancy 需要 embedding。**复用** hybrid_retriever 里
  已加载的 bge-m3 实例，不新建——6GB 显存容不下第二份（见台账 P3）。
"""
import sys
import types


def patch_missing_langchain_modules() -> None:
    """注册 LangChain 1.x 已移除、但 ragas 仍在 import 的占位模块"""
    stubs = {
        "langchain_community.chat_models.vertexai": ["ChatVertexAI"],
        "langchain_community.chat_models.anyscale": ["ChatAnyscale"],
        "langchain_community.chat_models.bedrock": ["BedrockChat"],
        "langchain_community.chat_models.llamacpp": ["LlamaCpp"],
        "langchain_community.chat_models.tongyi": ["ChatTongyi"],
        "langchain_community.llms.vertexai": ["VertexAI"],
        "langchain_community.llms.llamacpp": ["LlamaCpp"],
    }
    for mod_name, attrs in stubs.items():
        if mod_name in sys.modules:
            continue
        mod = types.ModuleType(mod_name)
        for a in attrs:
            setattr(mod, a, type(a, (), {}))
        sys.modules[mod_name] = mod
        if "." in mod_name:
            parent_name, child = mod_name.rsplit(".", 1)
            parent = sys.modules.get(parent_name)
            if parent is not None:
                setattr(parent, child, mod)


def build_ragas_llm():
    """DeepSeek -> ragas 可用的 wrapper（思考模式已禁用）"""
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    from rag_demo.generation.generator import API_KEY, BASE_URL, MODEL

    chat = ChatOpenAI(
        model=MODEL,
        api_key=API_KEY or "EMPTY",
        base_url=BASE_URL,
        temperature=0.0,
        # ragas 不会经过项目的 chat_completion，思考模式必须在这里关，
        # 否则 judge 调用会先吐一大段推理（P9 记录过：耗时差一个数量级）
        model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
    )
    return LangchainLLMWrapper(chat)


def build_ragas_embeddings():
    """复用已加载的 bge-m3 实例，供 AnswerRelevancy 使用"""
    from langchain_core.embeddings import Embeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    from rag_demo.retrieval.hybrid_retriever import get_model

    class _ProjectEmbeddings(Embeddings):
        """
        把项目里常驻的 bge-m3 包成 LangChain Embeddings 协议

        ⚠️ `model` 必须是**字符串**：ragas 会读它当作模型标识去构造
        EmbeddingUsageEvent，直接挂 SentenceTransformer 实例会 pydantic
        校验失败（实测报 "Input should be a valid string"），
        表现为 answer_relevancy 整列 NaN。实例另存 `_st`。
        """

        model = "bge-m3"

        def __init__(self):
            self._st = get_model()

        def embed_documents(self, texts):
            return [v.tolist() for v in self._st.encode(list(texts))]

        def embed_query(self, text):
            return self._st.encode(text).tolist()

    return LangchainEmbeddingsWrapper(_ProjectEmbeddings())
