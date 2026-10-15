#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
步骤 5：显存监控图表生成

读 outputs/gpu_memory.csv（train.py 里 GPUMonitor 采样得到），画三张图：
  1. gpu_memory_curve.png       显存占用随时间变化（含平均线、峰值点标注）
  2. gpu_utilization_curve.png  GPU 利用率随时间变化
  3. gpu_memory_summary.png     平均 / 峰值 / 最低 汇总柱状图

独立运行：uv run python src/rag_demo/bert_query_classify/plot_gpu.py
"""
import csv
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "outputs")
CSV_PATH = os.path.join(OUT_DIR, "gpu_memory.csv")

plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False
DPI = 150
FIGSIZE = (12, 6)


def load_csv(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"[fatal] {path} 没有采样数据，训练是否真的跑起来了？")
    return {
        "elapsed": np.array([float(r["elapsed_sec"]) for r in rows]),
        "used": np.array([float(r["used_mb"]) for r in rows]),
        "total": np.array([float(r["total_mb"]) for r in rows]),
        "util": np.array([float(r["utilization"]) for r in rows]),
        "n": len(rows),
    }


def plot_memory_curve(d: dict) -> str:
    used, t = d["used"], d["elapsed"]
    avg, peak_i = float(np.mean(used)), int(np.argmax(used))

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(t, used, color="#4C9BE8", lw=1.2, label="显存占用")
    ax.fill_between(t, used, alpha=0.15, color="#4C9BE8")
    ax.axhline(avg, ls="--", lw=1.5, color="#F2994A", label=f"平均 {avg:.0f} MB")
    ax.plot(t[peak_i], used[peak_i], "o", color="#EB5757", ms=8, zorder=5)
    ax.annotate(f"峰值 {used[peak_i]:.0f} MB\n@ {t[peak_i]:.1f}s",
                xy=(t[peak_i], used[peak_i]),
                xytext=(12, -34), textcoords="offset points",
                fontsize=11, color="#EB5757",
                arrowprops=dict(arrowstyle="->", color="#EB5757", lw=1.2))
    ax.axhline(d["total"][0], ls=":", lw=1.2, color="gray",
               label=f"显卡总显存 {d['total'][0]:.0f} MB")
    ax.set_title("训练过程 GPU 显存占用曲线", fontsize=14)
    ax.set_xlabel("训练时间（秒）")
    ax.set_ylabel("显存占用（MB）")
    ax.set_ylim(0, d["total"][0] * 1.05)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    p = os.path.join(OUT_DIR, "gpu_memory_curve.png")
    fig.savefig(p, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return p


def plot_utilization_curve(d: dict) -> str:
    util, t = d["util"], d["elapsed"]
    avg = float(np.mean(util))

    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(t, util, color="#6FCF97", lw=1.2, label="GPU 利用率")
    ax.fill_between(t, util, alpha=0.15, color="#6FCF97")
    ax.axhline(avg, ls="--", lw=1.5, color="#F2994A", label=f"平均 {avg:.1f}%")
    ax.set_title("训练过程 GPU 利用率曲线", fontsize=14)
    ax.set_xlabel("训练时间（秒）")
    ax.set_ylabel("GPU 利用率（%）")
    ax.set_ylim(0, 105)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    p = os.path.join(OUT_DIR, "gpu_utilization_curve.png")
    fig.savefig(p, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return p


def plot_summary(d: dict) -> str:
    used = d["used"]
    avg, peak, low = float(np.mean(used)), float(np.max(used)), float(np.min(used))

    fig, ax = plt.subplots(figsize=FIGSIZE)
    labels = ["平均", "峰值", "最低"]
    vals = [avg, peak, low]
    bars = ax.bar(labels, vals, color=["#4C9BE8", "#EB5757", "#6FCF97"], width=0.5)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.0f} MB",
                ha="center", va="bottom", fontsize=12)
    ax.axhline(d["total"][0], ls=":", lw=1.2, color="gray",
               label=f"显卡总显存 {d['total'][0]:.0f} MB")
    ax.text(0.02, 0.95,
            f"训练时长 {d['elapsed'][-1]:.1f}s\n采样 {d['n']} 点（间隔 0.5s）\n"
            f"峰值占用总显存 {peak / d['total'][0] * 100:.1f}%",
            transform=ax.transAxes, va="top", fontsize=11,
            bbox=dict(boxstyle="round", fc="#F7F7F7", ec="#CCCCCC"))
    ax.set_title("GPU 显存占用汇总", fontsize=14)
    ax.set_ylabel("显存（MB）")
    ax.set_ylim(0, d["total"][0] * 1.05)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="lower right")
    p = os.path.join(OUT_DIR, "gpu_memory_summary.png")
    fig.savefig(p, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return p


def main() -> None:
    print("=" * 78)
    print("步骤 5：生成显存监控图表")
    print("=" * 78)
    if not os.path.exists(CSV_PATH):
        sys.exit(f"[fatal] 找不到 {CSV_PATH}，请先跑 train.py")
    d = load_csv(CSV_PATH)
    print(f"读取 {CSV_PATH}")
    print(f"  采样点 {d['n']}，时长 {d['elapsed'][-1]:.1f}s")
    print(f"  显存 平均 {np.mean(d['used']):.0f} / 峰值 {np.max(d['used']):.0f} / "
          f"最低 {np.min(d['used']):.0f} MB")
    print(f"  利用率 平均 {np.mean(d['util']):.1f}% / 峰值 {np.max(d['util']):.0f}%")

    for fn in (plot_memory_curve, plot_utilization_curve, plot_summary):
        print(f"  {fn(d)}")
    print("=" * 78)


if __name__ == "__main__":
    main()
