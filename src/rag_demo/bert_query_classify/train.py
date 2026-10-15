#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 4：BERT 意图二分类微调（全量微调，不用 LoRA）

- 模型从**本地目录**加载，不联网：models/bert-base-chinese
- 训练前先做显存体检（gpu_monitor.preflight_check），不够直接中止
- 全程用 GPUMonitor 采样显存，训练后落 outputs/gpu_memory.csv

关于 warmup：任务给的是 warmup_ratio=0.1，但 transformers 5.x 的 TrainingArguments
已经**移除**了 warmup_ratio（只剩 warmup_steps）。所以这里按
  warmup_steps = round(0.1 × 总步数)
显式换算，语义与 warmup_ratio=0.1 等价。

独立运行：uv run python src/rag_demo/bert_query_classify/train.py
"""
import json
import os
import random
import shutil
import sys
import warnings

import numpy as np
import torch
from datasets import Dataset
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainerCallback,
    TrainingArguments,
)

from gpu_monitor import GPUMonitor, preflight_check

warnings.filterwarnings("ignore", message=".*pynvml package is deprecated.*")

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, "..", "..", ".."))
MODEL_PATH = os.path.join(ROOT, "models", "bert-base-chinese")
DATA = os.path.join(BASE, "data")
OUT_DIR = os.path.join(BASE, "outputs")
SAVE_DIR = os.path.join(BASE, "models", "bert-intent")
CKPT_DIR = os.path.join(OUT_DIR, "trainer_ckpt")

TRAIN_JSONL = os.path.join(DATA, "train.jsonl")
VAL_JSONL = os.path.join(DATA, "val.jsonl")
TRAIN_LOG = os.path.join(OUT_DIR, "train_log.txt")
EVAL_JSON = os.path.join(OUT_DIR, "eval_results.json")
GPU_CSV = os.path.join(OUT_DIR, "gpu_memory.csv")

LABEL_MAP = {"CHITCHAT": 0, "BUSINESS": 1}
ID2LABEL = {v: k for k, v in LABEL_MAP.items()}
MAX_LENGTH = 64
SEED = 42


class FileLogCallback(TrainerCallback):
    """把 Trainer 的日志逐条追加进 train_log.txt（JSONL），便于事后核对"""

    def __init__(self, path: str):
        self.path = path

    def on_log(self, args, state, control, logs=None, **kwargs):
        if not logs:
            return
        rec = {"step": state.global_step, "epoch": state.epoch, **logs}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def build_dataset(path: str, tokenizer) -> Dataset:
    rows = load_jsonl(path)
    ds = Dataset.from_dict({
        "text": [r["query"] for r in rows],
        "label": [LABEL_MAP[r["label"]] for r in rows],
    })

    def tokenize(batch):
        return tokenizer(batch["text"], truncation=True, max_length=MAX_LENGTH)

    ds = ds.map(tokenize, batched=True, remove_columns=["text"])
    return ds


def compute_metrics(eval_pred):
    """
    指标：accuracy + 两类别各自的 precision / recall / f1 + macro 平均

    `f1` 这个键必须存在——TrainingArguments 的 metric_for_best_model="f1"
    按名字取，取不到会静默退化成 loss 比较，那就选错模型了。
    这里 f1 = macro F1（两类同等重要，而不是被多数类带偏）。
    """
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    p, r, f, _ = precision_recall_fscore_support(
        labels, preds, labels=[0, 1], zero_division=0
    )
    return {
        "accuracy": float(accuracy_score(labels, preds)),
        "precision_chitchat": float(p[0]),
        "recall_chitchat": float(r[0]),
        "f1_chitchat": float(f[0]),
        "precision_business": float(p[1]),
        "recall_business": float(r[1]),
        "f1_business": float(f[1]),
        "precision_macro": float(np.mean(p)),
        "recall_macro": float(np.mean(r)),
        "f1": float(np.mean(f)),
    }


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(SAVE_DIR, exist_ok=True)
    set_seed(SEED)

    print("=" * 78)
    print("步骤 3-5：BERT 意图二分类微调 + 显存监控")
    print("=" * 78)
    print(f"模型（本地加载）: {MODEL_PATH}")
    for f in ("config.json", "vocab.txt", "tokenizer.json"):
        p = os.path.join(MODEL_PATH, f)
        print(f"  {'✓' if os.path.exists(p) else '✗'} {f}")
    if not os.path.exists(os.path.join(MODEL_PATH, "config.json")):
        sys.exit(f"[fatal] 本地模型目录不完整：{MODEL_PATH}")

    # ---------- 训练前显存体检（不够直接退出，不白跑） ----------
    pf = preflight_check()

    print(f"\n加载 tokenizer / 模型（num_labels=2）...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH, num_labels=2)
    n_param = sum(p.numel() for p in model.parameters())
    print(f"  参数量 {n_param / 1e6:.1f}M（全量微调，可训练 "
          f"{sum(p.numel() for p in model.parameters() if p.requires_grad) / 1e6:.1f}M）")

    ds_train = build_dataset(TRAIN_JSONL, tokenizer)
    ds_val = build_dataset(VAL_JSONL, tokenizer)
    print(f"  train {len(ds_train)} 条 / val {len(ds_val)} 条；"
          f"max_length={MAX_LENGTH}，动态 padding")

    # ---------- 训练参数 ----------
    bs, accum, epochs = 16, 1, 3
    steps_per_epoch = -(-len(ds_train) // (bs * accum))
    total_steps = steps_per_epoch * epochs
    warmup_steps = round(0.1 * total_steps)   # 等价于 warmup_ratio=0.1

    args = TrainingArguments(
        output_dir=CKPT_DIR,
        learning_rate=2e-5,
        per_device_train_batch_size=bs,
        per_device_eval_batch_size=32,
        gradient_accumulation_steps=accum,
        num_train_epochs=epochs,
        warmup_steps=warmup_steps,
        weight_decay=0.01,
        fp16=True,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        logging_steps=10,
        logging_first_step=True,
        seed=SEED,
        data_seed=SEED,
        report_to="none",
        dataloader_num_workers=0,
    )
    print(f"\n训练配置：lr=2e-5 bs={bs}×{accum} epochs={epochs} fp16=True")
    print(f"  steps/epoch={steps_per_epoch} total_steps={total_steps} "
          f"warmup_steps={warmup_steps}（= 0.1 × {total_steps}，"
          f"transformers 5.x 已移除 warmup_ratio，故显式换算）")

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ds_train,
        eval_dataset=ds_val,
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
        processing_class=tokenizer,
        callbacks=[FileLogCallback(TRAIN_LOG)],
    )

    # ---------- 训练（全程显存监控）----------
    with open(TRAIN_LOG, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "event": "start", "model_path": MODEL_PATH,
            "train_size": len(ds_train), "val_size": len(ds_val),
            "max_length": MAX_LENGTH, "seed": SEED,
            "hyperparams": {
                "learning_rate": 2e-5, "per_device_train_batch_size": bs,
                "per_device_eval_batch_size": 32,
                "gradient_accumulation_steps": accum, "num_train_epochs": epochs,
                "warmup_steps": warmup_steps, "total_steps": total_steps,
                "weight_decay": 0.01, "fp16": True, "metric_for_best_model": "f1",
            },
            "preflight": pf,
        }, ensure_ascii=False) + "\n")

    monitor = GPUMonitor(interval=0.5, output_csv=GPU_CSV)
    monitor.start()
    try:
        trainer.train()
    except torch.cuda.OutOfMemoryError:
        monitor.stop()
        print("\n[fatal] CUDA OOM。按下面顺序降级后重跑：")
        print("  1) per_device_train_batch_size 16 -> 8，并加 gradient_accumulation_steps=2")
        print("  2) per_device_train_batch_size 再降到 4")
        print("  另外确认 uvicorn / RAG 服务已停（bge-m3 + bge-reranker 约占 4.2GB）")
        raise
    finally:
        if monitor._thread and monitor._thread.is_alive():
            monitor.stop()

    summary = monitor.summary()
    print("\n" + "-" * 78)
    print("显存监控汇总")
    print("-" * 78)
    print(f"  平均显存: {summary['avg_mb']:.1f} MB")
    print(f"  峰值显存: {summary['peak_mb']:.1f} MB")
    print(f"  最低显存: {summary['min_mb']:.1f} MB")
    print(f"  训练时长: {summary['duration_sec']:.1f} 秒")
    print(f"  采样点数: {summary['samples']}（间隔 0.5s，失败 {summary['errors']} 次）")
    print(f"  平均利用率: {summary['avg_utilization']:.1f}%"
          f"（峰值 {summary['peak_utilization']:.1f}%）")
    print(f"  CSV: {GPU_CSV}")

    # ---------- 保存 ----------
    # 把标签映射写进 config.json。
    # 不写的话保存下来的 config 里没有 num_labels / id2label，下游
    # from_pretrained() 得到的是 LABEL_0 / LABEL_1，RAG 入口层只能靠
    # 「约定了下标 0 是闲聊」来翻译——这种隐式约定正是线上最容易踩的坑，
    # 而且踩了之后表现是「意图判反」，不报错，很难查。
    model.config.num_labels = 2
    model.config.id2label = ID2LABEL
    model.config.label2id = LABEL_MAP
    trainer.save_model(SAVE_DIR)
    tokenizer.save_pretrained(SAVE_DIR)
    print(f"\n模型已保存：{SAVE_DIR}")
    for f in sorted(os.listdir(SAVE_DIR)):
        p = os.path.join(SAVE_DIR, f)
        if os.path.isfile(p):
            print(f"  {f}  ({os.path.getsize(p) / 1024 ** 2:.1f} MB)")

    # 清理 Trainer 检查点：load_best_model_at_end=True 已在 save_model 之前把最优权重
    # 装进当前模型，checkpoint 目录只剩磁盘占用（save_total_limit=2，约 800MB）。
    if os.path.isdir(CKPT_DIR):
        n_ckpt = len([d for d in os.listdir(CKPT_DIR) if d.startswith("checkpoint-")])
        shutil.rmtree(CKPT_DIR, ignore_errors=True)
        print(f"已清理训练检查点 {n_ckpt} 个（{CKPT_DIR}）")

    history = trainer.state.log_history
    evals = [h for h in history if "eval_f1" in h]
    print("\n各 epoch 验证集结果：")
    print(f"  {'epoch':>6}{'loss':>9}{'acc':>9}{'f1(macro)':>11}"
          f"{'P_闲聊':>9}{'R_闲聊':>9}{'P_业务':>9}{'R_业务':>9}")
    for h in evals:
        print(f"  {h.get('epoch', 0):>6.0f}{h.get('eval_loss', 0):>9.4f}"
              f"{h.get('eval_accuracy', 0):>9.4f}{h.get('eval_f1', 0):>11.4f}"
              f"{h.get('eval_precision_chitchat', 0):>9.3f}"
              f"{h.get('eval_recall_chitchat', 0):>9.3f}"
              f"{h.get('eval_precision_business', 0):>9.3f}"
              f"{h.get('eval_recall_business', 0):>9.3f}")

    result = {
        "model_path": MODEL_PATH, "save_dir": SAVE_DIR,
        "num_params_million": round(n_param / 1e6, 2),
        "train_size": len(ds_train), "val_size": len(ds_val),
        "label_map": LABEL_MAP, "max_length": MAX_LENGTH, "seed": SEED,
        "hyperparams": {
            "learning_rate": 2e-5, "per_device_train_batch_size": bs,
            "per_device_eval_batch_size": 32,
            "gradient_accumulation_steps": accum, "num_train_epochs": epochs,
            "warmup_steps": warmup_steps, "warmup_ratio_equivalent": 0.1,
            "total_steps": total_steps, "weight_decay": 0.01, "fp16": True,
            "eval_strategy": "epoch", "save_strategy": "epoch",
            "load_best_model_at_end": True, "metric_for_best_model": "f1",
            "logging_steps": 10, "report_to": "none",
        },
        "preflight": pf,
        "gpu_monitor": summary,
        "epoch_eval_results": evals,
        "log_history": history,
        "best_model_checkpoint": trainer.state.best_model_checkpoint,
        "best_metric": trainer.state.best_metric,
    }
    with open(EVAL_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n评估结果已写入：{EVAL_JSON}")
    print(f"训练日志已写入：{TRAIN_LOG}")
    print("=" * 78)


if __name__ == "__main__":
    main()
