# BERT 意图分类模型训练记录

**日期**：2026-10-16
**状态**：已完成（可复现）
**代码目录**：`src/rag_demo/bert_query_classify/`
**模型产物**：`src/rag_demo/bert_query_classify/models/bert-intent/`（不入库）
**基座模型**：`models/bert-base-chinese`（本地加载，不联网，不入库）

## 1. 任务与结论速览

用 BERT-base 做 **CHITCHAT / BUSINESS 二分类**，替代原有的关键词规则路由。

| 项目 | 结果 |
|---|---|
| 训练集 / 验证集 / 测试集 | 2169 / 271 / 272 |
| 验证集（3 epoch） | acc 1.0，macro F1 1.0（第 1 个 epoch 即满分） |
| 测试集（同分布 hold-out） | acc **99.63%**（271/272），macro F1 **0.9963** |
| 短业务探针（30 条，分布外） | **93.3%**（28/30） |
| 长业务探针（25 条，分布外） | **100%**（25/25，但见 §6 的水分说明） |
| 训练显存（整卡口径） | 峰值 **2950.8 MB** / 均值 2929.3 MB（RTX 3060 Laptop 6GB） |
| 训练耗时 | 56.2 s（3 epoch，408 step） |
| 推理速度 | 单条 13.73 ms；batch32 0.971 ms/条（14.15× 加速） |

**一句话结论**：指标已经饱和到「测试集分辨不出模型好坏」的程度，真正的评估信号在短探针的 93.3% 与置信度分布上；显存占用远低于 6GB 上限，瓶颈不是显存。

## 2. 数据准备

### 2.1 数据来源与清洗

| 阶段 | 条数 | 说明 |
|---|---|---|
| 原始 `data/1.jsonl` | 2197 | 只读不改 |
| LLM 补充 `chitchat_generated.jsonl` | 300 | 长句闲聊（步骤 2.1） |
| LLM 补充 `chitchat_medium_generated.jsonl` | 250 | 中段闲聊（步骤 2.7） |
| LLM 补充 `business_generated.jsonl` | 342 | 短/中长/长句业务（步骤 2.7） |
| 合计 raw | 3089 | — |
| 丢弃：纯标点/无实义 | -14 | — |
| 丢弃：重复（含标点/空格变体） | -363 | 归一化后重复更严重（376 条） |
| **清洗后 `cleaned.jsonl`** | **2712** | CHITCHAT 1341 / BUSINESS 1371（比例 1.02），无标签冲突 |

清洗后长度：min 1 / max 22 / mean 8.98 / p50 8 / p95 19。

**为什么保留下限（1 字样本）**：线上真实存在「好 / 赞 / 在」这类单字 query，且把它们留在 CHITCHAT 里能削弱「短 = 闲聊」的伪关联。脚本里 `MAX_LEN=100` 只截上限，下限明确不剔除（保留 25 条短路样本）。

### 2.2 长度偏置治理（本次数据工作的核心）

初始数据里 CHITCHAT 集中在 2–4 字（"你好 / 在吗"），BUSINESS 是 9.3 字均值的中长术语，模型极易学到 **「短 = 闲聊」** 这条捷径。而只补长句业务，只是把偏置换方向变成「中长 = 业务」。

因此按「**没有任何长度桶被单一类别垄断**」为目标，四档一起补：

| 补充任务 | 长度区间 | 目标条数 | 修掉的偏置 |
|---|---|---|---|
| `business_short23` | 2–3 字 | 90 | 1–3 字业务零样本 |
| `business_short` | 2–4 字 | 150 | 补充极简业务输入 |
| `business_midlong` | 16–18 字 | 60 | 16–18 字业务稀疏 |
| `business_long` | 19–26 字 | 90 | 19+ 字业务零样本 |
| `chitchat_medium` | 8–16 字 | 250 | 7–12 字闲聊稀疏 |

两个已记录的坑：

1. `business_short` 区间写 2–4 字，实测模型绝大多数给 4 字，1–3 字桶只补进 37 条、少数类占比 13.3% 不达标 —— 所以另开 `business_short23` 把 2–3 字区间单独掐死，避免「区间给了但实际全落在同一头」。
2. **字数合规 ≠ 样本可用**。模型为凑字数会生造「沉睡户 / 积分余 / 渠道单 / 按品类分」这类词，入选前必须过一遍 LLM 质检（`judge_natural`）—— 这些词一旦进训练集，等于教模型学习不存在的词汇分布。

最终各长度桶少数类占比 0.26 ~ 0.42，全部 `pass`，长度对称性成立。

### 2.3 划分与探针集

分层抽样，`seed=42`，train 80% / val 10% / test 10%：

