"""Unit tests for sink read-back expressions."""

from __future__ import annotations

import qsql_demo.sinks  # noqa: F401  (register sinks)
from qsql_demo.config import resolve_cell
from qsql_demo.registry import SINKS


def test_parquet_ref_expr() -> None:
    cfg = resolve_cell({}, {"output": {"type": "parquet", "dir": "out/"}}, {})
    assert SINKS.get("parquet")().ref_expr("x", cfg) == "read_parquet('out/x.parquet')"


def test_duckdb_ref_expr() -> None:
    cfg = resolve_cell({}, {"output": {"type": "duckdb", "path": "wh.db"}}, {})
    assert SINKS.get("duckdb")().ref_expr("x", cfg) == "db_wh.main.x"
