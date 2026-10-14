#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : logging_setup.py
@Function: 日志统一配置（控制台 + 文件双通道）

为什么单独抽出来
----------------
此前各入口各写一遍 `logging.basicConfig`：api 用默认格式、ingest / build 脚本
用带时间戳的格式、ab 实验只留 WARNING。同一个项目三种风格，排查时对不上。

更要紧的是**只打屏**：服务跑在后台、或终端被关掉之后，日志就没了，
出问题只能靠复现。落盘之后可以回溯「刚才那一次到底发生了什么」——
2026-10-14 排查「数据库没起」时，就是因为没落盘 + 命令里加了 2>$null，
把唯一的关键报错丢掉了，白绕了一圈。

输出位置
--------
    logs/rag_demo.log                  当前日志（每天午夜轮转）
    logs/rag_demo.log.2026-10-13       历史日志，保留 BACKUP_DAYS 天

用法
----
    from rag_demo.logging_setup import setup_logging
    setup_logging()             # 幂等，重复调用不会叠加 handler

    setup_logging(to_file=False)    # 一次性脚本：只打屏，不往 logs/ 塞噪音
"""
import logging
import logging.handlers
import os

from rag_demo.config import BASE_DIR

LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "rag_demo.log")

# 文件里带模块名与行号：排查时能直接定位到代码
FILE_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s"
# 控制台保持简短：日常看效果不需要行号
CONSOLE_FORMAT = "%(levelname)s %(name)s: %(message)s"

BACKUP_DAYS = 7

# 「日志写到哪了」只播报一次——重复调用 setup_logging 时不必反复刷这行
_announced = False


def setup_logging(level: int = logging.INFO, to_file: bool = True,
                  filename: str | None = None) -> str | None:
    """
    配置根 logger 的输出通道，返回日志文件路径（to_file=False 时返回 None）

    **幂等**：先清空已有 handler 再重建。重复调用不会出现「一条日志打印两遍」，
    也不会和之前某处的 `basicConfig` 叠加。

    用根 logger 而非单个模块 logger，是为了让所有子模块
    （它们都是 `logging.getLogger(__name__)`）自然继承同一套配置。
    """
    root = logging.getLogger()
    root.setLevel(level)

    # 清空：既保证幂等，也顺手清掉入口处可能残留的 basicConfig handler
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    root.addHandler(console)

    if not to_file:
        return None

    path = filename or LOG_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # 按天轮转：日志量不大，按大小切反而不好定位「哪天的日志」
    file_handler = logging.handlers.TimedRotatingFileHandler(
        path, when="midnight", backupCount=BACKUP_DAYS, encoding="utf-8"
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
    root.addHandler(file_handler)

    global _announced
    if not _announced:
        logging.getLogger(__name__).info(
            "日志文件: %s（按天轮转，保留 %d 天）", path, BACKUP_DAYS
        )
        _announced = True
    return path