| 集合 | n | CHITCHAT | BUSINESS | 平均长度 |
|---|---|---|---|---|
| train | 2169 | 1073 | 1096 | 8.98 |
| val | 271 | 133 | 138 | 9.01 |
| test | 272 | 135 | 137 | 8.95 |

两端**分布外探针**（刻意不参与训练，`probes.py` 清单同时被 `gen_supplement.py` 用于排除）：

| 探针集 | n | 长度 | 类型 | 用途 |
|---|---|---|---|---|
| `short_business_test.jsonl` | 30 | 2–6 字（均值 3.6） | fragment 21 / unseen 9 | 抓「短 = 闲聊」捷径 |
| `long_business_test.jsonl` | 25 | 19–22 字（均值 20.72） | unseen 25 | 抓「长 = 闲聊」捷径 |

长度这条捷径有两个方向，普通测试集无法分别定位，必须把长/短业务各自单独拎出来打分才看得见。

## 3. 训练配置

| 项 | 值 |
|---|---|
| 基座 | `models/bert-base-chinese`（102.27M 参数，全量微调，不用 LoRA） |
| 头 | `num_labels=2`，`CHITCHAT=0 / BUSINESS=1` |
| max_length | 64（动态 padding） |
| learning_rate | 2e-5 |
| batch | train 16 / eval 32，`gradient_accumulation_steps=1` |
| epochs | 3（`total_steps = 408`） |
| warmup_steps | 41（= 0.1 × 408） |
| weight_decay | 0.01 |
| 精度 | fp16 |
| 选模 | `metric_for_best_model="f1"`，`load_best_model_at_end=True` |
| seed | 42（python/numpy/torch/cuda 全设） |
| 实际耗时 | 56.17 s，115.8 samples/s，7.26 steps/s，train_loss 0.0693 |

**两个必须解释的实现点**：

1. **`warmup_ratio` 已经不存在**。任务给的是 `warmup_ratio=0.1`，但 transformers 5.x 的 `TrainingArguments` 已移除该参数（只剩 `warmup_steps`），所以显式换算 `warmup_steps = round(0.1 × total_steps) = 41`，语义等价。
2. **标签映射写进 `config.json`**。训练完手动写 `num_labels / id2label / label2id` 再 `save_model`。不写的话保存下来的 config 没有这两个字段，下游 `from_pretrained()` 拿到的是 `LABEL_0 / LABEL_1`，RAG 入口层只能靠「约定了下标 0 是闲聊」翻译 —— 这种隐式约定踩了之后表现是「意图判反」，不报错，极难查。
3. **`f1` 这个键必须存在**：`metric_for_best_model="f1"` 是按名字取的，取不到会**静默退化成按 loss 比较**，那就选错模型了。这里 `f1` 定义为 **macro F1**（两类同等重要，不被多数类带偏）。
4. 训练结束后清理 `outputs/trainer_ckpt`（`load_best_model_at_end` 已把最优权重装进当前模型，checkpoint 只剩磁盘占用，约 800MB）。

## 4. 显存占用实测

显卡：`NVIDIA GeForce RTX 3060 Laptop GPU`，整卡 6144 MB

### 4.1 训练前体检（不足直接中止，不白跑）

| 项 | 值 |
|---|---|
| 已占用 | 932.1 MB |
| 空闲 | 5211.9 MB |
| 本次训练需要 | 2600 MB |
| 余量 | +2611.9 MB |
| 判定 | ✓ 可以开训 |

显存账（fp16 全量微调）：模型权重 0.6 GB + Adam 状态 1.2 GB + 激活 0.3 GB ≈ **2.1 GB**，另留碎片余量按 2600 MB 要求。

### 4.2 训练期间采样（0.5 s 间隔，115 个点）

| 指标 | 值 |
|---|---|
| 平均显存 | 2929.3 MB |
| **峰值显存** | **2950.8 MB** |
| p95 | 2950.8 MB |
| 最低 | 1472.8 MB |
| 采样时长 | 57.39 s |
| 平均利用率 | 32.5%（峰值 54.0%） |
| 采样失败 | 0 次 |

图表产物：`outputs/gpu_memory_curve.png`（时间曲线）、`outputs/gpu_memory_summary.png`（汇总）、`outputs/gpu_utilization_curve.png`（利用率）、`outputs/gpu_memory.csv`（原始采样）。

### 4.3 口径说明（重要，别误读）

