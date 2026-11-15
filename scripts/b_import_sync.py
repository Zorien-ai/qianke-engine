#!/usr/bin/env python
"""B 端商品手册 / SOP / 用户数据自动同步。

设计边界：
- 监听文件变化，自动上传为新的 wizard 批次；
- **不自动构建**，等待人工确认（`--confirm`）后才重建，避免误覆盖；
- 上传/构建使用真实 B 端登录会话和 `/api/wizard/*` 接口；
- 变更指纹落 `var/b_import_sync_state.json`，待确认批次落 `var/b_import_pending.json`。

用法：
    # 一次性检查，有变化则上传并生成待确认批次
    python scripts/b_import_sync.py --once

    # 人工确认构建最新待确认批次
    python scripts/b_import_sync.py --confirm

    # 持续监听（每 10 秒）
    python scripts/b_import_sync.py --watch --interval 10
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "var" / "b_import_sync_state.json"
PENDING_PATH = ROOT / "var" / "b_import_pending.json"
DEFAULT_FILES = (
    ROOT / "data" / "samples" / "merchant_users.csv",
    ROOT / "data" / "samples" / "m_sim_tea_products.md",
    ROOT / "data" / "samples" / "m_sim_tea_sop.md",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _signature(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(ROOT)): _sha256(path) for path in paths if path.is_file()}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def login(base_url: str, username: str, password: str) -> requests.Session:
    session = requests.Session()
    response = session.post(
        f"{base_url}/auth/login",
        json={"account": username, "password": password, "remember": False},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"登录失败（HTTP {response.status_code}）：{response.text[:300]}")
    return session


def upload_batch(
    session: requests.Session,
    base_url: str,
    paths: list[Path],
    *,
    mode: str = "full",
) -> dict[str, Any]:
    files = []
    for path in paths:
        content_type = "text/csv" if path.suffix.lower() == ".csv" else "text/markdown"
        files.append(("files", (path.name, path.read_bytes(), content_type)))
    response = session.post(f"{base_url}/api/wizard/upload", files=files, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"上传失败（HTTP {response.status_code}）：{response.text[:500]}")
    state = response.json()
    upload_id = str(state.get("upload_id") or "")
    if not upload_id:
        raise RuntimeError(f"上传响应缺少 upload_id：{state}")
    fields = {
        str(field.get("key")): field.get("column")
        for field in state.get("fields") or []
        if field.get("key") and field.get("column")
    }
    pending = {
        "upload_id": upload_id,
        "fields": fields,
        "mode": mode,
        "files": [str(path.relative_to(ROOT)) for path in paths],
        "staged_at": _now(),
        "summary": state.get("summary") or {},
    }
    _write_json(PENDING_PATH, pending)
    return pending


def wait_build(session: requests.Session, base_url: str, task_id: str) -> dict[str, Any]:
    for _ in range(600):
        response = session.get(f"{base_url}/api/wizard/build/{task_id}", timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"读取构建状态失败（HTTP {response.status_code}）：{response.text[:300]}")
        task = response.json()
        status = str(task.get("status") or "").lower()
        if status in {"done", "failed"}:
            return task
        time.sleep(2)
    raise RuntimeError("构建超时（20 分钟）")


def confirm_build(session: requests.Session, base_url: str, pending: dict[str, Any]) -> dict[str, Any]:
    upload_id = str(pending.get("upload_id") or "")
    if not upload_id:
        raise RuntimeError("待确认批次没有 upload_id")
    response = session.post(
        f"{base_url}/api/wizard/build",
        json={
            "upload_id": upload_id,
            "fields": pending.get("fields") or {},
            "mode": pending.get("mode") or "full",
        },
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"启动构建失败（HTTP {response.status_code}）：{response.text[:500]}")
    data = response.json()
    task_id = str(data.get("task_id") or "")
    if not task_id:
        raise RuntimeError(f"构建响应缺少 task_id：{data}")
    task = wait_build(session, base_url, task_id)
    if str(task.get("status") or "").lower() != "done":
        raise RuntimeError(f"构建失败：{task.get('error') or task.get('note') or task}")
    if PENDING_PATH.exists():
        PENDING_PATH.unlink()
    return task


def run_once(
    *,
    base_url: str,
    username: str,
    password: str,
    paths: list[Path],
    auto_build: bool,
) -> dict[str, Any]:
    current = _signature(paths)
    previous = _read_json(STATE_PATH).get("signature") or {}
    if current == previous:
        return {"changed": False, "files": len(current), "message": "文件没有变化"}
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError("源文件不存在：" + "、".join(missing))
    session = login(base_url, username, password)
    pending = upload_batch(session, base_url, paths)
    _write_json(STATE_PATH, {"signature": current, "updated_at": _now(), "username": username})
    result: dict[str, Any] = {
        "changed": True,
        "upload_id": pending["upload_id"],
        "files": pending["files"],
        "summary": pending["summary"],
        "message": "已上传，等待人工确认构建",
    }
    if auto_build:
        task = confirm_build(session, base_url, pending)
        result.update({"built": True, "task": task})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("B_IMPORT_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--username", default=os.environ.get("B_IMPORT_USERNAME", "sim_biz_tea"))
    parser.add_argument("--password", default=os.environ.get("B_IMPORT_PASSWORD", ""))
    parser.add_argument("--files", nargs="*", help="要同步的文件；缺省为商品手册 + SOP + 示例用户 CSV")
    parser.add_argument("--interval", type=int, default=10, help="监听间隔秒数")
    parser.add_argument("--watch", action="store_true", help="持续监听文件变化")
    parser.add_argument("--once", action="store_true", help="只检查一次（默认）")
    parser.add_argument("--confirm", action="store_true", help="确认构建最新待确认批次")
    parser.add_argument("--auto-build", action="store_true", help="上传后立即构建；仅限本地演示")
    args = parser.parse_args()
    if args.confirm:
        if not PENDING_PATH.is_file():
            print(json.dumps({"ok": False, "message": "没有待确认批次"}, ensure_ascii=False))
            return 1
        try:
            session = login(args.base_url, args.username, args.password)
            task = confirm_build(session, args.base_url, _read_json(PENDING_PATH))
            print(json.dumps({"ok": True, "task": task}, ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
    paths = [Path(item).expanduser().resolve() for item in args.files] if args.files else list(DEFAULT_FILES)
    if not args.password:
        print(json.dumps({"ok": False, "error": "缺少密码：设置 B_IMPORT_PASSWORD 或传 --password"}, ensure_ascii=False))
        return 1
    try:
        if args.watch:
            print(json.dumps({"ok": True, "message": f"开始监听 {len(paths)} 个文件，每 {args.interval}s"}, ensure_ascii=False))
            while True:
                result = run_once(base_url=args.base_url, username=args.username, password=args.password, paths=paths, auto_build=args.auto_build)
                if result.get("changed"):
                    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
                time.sleep(max(2, args.interval))
        result = run_once(base_url=args.base_url, username=args.username, password=args.password, paths=paths, auto_build=args.auto_build)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("changed") else 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
