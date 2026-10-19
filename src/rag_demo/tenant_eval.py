# -*- coding: utf-8 -*-
"""企业侧离线评测：题库存储、运行状态、LLM-as-a-Judge 执行。

设计约束：
- 题库与运行结果都按 dataset 分目录：``data/eval/<dataset>/...``；前端不能传 dataset，
  由登录账号推导（与 /qa、/kb 同一条红线）。
- 运行中的任务只在本进程内；结果落盘后重启仍可查看。进程重启时遗留的 running
  状态由读取端标记为 interrupted，避免页面永远转圈。
- 本模块不依赖 FastAPI，便于单测。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from rag_demo import config
from rag_demo.eval_utils import (
    build_judge_messages,
    parse_judge_json,
    render_markdown_report,
    source_recall,
    summarize_results,
    unique_sources,
)

EVAL_ROOT = Path(os.environ.get("RAG_EVAL_DATA_DIR") or (Path(config.BASE_DIR) / "data" / "eval"))
DATASET_RE = re.compile(r"^[A-Za-z0-9_]+$")
SET_ID_RE = re.compile(r"^qs_[a-f0-9]{12}$")
RUN_ID_RE = re.compile(r"^run_[a-f0-9]{12}$")
MAX_QUESTIONS = 50
MAX_QUESTION_CHARS = 500
MAX_ACCEPTANCE_CHARS = 1500
MAX_NAME_CHARS = 80
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "deepseek-chat")


class EvalInputError(ValueError):
    """客户端提交的题库/参数不合法。"""


# 本进程内正在跑的任务。读取端据此区分「真的还在跑」和「服务重启后的僵尸 running」。
ACTIVE_RUNS: set[str] = set()


def mark_active(run_id: str) -> None:
    ACTIVE_RUNS.add(run_id)


def mark_inactive(run_id: str) -> None:
    ACTIVE_RUNS.discard(run_id)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _atomic_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dataset_dir(dataset: str) -> Path:
    if not DATASET_RE.match(dataset or ""):
        raise EvalInputError("数据集名不合法")
    return EVAL_ROOT / dataset


def validate_questions(raw: object) -> list[dict]:
    """把前端上传的题库规范化为内部结构；不合法直接抛 EvalInputError。"""
    if isinstance(raw, dict):
        raw = raw.get("questions")
    if not isinstance(raw, list) or not raw:
        raise EvalInputError("题库必须是非空 JSON 数组")
    if len(raw) > MAX_QUESTIONS:
        raise EvalInputError(f"单次最多 {MAX_QUESTIONS} 道题")
    out: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise EvalInputError(f"第 {index} 题必须是对象")
        qid = str(item.get("id") or "").strip()
        question = str(item.get("question") or "").strip()
        acceptance = str(item.get("acceptance") or "").strip()
        if not qid or not question or not acceptance:
            raise EvalInputError(f"第 {index} 题缺少 id / question / acceptance")
        if qid in seen:
            raise EvalInputError(f"题号重复：{qid}")
        if len(question) > MAX_QUESTION_CHARS:
            raise EvalInputError(f"第 {index} 题 question 超过 {MAX_QUESTION_CHARS} 字")
        if len(acceptance) > MAX_ACCEPTANCE_CHARS:
            raise EvalInputError(f"第 {index} 题 acceptance 超过 {MAX_ACCEPTANCE_CHARS} 字")
        seen.add(qid)
        expect_sources = item.get("expect_sources") or []
        if not isinstance(expect_sources, list):
            raise EvalInputError(f"第 {index} 题 expect_sources 必须是数组")
        out.append(
            {
                "id": qid,
                "module": str(item.get("module") or "自定义").strip()[:40] or "自定义",
                "question": question,
                "type": str(item.get("type") or "custom").strip()[:20] or "custom",
                "acceptance": acceptance,
                "expect_sources": [str(x).strip() for x in expect_sources if str(x).strip()][:20],
            }
        )
    return out


def save_question_set(dataset: str, name: str | None, questions: list[dict]) -> dict:
    dataset_dir = _dataset_dir(dataset)
    qs_id = "qs_" + uuid.uuid4().hex[:12]
    payload = {
        "id": qs_id,
        "dataset": dataset,
        "name": (name or "自定义评测集").strip()[:MAX_NAME_CHARS] or "自定义评测集",
        "created_at": _now(),
        "questions": questions,
    }
    _atomic_json(dataset_dir / "sets" / f"{qs_id}.json", payload)
    return _public_set(payload)


def _public_set(payload: dict) -> dict:
    return {
        "id": payload["id"],
        "name": payload.get("name") or "自定义评测集",
        "count": len(payload.get("questions") or []),
        "created_at": payload.get("created_at"),
    }


def list_question_sets(dataset: str) -> list[dict]:
    root = _dataset_dir(dataset) / "sets"
    if not root.is_dir():
        return []
    rows = []
    for path in root.glob("qs_*.json"):
        try:
            payload = _read_json(path)
            if payload.get("dataset") != dataset:
                continue
            rows.append(_public_set(payload))
        except Exception:  # noqa: BLE001 坏文件不应拖垮列表
            continue
    rows.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return rows


def load_question_set(dataset: str, set_id: str) -> dict:
    if not SET_ID_RE.match(set_id or ""):
        raise EvalInputError("题库 ID 不合法")
    path = _dataset_dir(dataset) / "sets" / f"{set_id}.json"
    if not path.exists():
        raise FileNotFoundError("题库不存在或已被删除")
    payload = _read_json(path)
    if payload.get("dataset") != dataset:
        raise FileNotFoundError("题库不属于当前数据空间")
    return payload


def _run_dir(dataset: str, run_id: str) -> Path:
    if not RUN_ID_RE.match(run_id or ""):
        raise EvalInputError("评测 ID 不合法")
    return _dataset_dir(dataset) / "runs" / run_id


def create_run(dataset: str, qset: dict) -> dict:
    run_id = "run_" + uuid.uuid4().hex[:12]
    meta = {
        "id": run_id,
        "dataset": dataset,
        "set_id": qset["id"],
        "set_name": qset.get("name") or "自定义评测集",
        "status": "queued",
        "phase": "排队中",
        "progress": 0,
        "current": 0,
        "total": len(qset.get("questions") or []),
        "judge_model": JUDGE_MODEL,
        "started_at": _now(),
        "finished_at": None,
        "elapsed_s": None,
        "error": None,
        "summary": None,
        "failed_count": None,
    }
    _atomic_json(_run_dir(dataset, run_id) / "meta.json", meta)
    return meta


def _load_meta(dataset: str, run_id: str) -> dict:
    path = _run_dir(dataset, run_id) / "meta.json"
    if not path.exists():
        raise FileNotFoundError("评测任务不存在")
    meta = _read_json(path)
    if meta.get("dataset") != dataset:
        raise FileNotFoundError("评测任务不属于当前数据空间")
    # 进程重启后内存任务消失；过期 running 状态改成 interrupted，页面不会永远转圈
    if meta.get("status") in ("queued", "running") and run_id not in ACTIVE_RUNS:
        meta["status"] = "interrupted"
        meta["phase"] = "服务重启，任务已中断"
        meta["error"] = "评测进程已中断，请重新发起评测"
        _atomic_json(path, meta)
    return meta


def latest_run(dataset: str) -> dict | None:
    root = _dataset_dir(dataset) / "runs"
    if not root.is_dir():
        return None
    metas = []
    for child in root.iterdir():
        if not child.is_dir() or not RUN_ID_RE.match(child.name):
            continue
        try:
            meta = _load_meta(dataset, child.name)
            metas.append(meta)
        except Exception:  # noqa: BLE001
            continue
    if not metas:
        return None
    metas.sort(key=lambda m: m.get("started_at") or "", reverse=True)
    return metas[0]


def list_runs(dataset: str, limit: int = 10) -> list[dict]:
    root = _dataset_dir(dataset) / "runs"
    if not root.is_dir():
        return []
    metas = []
    for child in root.iterdir():
        if not child.is_dir() or not RUN_ID_RE.match(child.name):
            continue
        try:
            metas.append(_load_meta(dataset, child.name))
        except Exception:  # noqa: BLE001
            continue
    metas.sort(key=lambda m: m.get("started_at") or "", reverse=True)
    return metas[: max(1, min(limit, 50))]


def read_run(dataset: str, run_id: str, include_results: bool = False) -> dict:
    base = _run_dir(dataset, run_id)
    meta = _load_meta(dataset, run_id)
    data = {"run": meta}
    results_path = base / "results.json"
    if results_path.exists():
        try:
            payload = _read_json(results_path)
            data["summary"] = payload.get("summary")
            data["modules"] = _modules_from_summary(payload.get("summary") or {})
            data["failures"] = _failures_from_results(payload.get("results") or [])
            if include_results:
                data["results"] = payload.get("results") or []
        except Exception as exc:  # noqa: BLE001
            data["read_error"] = f"结果文件读取失败：{exc}"
    return data


def _modules_from_summary(summary: dict) -> list[dict]:
    rows = []
    for name, row in (summary.get("modules") or {}).items():
        rows.append({
            "module": name,
            "total": int(row.get("total") or 0),
            "judged": int(row.get("judged") or 0),
            "passed": int(row.get("passed") or 0),
            "pass_rate": row.get("pass_rate"),
            "recall": row.get("recall"),
        })
    rows.sort(key=lambda x: (-(x["total"] or 0), x["module"]))
    return rows


def _failure(row: dict) -> dict:
    answer = str(row.get("answer") or "")
    return {
        "id": row.get("id"),
        "module": row.get("module"),
        "question": row.get("question"),
        "acceptance": row.get("acceptance"),
        "score": row.get("score"),
        "judge_reason": row.get("judge_reason") or "",
        "judge_error": row.get("judge_error") or "",
        "answer_error": row.get("answer_error") or "",
        "answer_excerpt": answer[:1600] + ("…" if len(answer) > 1600 else ""),
        "actual_sources": row.get("actual_sources") or [],
        "expect_sources": row.get("expect_sources") or [],
        "source_recall": row.get("source_recall"),
        "route": row.get("route"),
        "elapsed_s": row.get("elapsed_s"),
    }


def _failures_from_results(results: list[dict]) -> list[dict]:
    return [_failure(r) for r in results if r.get("score") == 0 or r.get("judge_error") or r.get("answer_error")]


def _judge_answer(client, item: dict, answer: str, retries: int = 3) -> dict:
    messages = build_judge_messages(item, answer)
    last_raw, last_error = "", ""
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = client.chat.completions.create(
                model=JUDGE_MODEL,
                messages=messages if attempt == 1 else messages + [{
                    "role": "user",
                    "content": '上次输出不是合法 JSON。请只输出一个 JSON 对象：{"score": 0 或 1, "reason": "理由"}',
                }],
                temperature=0,
                max_tokens=400,
            )
            last_raw = (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2.0 * attempt, 6.0))
            continue
        parsed = parse_judge_json(last_raw)
        if parsed is not None:
            return {"score": parsed["score"], "judge_reason": parsed["reason"], "judge_raw": last_raw, "judge_error": None}
        last_error = f"裁判输出不是合法 JSON：{last_raw[:200]}"
    return {"score": None, "judge_reason": "", "judge_raw": last_raw, "judge_error": last_error}


ProgressFn = Callable[[dict], None]


def run_questions(dataset: str, qset: dict, on_progress: ProgressFn | None = None) -> dict:
    """在当前数据集上执行题库；同步函数，由 API 放到后台线程。"""
    from openai import OpenAI

    from rag_demo.db.connection import reset_dataset, use_dataset
    from rag_demo.generation.generator import API_KEY, BASE_URL
    from rag_demo.pipeline import answer_question

    if not API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，无法调用裁判/生成模型")
    judge_client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    questions = qset.get("questions") or []
    started = _now()
    t_all = time.time()
    token = use_dataset(dataset)
    results: list[dict] = []
    try:
        for index, item in enumerate(questions, 1):
            t0 = time.time()
            answer_error = None
            result: dict = {}
            try:
                result = answer_question(item["question"], use_cache=False)
            except Exception as exc:  # noqa: BLE001
                answer_error = f"{type(exc).__name__}: {exc}"
            elapsed = time.time() - t0
            answer = (result.get("answer") or "") if isinstance(result, dict) else ""
            actual_sources = unique_sources(
                (src or {}).get("source") for src in (result.get("sources") or [])
            )
            recall = source_recall(item.get("expect_sources") or [], actual_sources)
            if answer_error or not answer.strip():
                judge = {
                    "score": 0,
                    "judge_reason": "系统没有产出回答，按不合格处理。",
                    "judge_raw": "",
                    "judge_error": None,
                }
                if answer_error:
                    judge["judge_reason"] = f"回答异常：{answer_error}"
            else:
                judge = _judge_answer(judge_client, item, answer)
            results.append({
                **{key: item.get(key) for key in ("id", "module", "question", "type", "acceptance", "expect_sources")},
                "answer": answer,
                "actual_sources": actual_sources,
                "source_recall": recall,
                "route": result.get("route"),
                "sql": result.get("sql"),
                "rows_count": result.get("rows_count"),
                "elapsed_s": round(elapsed, 2),
                "score": judge.get("score"),
                "judge_reason": judge.get("judge_reason"),
                "judge_raw": judge.get("judge_raw"),
                "judge_error": judge.get("judge_error"),
                "answer_error": answer_error,
            })
            if on_progress:
                on_progress({
                    "current": index,
                    "total": len(questions),
                    "progress": round(index / max(1, len(questions)), 4),
                    "phase": f"已完成 {index}/{len(questions)} 题",
                    "partial": results[-1],
                })
    finally:
        reset_dataset(token)
    summary = summarize_results(results)
    elapsed_total = time.time() - t_all
    report_text = render_markdown_report(
        results=results,
        summary=summary,
        dataset=dataset,
        judge_model=JUDGE_MODEL,
        questions_path=f"data/eval/{dataset}/sets/{qset['id']}.json",
        started_at=started,
        elapsed_total=elapsed_total,
    )
    return {
        "started_at": started,
        "finished_at": _now(),
        "dataset": dataset,
        "judge_model": JUDGE_MODEL,
        "elapsed_total_s": round(elapsed_total, 2),
        "summary": summary,
        "results": results,
        "report_text": report_text,
    }


def persist_run_result(dataset: str, run_id: str, payload: dict) -> None:
    base = _run_dir(dataset, run_id)
    _atomic_json(base / "results.json", {
        "started_at": payload["started_at"],
        "finished_at": payload["finished_at"],
        "dataset": dataset,
        "judge_model": payload["judge_model"],
        "elapsed_total_s": payload["elapsed_total_s"],
        "summary": payload["summary"],
        "results": payload["results"],
    })
    (base / "report.md").write_text(payload["report_text"], encoding="utf-8")
    meta_path = base / "meta.json"
    meta = _read_json(meta_path)
    meta.update({
        "status": "completed",
        "phase": "已完成",
        "progress": 1,
        "finished_at": payload["finished_at"],
        "elapsed_s": payload["elapsed_total_s"],
        "summary": payload["summary"],
        "failed_count": len(_failures_from_results(payload["results"])),
        "error": None,
    })
    _atomic_json(meta_path, meta)


def mark_run_failed(dataset: str, run_id: str, error: str) -> None:
    path = _run_dir(dataset, run_id) / "meta.json"
    meta = _read_json(path)
    meta.update({
        "status": "failed",
        "phase": "评测失败",
        "error": error[:1000],
        "finished_at": _now(),
    })
    _atomic_json(path, meta)


def update_run_progress(dataset: str, run_id: str, patch: dict) -> None:
    path = _run_dir(dataset, run_id) / "meta.json"
    meta = _read_json(path)
    meta.update(patch)
    _atomic_json(path, meta)


__all__ = [
    "ACTIVE_RUNS",
    "EvalInputError",
    "EVAL_ROOT",
    "JUDGE_MODEL",
    "create_run",
    "latest_run",
    "list_question_sets",
    "list_runs",
    "load_question_set",
    "mark_active",
    "mark_inactive",
    "mark_run_failed",
    "persist_run_result",
    "read_run",
    "run_questions",
    "save_question_set",
    "update_run_progress",
    "validate_questions",
]
