"""控制面备份：SQLite 一致性复制 + 可选 PostgreSQL dump + manifest。

用法：
    python scripts/backup_control_plane.py
    python scripts/backup_control_plane.py --include-pg
    python scripts/backup_control_plane.py --output backups/manual
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_backup(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(str(source))
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()


def _pg_dump(target: Path) -> dict:
    """优先用宿主 pg_dump；没有时回退到 Docker 容器内 pg_dump。"""
    binary = shutil.which("pg_dump")
    docker = shutil.which("docker")
    container = (os.environ.get("QIANKE_PG_CONTAINER") or "pgvector").strip()
    settings = {
        "host": os.environ.get("QIANKE_MERCHANT_PG_HOST") or os.environ.get("RAG_PG_HOST") or "127.0.0.1",
        "port": os.environ.get("QIANKE_MERCHANT_PG_PORT") or os.environ.get("RAG_PG_PORT") or "5432",
        "user": os.environ.get("QIANKE_MERCHANT_PG_USER") or os.environ.get("RAG_PG_USER") or "postgres",
        "password": os.environ.get("QIANKE_MERCHANT_PG_PASSWORD") or os.environ.get("RAG_PG_PASSWORD") or "",
        "dbname": os.environ.get("QIANKE_MERCHANT_PG_DBNAME") or os.environ.get("RAG_PG_DBNAME") or "vec_db",
    }
    common = [
        "-h", settings["host"], "-p", str(settings["port"]),
        "-U", settings["user"], "-d", settings["dbname"], "-Fc",
    ]
    try:
        if binary:
            command = [binary, *common, "-f", str(target)]
            env = dict(os.environ)
            if settings["password"]:
                env["PGPASSWORD"] = settings["password"]
            subprocess.run(command, check=True, capture_output=True, env=env, timeout=300)
            mode = "host"
        elif docker:
            command = [docker, "exec"]
            if settings["password"]:
                command += ["-e", f"PGPASSWORD={settings['password']}"]
            command += [container, "pg_dump", *common]
            with target.open("wb") as handle:
                subprocess.run(command, check=True, stdout=handle, stderr=subprocess.PIPE, timeout=300)
            mode = "docker"
        else:
            return {"ok": False, "error": "pg_dump/docker not found"}
        if not target.exists() or target.read_bytes()[:5] != b"PGDMP":
            return {"ok": False, "error": "pg_dump 输出不是 PGDMP 格式"}
        return {"ok": True, "file": target.name, "database": settings["dbname"], "mode": mode}
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        return {"ok": False, "error": str(exc)[:300]}


def _prune_backups(parent: Path, keep: int) -> list[str]:
    """只清理带 manifest 的时间戳备份目录，保留最新 keep 个。"""
    if keep < 1 or not parent.exists():
        return []
    candidates = sorted(
        [
            path for path in parent.iterdir()
            if path.is_dir() and (path / "manifest.json").exists()
        ],
        key=lambda path: path.name,
        reverse=True,
    )
    removed = []
    for path in candidates[max(keep, 0):]:
        shutil.rmtree(path)
        removed.append(path.name)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    parser.add_argument("--include-pg", action="store_true")
    parser.add_argument("--keep", type=int, default=7, help="保留最近 N 份时间戳备份")
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()

    from rag_demo.c_end import store

    store.init()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output = Path(args.output) if args.output else Path("backups") / stamp
    output.mkdir(parents=True, exist_ok=True)

    files = []
    control_db = Path(store._db_path())
    target = output / control_db.name
    _sqlite_backup(control_db, target)
    files.append({"source": str(control_db), "file": target.name, "sha256": _sha256(target), "size": target.stat().st_size})

    merchant_db = Path(os.environ.get("QIANKE_MERCHANT_DB") or "var/merchant_v1.sqlite")
    if merchant_db.exists() and (os.environ.get("QIANKE_MERCHANT_BACKEND") or "postgres").lower() != "postgres":
        target = output / merchant_db.name
        _sqlite_backup(merchant_db, target)
        files.append({"source": str(merchant_db), "file": target.name, "sha256": _sha256(target), "size": target.stat().st_size})

    pg = None
    if args.include_pg:
        pg = _pg_dump(output / "vec_db.dump")
        if pg.get("ok"):
            dump_path = output / pg["file"]
            pg["sha256"] = _sha256(dump_path)
            pg["size"] = dump_path.stat().st_size

    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "files": files,
        "postgres": pg,
        "verified": not args.no_verify,
    }
    if not args.no_verify:
        for item in files:
            if _sha256(output / item["file"]) != item["sha256"]:
                raise SystemExit(f"verify failed: {item['file']}")
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    removed = _prune_backups(output.parent, args.keep) if not args.output else []
    print(f"backup={output} keep={args.keep}")
    for item in files:
        print(f"  {item['file']} {item['size']} bytes sha256={item['sha256'][:16]}…")
    if pg is not None:
        print(f"  postgres ok={pg.get('ok')} {pg.get('error') or pg.get('file', '')}")
    if removed:
        print(f"pruned={','.join(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