- 这里统计的是 **NVML 整卡 `used`**（`pynvml.nvmlDeviceGetMemoryInfo`），**不是** `torch.cuda.max_memory_allocated()`。它含桌面/浏览器等约 1 GB 基线，所以「训练进程实际占用」≈ 峰值 2950.8 − 基线 932 ≈ **2.0 GB**，与 §4.1 的 2.1 GB 估算吻合。
- `min_mb=1472.8` 是**采样起点**（`monitor.start()` 早于 `trainer.train()`，含权重加载的爬升段），不是训练稳态，不要当作「训练时只用 1.4GB」。
- 利用率平均只有 32.5%：数据量小（2169 条、408 步），瓶颈在数据加载/调度而非算力，`dataloader_num_workers=0`。
- **训练前必须停掉 uvicorn / RAG 服务**：bge-m3 + bge-reranker 约占 4.2 GB，6GB 卡上同时跑必然 OOM。OOM 降级顺序：① bs 16→8 且 `gradient_accumulation_steps=2`；② bs 再降到 4。
- 目前只有 **单一配置（bs=16 / fp16 / 不累积）** 的一次记录，没有做 batch/精度/累积步数的显存对比矩阵。

## 5. 指标结果

### 5.1 各 epoch 验证集（271 条）

| epoch | eval_loss | acc | macro F1 | P_闲聊 | R_闲聊 | P_业务 | R_业务 |
|---|---|---|---|---|---|---|---|
| 1 | 0.00120 | 1.0000 | 1.0000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 2 | 0.00032 | 1.0000 | 1.0000 | 1.000 | 1.000 | 1.000 | 1.000 |
| 3 | 0.00021 | 1.0000 | 1.0000 | 1.000 | 1.000 | 1.000 | 1.000 |

三个 epoch F1 完全并列，按 `load_best_model_at_end` 取最后一个（epoch 3）。

### 5.2 测试集（272 条，同分布）

```text
              precision    recall  f1-score   support
    CHITCHAT     1.0000    0.9926    0.9963       135
    BUSINESS     0.9928    1.0000    0.9964       137
    accuracy                         0.9963       272
   macro avg     0.9964    0.9963    0.9963       272
```

混淆矩阵（行=真实，列=预测）：`[[134, 1], [0, 137]]`

- 准确率 271/272 = **99.63%**，95% CI [97.95%, 99.94%]
- **macro F1 = 0.9963**
- 唯一错误：「收到」（真实 CHITCHAT → 预测 BUSINESS，P(真实)=0.0164，2 字极短）

### 5.3 分布外探针

| 探针 | n | 正确 | 准确率 | 95% CI | 注意 |
|---|---|---|---|---|---|
| short | 30 | 28 | 93.33% | [78.7%, 98.2%] | 错例 2 条 |
| └ fragment | 21 | 20 | 95.24% | [77.3%, 99.2%] | — |
| └ unseen | 9 | 8 | 88.89% | [56.5%, 98.0%] | — |
| long | 25 | 25 | 100% | [86.7%, 100%] | 见 §6 水分说明 |

短探针错例（均含字母/数字 ID）：`U2765`、`看下GMV`

### 5.4 置信度分布

| 集合 | 平均最大概率 | p05 | 最低 | <0.6 | <0.7 | <0.9 |
|---|---|---|---|---|---|---|
| test | 0.9980 | 0.9978 | 0.7098 | 0 | 0 | 1 |
| short | 0.9990 | 0.9941 | 0.9908 | 0 | 0 | 0 |
| long | 0.9891 | 0.9996 | 0.7330 | 0 | 0 | 1 |

- 分类别平均置信度（test）：CHITCHAT 0.9962 / BUSINESS 0.9997
- 最低的 test 样本是「闰年是怎么回事」（0.7098），仍判对
- **边界样本极少**（<0.9 仅 1 条），说明模型在测试分布上高度自信 —— 这是「数据同分布 + 任务简单」的特征，不代表线上鲁棒

### 5.5 逐长度桶（test）

| 桶 | n | acc | 说明 |
|---|---|---|---|
| 1-3 | 32 | 0.9688 | 唯一失分桶（就是「收到」） |
| 4-6 | 67 | 1.0 | — |
| 7-9 | 58 | 1.0 | — |
| 10-12 | 58 | 1.0 | — |
| 13-15 | 19 | 1.0 | — |
| 16-18 | 23 | 1.0 | — |
| 19-24 | 15 | 1.0 | — |

结论：模型**没有**按长度偷懒（否则短桶/长桶会塌），但这也可能是数据治理起效的结果，不能反推「长度特征无关」。

### 5.6 推理速度

| 项 | 值 |
|---|---|
| 单条 | 13.73 ms |
| batch32 总耗时 | 263.99 ms |
| batch32 单条 | 0.971 ms |
| 加速比 | 14.15× |
| device | cuda |

## 6. 关键发现与风险（这份记录最有价值的部分）

