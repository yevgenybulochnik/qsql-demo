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


def _load_ext_cached(ctx: RunContext, ext: str) -> None:
    if ext not in ctx.ext_cache:
        _load_extension(ctx.conn, ext)
        ctx.ext_cache.add(ext)


class RunSession:
    """Reusable conduit state across runs: connection, temp dir, extension cache.

    watch/TUI pass one session so reruns skip reconnect/re-LOAD; the conduit
    reconnects automatically when the project's target database changes.
    Without a session, run_project creates and closes a private one per run.
    """

    def __init__(self) -> None:
        self.conn: Any = None
        self.tmpdir: str | None = None
        self.loaded_extensions: set[str] = set()
        self._target: str | None = None

    def conduit(self, project: Project) -> Any:
        spec = (project.config.input or {}).get("duckdb")
        path = spec.get("path") if isinstance(spec, dict) else spec
        target = str(project.root / path) if path else ":memory:"
        if self.conn is None or target != self._target:
            if self.conn is not None:
                self.conn.close()
            self.conn = duckdb.connect(target)
            self._target = target
            self.loaded_extensions = set()
        return self.conn

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None
            self._target = None
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.tmpdir = None
        self.loaded_extensions = set()


def _selection(project: Project, select: list[str] | None, closure: bool) -> list[str]:
    if select is None:
        return list(project.order)
    unknown = [s for s in select if s not in project.cells]
    if unknown:
        from .errors import ConfigError

        raise ConfigError(f"unknown cell(s) in --select: {', '.join(unknown)}")
    wanted: set[str] = set(select)
    if closure:  # selected cells plus their upstream closure
        stack = list(select)
        while stack:
            name = stack.pop()
            wanted.add(name)
            stack.extend(u for u in project.cells[name].depends_on if u not in wanted)
    return [n for n in project.order if n in wanted]


def base_runner(project: Project) -> Inner:
    """The innermost cell-runner; `project` rides in via closure so the chain
    signature stays (cell, ctx)."""

    def run_cell(cell: RenderedCell, ctx: RunContext) -> RunResult:
        started = time.perf_counter()
        try:
            sink = make_sink(cell.config, ctx.root)
            for ext in (*cell.extensions, *sink.requires):
                _load_ext_cached(ctx, ext)
            for upstream in cell.depends_on:
                up_sink = make_sink(project.cells[upstream].config, ctx.root)
                for ext in up_sink.requires:
                    _load_ext_cached(ctx, ext)
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


def run_project(
    project: Project,
    select: list[str] | None = None,
    closure: bool = True,
    session: RunSession | None = None,
) -> list[RunResult]:
    owns_session = session is None
    session = session or RunSession()
    ctx = RunContext(
        conn=session.conduit(project),
        root=project.root,
        overrides=project.overrides,
        config=project.config,
        tmpdir=session.tmpdir,
        ext_cache=session.loaded_extensions,
    )
    chain = build_chain(project)
    results: list[RunResult] = []
    try:
        _notify(ctx, "before_run", lambda p: p.before_run(project, ctx))
        for name in _selection(project, select, closure):
            cell = project.cells[name]
            try:
                result = chain(cell, ctx)
            except Exception:  # a buggy plugin must not kill the run
                result = RunResult(cell=name, ok=False, error=traceback.format_exc())
            results.append(result)
        _notify(ctx, "after_run", lambda p: p.after_run(project, results))
    finally:
        session.tmpdir = ctx.tmpdir  # adopt a lazily-created temp dir
        if owns_session:
            session.close()
    return results


def _notify(ctx: RunContext, hook: str, call: Callable[[Any], None]) -> None:
    """Fire-and-forget lifecycle notifications: failures are logged, never fatal."""
    for plug in PLUGINS.overriding(hook):
        try:
            call(plug)
        except Exception:
            ctx.log.append(f"plugin {plug.name!r} {hook} failed:\n{traceback.format_exc()}")
