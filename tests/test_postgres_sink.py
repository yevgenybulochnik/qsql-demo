"""Unit tests for the Postgres sink (SQL/ref only; real writes are marker-gated)."""

from __future__ import annotations

import qsql_demo.sinks  # noqa: F401  (register sinks)
from qsql_demo.config import resolve_cell
from qsql_demo.registry import SINKS


def _sink():
    return SINKS.get("postgres")()


def test_postgres_ref_expr_default_schema() -> None:
    cfg = resolve_cell({}, {"output": {"type": "postgres", "dsn": "pg://x", "table": "active"}}, {})
    assert _sink().ref_expr("active", cfg).endswith(".public.active")


def test_postgres_ref_expr_schema_in_table() -> None:
    cfg = resolve_cell(
        {}, {"output": {"type": "postgres", "dsn": "pg://x", "table": "analytics.users"}}, {}
    )
    assert _sink().ref_expr("users", cfg).endswith(".analytics.users")


def test_postgres_ref_expr_falls_back_to_cell_name() -> None:
    cfg = resolve_cell({}, {"output": {"type": "postgres", "dsn": "pg://x"}}, {})
    assert _sink().ref_expr("orders", cfg).endswith(".public.orders")


def test_postgres_requires_extension() -> None:
    assert "postgres" in _sink().requires
