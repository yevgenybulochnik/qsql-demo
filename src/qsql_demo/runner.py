"""Execute a compiled Project: run each cell on its engine and land it via its sink.

Walks cells in topological order over a single conduit DuckDB connection. Each
cell runs through a decorator chain: registered plugins that override ``run``
wrap the base runner (priority-sorted, lower = outermore), which ATTACHes the
cell's sink and its upstreams' sinks so ref() expressions resolve, loads the
cell's DuckDB extensions, runs the executor, and writes the sink. The catch-all
error wrapper sits outside the chain, so a failing plugin degrades to an error
result and the run keeps going. Relative paths resolve against the project dir.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import duckdb

from .errors import ExecutorError, SinkError
from .models import RenderedCell, RunResult
from .registry import EXECUTORS, PLUGINS, SINKS
from .runtime import RunContext

if TYPE_CHECKING:
    from .compiler import Project

# ensure builtin executors/sinks are registered
from . import executors as _executors  # noqa: E402,F401
from . import sinks as _sinks  # noqa: E402,F401

CellRunner = Callable[[RenderedCell, RunContext], RunResult]


def run_project(project: "Project", project_dir: str | Path, select=None) -> list[RunResult]:
    """Run the selected cells (default: all, topo order) and return their results."""
    names = project.select(select) if select else project.order()
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    chain = _build_chain(project)
    results: list[RunResult] = []
    with contextlib.chdir(project_dir):
        ctx = RunContext(duck=duckdb.connect(), project_dir=project_dir)
        try:
            for name in names:
                results.append(_run_cell(chain, project.cell(name), ctx))
        finally:
            ctx.close()
    return results


def _run_cell(chain: CellRunner, cell: RenderedCell, ctx: RunContext) -> RunResult:
    try:
        return chain(cell, ctx)
    except (ExecutorError, SinkError) as exc:
        return RunResult(name=cell.name, target="", error=str(exc))
    except Exception as exc:  # surface any backend/plugin error on the result, keep going
        return RunResult(name=cell.name, target="", error=f"{type(exc).__name__}: {exc}")


def _build_chain(project: "Project") -> CellRunner:
    """Wrap the base runner with every plugin that overrides ``run``."""
    chain = _base_runner(project)
    for plugin_cls in reversed(PLUGINS.run_plugins()):  # innermost first, lowest priority outermost
        chain = _wrap(plugin_cls(), chain)
    return chain


def _wrap(plugin, inner: CellRunner) -> CellRunner:
    def wrapped(cell: RenderedCell, ctx: RunContext) -> RunResult:
        return plugin.run(cell, ctx, inner)

    return wrapped


def _base_runner(project: "Project") -> CellRunner:
    """The innermost runner: prepare sinks, load extensions, execute, land."""

    def base(cell: RenderedCell, ctx: RunContext) -> RunResult:
        executor_cls = EXECUTORS.get(cell.engine)
        sink_cls = SINKS.get(cell.sink)
        if executor_cls is None:
            return RunResult(name=cell.name, target="", error=f"no executor for engine {cell.engine!r}")
        if sink_cls is None:
            return RunResult(name=cell.name, target="", error=f"no sink for {cell.sink!r}")

        sink = sink_cls()
        # ATTACH this cell's sink and every upstream's sink so refs resolve
        sink.prepare(cell.config, ctx)
        for upstream in project.deps.get(cell.name, ()):
            up_cell = project.cell(upstream)
            up_sink = SINKS.get(up_cell.sink)
            if up_sink is not None:
                up_sink().prepare(up_cell.config, ctx)

        for ext in cell.extensions:
            ctx.load_extension(ext)

        result = executor_cls().run(cell, ctx)
        return sink.write(cell, result, ctx)

    return base
