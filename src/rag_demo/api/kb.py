#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Vincent
@File    : kb.py
@Function: 企业后台接口（M3）——知识库概况 / 清空 / 邀请码 / 企业总览

本模块是 `_contract_m3.md` 的 A、B、C、E 四节的实现：

    GET  /api/kb/overview                    知识库概况（登录即可读）
    POST /api/kb/clear                       清空整个租户数据空间（仅企业管理员）
    POST /admin/enterprise/invite-code/reset 重置邀请码（企业管理员=本企业，系统管理员=指定企业）
    GET  /admin/enterprises                  企业总览（仅系统管理员）

两条红线（整个 M3 不可协商）：

1. **读哪个库只能由登录账号推导**。四个接口都不接受 dataset / tenant_id 参数；
   目标数据空间一律来自 `main._tenant_dataset()`（系统管理员→demo，企业账号→本企业库）。
   连 `/api/kb/clear` 的 `confirm` 也只做「与推导出的库名比对」，
   不存在「请求体里写一个库名就能清另一个库」的路径。
2. **不硬编码业务事实**。文档数、切片数、构建时间、成员数、邀请码、库状态
   全部运行时从库/接口取；本模块里出现的字符串只有错误文案与人话说明。

为什么拆成独立模块：`api/main.py` 已经承担问答/权限/缓存多条线，
企业后台是又一条独立业务线。单独一个文件让注册入口（`register_kb`）
与实现放在一起，和 M2 的向导（`api/wizard.py`）是同一套组织方式。

