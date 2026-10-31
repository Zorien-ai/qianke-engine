"""Alembic environment for the merchant PostgreSQL schema.

The schema is independent (default ``merchant_v1``) and can be overridden with
``QIANKE_MERCHANT_PG_SCHEMA``. Credentials come from ``QIANKE_MERCHANT_PG_*``
(fallback ``RAG_PG_*``) so migrations use the same config as the runtime.
"""
from __future__ import annotations

import os
import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text
from sqlalchemy.engine import URL

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _env(name: str, legacy: str | None, default: str) -> str:
    for key in (f"QIANKE_MERCHANT_PG_{name}", legacy):
        if not key:
            continue
        raw = os.environ.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return default


def _settings() -> dict[str, object]:
    schema = _env("SCHEMA", None, "merchant_v1")
    if not _SCHEMA_RE.match(schema):
        raise RuntimeError(f"非法 PostgreSQL schema 名: {schema!r}")
    return {
        "host": _env("HOST", "RAG_PG_HOST", "127.0.0.1"),
        "port": int(_env("PORT", "RAG_PG_PORT", "5432")),
        "user": _env("USER", "RAG_PG_USER", "postgres"),
        "password": _env("PASSWORD", "RAG_PG_PASSWORD", "123456"),
        "dbname": _env("DBNAME", None, "vec_db"),
        "schema": schema,
    }


def _database_url(settings: dict[str, object]) -> URL:
    return URL.create(
        "postgresql+psycopg2",
        username=str(settings["user"]),
        password=str(settings["password"]),
        host=str(settings["host"]),
        port=int(settings["port"]),
        database=str(settings["dbname"]),
    )


def run_migrations_offline() -> None:
    settings = _settings()
    context.configure(
        url=_database_url(settings).render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema=str(settings["schema"]),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = _settings()
    schema = str(settings["schema"])
    connectable = create_engine(_database_url(settings), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=schema,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
