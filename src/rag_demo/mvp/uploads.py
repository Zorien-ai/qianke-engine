#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : uploads.py
@Function: 上传落盘与解析（M2 第一块：把「浏览器解析」换成「服务端解析」）

M1 的做法（已废弃）
-------------------
M1 把文件读进浏览器，用 JS 解码、按行切、数出「约 N 行」，再把解析结果当 JSON
发给服务端。服务端从头到尾**没见过文件本身**。两个问题：

  1. 行数是**估**的（带引号换行的字段会被多算），页面上只能写「约」；
  2. 编码判断、分隔符猜测这些「数据侧的事」散在前端，换一个前端就得重写一遍，
     而它们恰恰是入库口径的一部分（`ingest_data.load_transactions` 读的是
     **已经统一成 UTF-8** 的文件——这个约定以前没人真的实现）。

现在的约定（M2）
----------------
    上传 → 落盘为 UTF-8 → 用 pandas 真读一遍 → 返回列名与**真实行数**

落盘即「转码完成」，这是后面 `load_transactions` 能直接 `encoding="utf-8-sig"`
读的原因。库里的东西与浏览器无关，所以 M3 的联调、M4 的 5 份真实 CSV 走的都是这条路。

磁盘是唯一真源
--------------
上传内容放在 `data/uploads/<upload_id>/`，**状态从目录重扫**（`scan`），
不用进程内字典。理由：M1 用进程内 `_SESSION`，服务一重启用户上传的东西就没了，
而「重新上传一遍」对运营是大成本。顺带的好处是构建任务（下一步）与查询可以在
不同进程里读到同一份上传，不必要求同进程。

