#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : bert_intent.py
@Function: 意图二分类（闲聊 / 业务）的 BERT 推理封装

为什么需要它
------------
入口层的闲聊判断原本是关键词规则（router.py），规则拦不住「闰年是怎么回事」
「口红哪个色号好看」这类没有寒暄词、但同样与业务无关的问题。这类漏判会继续走
「多路规划 LLM(3.8s) + 检索(0.5s) + 答案生成(20.9s)」，为拦一句话付约 25s
（耗时口径见 bug/10.14/2026-10-14_性能逐模块计时与方案A实验.md）。

换成 102M 的 BERT 分类器后，判定在本地完成（fp16 约 0.2GB 显存、单条约 13ms），
既不用付 LLM 往返，也不再依赖词表覆盖。三种方案（规则 / BERT / 规则短路+BERT 兜底）
的准确率与延迟对比见 bug/bert意图路由替换-延迟与准确率对比.md。

⚠ 两个必须知道的约束
--------------------
1. **必须在服务启动时 preload()**，不要等第一个请求懒加载。
   实测（2026-10-15，api/main.py lifespan 里有完整记录）：请求期间首次加载模型
   会拿到「半转换的 fp16 模型」（权重 fp16 / 输入 fp32），首次 forward 抛
   `mat1 and mat2 must have the same dtype`，且该进程此后**每次**调用都失败，
   重启才恢复。触发条件是「加载时还有其他 CUDA 活动」（请求里的 embed 编码、
   或后台稀疏预热线程），所以加载必须和 get_model 那批放一起。

2. **模型目录不入库**（bert_query_classify/models/ 在 .gitignore 里）。
   缺失时 `predict()` 返回 None，由 router 回退关键词规则，服务照常可用。
   加载失败只记一次日志并**缓存失败结果**：重试必然失败，却要为每个请求白付
   约 1s 的加载尝试——那比漏判本身更糟。

