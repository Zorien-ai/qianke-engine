#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Function: 阿里云 OSS 私有桶访问层（文档图片 / 问答图片）

为什么单独一层、且**不 import rag_demo.config**
----------------------------------------------
config 会 import torch。mvp 的独立调试服务（`uvicorn rag_demo.mvp.app:app`）
刻意保持「不碰 torch、毫秒级启动」，而它同样需要独立上传图片。这里只读环境
变量，任何进程都能直接用，不引入任何重依赖（SDK 也是用时才 import）。

启用条件（缺一条就整体降级，**不让服务起不来**）
------------------------------------------------
    RAG_OSS_BUCKET
    RAG_OSS_ACCESS_KEY_ID      （也接受 OSS_ACCESS_KEY_ID，与官方 SDK 同名）
    RAG_OSS_ACCESS_KEY_SECRET  （也接受 OSS_ACCESS_KEY_SECRET）

可选：
    RAG_OSS_REGION       默认 cn-hangzhou
    RAG_OSS_ENDPOINT     默认 https://oss-cn-hangzhou.aliyuncs.com
    RAG_OSS_PREFIX       默认 kb/（所有对象的公共前缀）
    RAG_OSS_SIGN_EXPIRE  签名 URL 有效期，秒，默认 1800

为什么图片一定要签名 URL
------------------------
桶是私有的，没有公共读地址。读图必须现签一个带时效的地址；因此代码里**只存
object key**，签名放在响应序列化那一刻（permissions._render_source）——缓存
（answer_cache，TTL 1 小时）里若存了签好的 URL，命中缓存时拿到的就是过期地址。

