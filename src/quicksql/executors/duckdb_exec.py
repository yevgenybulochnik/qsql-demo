"""The primary executor and cross-cell conduit: everything stays in DuckDB SQL."""

from __future__ import annotations

from typing import Any

from ..models import RenderedCell, RunContext
from ..registry import executor
from .base import Executor, result_view, strip_trailing_semicolon


@executor("duckdb")
class DuckDBExecutor(Executor):
    supports_context_refs = True

    def context_key(self, config: Any) -> str:
        spec = (config.input or {}).get("duckdb")
        path = spec.get("path") if isinstance(spec, dict) else spec
        return f"duckdb:{path or ':memory:'}"

    def execute(self, cell: RenderedCell, ctx: RunContext) -> str:
        sql = strip_trailing_semicolon(cell.sql)
        if cell.reffed_in_context:
            # same-context consumers reference the bare cell name: materialize
            # once as a temp table (a view would recompute per consumer)
            ctx.conn.execute(f'CREATE OR REPLACE TEMP TABLE "{cell.name}" AS {sql}')
            return cell.name
        view = result_view(cell.name)
        ctx.conn.execute(f'CREATE OR REPLACE TEMP VIEW "{view}" AS {sql}')
        return view
