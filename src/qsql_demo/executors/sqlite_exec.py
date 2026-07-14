"""Zero-dependency executor: proves cross-engine flow entirely offline."""

from __future__ import annotations

import sqlite3
from typing import Any

import polars as pl

from ..errors import ExecutorError
from ..models import RenderedCell, RunContext
from ..registry import executor
from .base import Executor, register_frame, result_view, strip_trailing_semicolon


@executor("sqlite")
class SQLiteExecutor(Executor):
    def context_key(self, config: Any) -> str:
        spec = (config.input or {}).get("sqlite")
        path = spec.get("path") if isinstance(spec, dict) else spec
        return f"sqlite:{path or ':memory:'}"

    def execute(self, cell: RenderedCell, ctx: RunContext) -> str:
        spec = (cell.config.input or {}).get("sqlite")
        path = spec.get("path") if isinstance(spec, dict) else spec
        db = str(ctx.root / path) if path and path != ":memory:" else (path or ":memory:")
        con = sqlite3.connect(db)
        try:
            cur = con.execute(strip_trailing_semicolon(cell.sql))
            if cur.description is None:
                raise ExecutorError(f"cell {cell.name!r}: sqlite query returned no result set")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ExecutorError(f"cell {cell.name!r}: sqlite: {exc}") from exc
        finally:
            con.close()
        frame = pl.DataFrame(rows, schema=cols, orient="row")
        return register_frame(ctx, result_view(cell.name), frame)
