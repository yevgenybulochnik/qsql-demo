"""Write a cell's result to a Postgres table via DuckDB's ``postgres`` extension.

DuckDB ATTACHes the Postgres database and writes/reads the table, so no extra
Python dependency is required (the extension auto-installs, needing network + a
running server — real writes are covered by a marker-gated test).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import polars as pl

from ..models import RenderedCell, RunResult, Sink
from ..registry import sink
from ..runtime import ExecResult, RunContext, as_subquery


def _alias(dsn: str) -> str:
    return "pg_" + hashlib.sha1((dsn or "").encode()).hexdigest()[:8]


def _parts(config: Any) -> tuple[str, str, str | None]:
    out = getattr(config, "output", {}) or {}
    dsn = out.get("dsn") or out.get("connection") or ""
    schema = out.get("schema", "public")
    table = out.get("table")
    name: str | None = None
    if table and "." in table:
        schema, name = table.split(".", 1)
    elif table:
        name = table
    return dsn, schema, name


@sink("postgres")
class PostgresSink(Sink):
    requires = ["postgres"]

    def prepare(self, config: Any, ctx: RunContext) -> None:
        dsn, schema, _ = _parts(config)
        alias = _alias(dsn)
        ctx.load_extension("postgres")
        ctx.ensure_attached(alias, f"ATTACH '{dsn}' AS {alias} (TYPE postgres)")
        if schema != "public":
            ctx.duck.execute(f"CREATE SCHEMA IF NOT EXISTS {alias}.{schema}")

    def ref_expr(self, name: str, config: Any) -> str:
        dsn, schema, table = _parts(config)
        return f"{_alias(dsn)}.{schema}.{table or name}"

    def write(self, cell: RenderedCell, result: ExecResult, ctx: RunContext) -> RunResult:
        self.prepare(cell.config, ctx)
        dsn, schema, table = _parts(cell.config)
        target = f"{_alias(dsn)}.{schema}.{table or cell.name}"
        mode = (getattr(cell.config, "output", {}) or {}).get("mode", "replace")

        registered = None
        if result.sql is not None:
            source_sql = as_subquery(result.sql)
        else:
            registered = f"__qsql_tmp_{cell.name}"
            ctx.duck.register(registered, result.frame)
            source_sql = f"SELECT * FROM {registered}"

        started = time.perf_counter()
        if mode == "append":
            ctx.duck.execute(f"INSERT INTO {target} {source_sql}")
        else:
            ctx.duck.execute(f"DROP TABLE IF EXISTS {target}")
            ctx.duck.execute(f"CREATE TABLE {target} AS ({source_sql})")
        elapsed = time.perf_counter() - started

        rows = ctx.duck.execute(f"SELECT count(*) FROM {target}").fetchone()[0]
        cursor = ctx.duck.execute(f"SELECT * FROM {target} LIMIT 20")
        columns = [desc[0] for desc in cursor.description]
        preview = pl.DataFrame(cursor.fetchall(), schema=columns, orient="row")
        if registered is not None:
            ctx.duck.unregister(registered)
        return RunResult(name=cell.name, target=target, rows=rows, elapsed=elapsed, preview=preview)
