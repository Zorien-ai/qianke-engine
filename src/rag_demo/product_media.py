"""商品图本地存储目录。

与现有的 Markdown 媒体解析模块（``rag_demo.media``）分开，避免覆盖其职责。
演示环境落本地磁盘；接入对象存储时只替换 b_workbench 的保存实现。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from rag_demo.config import BASE_DIR

UPLOAD_ROOT = Path(
    os.environ.get("QIANKE_UPLOAD_DIR") or (Path(BASE_DIR) / "var" / "uploads")
).resolve()
PRODUCT_UPLOAD_ROOT = UPLOAD_ROOT / "products"
AUDIT_PATH = PRODUCT_UPLOAD_ROOT / "image-audit.jsonl"
_audit_lock = threading.Lock()


def ensure_upload_dirs() -> None:
    PRODUCT_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def public_url(relative: str) -> str:
    """返回可被浏览器访问的图片 URL；可用 CDN 前缀覆盖本地路径。"""
    path = "/" + str(relative or "").lstrip("/")
    base = (os.environ.get("QIANKE_PRODUCT_MEDIA_BASE_URL") or "").strip().rstrip("/")
    return f"{base}{path}" if base else path


def record_image_audit(
    *,
    merchant_id: str,
    product_id: str,
    action: str,
    image_url: str,
    actor_id: str | int | None = None,
) -> None:
    """本地 JSONL 审计；生产环境可替换为 DB/对象存储审计。"""
    ensure_upload_dirs()
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "merchant_id": str(merchant_id),
        "product_id": str(product_id),
        "action": str(action).upper(),
        "image_url": str(image_url or ""),
        "actor_id": str(actor_id or ""),
    }
    with _audit_lock:
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def list_image_audit(merchant_id: str, product_id: str, limit: int = 20) -> list[dict]:
    """读取某商品的最近图片操作审计。"""
    if not AUDIT_PATH.is_file():
        return []
    rows: list[dict] = []
    with _audit_lock:
        for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get("merchant_id") != merchant_id or item.get("product_id") != product_id:
                continue
            rows.append(item)
    return list(reversed(rows[-max(1, min(int(limit or 20), 100)):]))
