"""Run cells in topo order: per-cell executor + sink, wrapped by the plugin chain.

The base cell-runner does the real work (prepare sinks, execute, write, preview);
plugins overriding ``run`` wrap it as decorators, outermost = lowest priority.
Cell failures become ``RunResult(ok=False)`` inside the base runner so chain
plugins (retries, ...) see error results; a catch-all *outside* the chain turns
a buggy plugin into an error result too, and the run continues.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import traceback
from typing import TYPE_CHECKING, Any, Callable

import duckdb
import polars as pl

from .models import RenderedCell, RunContext, RunResult
from .registry import EXECUTORS, PLUGINS
from .sinks import make_sink

if TYPE_CHECKING:
    from .compiler import Project

Inner = Callable[[RenderedCell, RunContext], RunResult]


def _preview(conn: Any, ref_expr: str, limit: int = 100) -> pl.DataFrame:
    """Read the landed output back through ref_expr into a small Polars frame.
    Built row-wise: duckdb's .pl()/.arrow() need pyarrow, an optional extra."""
    rel = conn.sql(f"SELECT * FROM {ref_expr} LIMIT {limit}")
    return pl.DataFrame(rel.fetchall(), schema=rel.columns, orient="row")


def _load_extension(conn: Any, ext: str) -> None:
    try:
        conn.execute(f"LOAD {ext}")
    except duckdb.Error:
        conn.execute(f"INSTALL {ext}")
        conn.execute(f"LOAD {ext}")


def _conduit(project: Project) -> Any:
    spec = (project.config.input or {}).get("duckdb")
    path = spec.get("path") if isinstance(spec, dict) else spec
    return duckdb.connect(str(project.root / path) if path else ":memory:")


def _selection(project: Project, select: list[str] | None) -> list[str]:
    if not select:
        return list(project.order)
    unknown = [s for s in select if s not in project.cells]
    if unknown:
        from .errors import ConfigError

        raise ConfigError(f"unknown cell(s) in --select: {', '.join(unknown)}")
    wanted: set[str] = set()
    stack = list(select)
    while stack:  # selected cells plus their upstream closure
        name = stack.pop()
        if name not in wanted:
            wanted.add(name)
            stack.extend(project.cells[name].depends_on)
    return [n for n in project.order if n in wanted]


def base_runner(project: Project) -> Inner:
    """The innermost cell-runner; `project` rides in via closure so the chain
    signature stays (cell, ctx)."""

    def run_cell(cell: RenderedCell, ctx: RunContext) -> RunResult:
        started = time.perf_counter()
        try:
            sink = make_sink(cell.config, ctx.root)
            for ext in (*cell.extensions, *sink.requires):
                _load_extension(ctx.conn, ext)
            for upstream in cell.depends_on:
                up_sink = make_sink(project.cells[upstream].config, ctx.root)
                for ext in up_sink.requires:
                    _load_extension(ctx.conn, ext)
                up_sink.prepare(ctx.conn)
            sink.prepare(ctx.conn)
            view = EXECUTORS.get(cell.engine).execute(cell, ctx)
            rows, target = sink.write(cell, view, ctx.conn)
            preview = _preview(ctx.conn, sink.ref_expr(cell.name))
            return RunResult(
                cell=cell.name,
                ok=True,
                rows=rows,
                target=target,
                elapsed=time.perf_counter() - started,
                preview=preview,
            )
        except Exception:
            return RunResult(
                cell=cell.name,
                ok=False,
                elapsed=time.perf_counter() - started,
                error=traceback.format_exc(),
            )

    return run_cell


def build_chain(project: Project) -> Inner:
    runner: Inner = base_runner(project)
    for plug in reversed(PLUGINS.chain()):
        runner = _wrap(plug, runner)
    return runner


def _wrap(plug: Any, inner: Inner) -> Inner:
    def wrapped(cell: RenderedCell, ctx: RunContext) -> RunResult:
        return plug.run(cell, ctx, inner)

    return wrapped


def run_project(project: Project, select: list[str] | None = None) -> list[RunResult]:
    conn = _conduit(project)
    ctx = RunContext(
        conn=conn, root=project.root, overrides=project.overrides, config=project.config
    )
    chain = build_chain(project)
    results: list[RunResult] = []
    try:
        for name in _selection(project, select):
            cell = project.cells[name]
            try:
                result = chain(cell, ctx)
            except Exception:  # a buggy plugin must not kill the run
                result = RunResult(cell=name, ok=False, error=traceback.format_exc())
            results.append(result)
    finally:
        conn.close()
        if ctx.tmpdir:
            shutil.rmtree(ctx.tmpdir, ignore_errors=True)
    return results
