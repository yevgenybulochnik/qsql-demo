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
        ctx.conn.register(view, _normalize_arrow(ctx, frame))
    return view


def _normalize_arrow(ctx: RunContext, frame: Any) -> Any:
    """duckdb cannot scan decimal256 (BigQuery BIGNUMERIC) at any precision:
    downcast to decimal128 when the precision fits DECIMAL(38), else cast to
    string — lossless text, since no duckdb decimal can hold the value."""
    try:
        import pyarrow as pa
    except ImportError:
        return frame
    if not isinstance(frame, pa.Table):
        return frame
    for index, fld in enumerate(frame.schema):
        if not isinstance(fld.type, pa.Decimal256Type):
            continue
        if fld.type.precision <= 38:
            target = pa.decimal128(fld.type.precision, fld.type.scale)
        else:
            target = pa.string()
            ctx.log.append(
                f"column {fld.name!r}: decimal256({fld.type.precision},{fld.type.scale}) "
                f"exceeds duckdb's DECIMAL(38); cast to string"
            )
        frame = frame.set_column(index, fld.name, frame.column(index).cast(target))
    return frame


class Executor(ABC):
    name: ClassVar[str] = ""
    # engines that keep a per-context session where same-context cells can
    # reference each other as temp tables (in the engine's own dialect)
    supports_context_refs: ClassVar[bool] = False

    def context_key(self, config: Any) -> str:
        """Cells with equal keys share an execution context (engine + target)."""
        return f"{self.name}:"

    @abstractmethod
    def execute(self, cell: RenderedCell, ctx: RunContext) -> str:
        """Materialize the cell's result on ctx.conn; return the view name."""
