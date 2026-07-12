"""The default sink: write each cell's result to ``{output_dir}/{name}.parquet``."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import polars as pl

from ..models import RenderedCell, RunResult, Sink
from ..registry import sink
from ..runtime import ExecResult, RunContext, as_subquery


def _out_dir(config: Any) -> str:
    return (getattr(config, "output", {}) or {}).get("dir", "data/")


@sink("parquet")
class ParquetSink(Sink):
    def ref_expr(self, name: str, config: Any) -> str:
        out_dir = _out_dir(config).rstrip("/")
        return f"read_parquet('{out_dir}/{name}.parquet')"

    def write(self, cell: RenderedCell, result: ExecResult, ctx: RunContext) -> RunResult:
        out_dir = _out_dir(cell.config)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        path = f"{out_dir.rstrip('/')}/{cell.name}.parquet"

        started = time.perf_counter()
        if result.sql is not None:
            ctx.duck.execute(f"COPY ({as_subquery(result.sql)}) TO '{path}' (FORMAT PARQUET)")
        else:
            result.frame.write_parquet(path)
        elapsed = time.perf_counter() - started

        rows = ctx.duck.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
        preview = pl.scan_parquet(path).head(20).collect()
        return RunResult(name=cell.name, target=path, rows=rows, elapsed=elapsed, preview=preview)