推理只做「取概率」，不在这里做阈值判断：阈值属于路由策略（config.INTENT_CHITCHAT_THRESHOLD），
放在这里会让「调阈值」变成「改模型代码」。
"""
import logging
import os
import threading

from rag_demo import config

logger = logging.getLogger(__name__)

LABEL_CHITCHAT = "CHITCHAT"
LABEL_BUSINESS = "BUSINESS"

# 进程级单例。加锁是因为 FastAPI 的同步接口跑在线程池里，首个并发请求会同时进加载。
_lock = threading.Lock()
_tokenizer = None
_model = None
_chitchat_index: int | None = None
_load_error: str | None = None
_load_sec: float | None = None


def _resolve_chitchat_index(id2label: dict | None) -> int:
    """
    从模型 config 里读出「闲聊」是第几个 logits 下标

    训练脚本把 id2label 写进了 config.json（bert_query_classify/train.py），下游
    就该读它，而不是硬编码 0——硬编码一旦和训练侧不一致，表现是「意图判反」，
    不报错，线上极难查。
    """
    for idx, name in (id2label or {}).items():
        if str(name).upper() == LABEL_CHITCHAT:
            return int(idx)
    logger.warning("模型 config 缺少 id2label（或未含 %s），回退按下标 0 处理", LABEL_CHITCHAT)
    return 0


def load(device: str | None = None, dtype=None, force: bool = False):
    """
    加载 tokenizer + 模型（进程级单例）

    返回 (tokenizer, model)；不可用时返回 None。device / dtype 默认取 config，
    传参只是为了离线实验（例如同机对比 cuda 与 cpu 的延迟）。
    """
    global _tokenizer, _model, _chitchat_index, _load_error, _load_sec

    if force:
        with _lock:
            _tokenizer = _model = None
            _chitchat_index = None
            _load_error = None

    if _model is not None:
        return _tokenizer, _model
    if _load_error is not None:
        return None

    with _lock:
        if _model is not None:
            return _tokenizer, _model
        if _load_error is not None:
            return None

        path = config.INTENT_MODEL_PATH
        if not os.path.isfile(os.path.join(path, "config.json")):
            _load_error = f"模型目录不存在或不完整: {path}"
            logger.warning(
                "意图分类模型不可用（%s）——本次进程回退关键词规则路由。"
                "如需 BERT 路由请先跑 bert_query_classify/train.py",
                _load_error,
            )
            return None

        import time

        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        resolved_device = device or config.DEVICE
        resolved_dtype = config.DTYPE if dtype is None else dtype
        t0 = time.perf_counter()
        try:
            tokenizer = AutoTokenizer.from_pretrained(path)
            model = AutoModelForSequenceClassification.from_pretrained(
                path,
                # 与检索侧同因：cuda 下 fp16 省显存（102M 模型约 0.2GB），
                # cpu 下必须 fp32（fp16 算子在 CPU 上不可用）
                dtype=resolved_dtype,
            )
            model.to(resolved_device)
            model.eval()
        except Exception as e:  # noqa: BLE001
            _load_error = f"{type(e).__name__}: {e}"
            logger.warning("意图分类模型加载失败，回退关键词规则路由: %s", _load_error)
            return None

        _tokenizer, _model = tokenizer, model
        _chitchat_index = _resolve_chitchat_index(model.config.id2label)
        _load_sec = time.perf_counter() - t0
        logger.info(
            "意图分类模型已加载: %s（device=%s, dtype=%s, CHITCHAT 下标=%d, 耗时 %.2fs）",
            path, resolved_device, resolved_dtype, _chitchat_index, _load_sec,
        )
        return _tokenizer, _model


def preload() -> bool:
    """
    服务启动时预热。返回是否可用——不可用不抛异常：路由会回退规则，
    没有理由让整个服务起不来（闲聊判定是优化项，不是功能依赖）。
    """
    return load() is not None


def is_ready() -> bool:
    return _model is not None


def load_info() -> dict:
    """加载状态（供日志 / 健康检查 / 实验脚本）"""
    return {
        "ready": _model is not None,
        "model_path": config.INTENT_MODEL_PATH,
        "device": config.DEVICE,
        "chitchat_index": _chitchat_index,
        "load_sec": _load_sec,
        "error": _load_error,
    }


def predict(texts: list[str], batch_size: int = 32, device: str | None = None):
    """
    批量推理，返回与输入等长的 list[dict]（含 label / p_chitchat / p_business）

    模型不可用时返回 None——调用方必须处理 None（回退），不要在这里偷偷返回
    「都判业务」之类的默认值：那会把「模型没加载」伪装成「模型判了业务」。
    """
    payload = load(device=device)
    if payload is None:
        return None
    tokenizer, model = payload

    import torch

    out: list[dict] = []
    for i in range(0, len(texts), batch_size):
        batch = [t or "" for t in texts[i:i + batch_size]]
        enc = tokenizer(
            batch,
            truncation=True,
            max_length=config.INTENT_MAX_LENGTH,
            padding=True,
            return_tensors="pt",
        )
        enc = {k: v.to(model.device) for k, v in enc.items()}
        with torch.inference_mode():
            logits = model(**enc).logits
        # logits 在 fp16 下直接 softmax 会有精度损失（且极值容易溢出），先升 fp32
        probs = torch.softmax(logits.float(), dim=-1).cpu()
        for row in probs:
            p_chitchat = float(row[_chitchat_index])
            p_business = float(row[1 - _chitchat_index]) if row.numel() == 2 else None
            out.append({
                "label": LABEL_CHITCHAT if p_chitchat >= 0.5 else LABEL_BUSINESS,
                "p_chitchat": p_chitchat,
                "p_business": p_business,
            })
    return out


def chitchat_prob(question: str) -> float | None:
    """单条：返回 P(闲聊)；模型不可用返回 None（调用方回退）"""
    if not question:
        return None
    res = predict([question], batch_size=1)
    return None if res is None else res[0]["p_chitchat"]
