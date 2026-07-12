"""A zero-dependency SQLite executor.

Runs a cell's SQL in stdlib ``sqlite3`` and materializes the result as a Polars
frame — proving the multi-engine + parquet-interchange path offline. Because it
cannot read local parquet, cells with ref()/source() must run on DuckDB (enforced
by the compiler guardrail).
"""

from __future__ import annotations

import sqlite3
from typing import Any

import polars as pl

from ..models import Executor, RenderedCell
from ..registry import executor
from ..runtime import ExecResult, RunContext


@executor("sqlite")
class SQLiteExecutor(Executor):
    reads_parquet = False

    def run(self, cell: RenderedCell, ctx: RunContext) -> ExecResult:
        path = (getattr(cell.config, "input", {}) or {}).get("sqlite", ":memory:")
        conn = ctx.get_conn(("sqlite", path), lambda: sqlite3.connect(path))
        cursor = conn.execute(cell.sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        frame = pl.DataFrame(rows, schema=columns, orient="row")
        return ExecResult(frame=frame)
