"""The DuckDB executor — the primary engine and universal conduit.

DuckDB cells stay in-SQL: ``run`` loads any needed extensions, optionally ATTACHes
an ``input.duckdb`` file, and hands the rendered SELECT to the sink to COPY/CTAS.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..models import Executor, RenderedCell
from ..registry import executor
from ..runtime import ExecResult, RunContext


def duckdb_alias(path: str) -> str:
    return "db_" + re.sub(r"\W", "_", Path(path).stem)


@executor("duckdb")
class DuckDBExecutor(Executor):
    reads_parquet = True

    def run(self, cell: RenderedCell, ctx: RunContext) -> ExecResult:
        for ext in cell.extensions:
            ctx.load_extension(ext)
        db_path = (getattr(cell.config, "input", {}) or {}).get("duckdb")
        if db_path and db_path != ":memory:" and Path(db_path).exists():
            alias = duckdb_alias(db_path)
            ctx.ensure_attached(alias, f"ATTACH '{db_path}' AS {alias} (READ_ONLY)")
        return ExecResult(sql=cell.sql)
