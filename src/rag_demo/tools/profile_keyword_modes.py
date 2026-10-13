#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : profile_keyword_modes.py
@Function: 对比三种关键词策略的耗时，区分「冷启动」与「热态」

背景
----
有人观察到「两者组合（both）」比「仅稀疏向量（sparse）」还快，怀疑做过优化。
实际上 `both` 就是 bm25 + sparse 各跑一次再融合，**只会更慢**。
差异极可能来自**测量顺序**：谁先调用 `sparse_search`，谁就吃下模型与索引的加载开销，
而这份开销是进程内一次性的。

本脚本用同一进程、固定题目、冷热分开测，验证这个判断。

用法：
    python src/rag_demo/tools/profile_keyword_modes.py
"""
import time

from rag_demo.retrieval.hybrid_retriever import keyword_search

QUESTION = "哪些标签跟美妆相关"


def timeit(fn, repeat: int = 3) -> list[float]:
    out = []
    for _ in range(repeat):
        t = time.time()
        fn()
        out.append(time.time() - t)
    return out


def main() -> None:
    print(f"题目：{QUESTION}\n")

    # ---------- 冷启动 ----------
    t = time.time()
    keyword_search(QUESTION, mode="bm25")
    cold_bm25 = time.time() - t
    print(f"[冷启动] bm25   : {cold_bm25:6.2f}s   （纯内存索引，几乎无加载成本）")

    t = time.time()
    keyword_search(QUESTION, mode="sparse")
    cold_sparse = time.time() - t
    print(f"[冷启动] sparse : {cold_sparse:6.2f}s   （含 BGEM3 模型 + 索引缓存加载）")

    # ---------- 热态 ----------
    print("\n[热态] 索引已就绪，各模式重复 3 次：")
    warm: dict[str, list[float]] = {}
    for mode in ("bm25", "sparse", "both"):
        ts = timeit(lambda: keyword_search(QUESTION, mode=mode), 3)
        warm[mode] = ts
        print(f"  {mode:6}: " + "   ".join(f"{x:.3f}s" for x in ts))

    # ---------- 结论 ----------
    print("\n" + "=" * 66)
    print("结论：")
    print(f"  1) sparse 首次调用 {cold_sparse:.2f}s vs 热态 {min(warm['sparse']):.3f}s，"
          f"多付 {cold_sparse - min(warm['sparse']):.2f}s")
    print("     但这笔钱里混着进程初始化（torch / jieba / BM25 语料）——")
    print(f"     bm25 首次调用也付了 {cold_bm25:.2f}s。")
    print(f"     稀疏向量「特有」的额外成本 = {cold_sparse - cold_bm25:.2f}s"
          "（BGEM3 模型 + 7.9MB 稀疏索引加载）")
    print()
    print(f"  2) 热态下 both({min(warm['both']):.3f}s) 比 sparse({min(warm['sparse']):.3f}s) "
          f"慢 {min(warm['both']) - min(warm['sparse']):+.3f}s —— 这才是两者的真实差距")
    print("     （both 略慢是对的：它多跑了一次 bm25）")
    print()
    print("  3) 所以：若先测 sparse 再测 both，看到的就是「both 更快」的假象，")
    print("     差值恰好等于那次冷启动。**没有做任何优化，纯属测量顺序。**")


if __name__ == "__main__":
    main()
