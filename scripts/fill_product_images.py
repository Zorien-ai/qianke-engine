#!/usr/bin/env python
"""为缺少图片的商品生成统一演示封面，并写回商家商品库。

当前环境没有可用的 B 端管理员密码，因此脚本走确定性的商品库写入：
- 生成带品牌 / 商品名 / 类目 / 编号的封面；
- 写入 `static/products/generated/`；
- 通过 MerchantRepository.set_product_images 更新 m_product.image_url/images_json。

用法：
    python scripts/fill_product_images.py
    python scripts/fill_product_images.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 先加载 .env，保证直接执行脚本时 PG 连接参数与 API 一致。
for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").is_file() else []:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
os.environ.setdefault("QIANKE_MERCHANT_BACKEND", "postgres")

from rag_demo.merchant import get_merchant_repository  # noqa: E402

OUT_DIR = ROOT / "src" / "rag_demo" / "api" / "static" / "products" / "generated"
MERCHANTS = (
    "m_gear_002", "m_tea_001", "m_sim_tea", "m_sim_outdoor",
    "m_sim_home", "m_sim_coffee", "m_sim_stationery", "m_sim_fresh",
)
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
)
PALETTE = {
    "运动": ((245, 130, 90), (255, 211, 160)),
    "箱包": ((167, 135, 105), (239, 219, 190)),
    "生活": ((135, 160, 145), (218, 232, 210)),
    "数码": ((89, 116, 152), (194, 212, 231)),
    "户外": ((98, 126, 95), (201, 218, 178)),
    "户外装备": ((98, 126, 95), (201, 218, 178)),
    "户外服饰": ((98, 126, 95), (201, 218, 178)),
    "绿茶": ((83, 140, 108), (203, 226, 185)),
    "白茶": ((166, 150, 113), (241, 230, 198)),
    "乌龙茶": ((142, 109, 76), (233, 205, 171)),
    "家居香氛": ((171, 139, 126), (245, 221, 205)),
    "家纺": ((153, 143, 170), (226, 218, 237)),
    "收纳": ((147, 139, 120), (231, 223, 204)),
    "咖啡豆": ((103, 76, 60), (215, 190, 166)),
    "咖啡器具": ((116, 121, 128), (220, 222, 224)),
    "咖啡礼盒": ((133, 89, 72), (229, 195, 177)),
    "手账": ((174, 129, 111), (244, 216, 202)),
    "书写工具": ((140, 126, 90), (233, 222, 194)),
    "文具周边": ((160, 130, 150), (236, 214, 228)),
    "休闲食品": ((182, 113, 87), (247, 207, 172)),
    "冲调饮品": ((164, 121, 84), (242, 213, 178)),
    "普洱茶": ((142, 109, 76), (233, 205, 171)),
    "红茶": ((142, 83, 74), (233, 193, 177)),
    "花茶": ((174, 139, 158), (241, 213, 224)),
    "黑茶": ((93, 78, 70), (203, 184, 166)),
}


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in str(text or ""):
        trial = current + char
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines[:2] or [str(text or "")]


def render_cover(product: dict[str, Any]) -> Image.Image:
    category = str(product.get("category") or "商品")
    start, end = PALETTE.get(category, ((105, 116, 135), (205, 214, 227)))
    width = height = 900
    image = Image.new("RGB", (width, height), end)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / height
        draw.line((0, y, width, y), fill=tuple(int(start[i] * (1 - ratio) + end[i] * ratio) for i in range(3)))
    draw.ellipse((500, -150, 1100, 450), fill=(255, 255, 255))
    draw.ellipse((-200, 550, 400, 1150), fill=(255, 245, 235))
    title_font = _font(54)
    brand_font = _font(30)
    meta_font = _font(26)
    title = str(product.get("title") or product.get("name") or "商品")
    brand = str(product.get("brand") or "千客严选")
    product_id = str(product.get("product_id") or "")
    y = 430
    for line in _wrap(title, title_font, 700, draw):
        box = draw.textbbox((0, 0), line, font=title_font)
        draw.text(((width - (box[2] - box[0])) / 2, y), line, font=title_font, fill=(255, 255, 255))
        y += 64
    bbox = draw.textbbox((0, 0), category, font=meta_font)
    pad = 18
    bw, bh = bbox[2] - bbox[0] + pad * 2, bbox[3] - bbox[1] + pad * 2
    bx = (width - bw) / 2
    draw.rounded_rectangle((bx, y + 18, bx + bw, y + 18 + bh), radius=18, fill=(255, 255, 255))
    draw.text((bx + pad, y + 18 + pad - bbox[1]), category, font=meta_font, fill=start)
    brand_box = draw.textbbox((0, 0), brand, font=brand_font)
    draw.text(((width - (brand_box[2] - brand_box[0])) / 2, 100), brand, font=brand_font, fill=(255, 255, 255))
    footer = f"{product_id} · 千客演示商品"
    footer_box = draw.textbbox((0, 0), footer, font=meta_font)
    draw.text(((width - (footer_box[2] - footer_box[0])) / 2, 810), footer, font=meta_font, fill=(255, 255, 255))
    return image


def run(*, apply: bool) -> dict[str, Any]:
    repo = get_merchant_repository()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    for merchant_id in MERCHANTS:
        products = repo.list_products(merchant_id, limit=200)
        missing = [product for product in products if not str(product.image_url or "").strip()]
        uploaded = 0
        errors: list[str] = []
        for product in missing:
            image = render_cover(product.to_dict())
            target = OUT_DIR / f"{product.product_id}.png"
            if apply:
                image.save(target, format="PNG")
                url = f"/static/products/generated/{product.product_id}.png"
                if not repo.set_product_images(merchant_id, product.product_id, [{"url": url, "thumb_url": url}]):
                    errors.append(f"{product.product_id}: 更新失败")
                else:
                    uploaded += 1
        summary.append({"merchant_id": merchant_id, "products": len(products), "missing": len(missing), "uploaded": uploaded, "errors": errors})
    return {"ok": all(not item["errors"] for item in summary), "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = run(apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