1. **验证集 F1 = 1.0 意味着评估集已经失效**。好模型、差模型、过拟合模型在这个集上都是 1.0，无法据此区分。test 集在这里只承担「确认没跑飞」的角色，不能当能力上限证据 —— `transformers` 选模也因此失去区分度（三个 epoch 完全并列）。
2. **短端是真实短板**：93.3%，错例都是「字母/数字 ID + 短文本」（`U2765`、`看下GMV`），训练集中同类样本极少。
3. **长端 100% 有水分**：双向词面重合度显示长探针与训练集重合偏高 ——

   | 探针 | n | 平均 p→t（探针词被训练集覆盖） | 平均 t→p（训练句被探针复现） | 词面全覆盖 | 最高整句相似(4-gram) |
   |---|---|---|---|---|---|
   | short | 30 | 0.9667 | 0.1274 | 28/30 | 0.40 |
   | long | 25 | 0.8892 | **0.6177** | 5/25 | 0.25 |

   长探针的 `t→p = 0.6177` 说明它复现了训练句的大量词汇（如「上个月流失预警名单…」对应训练集「流失预警」），所以「长端 100%」不能直接读作「长句泛化能力强」。
4. **缺高重合对照组**：没有任何探针落在「高重合（整句相似 ≥ 0.6）」组 —— 缺少对照组，**分组对比本身不成立**，`eval_report.json` 里已显式输出告警，不要据此做「高重合 vs 低重合」的结论。
5. **显存不是瓶颈**（峰值约 2.95GB 整卡 / 约 2.0GB 进程），但训练前不停 RAG 服务就会 OOM，这条检查成本收益比很高，必须保留。
6. **训练集规模小**（2169 条）+ 任务本身简单，是目前所有指标饱和的根因；继续加数据不如先补「难样本」（字母数字 ID、极短业务词）。

## 7. 复现步骤

```bash
# 1) 数据（gen_* 需要 LLM API，其余离线）
uv run python src/rag_demo/bert_query_classify/gen_chitchat.py       # 长句闲聊
uv run python src/rag_demo/bert_query_classify/gen_supplement.py     # 短业务/长业务/中段闲聊
uv run python src/rag_demo/bert_query_classify/analyze_data.py       # 清洗 + 分析
uv run python src/rag_demo/bert_query_classify/split_data.py         # 划分 + 两端探针

# 2) 训练（务必先停 uvicorn / RAG 服务）
uv run python src/rag_demo/bert_query_classify/train.py              # 含 preflight + 显存监控

# 3) 评估与绘图
uv run python src/rag_demo/bert_query_classify/evaluate.py
uv run python src/rag_demo/bert_query_classify/plot_gpu.py
```

产物清单：

| 文件 | 内容 |
|---|---|
| `outputs/train_log.txt` | 训练日志（JSONL，逐 step + 各 epoch 验证指标） |
| `outputs/eval_results.json` | 训练结果（超参、preflight、gpu_monitor、各 epoch、完整 log_history） |
| `outputs/gpu_memory.csv` | 显存原始采样（0.5s 间隔） |
| `outputs/gpu_memory_*.png` / `gpu_utilization_curve.png` | 显存与利用率图表 |
| `outputs/classification_report.txt` | 测试集分类报告 + 混淆矩阵 |
| `outputs/eval_report.json` | 完整评估结果（探针、置信度、重合度、长度桶、速度） |
| `outputs/error_analysis.txt` | 错误样本 + 低置信 Top20 归因 |
| `outputs/confusion_matrix.png` / `confidence_distribution.png` | 评估图表 |
| `outputs/split_summary.json` | 划分摘要 + 探针清单 |
| `outputs/data_analysis/analysis_report.json` | 数据清洗与长度对称性报告 |

## 8. 记录时的环境

| 项 | 版本 / 值 |
|---|---|
| 显卡 | NVIDIA GeForce RTX 3060 Laptop GPU（6144 MB） |
| Python | 3.12（`requires-python = ">=3.12,<3.13"`） |
| torch | 2.14.1+cu126（本地 wheel） |
| transformers | >= 5.19.0（已移除 `warmup_ratio`） |
| datasets / scikit-learn / pynvml | >= 5.1.0 / >= 1.9.1 / >= 13.0.1 |
| 操作系统 | Windows（win32） |
| 基座模型来源 | 本地 `models/bert-base-chinese`（不联网加载） |

## 9. 待办 / 下一步

- [ ] 用 `torch.cuda.max_memory_allocated()` 补记**纯进程显存**，消除整卡口径被误读的隐患
- [ ] 补一组 bs / 累积步数 / 精度的显存–耗时对比，让「6GB 能跑多大 batch」有数
- [ ] 补「高重合（整句相似 ≥ 0.6）」对照组探针，让 §6.3/6.4 的分组对比成立
- [ ] 针对短端短板补「字母/数字 ID + 极短业务词」难样本，重训后以**短探针准确率**作为验收指标（不看 test F1）
