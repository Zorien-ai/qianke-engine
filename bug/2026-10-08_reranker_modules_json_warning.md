# reranker 加载警告：No modules.json found

**日期**：2026-10-08
**严重度**：🟢 低（不阻塞，当前结果正确）
**状态**：观察中，暂不处理

## 现象

加载 `models/bge-reranker-v2-m3` 时日志出现：

```text
INFO:sentence_transformers.base.model:No modules.json found for F:\workspace\python\qianke-engine\models\bge-reranker-v2-m3, initializing a new CrossEncoder model.
```

## 原因

ModelScope 下载的 `BAAI/bge-reranker-v2-m3` 仓库**不包含 `modules.json`**。

该文件用于告诉 sentence-transformers 模型由哪些子模块组成（Transformer + Pooling 等）以及顺序。缺失时无法按清单组装，只能 fallback 到「初始化一个新的 CrossEncoder」，套用默认的 pooling 逻辑。

## 影响

- 当前**结果正确**：rerank 分数分布合理（相关文档 0.87~0.94，非相关明显偏低）
- 但这是**隐式依赖**：默认 pooling 逻辑由 sentence-transformers 版本决定，升级版本后行为可能变化
- 属于「现在能跑，但不能假设永远能跑」

## 处理方式

暂不处理，理由：

1. Demo 阶段不阻塞业务
2. 手动补 `modules.json` 有风险——格式或字段不匹配会导致加载**直接失败**，比现在的 warning 更糟
3. 官方 HuggingFace 仓库 `BAAI/bge-reranker-v2-m3` 是带 `modules.json` 的，真要解决时从 HF 重下一份即可

## 触发复查的条件

- 升级 `sentence-transformers` 版本时
- rerank 分数分布出现异常（例如所有候选分数趋同、排序失去区分度）
- 更换 reranker 模型时

## 记录时的环境

| 项 | 版本 / 值 |
|---|---|
| sentence-transformers | 6.1.0 |
| transformers | 5.19.0 |
| torch | 2.14.1 |
| 设备 | cpu |
| 模型来源 | ModelScope `BAAI/bge-reranker-v2-m3` |
