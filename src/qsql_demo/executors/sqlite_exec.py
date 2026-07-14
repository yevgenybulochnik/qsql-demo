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
    supports_context_refs = True

    def context_key(self, config: Any) -> str:
        spec = (config.input or {}).get("sqlite")
        path = spec.get("path") if isinstance(spec, dict) else spec
        return f"sqlite:{path or ':memory:'}"

    def _connect(self, cell: RenderedCell, ctx: RunContext) -> tuple[sqlite3.Connection, bool]:
        """The context session's shared connection (temp tables live there;
        :memory: contexts only exist there), or an ephemeral one without a session."""
        spec = (cell.config.input or {}).get("sqlite")
        path = spec.get("path") if isinstance(spec, dict) else spec
        db = str(ctx.root / path) if path and path != ":memory:" else (path or ":memory:")
        if ctx.session is None:
            return sqlite3.connect(db), True
        key = self.context_key(cell.config)
        if key not in ctx.session.engine_sessions:
            # runs are serialized (exclusive workers); threads change between them
            ctx.session.engine_sessions[key] = sqlite3.connect(db, check_same_thread=False)
        return ctx.session.engine_sessions[key], False

    def execute(self, cell: RenderedCell, ctx: RunContext) -> str:
        con, ephemeral = self._connect(cell, ctx)
        sql = strip_trailing_semicolon(cell.sql)
        try:
            if cell.reffed_in_context:
                con.execute(f'DROP TABLE IF EXISTS temp."{cell.name}"')
                con.execute(f'CREATE TEMP TABLE "{cell.name}" AS {sql}')
                cur = con.execute(f'SELECT * FROM temp."{cell.name}"')
            else:
                cur = con.execute(sql)
            if cur.description is None:
                raise ExecutorError(f"cell {cell.name!r}: sqlite query returned no result set")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ExecutorError(f"cell {cell.name!r}: sqlite: {exc}") from exc
        finally:
            if ephemeral:
                con.close()
        frame = pl.DataFrame(rows, schema=cols, orient="row")
        return register_frame(ctx, result_view(cell.name), frame)
