"""恢复控制面备份。

默认 dry-run；--yes 才覆盖。覆盖前自动保存当前 DB 为 *.before-restore-<ts>。

用法：
    python scripts/restore_control_plane.py backups/20261104-003000
    python scripts/restore_control_plane.py backups/20261104-003000 --yes
    python scripts/restore_control_plane.py backups/... --yes --include-pg
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pg_restore(dump: Path) -> dict:
    binary = shutil.which("pg_restore")
    if not binary:
        return {"ok": False, "error": "pg_restore not found"}
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
        "-n", settings["schema"], "--clean", "--if-exists", str(dump),
    ]
    env = dict(os.environ)
    if settings["password"]:
        env["PGPASSWORD"] = settings["password"]
    try:
        subprocess.run(command, check=True, capture_output=True, env=env, timeout=600)
        return {"ok": True, "schema": settings["schema"]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--include-pg", action="store_true")
    args = parser.parse_args()
    backup_dir = Path(args.backup)
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files") or []
    for item in files:
        target = backup_dir / item["file"]
        if not target.exists():
            print(f"missing backup file: {target}")
            return 2
        actual = _sha256(target)
        if actual != item["sha256"]:
            print(f"checksum mismatch: {target}")
            return 2
        print(f"ok {target.name} {item['size']} bytes")
    if not args.yes:
        print("dry-run：加 --yes 才会覆盖当前数据库")
        return 0

    for item in files:
        source = backup_dir / item["file"]
        destination = Path(item["source"])
        if destination.exists():
            saved = destination.with_name(destination.name + f".before-restore-{int(time.time())}")
            shutil.copy2(destination, saved)
            print(f"current saved: {saved}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        print(f"restored: {destination}")

    if args.include_pg:
        dump = backup_dir / "merchant_v1.dump"
        if dump.exists():
            print(_pg_restore(dump))
    print("restore done; restart API/Worker to reload connections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
