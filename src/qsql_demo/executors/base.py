"""Executor: run a cell's SQL on a backend, land the result as a view DuckDB can read."""

from __future__ import annotations

import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from ..models import RenderedCell, RunContext


def strip_trailing_semicolon(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def result_view(cell_name: str) -> str:
    return f"__qsql_{cell_name}"


def register_frame(ctx: RunContext, view: str, frame: Any) -> str:
    """Expose an extracted result on the conduit as `view`.

    Polars frames roundtrip through a temp parquet file (duckdb.register on a
    polars frame needs pyarrow, which only the bigquery extra ships); anything
    else (e.g. a real pyarrow Table) registers directly.
    """
    import polars as pl

    if isinstance(frame, pl.DataFrame):
        if ctx.tmpdir is None:
            ctx.tmpdir = tempfile.mkdtemp(prefix="qsql-run-")
        tmp = Path(ctx.tmpdir) / f"{view}.parquet"
        frame.write_parquet(tmp)
        ctx.conn.execute(
            f'CREATE OR REPLACE TEMP VIEW "{view}" AS SELECT * FROM read_parquet(\'{tmp}\')'
        )
    else:
        ctx.conn.register(view, frame)
    return view


class Executor(ABC):
    name: ClassVar[str] = ""

    @abstractmethod
    def execute(self, cell: RenderedCell, ctx: RunContext) -> str:
        """Materialize the cell's result on ctx.conn; return the view name."""
