"""merchant_v1 baseline (PostgreSQL)

Revision ID: 0001_merchant_v1
Revises:
Create Date: 2026-11-01

The merchant schema is independent from public/vec_db. Use
QIANKE_MERCHANT_PG_SCHEMA to target another schema.
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

from alembic import op

revision: str = "0001_merchant_v1"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _schema() -> str:
    name = (os.environ.get("QIANKE_MERCHANT_PG_SCHEMA") or "merchant_v1").strip()
    if not _SCHEMA_RE.match(name):
        raise RuntimeError(f"非法 PostgreSQL schema 名: {name!r}")
    return name


def _statements(schema: str) -> list[str]:
    s = f'"{schema}"'
    return [
        f"CREATE SCHEMA IF NOT EXISTS {s}",
        f"""
        CREATE TABLE IF NOT EXISTS {s}.m_product (
            product_id TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            title       TEXT NOT NULL,
            category    TEXT NOT NULL,
            brand       TEXT,
            status      TEXT NOT NULL,
            created_at  TEXT
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {s}.m_sku (
            sku         TEXT PRIMARY KEY,
            merchant_id TEXT NOT NULL,
            product_id  TEXT NOT NULL REFERENCES {s}.m_product (product_id),
            spec        TEXT NOT NULL,
            price       TEXT NOT NULL,
            status      TEXT NOT NULL,
            barcode     TEXT
        )
        """,
        f"CREATE INDEX IF NOT EXISTS idx_m_sku_merchant ON {s}.m_sku (merchant_id)",
        f"CREATE INDEX IF NOT EXISTS idx_m_sku_product ON {s}.m_sku (product_id)",
        f"""
        CREATE TABLE IF NOT EXISTS {s}.m_inventory (
            sku           TEXT NOT NULL REFERENCES {s}.m_sku (sku),
            warehouse_id  TEXT NOT NULL,
            merchant_id   TEXT NOT NULL,
            available_qty INTEGER NOT NULL,
            reserved_qty  INTEGER NOT NULL,
            safety_stock  INTEGER NOT NULL,
            updated_at    TEXT NOT NULL,
            PRIMARY KEY (sku, warehouse_id)
        )
        """,
        f"CREATE INDEX IF NOT EXISTS idx_m_inventory_merchant ON {s}.m_inventory (merchant_id)",
        f"""
        CREATE TABLE IF NOT EXISTS {s}.m_order (
            order_id     TEXT PRIMARY KEY,
            merchant_id  TEXT NOT NULL,
            buyer_id     TEXT NOT NULL,
            status       TEXT NOT NULL,
            total_amount TEXT NOT NULL,
            currency     TEXT NOT NULL,
            channel      TEXT,
            created_at   TEXT NOT NULL,
            paid_at      TEXT,
            source_ref   TEXT,
            tracking_no  TEXT,
            carrier      TEXT,
            shipped_at   TEXT,
            completed_at TEXT,
            cancelled_at TEXT,
            refund_amount TEXT,
            refunded_at  TEXT,
            cancel_request_id TEXT,
            refund_request_id TEXT,
            returned_at  TEXT,
            restock_request_id TEXT
        )
        """,
        f"CREATE INDEX IF NOT EXISTS idx_m_order_merchant ON {s}.m_order (merchant_id, created_at)",
        f"CREATE INDEX IF NOT EXISTS idx_m_order_buyer ON {s}.m_order (buyer_id)",
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_m_order_cancel_request
            ON {s}.m_order (cancel_request_id)
            WHERE cancel_request_id IS NOT NULL
        """,
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_m_order_refund_request
            ON {s}.m_order (refund_request_id)
            WHERE refund_request_id IS NOT NULL
        """,
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_m_order_restock_request
            ON {s}.m_order (restock_request_id)
            WHERE restock_request_id IS NOT NULL
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {s}.m_order_item (
            order_id    TEXT NOT NULL REFERENCES {s}.m_order (order_id) ON DELETE CASCADE,
            line_no     INTEGER NOT NULL,
            sku         TEXT NOT NULL,
            product_id  TEXT NOT NULL,
            title       TEXT NOT NULL,
            quantity    INTEGER NOT NULL,
            unit_price  TEXT NOT NULL,
            line_amount TEXT NOT NULL,
            PRIMARY KEY (order_id, line_no)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {s}.m_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {s}.m_reservation (
            reservation_id TEXT PRIMARY KEY,
            merchant_id    TEXT NOT NULL,
            buyer_id       TEXT,
            status         TEXT NOT NULL,
            expires_at     TEXT NOT NULL,
            items_json     TEXT NOT NULL,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            order_id       TEXT
        )
        """,
        f"CREATE INDEX IF NOT EXISTS idx_m_reservation_merchant ON {s}.m_reservation (merchant_id, status)",
    ]


def upgrade() -> None:
    schema = _schema()
    for statement in _statements(schema):
        op.execute(statement)


def downgrade() -> None:
    schema = _schema()
    s = f'"{schema}"'
    for table in (
        "m_reservation",
        "m_meta",
        "m_order_item",
        "m_order",
        "m_inventory",
        "m_sku",
        "m_product",
    ):
        op.execute(f"DROP TABLE IF EXISTS {s}.{table} CASCADE")
    op.execute(f"DROP TABLE IF EXISTS {s}.alembic_version")
