"""The primary executor and cross-cell conduit: everything stays in DuckDB SQL."""

from __future__ import annotations

from ..models import RenderedCell, RunContext
from ..registry import executor
from .base import Executor, result_view, strip_trailing_semicolon


@executor("duckdb")
class DuckDBExecutor(Executor):
    def execute(self, cell: RenderedCell, ctx: RunContext) -> str:
        view = result_view(cell.name)
        sql = strip_trailing_semicolon(cell.sql)
        ctx.conn.execute(f'CREATE OR REPLACE TEMP VIEW "{view}" AS {sql}')
        return view
