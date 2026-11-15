#!/usr/bin/env python
"""用 Pexels 真实商品/场景照片替换演示商品封面。

图片来源：Pexels（Pexels License，免费商用，无需署名；仍建议保留来源记录）。
每张图按商品 ID 显式映射，避免关键词搜索抓到不相关图片。

用法：
    python scripts/fetch_real_product_images.py
    python scripts/fetch_real_product_images.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").is_file() else []:
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
os.environ.setdefault("QIANKE_MERCHANT_BACKEND", "postgres")
from rag_demo.merchant import get_merchant_repository  # noqa: E402

OUT = ROOT / "src" / "rag_demo" / "api" / "static" / "products" / "real"
SOURCES = ROOT / "var" / "real_product_images_sources.json"

# 商品 ID -> (Pexels photo id, 商家, 检索说明)
PEXELS: dict[str, tuple[int, str, str]] = {
    "P001": (39592199, "m_gear_002", "beige and black running shoes"),
    "P002": (5721338, "m_gear_002", "backpacks on store shelf"),
    "P003": (34140882, "m_gear_002", "stainless steel water bottle"),
    "P004": (32814156, "m_gear_002", "wireless earbuds charging case"),
    "P005": (37704840, "m_gear_002", "white t-shirt flat lay"),
    "P006": (35919647, "m_gear_002", "orange outdoor jacket hiking"),
    "P-GEAR-001": (35919622, "m_gear_002", "woman hiking with trekking pole"),
    "P-GEAR-002": (12106791, "m_gear_002", "headlamp in forest at night"),
    "P-GEAR-003": (36086219, "m_gear_002", "outdoor sports jacket in cart"),
    "P-GEAR-004": (35915132, "m_gear_002", "black insulated bottle"),
    "SIM-OUT-01": (35925204, "m_sim_outdoor", "pink jacket mountain hiking"),
    "SIM-OUT-02": (29773331, "m_sim_outdoor", "man hiking with trekking poles"),
    "SIM-OUT-03": (8855847, "m_sim_outdoor", "thermos pouring hot drink"),
    "SIM-HOME-01": (6915261, "m_sim_home", "wooden aroma diffuser"),
    "SIM-HOME-02": (4153160, "m_sim_home", "white bed linen"),
    "SIM-HOME-03": (7372259, "m_sim_home", "rattan basket"),
    "SIM-COF-01": (20708728, "m_sim_coffee", "roasted coffee beans"),
    "SIM-COF-02": (34386686, "m_sim_coffee", "gooseneck pour over kettle"),
    "SIM-COF-03": (20192283, "m_sim_coffee", "coffee gift box flat lay"),
    "SIM-STA-01": (936320, "m_sim_stationery", "notebook and pen"),
    "SIM-STA-02": (15877831, "m_sim_stationery", "black fountain pen"),
    "SIM-STA-03": (38296145, "m_sim_stationery", "colorful sticker magnets"),
    "SIM-FRE-01": (11931801, "m_sim_fresh", "mixed berries and nuts"),
    "SIM-FRE-02": (33389643, "m_sim_fresh", "freeze dried strawberry slices"),
    "SIM-FRE-03": (9575302, "m_sim_fresh", "organic honey jar"),
}


def image_url(photo_id: int) -> str:
    return f"https://images.pexels.com/photos/{photo_id}/pexels-photo-{photo_id}.jpeg?auto=compress&cs=tinysrgb&w=1200"


def download(photo_id: int) -> tuple[bytes, int, int]:
    response = requests.get(image_url(photo_id), headers={"User-Agent": "Mozilla/5.0"}, timeout=45)
    response.raise_for_status()
    if not response.headers.get("Content-Type", "").startswith("image/"):
        raise ValueError(f"不是图片: {response.headers.get('Content-Type')}")
    image = Image.open(BytesIO(response.content))
    image.verify()
    image = Image.open(BytesIO(response.content)).convert("RGB")
    if image.width < 450 or image.height < 450:
        raise ValueError(f"图片太小 {image.width}x{image.height}")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    return buffer.getvalue(), image.width, image.height


def run(*, apply: bool) -> dict[str, Any]:
    repo = get_merchant_repository()
    OUT.mkdir(parents=True, exist_ok=True)
    sources: list[dict[str, Any]] = []
    for product_id, (photo_id, merchant_id, note) in PEXELS.items():
        item: dict[str, Any] = {
            "product_id": product_id,
            "merchant_id": merchant_id,
            "photo_id": photo_id,
            "source_page": f"https://www.pexels.com/photo/{photo_id}/",
            "license": "Pexels License",
            "note": note,
        }
        try:
            raw, width, height = download(photo_id)
        except Exception as exc:  # noqa: BLE001
            item["error"] = str(exc)
            sources.append(item)
            print(product_id, "ERROR", exc)
            continue
        item.update({"bytes": len(raw), "width": width, "height": height})
        if apply:
            filename = f"{product_id}.jpg"
            (OUT / filename).write_bytes(raw)
            public = f"/static/products/real/{filename}"
            if repo.set_product_images(merchant_id, product_id, [{"url": public, "thumb_url": public}]):
                item["applied"] = public
            else:
                item["error"] = "商品写回失败"
        sources.append(item)
        print(product_id, "->", item["source_page"], f"{width}x{height}")
    SOURCES.parent.mkdir(parents=True, exist_ok=True)
    SOURCES.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": all("error" not in item for item in sources), "sources": sources}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = run(apply=args.apply)
    print(json.dumps({"ok": result["ok"], "count": len(result["sources"])}, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

