"""Postgres access for evaluators and scripts. Uses DATABASE_URL."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Optional, Sequence

import psycopg
from psycopg.rows import dict_row
from core.schema_contract import TABLE_FIELDS


class DatabaseContractError(RuntimeError):
    """The configured application role or database schema is not ready."""


def connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    statement_timeout = os.getenv("EVAL_STATEMENT_TIMEOUT_MS", "5000")
    lock_timeout = os.getenv("EVAL_LOCK_TIMEOUT_MS", "1000")
    connect_timeout = os.getenv("EVAL_CONNECT_TIMEOUT_SECONDS", "5")
    options = (
        f"-c default_transaction_read_only=on "
        f"-c statement_timeout={statement_timeout} "
        f"-c lock_timeout={lock_timeout}"
    )
    try:
        return psycopg.connect(
            url,
            row_factory=dict_row,
            connect_timeout=int(connect_timeout),
            options=options,
        )
    except psycopg.OperationalError as exc:
        raise DatabaseContractError(
            "cannot authenticate to PostgreSQL using DATABASE_URL. If this is an "
            "existing volume, run db/migrate_existing_roles.sql as the volume's "
            "actual PostgreSQL superuser (POSTGRES_USER is init-only); otherwise "
            "verify the eval_app password."
        ) from exc


def validate_database_contract() -> None:
    """Verify app-role access and the schema advertised to the SQL evaluator."""
    expected = {
        table: {field.split()[0] for field in fields.split(", ")}
        for table, fields in TABLE_FIELDS.items()
    }
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                """
            )
            actual: dict[str, set[str]] = {}
            for row in cur.fetchall():
                actual.setdefault(row["table_name"], set()).add(row["column_name"])

    missing = {
        table: sorted(columns - actual.get(table, set()))
        for table, columns in expected.items()
        if columns - actual.get(table, set())
    }
    if missing:
        details = ", ".join(
            f"{table} ({', '.join(columns)})" for table, columns in missing.items()
        )
        raise DatabaseContractError(
            f"PostgreSQL login succeeded, but the database schema is incomplete: "
            f"{details}. Apply a non-destructive schema migration for this existing "
            f"volume; do not run the destructive seed profile."
        )


def fetch(sql: str, params: Optional[Sequence[Any]] = None) -> list[dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def execute(sql: str, params: Optional[Sequence[Any]] = None) -> int:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.rowcount


def scalar_value(rows: list[dict[str, Any]]) -> Any:
    if not rows:
        return None
    if len(rows) == 1 and len(rows[0]) == 1:
        return _normalize_value(next(iter(rows[0].values())))
    return [_normalize_row(row) for row in rows]


def scalar_count(rows: list[dict[str, Any]]) -> int:
    """Require the exact one-row/one-column non-negative integer count contract."""
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError("count query must return exactly one row and one column")
    value = next(iter(rows[0].values()))
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("count query must return a non-negative integer, not a boolean")
    return value


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _normalize_value(value) for key, value in row.items()}


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value