循环导入说明：本模块由 `api/main.py` 在模块顶层 import（为了注册路由），
因此**不能**在顶层 import `rag_demo.api.main` 里的助手函数（那时 main 还没定义完）。
统一用 `_main()` 延迟导入——导入发生在请求内，`sys.modules` 查表，没有额外成本。
"""
import hashlib
import logging
import re

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from rag_demo import auth
from rag_demo.kb_stats import (
    UNKNOWN,
    docs_from_rows,
    freshness_payload,
    last_source_from,
    totals_from,
    validate_clear_confirm,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["kb"])


def register_kb(app: FastAPI) -> None:
    """
    把企业后台接口注册到正式服务

    调用位置在 `api/main.py` 里、与 `register_wizard` 同级：
    都在既有 `/static` 挂载之前（路由注册顺序对静态挂载有影响，见 main.py 的注释）。
    """
    app.include_router(router)


def _main():
    """
    延迟导入 `rag_demo.api.main`（取登录/租户推导等唯一真源）

    不用 `from rag_demo.api.main import _tenant_dataset`：那会在 main 模块
    还未执行完时触发循环导入。请求内 `from rag_demo.api import main` 拿的是
    已经初始化完成的模块对象。
    """
    from rag_demo.api import main

    return main


# ==================== 请求模型 ====================
class ClearRequest(BaseModel):
    """
    清空请求：**只有 confirm 一个字段**

    目标数据空间只能由登录账号推导（红线），所以这里刻意不声明 dataset /
    tenant_id 之类字段。Pydantic 默认忽略未声明字段，老前端多传的库名会被
    静默忽略，不会改变清空目标——这正是「不允许前端指定库」的实现方式。
    """

    confirm: str | None = None


class InviteResetRequest(BaseModel):
    """
    邀请码重置请求

    - 企业管理员：字段被忽略（只能重置本企业，传别人的 id 会 403）
    - 系统管理员：必须传，否则 400
    """

    enterprise_id: int | None = None


# ==================== 工具 ====================
def _upload_available(upload_id) -> bool:
    """上传目录里的源文件是否还在（last_source.available：不在就提示重新导入）"""
    if not upload_id:
        return False
    from rag_demo.mvp import uploads

    try:
        csv_paths, md_paths = uploads.paths(str(upload_id))
    except uploads.UploadError:
        return False
    except Exception as e:  # noqa: BLE001 磁盘/权限异常也不该让概况页整页 500
        logger.warning("检查上传批次文件失败（%s）: %s", upload_id, e)
        return False
    return bool(csv_paths or md_paths)


def _dataset_last_build_at(dataset: str) -> str | None:
    """
    读某个数据集的最近构建时间（企业总览用）

    库不存在 / 未注册 / meta 缺失都返回 None：企业总览是「全部企业」的列表，
    不能因为其中一家还没建库就让整个页面 500。
    必须在 use_dataset + finally reset_dataset 内读：读连接靠 contextvar 选库，
    漏掉 reset 会让同一线程上的下一个请求继续读这家企业的库。
    """
    if not dataset:
        return None
    from rag_demo.db.connection import reset_dataset, use_dataset
    from rag_demo.db.schema import read_last_build

    token = None
    try:
        token = use_dataset(dataset)
        return (read_last_build() or {}).get("at")
    except Exception as e:  # noqa: BLE001 库不存在 / 未注册 / meta 读失败
        logger.info("企业最近构建时间不可读（%s）: %s", dataset, e)
        return None
    finally:
        if token is not None:
            reset_dataset(token)


def _reset_bm25_after_clear(dataset: str) -> None:
    """
    清空后刷新 BM25 内存索引

    正常路径：索引表被清空 → `reload_bm25` 会因「语料为空」抛错（空库本来就不能问，
    这是预期状态）。但**内存里可能还留着清空前的旧索引**，不丢掉就会出现
    「数据已经清空了，关键词召回还能捞出旧文档」——这类静默串数据是最难查的。
    所以重建失败时手动把该数据集的缓存摘掉，等下次构建成功后再由 reload_bm25 建回来。
    """
    from rag_demo.retrieval import hybrid_retriever

    try:
        hybrid_retriever.reload_bm25(dataset)
    except Exception as e:  # noqa: BLE001 空语料 / 表不存在都属「清空后的预期状态」
        hybrid_retriever._bm25.pop(dataset, None)  # noqa: SLF001 内存索引是模块级 dict
        hybrid_retriever._bm25_corpus.pop(dataset, None)  # noqa: SLF001
        logger.info("清空后 BM25 内存索引已丢弃（空语料无法重建）: %s（%s）", dataset, e)


# ==================== A. 知识库概况 ====================
_DEMO_READONLY_REASON = (
    "演示数据集是评测基线，只读；要操作企业库请用企业管理员账号登录"
)
_EMPLOYEE_READONLY_REASON = "只有企业管理员可以重建或清空数据"


@router.get("/api/kb/overview")
def kb_overview() -> dict:
    """
    知识库概况（登录即可读）

    接口不接受任何参数：读哪个库由 `main._tenant_dataset()` 按登录账号推导。
    未构建的企业库**不报错**，而是 200 + ready=false——「还没有数据」与
    「你没有权限」是两件完全不同的事，页面要能分别展示（前者引导去构建）。

    查询全部在 `use_dataset(dataset)` 作用域内，finally 还原 contextvar；
    这里不能复用 `main._tenant_scope()`：它在库未就绪时会抛 403，
    而本接口需要 200 + ready=false。
    """
    api = _main()
    account = api._require_login()
    dataset = api._tenant_dataset()

    system_admin = bool(account and account.get("is_system_admin"))
    enterprise_admin = bool(account and account.get("is_enterprise_admin"))
    # 系统管理员看的是 demo（没有「自己的企业」）；企业账号看本企业库
    mode = "demo" if (system_admin or account is None) else "enterprise"
    can_write = enterprise_admin
    if can_write:
        readonly_reason = None
    elif mode == "demo":
        readonly_reason = _DEMO_READONLY_REASON
    else:
        readonly_reason = _EMPLOYEE_READONLY_REASON
    notes = ["演示数据集是评测基线，只读"] if mode == "demo" else []

    ready = bool(api._tenant_ready(dataset))
    docs: list[dict] = []
    totals = totals_from([], 0)
    built_at = None
    freshness = freshness_payload(UNKNOWN, "当前租户数据空间尚未构建，无法判定索引新鲜度")
    last_source = None

    if ready:
        from rag_demo.db.connection import get_conn, reset_dataset, use_dataset
        from rag_demo.db.schema import index_freshness, read_fingerprint, read_last_build

        token = use_dataset(dataset)
        try:
            # 文档矩阵 + 画像规模：与 /stats 同一口径，但只取概况需要的列
            conn = get_conn()
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT doc_name, COUNT(*), SUM(length(chunk_text)) FROM wiki_vectors "
                    "GROUP BY doc_name ORDER BY COUNT(*) DESC, doc_name ASC"
                )
                docs = docs_from_rows(cur.fetchall())

                cur.execute("SELECT COUNT(*) FROM user_profile_vectors")
                profiles = cur.fetchone()[0]
            finally:
                conn.rollback()  # 清查询事务，避免连接停在 idle in transaction
                cur.close()
            totals = totals_from(docs, profiles)

            # 构建时间 + 新鲜度：判定逻辑在 db/schema.py，这里只负责降级
            try:
                fresh = index_freshness()
                built_at = (fresh.get("stored") or {}).get("built_at")
                freshness = freshness_payload(fresh.get("status"), fresh.get("reason"))
            except Exception as e:  # noqa: BLE001 检查失败要降级成 unknown，而不是 500
                logger.warning("索引新鲜度读取失败（%s）: %s", dataset, e)
                freshness = freshness_payload(UNKNOWN, f"索引新鲜度读取失败：{e}")
                try:
                    built_at = (read_fingerprint() or {}).get("built_at")
                except Exception:  # noqa: BLE001
                    built_at = None

            # 最近一次构建的源（重建用）；available=false 时前端应提示重新导入
            try:
                last_build = read_last_build()
            except Exception as e:  # noqa: BLE001
                logger.warning("last_build 读取失败（%s）: %s", dataset, e)
                last_build = None
            if last_build:
                last_source = last_source_from(
                    last_build, _upload_available(last_build.get("upload_id"))
                )
        finally:
            reset_dataset(token)

    return {
        "dataset": dataset,
        "mode": mode,
        "ready": ready,
        "empty": bool(ready and totals["chunks"] + totals["profiles"] == 0),
        "can_write": can_write,
        "readonly_reason": readonly_reason,
        "totals": totals,
        "docs": docs,
        "built_at": built_at,
        "freshness": freshness,
        "last_source": last_source,
        "notes": notes,
    }


# ==================== A2. 画像卡牌 / 文档切片预览 ====================
_NAME_RE = re.compile(r"用户[^（(]*[（(]([^）)]{1,24})[）)]")
_PROFILE_PAGE_SIZE = 20
_DOC_CHUNK_LIMIT = 500


def mask_profile_name(profile_text: str) -> str | None:
    """从 profile_text 提取姓名并脱敏：张三 → 张**；不返回完整姓名。"""
    match = _NAME_RE.search(profile_text or "")
    if not match:
        return None
    name = match.group(1).strip()
    if not name:
        return None
    return name[:1] + "**" if len(name) > 1 else name + "**"


def doc_id_for(name: str) -> str:
    """文档名 → 稳定、URL 安全的短 ID；不把原始文件名直接暴露在路径里。"""
    return hashlib.sha1((name or "").encode("utf-8")).hexdigest()[:16]


def normalize_page(page: int, size: int) -> tuple[int, int]:
    return max(1, int(page or 1)), min(50, max(1, int(size or _PROFILE_PAGE_SIZE)))


def _profile_row(row) -> dict:
    user_id, profile_text, age, gender, city, member_level, order_count, avg_amount, top_category, days_since_last_buy = row
    return {
        "user_id": user_id,
        "name": mask_profile_name(profile_text),
        "age": age,
        "gender": gender,
        "city": city,
        "member_level": member_level,
        "order_count": int(order_count or 0),
        "avg_amount": round(float(avg_amount), 2) if avg_amount is not None else None,
        "top_category": top_category,
        "days_since_last_buy": days_since_last_buy,
    }


@router.get("/api/kb/profiles")
def kb_profiles(page: int = 1, size: int = _PROFILE_PAGE_SIZE) -> dict:
    """当前账号数据空间的画像卡牌（只读、分页；不返回 profile_text/embedding）。"""
    api = _main()
    api._require_login()
    dataset = api._tenant_dataset()
    page, size = normalize_page(page, size)
    result = {
        "dataset": dataset,
        "ready": False,
        "page": page,
        "size": size,
        "total": 0,
        "total_pages": 0,
        "items": [],
    }
    if not api._tenant_ready(dataset):
        return result

    from rag_demo.db.connection import get_conn, reset_dataset, use_dataset

    token = use_dataset(dataset)
    try:
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM user_profile_vectors")
            total = int(cur.fetchone()[0] or 0)
            cur.execute(
                """SELECT user_id, profile_text, age, gender, city, member_level,
                          order_count, avg_amount::float8, top_category, days_since_last_buy
                   FROM user_profile_vectors
                   ORDER BY user_id ASC
                   LIMIT %s OFFSET %s""",
                (size, (page - 1) * size),
            )
            items = [_profile_row(row) for row in cur.fetchall()]
        finally:
            conn.rollback()
            cur.close()
    except Exception as exc:  # noqa: BLE001
        logger.exception("画像卡牌读取失败 dataset=%s", dataset)
        raise HTTPException(status_code=500, detail=f"画像数据读取失败：{exc}") from exc
    finally:
        reset_dataset(token)

    return {
        **result,
        "ready": True,
        "total": total,
        "total_pages": (total + size - 1) // size if total else 0,
        "items": items,
    }


@router.get("/api/kb/documents")
def kb_documents() -> dict:
    """当前账号数据空间的文档列表（不返回 chunk_text 全文）。"""
    api = _main()
    api._require_login()
    dataset = api._tenant_dataset()
    result = {"dataset": dataset, "ready": False, "items": []}
    if not api._tenant_ready(dataset):
        return result

    from rag_demo.db.connection import get_conn, reset_dataset, use_dataset

    token = use_dataset(dataset)
    try:
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """SELECT doc_name, COUNT(*), SUM(length(chunk_text)), MAX(update_time)
                   FROM wiki_vectors
                   GROUP BY doc_name
                   ORDER BY COUNT(*) DESC, doc_name ASC"""
            )
            items = [
                {
                    "doc_id": doc_id_for(row[0]),
                    "name": row[0],
                    "chunks": int(row[1] or 0),
                    "chars": int(row[2] or 0),
                    "updated_at": row[3].strftime("%Y-%m-%d %H:%M:%S") if row[3] else None,
                }
                for row in cur.fetchall()
            ]
        finally:
            conn.rollback()
            cur.close()
    except Exception as exc:  # noqa: BLE001
        logger.exception("文档列表读取失败 dataset=%s", dataset)
        raise HTTPException(status_code=500, detail=f"文档列表读取失败：{exc}") from exc
    finally:
        reset_dataset(token)

    return {**result, "ready": True, "items": items}


@router.get("/api/kb/documents/{doc_id}/chunks")
def kb_document_chunks(doc_id: str) -> dict:
    """按 doc_id 取当前数据空间的切片；doc_id 只是文档名的哈希，不是任意查询入口。"""
    api = _main()
    api._require_login()
    dataset = api._tenant_dataset()
    if not api._tenant_ready(dataset):
        return {"dataset": dataset, "ready": False, "document": None, "items": [], "total": 0, "truncated": False}

    from rag_demo.db.connection import get_conn, reset_dataset, use_dataset

    token = use_dataset(dataset)
    try:
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT DISTINCT doc_name FROM wiki_vectors")
            names = [row[0] for row in cur.fetchall() if row[0]]
            matched = next((name for name in names if doc_id_for(name) == doc_id), None)
            if matched is None:
                raise HTTPException(status_code=404, detail="文档不存在或不属于当前数据空间")
            cur.execute("SELECT COUNT(*), COALESCE(SUM(length(chunk_text)), 0) FROM wiki_vectors WHERE doc_name = %s", (matched,))
            total, chars = cur.fetchone()
            total = int(total or 0)
            cur.execute(
                """SELECT id, chunk_text, length(chunk_text), parent_key
                   FROM wiki_vectors
                   WHERE doc_name = %s
                   ORDER BY id ASC
                   LIMIT %s""",
                (matched, _DOC_CHUNK_LIMIT),
            )
            items = [
                {
                    "chunk_index": index,
                    "id": row[0],
                    "text": row[1],
                    "chars": int(row[2] or len(row[1] or "")),
                    "parent_key": row[3],
                }
                for index, row in enumerate(cur.fetchall(), 1)
            ]
        finally:
            conn.rollback()
            cur.close()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("文档切片读取失败 dataset=%s doc_id=%s", dataset, doc_id)
        raise HTTPException(status_code=500, detail=f"文档切片读取失败：{exc}") from exc
    finally:
        reset_dataset(token)

    return {
        "dataset": dataset,
        "ready": True,
        "document": {"doc_id": doc_id, "name": matched, "chunks": total, "chars": int(chars or 0)},
        "items": items,
        "total": total,
        "truncated": total > len(items),
    }


# ==================== A3. 原文阅读 + 构建历史 ====================
@router.get("/api/kb/docs/{doc_id}/raw")
def kb_document_raw(doc_id: str) -> dict:
    """返回当前数据空间某篇文档的原始 Markdown；找不到源文件时用切片拼回并标记。"""
    api = _main()
    api._require_login()
    dataset = api._tenant_dataset()
    if not api._tenant_ready(dataset):
        return {"dataset": dataset, "ready": False, "document": None}

    from pathlib import Path

    from rag_demo.db.connection import get_conn, reset_dataset, use_dataset
    from rag_demo.db.schema import read_last_build
    from rag_demo.mvp import uploads

    token = use_dataset(dataset)
    try:
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT DISTINCT doc_name FROM wiki_vectors")
            names = [row[0] for row in cur.fetchall() if row[0]]
            matched = next((name for name in names if doc_id_for(name) == doc_id), None)
            if matched is None:
                raise HTTPException(status_code=404, detail="文档不存在或不属于当前数据空间")

            content = None
            source = None
            # 1) 上传批次的原始 Markdown（企业用户的真实来源）
            try:
                last_build = read_last_build() or {}
                upload_id = last_build.get("upload_id")
                if upload_id:
                    _, md_paths = uploads.paths(upload_id)
                    for path in md_paths:
                        if Path(path).name == matched:
                            content = Path(path).read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
                            source = "upload"
                            break
            except Exception as exc:  # noqa: BLE001 源文件不可用不应阻断阅读
                logger.info("原文读取：上传源不可用（%s）：%s", dataset, exc)

            # 2) demo / 仓库自带文档目录
            if content is None:
                from rag_demo.config import BASE_DIR

                candidate = Path(BASE_DIR) / "data" / "docs" / matched
                if candidate.is_file():
                    content = candidate.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
                    source = "repo_docs"

            # 3) 最后兜底：用已入库切片按顺序拼回（明确标记非原始文件）
            if content is None:
                cur.execute("SELECT chunk_text FROM wiki_vectors WHERE doc_name = %s ORDER BY id ASC", (matched,))
                content = "\n\n".join(row[0] or "" for row in cur.fetchall())
                source = "chunks_reconstructed"
        finally:
            conn.rollback()
            cur.close()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("原文读取失败 dataset=%s doc_id=%s", dataset, doc_id)
        raise HTTPException(status_code=500, detail=f"原文读取失败：{exc}") from exc
    finally:
        reset_dataset(token)

    return {
        "dataset": dataset,
        "ready": True,
        "document": {
            "doc_id": doc_id,
            "name": matched,
            "content": content or "",
            "source": source,
        },
    }


@router.get("/api/kb/history")
def kb_history() -> dict:
    """当前数据空间的构建流水；旧库无历史表时从 last_build 降级成一条。"""
    api = _main()
    api._require_login()
    dataset = api._tenant_dataset()
    result = {"dataset": dataset, "ready": False, "items": []}
    if not api._tenant_ready(dataset):
        return result

    from rag_demo.db.connection import get_conn, reset_dataset, use_dataset
    from rag_demo.db.schema import ensure_build_history, read_fingerprint, read_last_build

    token = use_dataset(dataset)
    try:
        conn = get_conn()
        cur = conn.cursor()
        try:
            ensure_build_history(cur)
            conn.commit()
            cur.execute(
                """SELECT built_at, mode, elapsed_s, rows, profiles, status, error
                   FROM build_history
                   ORDER BY built_at DESC, id DESC
                   LIMIT 50"""
            )
            items = [
                {
                    "built_at": row[0].strftime("%Y-%m-%d %H:%M:%S") if row[0] else None,
                    "mode": row[1],
                    "elapsed_s": float(row[2]) if row[2] is not None else None,
                    "rows": row[3],
                    "profiles": row[4],
                    "status": row[5] or "success",
                    "error": row[6],
                }
                for row in cur.fetchall()
            ]
            if not items:
                # 旧数据空间没有历史表：用 last_build 给出一条“最近构建”，并标记来源
                try:
                    last = read_last_build()
                except Exception:  # noqa: BLE001
                    last = None
                if last:
                    items = [{
                        "built_at": last.get("at"),
                        "mode": last.get("mode") or "full",
                        "elapsed_s": last.get("elapsed_s"),
                        "rows": last.get("rows"),
                        "profiles": last.get("profiles"),
                        "status": "success",
                        "error": None,
                        "note": "历史表为空，显示最近一次构建",
                    }]
                if not items:
                    # 连 last_build 都没有（例如仓库自带 demo 基线）：用索引指纹的 built_at 回填
                    try:
                        fp = read_fingerprint() or {}
                    except Exception:  # noqa: BLE001
                        fp = {}
                    if fp.get("built_at"):
                        items = [{
                            "built_at": fp.get("built_at"),
                            "mode": "full",
                            "elapsed_s": None,
                            "rows": fp.get("profile_count"),
                            "profiles": fp.get("profile_count"),
                            "status": "success",
                            "error": None,
                            "note": "历史表为空，按当前索引构建时间回填",
                        }]
        finally:
            conn.rollback()
            cur.close()
    except Exception as exc:  # noqa: BLE001
        logger.exception("构建历史读取失败 dataset=%s", dataset)
        raise HTTPException(status_code=500, detail=f"构建历史读取失败：{exc}") from exc
    finally:
        reset_dataset(token)

    return {**result, "ready": True, "items": items}


# ==================== B. 清空数据空间 ====================
_CLEAR_EMPTY = "当前租户数据为空，无需清空"
_CLEAR_BUSY = (
    "数据集正忙：可能有一次构建正在进行，或有人正在提问（一次问答要十几秒）。"
    "等这次操作结束后再清空。"
)


@router.post("/api/kb/clear")
def kb_clear(payload: ClearRequest | None = None) -> dict:
    """
    清空整个租户数据空间（仅企业管理员）

    顺序即权限顺序：
        401 未登录 → 403 非企业管理员 → 400 confirm 不符 → 409 空库/正忙 → 执行。

    写路径的三道保护缺一不可：
        `_tenant_dataset()`   决定写哪个库（不接受请求参数，红线）
        `writes_to(dataset)`  声明作用域（没有声明时 require_write_scope 直接拒绝）
        `dataset_lock`        非阻塞试探成功后**整段持有**（构建/问答与清空互斥）

    清空只 TRUNCATE 数据表 + 删指纹类 meta 键，**保留** last_build / ui_* /
    doc_source_dir：清空的是数据，不是「这个数据空间怎么用」。
    """
    from rag_demo.db.connection import dataset_lock, get_conn, writes_to
    from rag_demo.db.schema import dataset_counts, truncate_dataset_data

    api = _main()
    account = api._require_login()
    if account is None:
        raise HTTPException(
            status_code=403, detail="该接口需要登录态（当前为离线脚本模式），无法清空数据"
        )
    if not account.get("is_enterprise_admin"):
        if account.get("is_system_admin"):
            # 系统管理员清的是 demo（评测基线），必须明确拒绝
            raise HTTPException(
                status_code=403,
                detail="演示数据集是评测基线，只读，不能清空；要清空企业库请用企业管理员账号登录",
            )
        raise HTTPException(status_code=403, detail="只有企业管理员可以清空数据")

    dataset = api._tenant_dataset()
    confirm_error = validate_clear_confirm(
        getattr(payload, "confirm", None) if payload is not None else None, dataset
    )
    if confirm_error is not None:
        raise HTTPException(status_code=400, detail=confirm_error)

    # 非阻塞试探：拿不到锁说明有构建在跑，或有人正持锁提问。
    # 注意锁要在「判断库是否已建」**之前**拿：_tenant_ready 会读库，而构建线程
    # 正在用同一条 psycopg2 连接（它非线程安全），先拿锁才能避免并发读写撞车。
    try:
        lock = dataset_lock(dataset)
    except Exception as e:  # noqa: BLE001 数据集未注册（企业记录被删）按「没有数据」处理
        logger.info("清空目标数据集不可用（%s）: %s", dataset, e)
        raise HTTPException(status_code=409, detail=_CLEAR_EMPTY) from e
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=_CLEAR_BUSY)

    try:
        if not api._tenant_ready(dataset):
            raise HTTPException(status_code=409, detail=_CLEAR_EMPTY)
        with writes_to(dataset):
            conn = get_conn()
            cur = conn.cursor()
            try:
                counts = dataset_counts(cur)
                if counts["profiles"] == 0 and counts["chunks"] == 0 and counts["index"] == 0:
                    conn.rollback()
                    raise HTTPException(status_code=409, detail=_CLEAR_EMPTY)
                # TRUNCATE 与 meta 删除同一事务提交：不留「表清了、指纹还在」的中间态
                truncate_dataset_data(cur)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                cur.close()
    finally:
        lock.release()

    # 锁已释放：下面两步只动内存态（问答缓存 + BM25 索引），不影响库的一致性
    from rag_demo.cache import answer_cache

    _reset_bm25_after_clear(dataset)
    answer_cache.clear()
    logger.info("已清空租户数据空间: %s by %s", dataset, account.get("username") or "-")
    return {
        "status": "cleared",
        "dataset": dataset,
        "cleared": {
            "profiles": counts["profiles"],
            "chunks": counts["chunks"],
            "docs": counts["docs"],
            "index": counts["index"],
        },
    }


# ==================== C. 重置邀请码 ====================
_INVITE_CODE_RETRY = 5


def _rotate_enterprise_invite(enterprise_id: int) -> dict:
    """
    生成新邀请码并写回企业表；唯一冲突重试 ≤ 5 次

    旧码**立即失效**：注册时 `auth.find_enterprise_by_code` 直接查库，
    这里没有缓存层，所以更新提交的那一刻旧码就查不到了。
    """
    import psycopg2.errors

    for attempt in range(1, _INVITE_CODE_RETRY + 1):
        code = auth._new_invite_code()  # noqa: SLF001 邀请码规则由 auth 唯一维护
        try:
            with auth._cursor() as cur:  # noqa: SLF001 复用 auth 的事务/连接池
                cur.execute(
                    "UPDATE enterprise SET invite_code = %s WHERE id = %s",
                    (code, int(enterprise_id)),
                )
                changed = cur.rowcount
        except psycopg2.errors.UniqueViolation:
            logger.warning(
                "邀请码唯一冲突（第 %d/%d 次），重新生成: enterprise=%s",
                attempt, _INVITE_CODE_RETRY, enterprise_id,
            )
            continue
        if not changed:
            raise HTTPException(status_code=404, detail="企业不存在")
        enterprise = auth.find_enterprise(int(enterprise_id))
        if enterprise is None:
            raise HTTPException(status_code=404, detail="企业不存在")
        return enterprise
    raise HTTPException(
        status_code=409,
        detail="邀请码重置失败：连续生成到重复值，请稍后重试",
    )


@router.post("/admin/enterprise/invite-code/reset")
def reset_invite_code(payload: InviteResetRequest | None = None) -> dict:
    """
    重置邀请码

    - 企业管理员：只能重置**本企业**的码。请求体里的 enterprise_id 会被忽略；
      若传了一个不是本企业的 id → 403（不能因为「反正会忽略」就静默接受）。
    - 系统管理员：必须显式指定 enterprise_id（否则 400），企业不存在 → 404。
    """
    api = _main()
    account = api._require_login()
    if account is None:
        raise HTTPException(
            status_code=403, detail="该接口需要登录态（当前为离线脚本模式）"
        )
    requested = getattr(payload, "enterprise_id", None) if payload is not None else None

    if account.get("is_system_admin"):
        if requested is None:
            raise HTTPException(
                status_code=400,
                detail="系统管理员必须指定 enterprise_id（要重置哪家企业的邀请码）",
            )
        enterprise = auth.find_enterprise(int(requested))
        if enterprise is None:
            raise HTTPException(status_code=404, detail=f"企业不存在: {requested}")
    elif account.get("is_enterprise_admin"):
        own_id = account.get("enterprise_id")
        if not own_id:
            raise HTTPException(
                status_code=403, detail="该账号还没有绑定企业，无法重置邀请码"
            )
        if requested is not None and int(requested) != int(own_id):
            raise HTTPException(status_code=403, detail="只能管理本企业的邀请码")
        enterprise = auth.find_enterprise(int(own_id))
        if enterprise is None:
            raise HTTPException(status_code=404, detail="企业不存在")
    else:
        raise HTTPException(status_code=403, detail="只有企业管理员可以重置邀请码")

    updated = _rotate_enterprise_invite(int(enterprise["id"]))
    logger.info(
        "邀请码已重置: enterprise=%s(%s) actor=%s",
        updated.get("name"), updated.get("id"), account.get("username"),
    )
    return {
        "enterprise": {
            key: updated.get(key) for key in ("id", "name", "dataset", "invite_code")
        }
    }


# ==================== E. 企业总览 ====================
@router.get("/admin/enterprises")
def list_enterprises_overview() -> dict:
    """
    企业总览（仅系统管理员）

    成员数 / 待审核 / 停用**一次取回全部账号后再聚合**（`auth.list_users(None)`），
    不按企业逐个查询——企业多了就是 N+1，而这只是打开后台首页的一次请求。

    `dataset_ready` / `last_build_at` 每家企业各查一次，异常一律降级：
    一家企业的库没建好，不该让整张企业列表 500。
    """
    api = _main()
    account = api._require_login()
    if account is None or not account.get("is_system_admin"):
        # 文案按契约固定：企业管理员 / 员工看到的是同一句
        raise HTTPException(status_code=403, detail="仅系统管理员可查看全部企业")

    enterprises = auth.list_enterprises()
    users = auth.list_users(None)

    # enterprise_id -> 该企业的成员/待审核/停用计数（系统管理员没有企业，跳过）
    by_enterprise: dict[int, dict[str, int]] = {}
    for user in users:
        enterprise_id = user.get("enterprise_id")
        if enterprise_id is None:
            continue
        bucket = by_enterprise.setdefault(
            int(enterprise_id), {"members": 0, "pending": 0, "disabled": 0}
        )
        bucket["members"] += 1
        if user.get("status") == auth.STATUS_PENDING:
            bucket["pending"] += 1
        elif user.get("status") == auth.STATUS_DISABLED:
            bucket["disabled"] += 1

    rows: list[dict] = []
    totals = {"enterprises": len(enterprises), "members": 0, "pending": 0}
    for enterprise in enterprises:
        dataset = enterprise.get("dataset") or ""
        stats = by_enterprise.get(
            int(enterprise["id"]), {"members": 0, "pending": 0, "disabled": 0}
        )
        rows.append(
            {
                "id": enterprise.get("id"),
                "name": enterprise.get("name"),
                "dataset": dataset,
                "invite_code": enterprise.get("invite_code"),
                "created_at": enterprise.get("created_at"),
                "dataset_ready": api._tenant_ready(dataset) if dataset else False,
                "members": stats["members"],
                "pending": stats["pending"],
                "disabled": stats["disabled"],
                "last_build_at": _dataset_last_build_at(dataset),
            }
        )
        totals["members"] += stats["members"]
        totals["pending"] += stats["pending"]

    return {"enterprises": rows, "totals": totals}
