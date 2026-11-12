"""商品图本地存储目录。

与现有的 Markdown 媒体解析模块（``rag_demo.media``）分开，避免覆盖其职责。
演示环境落本地磁盘；接入对象存储时只替换 b_workbench 的保存实现。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from rag_demo.config import BASE_DIR
from rag_demo.storage import oss_store

logger = logging.getLogger(__name__)

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


def oss_product_enabled() -> bool:
    backend = (os.environ.get("QIANKE_PRODUCT_MEDIA_BACKEND") or "local").strip().lower()
    return backend == "oss" and oss_store.is_enabled()


def product_key_prefix() -> str:
    raw = (os.environ.get("QIANKE_PRODUCT_MEDIA_PREFIX") or "products/").strip("/")
    return f"{raw}/" if raw else ""


def oss_public_url(key: str) -> str:
    base = (os.environ.get("QIANKE_PRODUCT_MEDIA_BASE_URL") or "").strip().rstrip("/")
    if not base:
        endpoint = oss_store.endpoint()
        parsed = urlparse(endpoint if "://" in endpoint else f"https://{endpoint}")
        base = f"https://{oss_store.bucket()}.{parsed.netloc}"
    return f"{base}/{str(key or '').lstrip('/')}"


def save_product_image_bytes(
    main: bytes,
    thumb: bytes,
    *,
    merchant_id: str,
    product_id: str,
    base_name: str,
) -> dict[str, str]:
    """保存主图/缩略图：OSS 优先，本地兜底；返回浏览器 URL。"""
    safe_merchant = _safe_slug(merchant_id)
    safe_product = _safe_slug(product_id)
    safe_base = _safe_slug(base_name)
    if oss_product_enabled():
        prefix = product_key_prefix()
        key = f"{prefix}{safe_merchant}/{safe_product}/{safe_base}.webp"
        thumb_key = f"{prefix}{safe_merchant}/{safe_product}/{safe_base}.thumb.webp"
        oss_store.upload_bytes(key, main, "image/webp")
        oss_store.upload_bytes(thumb_key, thumb, "image/webp")
        return {"url": oss_public_url(key), "thumb_url": oss_public_url(thumb_key)}

    folder = PRODUCT_UPLOAD_ROOT / safe_merchant
    folder.mkdir(parents=True, exist_ok=True)
    main_path = folder / f"{safe_base}.webp"
    thumb_path = folder / f"{safe_base}.thumb.webp"
    main_path.write_bytes(main)
    thumb_path.write_bytes(thumb)
    version = int(time.time() * 1000)
    return {
        "url": f"{public_url(f'uploads/products/{folder.name}/{main_path.name}')}?v={version}",
        "thumb_url": f"{public_url(f'uploads/products/{folder.name}/{thumb_path.name}')}?v={version}",
    }


def delete_image_objects(image: dict[str, str]) -> None:
    """删除主图/缩略图对象；仅删除本模块生成的 URL，失败只记日志。"""
    for field in ("url", "thumb_url"):
        raw = str(image.get(field) or "").split("?", 1)[0]
        if not raw:
            continue
        try:
            if raw.startswith("/uploads/"):
                local = UPLOAD_ROOT / raw.removeprefix("/uploads/")
                local.unlink(missing_ok=True)
                continue
            if not oss_product_enabled():
                continue
            base = oss_public_url("").rstrip("/")
            if raw.startswith(f"{base}/"):
                oss_store.delete_object(raw[len(base) + 1:])
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除商品图片失败（%s）: %s", raw, exc)


def _safe_slug(value: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or ""))[:100]


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
