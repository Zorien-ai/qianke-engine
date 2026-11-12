"""商品图本地存储目录。

与现有的 Markdown 媒体解析模块（``rag_demo.media``）分开，避免覆盖其职责。
演示环境落本地磁盘；接入对象存储时只替换 b_workbench 的保存实现。
"""
from __future__ import annotations

import os
from pathlib import Path

from rag_demo.config import BASE_DIR

UPLOAD_ROOT = Path(
    os.environ.get("QIANKE_UPLOAD_DIR") or (Path(BASE_DIR) / "var" / "uploads")
).resolve()
PRODUCT_UPLOAD_ROOT = UPLOAD_ROOT / "products"


def ensure_upload_dirs() -> None:
    PRODUCT_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
