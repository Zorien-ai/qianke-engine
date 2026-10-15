#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 5：GPU 显存监控

两个东西：
1. `GPUMonitor`  —— 训练过程中后台线程采样显存/利用率，落 CSV，给出 avg/peak/min
2. `preflight_check` —— **训练前**的显存体检

preflight 为什么要单独存在：6GB 卡上跑 RAG 服务（bge-m3 + bge-reranker 约 4.2GB）
时只剩不到 1GB，BERT 全量微调需要约 2.1GB，直接开训必然 OOM。OOM 有两种表现：
要么几十秒就炸（还好），要么进了训练循环后在第 N 步炸掉——后者等于白等，
而检查只要 30 秒。这条检查的成本收益比实在太划算，不能省。

独立运行（体检）：uv run python src/rag_demo/bert_query_classify/gpu_monitor.py
"""
import csv
import os
import sys
import threading
import time
import warnings
from datetime import datetime

warnings.filterwarnings("ignore", message=".*pynvml package is deprecated.*")

try:
    import pynvml
except ImportError as e:  # pragma: no cover
    print(f"[fatal] 缺少 pynvml：{e}\n        请执行 uv add pynvml")
    raise

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "outputs")


# ---------------------------------------------------------------------------
# 训练前显存体检
# ---------------------------------------------------------------------------
# BERT-base 全量微调 fp16 的显存账（6GB 卡）：
#   模型权重 fp16      约 0.6 GB
#   Adam 优化器状态    约 1.2 GB   （fp32 一阶+二阶动量，是权重 fp16 的 2 倍）
#   激活值 + batch     约 0.3 GB
#   合计              约 2.1 GB
# 再留一点碎片余量，按 2600MB 要求。
REQUIRED_FREE_MB = 2600.0


def preflight_check(required_mb: float = REQUIRED_FREE_MB, strict: bool = True) -> dict:
    """
    训练前检查显存是否够用；不够就**直接中止**并说清是谁占着。

    strict=True 时不足则 SystemExit(1)——宁可现在退出，也不要训练到一半 OOM。
    """
    pynvml.nvmlInit()
    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    info = pynvml.nvmlDeviceGetMemoryInfo(handle)
    total = info.total / 1024 ** 2
    used = info.used / 1024 ** 2
    free = info.free / 1024 ** 2
    name = pynvml.nvmlDeviceGetName(handle)
    if isinstance(name, bytes):
        name = name.decode()

    print("=" * 78)
    print("训练前显存体检")
    print("=" * 78)
    print(f"  显卡        {name}")
    print(f"  总显存      {total:8.0f} MB")
    print(f"  已占用      {used:8.0f} MB")
    print(f"  空闲        {free:8.0f} MB")
    print(f"  本次训练需要 {required_mb:8.0f} MB"
          f"（权重 600 + Adam 1200 + 激活 300，另留碎片余量）")
    print(f"  余量        {free - required_mb:+8.0f} MB")

    # 列出占用显存的进程，便于直接定位该停谁
    procs = []
    try:
        for p in (pynvml.nvmlDeviceGetComputeRunningProcesses(handle) or []):
            mb = (p.usedGpuMemory / 1024 ** 2) if getattr(p, "usedGpuMemory", None) else -1
            procs.append((p.pid, mb))
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 读取占用进程失败：{type(e).__name__}: {e}")
    ok = free >= required_mb
    if procs:
        # 只在「不够」时才列明细。
        # Windows WDDM 下 nvmlDeviceGetComputeRunningProcesses 会把所有持有 GPU 上下文
        # 的进程都报出来（桌面程序、浏览器都在内）且不给单进程显存，通过时刷 18 行纯噪音；
        # 不足时它才有价值——那时你要知道该停谁。
        if ok:
            print(f"\n  持有 GPU 上下文的进程 {len(procs)} 个（Windows 不提供单进程显存，"
                  f"需要明细用 nvidia-smi）")
        else:
            print("\n  当前持有 GPU 上下文的进程（pid，Windows 不提供单进程显存）：")
            for pid, _ in procs:
                print(f"    pid {pid}")

    print()
    if ok:
        print("  判定：✓ 显存充足，可以开训")
    else:
        print("  判定：✗ 显存不足，现在中止（避免训练到一半 OOM 白等）")
        print("        处理办法（按顺序试）：")
        print("          1. 停掉 uvicorn / RAG 服务，释放 bge-m3 与 bge-reranker")
        print("             （两者各约 2.1GB，停了通常就够了）")
        print("          2. per_device_train_batch_size 16 -> 8，并加 gradient_accumulation_steps=2")
        print("          3. per_device_train_batch_size 再降到 4")
    print("=" * 78)
    pynvml.nvmlShutdown()

    result = {"gpu": name, "total_mb": total, "used_mb": used, "free_mb": free,
              "required_mb": required_mb, "ok": ok,
              "processes": [{"pid": p, "used_mb": m} for p, m in procs]}
    if not ok and strict:
        sys.exit(1)
    return result


# ---------------------------------------------------------------------------
# 训练过程中的采样
# ---------------------------------------------------------------------------
class GPUMonitor:
    """后台线程按固定间隔采样显存与 GPU 利用率，训练结束后落 CSV 并给出汇总"""

    def __init__(self, interval: float = 0.5,
                 output_csv: str = os.path.join(OUT_DIR, "gpu_memory.csv")):
        pynvml.nvmlInit()
        self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        self.interval = interval
        self.output_csv = output_csv
        self.samples: list[dict] = []
        self.errors = 0
        self._stop = False
        self._thread: threading.Thread | None = None
        self._t0: float | None = None

    def _sample(self) -> None:
        while not self._stop:
            try:
                info = pynvml.nvmlDeviceGetMemoryInfo(self.handle)
                used_mb = info.used / 1024 ** 2
                total_mb = info.total / 1024 ** 2
                util = pynvml.nvmlDeviceGetUtilizationRates(self.handle).gpu
                self.samples.append({
                    "timestamp": datetime.now().isoformat(timespec="milliseconds"),
                    "elapsed_sec": round(time.time() - self._t0, 3),
                    "used_mb": round(used_mb, 1),
                    "total_mb": round(total_mb, 1),
                    "utilization": util,
                })
            except Exception:  # noqa: BLE001
                # 采样失败不能把训练带崩；只计数，最后在汇总里暴露出来
                self.errors += 1
                if self.errors > 20:
                    break
            time.sleep(self.interval)

    def start(self) -> None:
        self._stop = False
        self._t0 = time.time()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        if self._thread:
            self._thread.join(timeout=5)
        self._save()

    def _save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.output_csv)), exist_ok=True)
        with open(self.output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["timestamp", "elapsed_sec", "used_mb", "total_mb", "utilization"])
            writer.writeheader()
            writer.writerows(self.samples)

    def summary(self) -> dict:
        import numpy as np
        used = [s["used_mb"] for s in self.samples]
        util = [s["utilization"] for s in self.samples]
        if not used:
            return {"avg_mb": 0.0, "peak_mb": 0.0, "min_mb": 0.0, "samples": 0,
                    "duration_sec": 0.0, "avg_utilization": 0.0, "errors": self.errors}
        return {
            "avg_mb": float(np.mean(used)),
            "peak_mb": float(np.max(used)),
            "min_mb": float(np.min(used)),
            "p95_mb": float(np.percentile(used, 95)),
            "samples": len(used),
            "duration_sec": float(self.samples[-1]["elapsed_sec"]),
            "avg_utilization": float(np.mean(util)),
            "peak_utilization": float(np.max(util)),
            "errors": self.errors,
        }


if __name__ == "__main__":
    preflight_check()
