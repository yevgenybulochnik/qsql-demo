"""Write a cell's result to a table in a DuckDB database file (via ATTACH)."""

from __future__ import annotations

import time
from typing import Any

import polars as pl

from ..executors.duckdb_exec import duckdb_alias
from ..models import RenderedCell, RunResult, Sink
from ..registry import sink
from ..runtime import ExecResult, RunContext, as_subquery


def _parts(config: Any) -> tuple[str, str, str]:
    out = getattr(config, "output", {}) or {}
    path = out["path"]
    alias = duckdb_alias(path)
    schema = out.get("schema", "main")
    return path, alias, schema


@sink("duckdb")
class DuckDBSink(Sink):
    def prepare(self, config: Any, ctx: RunContext) -> None:
        path, alias, schema = _parts(config)
        ctx.ensure_attached(alias, f"ATTACH '{path}' AS {alias}")
        if schema != "main":
            ctx.duck.execute(f"CREATE SCHEMA IF NOT EXISTS {alias}.{schema}")

    def ref_expr(self, name: str, config: Any) -> str:
        _, alias, schema = _parts(config)
        return f"{alias}.{schema}.{name}"

    def write(self, cell: RenderedCell, result: ExecResult, ctx: RunContext) -> RunResult:
        self.prepare(cell.config, ctx)
        out = getattr(cell.config, "output", {}) or {}
        _, alias, schema = _parts(cell.config)
        target = f"{alias}.{schema}.{cell.name}"
        mode = out.get("mode", "replace")

        registered = None
        if result.sql is not None:
            source_sql = as_subquery(result.sql)
        else:
            registered = f"__qsql_tmp_{cell.name}"
            ctx.duck.register(registered, result.frame)
            source_sql = f"SELECT * FROM {registered}"

        started = time.perf_counter()
        if mode == "append":
            ctx.duck.execute(f"CREATE TABLE IF NOT EXISTS {target} AS ({source_sql}) WITH NO DATA")
            ctx.duck.execute(f"INSERT INTO {target} {source_sql}")
        else:
            ctx.duck.execute(f"CREATE OR REPLACE TABLE {target} AS ({source_sql})")
        elapsed = time.perf_counter() - started

        rows = ctx.duck.execute(f"SELECT count(*) FROM {target}").fetchone()[0]
        cursor = ctx.duck.execute(f"SELECT * FROM {target} LIMIT 20")
        columns = [desc[0] for desc in cursor.description]
        preview = pl.DataFrame(cursor.fetchall(), schema=columns, orient="row")
        if registered is not None:
            ctx.duck.unregister(registered)
        return RunResult(name=cell.name, target=target, rows=rows, elapsed=elapsed, preview=preview)
