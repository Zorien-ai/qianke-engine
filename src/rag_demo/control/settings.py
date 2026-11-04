"""控制面存储后端配置。"""
from __future__ import annotations

import os
import re
from typing import Any

CONTROL_BACKEND = "sqlite"
SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _env(name: str, fallback: str) -> str:
    return (
        os.environ.get(f"QIANKE_CONTROL_PG_{name}")
        or os.environ.get(f"RAG_PG_{name}")
        or fallback
    )


def backend() -> str:
    value = (os.environ.get("QIANKE_CONTROL_BACKEND") or CONTROL_BACKEND).strip().lower()
    return "postgres" if value in {"postgres", "postgresql", "pg"} else "sqlite"


def pg_settings(*, schema: str | None = None) -> dict[str, Any]:
    resolved_schema = (
        schema
        or os.environ.get("QIANKE_CONTROL_PG_SCHEMA")
        or "qianke_control"
    ).strip()
    if not SCHEMA_PATTERN.match(resolved_schema):
        raise ValueError(
            f"非法控制面 schema 名: {resolved_schema!r}"
            "（只允许字母/数字/下划线，且不能以数字开头）"
        )
    port_text = _env("PORT", "5432")
    try:
        port = int(port_text)
    except (TypeError, ValueError):
        raise ValueError(f"非法 PostgreSQL 端口: {port_text!r}") from None
    return {
        "host": _env("HOST", "127.0.0.1"),
        "port": port,
        "user": _env("USER", "postgres"),
        "password": _env("PASSWORD", "123456"),
        "dbname": _env("DBNAME", "vec_db"),
        "schema": resolved_schema,
        "connect_timeout": 5,
    }