⚠ 目录穿越：`upload_id` 与文件名都会拼进路径，两者都过 `_safe_*` 白名单校验。
"""
import io
import json
import logging
import os
import re
import shutil
import time
import uuid

import pandas as pd

logger = logging.getLogger(__name__)

# 从这里往上是项目根：uploads.py -> mvp -> rag_demo -> src -> 根
# 不用 config.BASE_DIR：config 会 import torch，而本包（可独立启动的调试服务）
# 刻意不碰 torch / 数据库，启动要保持在毫秒级。
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)
))))
UPLOAD_ROOT = os.path.join(BASE_DIR, "data", "uploads")

# 表格数据与文档的允许后缀。**.txt 归到表格侧**是沿用 M1 的上传口
# （accept=".csv,.txt"）——有的平台导出就是 .txt 里放逗号分隔。
CSV_SUFFIXES = (".csv", ".txt")
MD_SUFFIXES = (".md", ".markdown")

MAX_FILE_BYTES = 200 * 1024 * 1024   # 单文件 200MB：挡住「拖错了一个数据库备份」

# 批次目录里的旁挂元数据：记录每个文件的**原始编码**。
# 为什么不直接看落盘文件：落盘时已经统一转成 UTF-8 了，原始编码这个信息丢了。
# 而它对用户有用——运营拿到一份 GBK 导出的会员表，最想知道的是「我用不用自己转」。
_META_NAME = "_meta.json"

_ID_RE = re.compile(r"^[0-9a-f]{12}$")
# 落盘文件名：只留基名 + 去掉路径分隔符与上跳，杜绝 ../../ 之类
_UNSAFE_NAME_RE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")


class UploadError(ValueError):
    """上传内容不可用（编码坏、不是表格、空文件…）——带给用户看的中文原因"""


def _safe_upload_id(upload_id: str) -> str:
    if not _ID_RE.match(upload_id or ""):
        raise UploadError("上传批次标识不合法，请重新上传文件。")
    return upload_id


def _safe_name(name: str) -> str:
    """只取基名并过滤非法字符——上传的文件名是**外部输入**，不能直接当路径用"""
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    safe = _UNSAFE_NAME_RE.sub("_", base)
    if not safe or safe in (".", ".."):
        raise UploadError("文件名不合法，无法保存。")
    return safe


def upload_dir(upload_id: str) -> str:
    return os.path.join(UPLOAD_ROOT, _safe_upload_id(upload_id))


def new_upload_id() -> str:
    return uuid.uuid4().hex[:12]


def kind_of(name: str) -> str | None:
    """按后缀判类型：'csv' / 'md' / None（不支持）"""
    lower = (name or "").lower()
    if lower.endswith(CSV_SUFFIXES):
        return "csv"
    if lower.endswith(MD_SUFFIXES):
        return "md"
    return None


def decode_bytes(raw: bytes, name: str) -> tuple[str, str]:
    """
    统一解码成 UTF-8 文本，返回 (文本, 原始编码名)

    顺序不能反：GBK 几乎能解码任意字节流，先试 GBK 会把 UTF-8 中文读成乱码。
    所以 BOM → 严格 UTF-8 → GBK → 兜底（带替换符，至少让用户看见哪一行坏了）。
    """
    if not raw:
        raise UploadError(f"{name} 是空文件，没有内容可以导入。")
    if len(raw) > MAX_FILE_BYTES:
        raise UploadError(
            f"{name} 超过 {MAX_FILE_BYTES // 1024 // 1024}MB，请先拆分后再上传。"
        )
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig"), "utf-8(BOM)"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gbk"), "gbk"
    except UnicodeDecodeError:
        logger.warning("文件 %s 既不是 UTF-8 也不是 GBK，按 UTF-8 兜底（可能出现替换符）", name)
        return raw.decode("utf-8", errors="replace"), "未知(部分字符已替换)"


def _parse_table(text: str, name: str) -> tuple[list[str], int]:
    """
    真读一遍表格，返回 (列名, 行数)

    与 M1 的差别不只是「准」：M1 按 `\\n` 切行、按第一个分隔符数逗号，
    字段里带换行或带逗号引号就会错位；这里交给 pandas，按 CSV 语法解析。

    delimiter 用嗅探（sep=None + python 引擎）以兼容 `\\t` / `;` 导出的表，
    嗅探失败就退回逗号——宁可读成「一列巨长的名字」，也不要直接报错挡住用户。
    """
    def read(**kw) -> pd.DataFrame:
        return pd.read_csv(io.StringIO(text), **kw)

    try:
        df = read(sep=None, engine="python")
    except Exception as e:  # noqa: BLE001 嗅探失败/解析失败都退回落
        logger.info("表格 %s 分隔符嗅探失败（%s），按逗号读", name, type(e).__name__)
        try:
            df = read(sep=",")
        except Exception as e2:  # noqa: BLE001
            raise UploadError(
                f"{name} 读不出表格结构（{type(e2).__name__}）。"
                "请确认它是逗号/制表符分隔的文本表，且第一行是列名。"
            ) from e2

    columns = [str(c).strip() for c in df.columns]
    if not any(columns):
        raise UploadError(f"{name} 的第一行没有读出列名，无法做字段匹配。")
    return columns, int(len(df))


def _load_meta(dest: str) -> dict:
    """读旁挂元数据；坏了就当没有（它只影响展示，不该让上传批次变得不可用）"""
    path = os.path.join(dest, _META_NAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        logger.warning("上传批次元数据不可读，按缺省处理: %s", path)
        return {}


def _save_meta(dest: str, meta: dict) -> None:
    path = os.path.join(dest, _META_NAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("上传批次元数据写入失败（不影响本次上传）: %s", e)


def save(upload_id: str | None, files: list[tuple[str, bytes]]) -> tuple[str, list[str]]:
    """
    把上传的文件统一转成 UTF-8 落盘，返回 (upload_id, 被拒绝的文件说明)

    同名文件**拒绝而不是覆盖**：多份 CSV 合并是常态（订单表 + 会员表），
    静默覆盖会让用户少了一份数据还不知道。
    """
    uid = _safe_upload_id(upload_id) if upload_id else new_upload_id()
    dest = upload_dir(uid)
    os.makedirs(dest, exist_ok=True)

    # 追加式写入：同一批次可能被上传两三次（用户分批拖文件），元数据要累加而不是覆盖
    meta = _load_meta(dest)
    saved_any = False
    rejected: list[str] = []
    for name, raw in files:
        kind = kind_of(name)
        if kind is None:
            rejected.append(f"{name}（只支持 .csv/.txt 与 .md/.markdown）")
            continue
        try:
            safe = _safe_name(name)
        except UploadError as e:
            rejected.append(f"{name}（{e}）")
            continue
        if os.path.exists(os.path.join(dest, safe)):
            rejected.append(f"{safe}（已存在，跳过）")
            continue

        # 解码与解析都必须**按文件**兜住异常：一次拖进来 6 个文件，其中一个是空的
        # 或编码坏了，另外 5 个不该跟着白传（这里曾经漏兜 decode_bytes，
        # 结果是「明明传了 4 个，只有一个没进去，另外 3 个也没了」）。
        try:
            text, encoding = decode_bytes(raw, safe)
        except UploadError as e:
            rejected.append(str(e))   # 这些提示自带文件名，直接展示
            continue
        try:
            if kind == "csv":
                columns, rows = _parse_table(text, safe)
                logger.info("[上传] %s: %d 行 / %d 列（原始编码 %s）", safe, rows, len(columns), encoding)
            else:
                logger.info("[上传] %s: %d 字符（原始编码 %s）", safe, len(text), encoding)
        except UploadError as e:
            rejected.append(str(e))
            continue

        # 一律写 utf-8-sig（带 BOM）：与 ingest_data 的读取口径一致，Excel 打开也不乱码
        with open(os.path.join(dest, safe), "w", encoding="utf-8-sig", newline="") as f:
            f.write(text)
        meta[safe] = {"encoding": encoding, "original_name": name, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        saved_any = True

    if saved_any:
        _save_meta(dest, meta)

    return uid, rejected


def paths(upload_id: str) -> tuple[list[str], list[str]]:
    """
    列出该批次已落盘的 (csv 路径, md 路径)，按文件名排序

    排序是为了「同一次上传，重跑结果一致」——构建要用它、指纹比对也依赖它。
    """
    dest = upload_dir(upload_id)
    if not os.path.isdir(dest):
        raise UploadError("上传内容不存在或已被清理，请回到第 1 步重新上传。")
    csvs, mds = [], []
    for name in sorted(os.listdir(dest)):
        if kind_of(name) == "csv":
            csvs.append(os.path.join(dest, name))
        elif kind_of(name) == "md":
            mds.append(os.path.join(dest, name))
    return csvs, mds


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def scan(upload_id: str) -> dict:
    """
    重扫磁盘得出该批次的内容清单（**不依赖进程内存**）

    每次调用都重新解析表格：文件量级是几十 MB 以内，解析一次不到一秒，
    换来的是「服务重启后用户上传的东西还在」。真到性能瓶颈（或上传量级变大）时，
    再加缓存层，而不是先加缓存再想为什么状态会丢。
    """
    csvs, mds = paths(upload_id)
    meta = _load_meta(upload_dir(upload_id))
    csv_files = []
    md_files = []
    for path in csvs:
        name = os.path.basename(path)
        text = read_text(path)
        columns, rows = _parse_table(text, name)
        csv_files.append({
            "name": name,
            "size": os.path.getsize(path),
            # 回的是**原始**编码（盘上那份已经是 UTF-8）：用户要看到的是
            # 「他给的文件是什么格式、我们替他转好了」，不是我们内部存成什么
            "encoding": (meta.get(name) or {}).get("encoding", "utf-8"),
            "row_count": rows,
            "columns": columns,
        })
    for path in mds:
        name = os.path.basename(path)
        text = read_text(path)
        md_files.append({
            "name": name,
            "size": os.path.getsize(path),
            "encoding": (meta.get(name) or {}).get("encoding", "utf-8"),
            # 标题统计与分块预估由调用方用真实切分器算（见 app._analyze_docs），
            # 这里只回传文本长度，避免把正文搬来搬去
            "chars": len(text),
        })
    return {"upload_id": upload_id, "csv_files": csv_files, "md_files": md_files}


def remove(upload_id: str, name: str) -> None:
    """删掉批次里的一个文件；删光了就连目录一起清掉（不留空批次）"""
    dest = upload_dir(upload_id)
    safe = _safe_name(name)
    target = os.path.join(dest, safe)
    if not os.path.isfile(target):
        raise UploadError(f"{name} 不在这个上传批次里。")
    os.remove(target)

    meta = _load_meta(dest)
    if meta.pop(safe, None) is not None:
        _save_meta(dest, meta)

    # 判空要**忽略元数据文件**：只看目录里还有没有东西的话，
    # 删完最后一个数据文件后目录会带着一个 _meta.json 永远留下
    csvs, mds = paths(upload_id)
    if not csvs and not mds:
        shutil.rmtree(dest, ignore_errors=True)
