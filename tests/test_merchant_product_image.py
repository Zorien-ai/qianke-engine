# -*- coding: utf-8 -*-
"""商品主图：种子 URL、仓储写入与静态资源存在性。"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest
from starlette.datastructures import Headers, UploadFile

from rag_demo import product_media as media
from rag_demo.api import b_workbench
from rag_demo.merchant import (
    get_merchant_repository,
    load_seed_data,
    reset_merchant_repository_cache,
)

_STATIC_ROOT = Path(__file__).resolve().parents[1] / "src" / "rag_demo" / "api" / "static"


@pytest.fixture()
def merchant_db(tmp_path, monkeypatch):
    db_path = tmp_path / "merchant.sqlite"
    monkeypatch.setenv("QIANKE_MERCHANT_DB", str(db_path))
    reset_merchant_repository_cache()
    try:
        yield db_path
    finally:
        reset_merchant_repository_cache()


@pytest.fixture()
def repo(merchant_db):
    repository = get_merchant_repository()
    try:
        yield repository
    finally:
        repository.close()


def test_tea_seed_has_local_public_tea_images():
    data = load_seed_data()
    tea = [product for product in data.products if product.merchant_id == "m_tea_001"]
    assert len(tea) >= 8
    for product in tea:
        assert product.image_url, f"{product.product_id} 缺少主图"
        assert product.image_url.startswith("/static/products/")
        relative = product.image_url.removeprefix("/static/")
        assert (_STATIC_ROOT / relative).is_file(), f"图片不存在: {product.image_url}"


def test_product_to_dict_contains_image_url():
    data = load_seed_data()
    payload = data.products[0].to_dict()
    assert "image_url" in payload


def test_set_product_image_is_tenant_scoped(repo):
    assert repo.set_product_image("m_tea_001", "P-TEA-001", "/static/products/tea-white.jpg")
    products = {item.product_id: item for item in repo.list_products("m_tea_001", limit=20)}
    assert products["P-TEA-001"].image_url == "/static/products/tea-white.jpg"

    # 别的商家不能改这条商品
    assert repo.set_product_image("m_gear_002", "P-TEA-001", "/static/products/tea-black.jpg") is False


def test_upload_product_image_writes_webp_and_updates_product(repo, tmp_path, monkeypatch):
    source = (_STATIC_ROOT / "products" / "tea-lungching.jpg").read_bytes()
    upload_dir = tmp_path / "uploads" / "products"
    monkeypatch.setattr(media, "PRODUCT_UPLOAD_ROOT", upload_dir)
    monkeypatch.setattr(b_workbench, "_account", lambda: {"id": 1, "status": "active"})
    monkeypatch.setattr(
        b_workbench, "_membership",
        lambda account: {"account_id": 1, "merchant_id": "m_tea_001", "role": "owner"},
    )
    upload = UploadFile(
        file=io.BytesIO(source),
        filename="tea.jpg",
        headers=Headers({"content-type": "image/jpeg"}),
    )
    result = asyncio.run(b_workbench.upload_product_image("P-TEA-001", upload))
    assert result["image_url"].startswith("/uploads/products/m_tea_001/P-TEA-001.webp?v=")
    saved = upload_dir / "m_tea_001" / "P-TEA-001.webp"
    assert saved.is_file()
    assert saved.stat().st_size > 0
    product = {item.product_id: item for item in repo.list_products("m_tea_001")}["P-TEA-001"]
    assert product.image_url == result["image_url"]


def test_upload_rejects_non_image(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(media, "PRODUCT_UPLOAD_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(b_workbench, "_account", lambda: {"id": 1, "status": "active"})
    monkeypatch.setattr(
        b_workbench, "_membership",
        lambda account: {"account_id": 1, "merchant_id": "m_tea_001", "role": "owner"},
    )
    upload = UploadFile(
        file=io.BytesIO(b"not an image"),
        filename="bad.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    with pytest.raises(Exception) as exc:
        asyncio.run(b_workbench.upload_product_image("P-TEA-001", upload))
    assert getattr(exc.value, "status_code", None) == 400
