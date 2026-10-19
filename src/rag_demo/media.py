#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Function: Markdown 图片引用解析与上传（入库侧素材处理）

支持的引用形态
--------------
1. 相对路径：`![架构图](images/arch.png)`
   文件必须在该批上传目录（`data/uploads/<id>/`）里，入库时逐张上传到 OSS。
2. OSS key：`![架构图](oss://kb/inline/202610/abc.png)`
   用于「先通过独立接口传图、再在 md 里引用」的场景，入库时原样保留 key。
3. 外链：`https://...`
   不做下载转存（网络不可控、也可能有版权问题），直接把 URL 透传给前端。

不做的事
--------
不解析远程图片、不压缩、不生成缩略图。图片处理属于另一个问题域，先让
「引用能落地、检索能返回签名 URL」这条路通。
"""
import logging
import os
import re
import urllib.parse

from rag_demo.storage import oss_store

logger = logging.getLogger(__name__)

# 与 oss_store 的 content-type 表保持一致；svg 也算图片（矢量图常见于架构文档）
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")

# 单张图上限：知识库里的配图极少超过 20MB，超过基本是传错文件
MAX_IMAGE_BYTES = 20 * 1024 * 1024

# 每篇文档最多处理多少张图：防止一篇病态文档把构建拖死
MAX_IMAGES_PER_DOC = 100

OSS_REF_PREFIX = "oss://"

# ![alt](ref) 或 ![alt](ref "title")；ref 里不允许空白与右括号
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")


def is_image_name(name: str) -> bool:
    return (name or "").lower().endswith(IMAGE_SUFFIXES)


def extract_image_refs(text: str) -> list[tuple[str, str]]:
    """按出现顺序取出 [(alt, ref)]，去重保序"""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for match in _IMAGE_RE.finditer(text or ""):
        ref = (match.group(2) or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        out.append(((match.group(1) or "").strip(), ref))
    return out


def is_external(ref: str) -> bool:
    return ref.lower().startswith(("http://", "https://", "data:"))


def _local_path(base_dir: str, ref: str) -> tuple[str, str] | None:
    """
    相对引用 → (本地绝对路径, 用于 OSS key 的相对路径)；不合法或不存在返回 None

    ref 来自文档正文（外部输入），必须挡住 `../../etc/passwd` 这类路径。

    扁平兜底：上传接口按 `basename` 落盘（浏览器多选/拖文件夹不会保留子目录），
    而 Typora 等工具导出的引用常是 `assets/xxx.png`。所以原样找不到时再按文件名
    试一次——否则用户明明把图传上来了，却因为路径带一层目录而全部失效。
    """
    clean = urllib.parse.unquote(ref.split("?", 1)[0].split("#", 1)[0])
    clean = clean.replace("\\", "/").lstrip("/")
    if not clean or clean.startswith("../") or "/../" in clean:
        logger.warning("图片引用越界，已跳过: %s", ref)
        return None
    if not is_image_name(clean):
        return None

    base = os.path.normpath(base_dir)
    for candidate in (clean, os.path.basename(clean)):
        path = os.path.normpath(os.path.join(base, candidate))
        if not path.startswith(base + os.sep):
            logger.warning("图片引用不在上传目录内，已跳过: %s", ref)
            return None
        if os.path.isfile(path):
            return path, candidate
    return None


def prepare_doc_images(
    text: str,
    doc_name: str,
    base_dir: str | None,
    dataset: str | None = None,
) -> dict[str, dict]:
    """
    预处理一篇文档里的图片，返回 {原始引用: {"alt":..., "key":... 或 "url":...}}

    上传失败只跳过该图（记 warning），不抛异常——文档正文照样入库，只是少几张配图。
    OSS 未配置时：只保留 `oss://` 引用，本地图片不传（并记录一次原因）。
    """
    refs = extract_image_refs(text)
    if not refs:
        return {}

    enabled = oss_store.is_enabled()
    if not enabled:
        logger.info(
            "OSS 未启用（%s），文档 %s 的 %d 张本地图片只入库文本、不入对象存储",
            oss_store.disabled_reason(), doc_name, len(refs),
        )

    out: dict[str, dict] = {}
    uploaded = 0
    failed = 0
    for alt, ref in refs[:MAX_IMAGES_PER_DOC]:
        if ref.startswith(OSS_REF_PREFIX):
            key = ref[len(OSS_REF_PREFIX):].strip()
            if key:
                out[ref] = {"alt": alt, "key": key}
            continue

        if is_external(ref):
            out[ref] = {"alt": alt, "url": ref}
            continue

        if not enabled or not base_dir:
            continue

        found = _local_path(base_dir, ref)
        if found is None:
            failed += 1
            continue
        path, rel = found
        try:
            if os.path.getsize(path) > MAX_IMAGE_BYTES:
                logger.warning("图片超过 %dMB，已跳过: %s", MAX_IMAGE_BYTES // 1024 // 1024, ref)
                failed += 1
                continue
            with open(path, "rb") as f:
                data = f.read()
            key = oss_store.doc_image_key(dataset or "demo", doc_name, rel)
            out[ref] = {
                "alt": alt,
                "key": oss_store.upload_bytes(key, data, oss_store.content_type_of(path)),
            }
            uploaded += 1
        except Exception as e:  # noqa: BLE001 单张图失败不影响整篇
            failed += 1
            logger.warning("图片上传失败（%s）: %s: %s", ref, type(e).__name__, e)

    if uploaded or failed:
        logger.info("文档 %s 图片入库：成功 %d 张 / 跳过 %d 张", doc_name, uploaded, failed)
    return out


def images_for_chunk(chunk_text: str, ref_map: dict[str, dict]) -> list[dict]:
    """取出这个 chunk 里出现的图片（保持正文顺序，按 key/url 去重）"""
    if not ref_map:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for alt, ref in extract_image_refs(chunk_text):
        item = ref_map.get(ref)
        if not item:
            continue
        ident = item.get("key") or item.get("url") or ""
        if not ident or ident in seen:
            continue
        seen.add(ident)
        out.append({"alt": item.get("alt") or alt, "key": item.get("key", ""),
                    "url": item.get("url", "")})
    return out


def store_inline_image(filename: str, data: bytes) -> dict:
    """
    独立上传接口用：字节 → OSS，返回 {"name","key","url","size"}

    url 是**当下**的签名地址（供页面即时预览），真正入库靠 key；
    调用方要把 key 写进 md（`![name](oss://<key>)`）而不是把 url 贴进去。
    """
    if not oss_store.is_enabled():
        raise oss_store.OssError(f"图片存储未启用（{oss_store.disabled_reason()}）")
    if not is_image_name(filename):
        raise ValueError(f"{filename} 不是支持的图片格式（{'/'.join(IMAGE_SUFFIXES)}）")
    if not data:
        raise ValueError(f"{filename} 是空文件")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"{filename} 超过 {MAX_IMAGE_BYTES // 1024 // 1024}MB")

    key = oss_store.upload_bytes(
        oss_store.inline_image_key(filename), data, oss_store.content_type_of(filename)
    )
    return {
        "name": os.path.basename(filename),
        "key": key,
        "url": oss_store.sign_url(key),
        "size": len(data),
        "markdown": f"![{os.path.splitext(os.path.basename(filename))[0]}]({OSS_REF_PREFIX}{key})",
    }


def sign_images(images: list[dict] | None) -> list[dict]:
    """
    给响应里的图片补签名 URL；缓存里只存 key，所以在**每次响应**时现签

    返回结构：{"alt", "url", "key"}；签不出来（未启用/失败）就跳过该图。
    """
    out: list[dict] = []
    for item in images or []:
        if not isinstance(item, dict):
            continue
        alt = item.get("alt") or ""
        key = item.get("key") or ""
        url = item.get("url") or ""
        if key:
            signed = oss_store.sign_url(key)
            if not signed:
                continue
            out.append({"alt": alt, "url": signed, "key": key})
        elif url:
            out.append({"alt": alt, "url": url, "key": ""})
    return out
