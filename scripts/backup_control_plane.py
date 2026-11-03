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
    binary = shutil.which("pg_dump")
    if not binary:
        return {"ok": False, "error": "pg_dump not found"}
    settings = {
        "host": os.environ.get("QIANKE_MERCHANT_PG_HOST") or os.environ.get("RAG_PG_HOST") or "127.0.0.1",
        "port": os.environ.get("QIANKE_MERCHANT_PG_PORT") or os.environ.get("RAG_PG_PORT") or "5432",
        "user": os.environ.get("QIANKE_MERCHANT_PG_USER") or os.environ.get("RAG_PG_USER") or "",
        "password": os.environ.get("QIANKE_MERCHANT_PG_PASSWORD") or os.environ.get("RAG_PG_PASSWORD") or "",
        "dbname": os.environ.get("QIANKE_MERCHANT_PG_DBNAME") or os.environ.get("RAG_PG_DBNAME") or "vec_db",
        "schema": os.environ.get("QIANKE_MERCHANT_PG_SCHEMA") or "merchant_v1",
    }
    command = [
        binary, "-h", settings["host"], "-p", str(settings["port"]),
        "-U", settings["user"], "-d", settings["dbname"],
        "-n", settings["schema"], "-Fc", "-f", str(target),
    ]
    env = dict(os.environ)
    if settings["password"]:
        env["PGPASSWORD"] = settings["password"]
    try:
        subprocess.run(command, check=True, capture_output=True, env=env, timeout=300)
        return {"ok": True, "schema": settings["schema"], "file": target.name}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    parser.add_argument("--include-pg", action="store_true")
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
        pg = _pg_dump(output / "merchant_v1.dump")

    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "files": files,
        "postgres": pg,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"backup={output}")
    for item in files:
        print(f"  {item['file']} {item['size']} bytes sha256={item['sha256'][:16]}…")
    if pg is not None:
        print(f"  postgres ok={pg.get('ok')} {pg.get('error') or pg.get('file', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