失败策略
--------
上传失败只记日志并跳过该图，**不阻断文档入库**：一篇带 20 张图的文档不该因为
一张图网络超时整篇失败。是否启用由上面三个环境变量决定，日志会写清原因。
"""
import datetime
import logging
import os
import posixpath

logger = logging.getLogger(__name__)

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}

_DEFAULT_SIGN_EXPIRE = 1800

_client = None


class OssError(RuntimeError):
    """OSS 未启用或操作失败——调用方按「图片功能不可用」处理"""


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _access_key_id() -> str:
    return _env("RAG_OSS_ACCESS_KEY_ID") or _env("OSS_ACCESS_KEY_ID")


def _access_key_secret() -> str:
    return _env("RAG_OSS_ACCESS_KEY_SECRET") or _env("OSS_ACCESS_KEY_SECRET")


def bucket() -> str:
    return _env("RAG_OSS_BUCKET")


def region() -> str:
    return _env("RAG_OSS_REGION", "cn-hangzhou")


def endpoint() -> str:
    return _env("RAG_OSS_ENDPOINT", f"https://oss-{region()}.aliyuncs.com")


def prefix() -> str:
    """公共前缀，统一成「不带首斜杠、带尾斜杠」的形式"""
    raw = _env("RAG_OSS_PREFIX", "kb/").strip("/")
    return f"{raw}/" if raw else ""


def sign_expire() -> int:
    try:
        return max(60, int(_env("RAG_OSS_SIGN_EXPIRE", str(_DEFAULT_SIGN_EXPIRE))))
    except ValueError:
        return _DEFAULT_SIGN_EXPIRE


def is_enabled() -> bool:
    return bool(bucket() and _access_key_id() and _access_key_secret())


def disabled_reason() -> str:
    """给日志/接口用的人话原因（不参与业务判断）"""
    missing = []
    if not bucket():
        missing.append("RAG_OSS_BUCKET")
    if not _access_key_id():
        missing.append("RAG_OSS_ACCESS_KEY_ID")
    if not _access_key_secret():
        missing.append("RAG_OSS_ACCESS_KEY_SECRET")
    return "缺少 " + " / ".join(missing) if missing else ""


def reset_client() -> None:
    """测试用：环境变量改了之后重建客户端"""
    global _client
    _client = None


def get_client():
    """懒加载 SDK 与客户端：没装 SDK 时也只是「图片不可用」，不影响服务启动"""
    global _client
    if not is_enabled():
        raise OssError(f"OSS 未配置（{disabled_reason()}）")
    if _client is not None:
        return _client

    try:
        import alibabacloud_oss_v2 as oss
    except ImportError as e:  # pragma: no cover 依赖缺失时给出可执行提示
        raise OssError("缺少 alibabacloud-oss-v2，请执行 uv add alibabacloud-oss-v2") from e

    cfg = oss.config.load_default()
    cfg.region = region()
    cfg.endpoint = endpoint()
    cfg.credentials_provider = oss.credentials.StaticCredentialsProvider(
        _access_key_id(), _access_key_secret()
    )
    _client = oss.Client(cfg)
    logger.info("OSS 客户端已就绪：bucket=%s region=%s prefix=%s", bucket(), region(), prefix())
    return _client


def normalize_key(key: str) -> str:
    """
    object key 归一化：反斜杠转正斜杠、去掉首斜杠、拒绝上跳

    文档里的图片引用是**外部输入**，`../` 之类不能带进 key。
    """
    raw = (key or "").replace("\\", "/").strip().lstrip("/")
    if not raw:
        raise OssError("OSS object key 不能为空")
    norm = posixpath.normpath(raw)
    if norm in ("", ".", "..") or norm.startswith("../") or "/../" in norm:
        raise OssError(f"非法的 OSS object key: {key!r}")
    return norm


def content_type_of(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return _CONTENT_TYPES.get(ext, "application/octet-stream")


def _sdk():
    """懒加载 SDK：没装依赖时只在真正用图片功能的那一刻报错"""
    import alibabacloud_oss_v2 as oss

    return oss


def upload_bytes(key: str, data: bytes, content_type: str | None = None) -> str:
    """上传一段字节，返回归一化后的 key；失败抛 OssError（调用方自己决定是否兜底）"""
    if not data:
        raise OssError("空内容，不上传")
    oss = _sdk()
    client = get_client()
    safe_key = normalize_key(key)
    request = oss.PutObjectRequest(
        bucket=bucket(),
        key=safe_key,
        body=data,
        content_type=content_type or content_type_of(safe_key),
    )
    client.put_object(request)
    return safe_key


def sign_url(key: str, expire_seconds: int | None = None) -> str:
    """
    生成私有桶的临时读地址；未启用/失败返回空串

    返回空串而不是抛异常：图片是增强信息，签不出来不该让整条回答 500。
    """
    if not key or not is_enabled():
        return ""
    try:
        oss = _sdk()
        client = get_client()
        result = client.presign(
            oss.GetObjectRequest(bucket=bucket(), key=normalize_key(key)),
            expires=datetime.timedelta(seconds=expire_seconds or sign_expire()),
        )
        return getattr(result, "url", "") or ""
    except Exception as e:  # noqa: BLE001 签名失败降级为无图
        logger.warning("OSS 签名失败（key=%s）: %s: %s", key, type(e).__name__, e)
        return ""


def doc_image_key(dataset: str, doc_name: str, rel_path: str) -> str:
    """
    文档内嵌图片的 key 布局：`{prefix}{dataset}/{doc_name}/{相对路径}`

    保留原始相对路径是为了「同一篇文档重导入时覆盖同一张图」，而不是每次新增
    一份孤儿对象。dataset 进 key 是必须的：demo / user / ent_x 的图片互不覆盖。
    """
    parts = [prefix(), (dataset or "demo").strip("/"), os.path.basename(doc_name or "doc")]
    rel = normalize_key(rel_path)
    return normalize_key("/".join(p for p in parts if p) + "/" + rel)


def inline_image_key(filename: str) -> str:
    """独立上传的图片：`{prefix}inline/{yyyymm}/{uuid}{ext}`（不绑数据集）"""
    stem, ext = os.path.splitext(os.path.basename(filename or "image"))
    safe_ext = ext.lower() if ext.lower() in _CONTENT_TYPES else ".png"
    stamp = datetime.datetime.now().strftime("%Y%m")
    import uuid

    return normalize_key(f"{prefix()}inline/{stamp}/{uuid.uuid4().hex[:16]}{safe_ext}")
