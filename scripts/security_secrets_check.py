"""生产密钥基线检查：只输出状态，不打印密钥值。

用法：
    python scripts/security_secrets_check.py
    python scripts/security_secrets_check.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import rag_demo.config  # noqa: E402,F401 加载 .env

_DEFAULT_VALUES = {
    "RAG_ADMIN_PASSWORD": {"admin123", "admin", "password"},
    "RAG_PG_PASSWORD": {"123456", "postgres", "password"},
    "RAG_SQL_READONLY_PASSWORD": {"sql_reader_demo_pwd", "password"},
}


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _env(name: str) -> str:
    return str(os.environ.get(name, ""))


def _git_tracked(path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", path],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def run() -> dict:
    checks: list[dict] = []
    for name, defaults in _DEFAULT_VALUES.items():
        value = _env(name)
        weak = not value or value in defaults or len(value) < 8
        checks.append(_check(
            name, not weak,
            f"set={bool(value)} len={len(value)} weak={weak}",
        ))

    checks.append(_check(
        "RAG_AUTH_ENABLED", _env("RAG_AUTH_ENABLED").lower() in {"1", "true", "yes"},
        f"value={_env('RAG_AUTH_ENABLED') or 'unset'}",
    ))
    checks.append(_check(
        "RAG_ALLOW_HEADER_AUTH",
        _env("RAG_ALLOW_HEADER_AUTH").lower() not in {"1", "true", "yes"},
        f"value={_env('RAG_ALLOW_HEADER_AUTH') or 'unset'}（True 表示可自报身份，仅限演示）",
    ))
    checks.append(_check(
        "RAG_ENABLE_API_DOCS",
        _env("RAG_ENABLE_API_DOCS").lower() in {"0", "false", "no"},
        f"value={_env('RAG_ENABLE_API_DOCS') or 'unset'}（生产建议关闭）",
    ))
    checks.append(_check(
        ".env_not_tracked", not _git_tracked(".env"), f"tracked={_git_tracked('.env')}",
    ))
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result["checks"]:
            print(("PASS" if item["ok"] else "FAIL"), item["name"], "-", item["detail"])
        print("OVERALL", "PASS" if result["ok"] else "FAIL")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
