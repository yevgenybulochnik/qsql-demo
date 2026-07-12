"""Execute a compiled Project: run each cell on its engine and land it via its sink.

Walks cells in topological order over a single conduit DuckDB connection, ATTACHing
each cell's sink and its upstreams' sinks so ref() expressions resolve, then runs
the executor and writes the sink. Relative paths resolve against the project dir.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from .errors import ExecutorError, SinkError
from .models import RunResult
from .registry import EXECUTORS, SINKS
from .runtime import RunContext

if TYPE_CHECKING:
    from .compiler import Project

# ensure builtin executors/sinks are registered
from . import executors as _executors  # noqa: E402,F401
from . import sinks as _sinks  # noqa: E402,F401


def run_project(project: "Project", project_dir: str | Path, select=None) -> list[RunResult]:
    """Run the selected cells (default: all, topo order) and return their results."""
    names = project.select(select) if select else project.order()
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    results: list[RunResult] = []
    with contextlib.chdir(project_dir):
        ctx = RunContext(duck=duckdb.connect(), project_dir=project_dir)
        try:
            for name in names:
                results.append(_run_cell(project, name, ctx))
        finally:
            ctx.close()
    return results


def _run_cell(project: "Project", name: str, ctx: RunContext) -> RunResult:
    cell = project.cell(name)
    executor_cls = EXECUTORS.get(cell.engine)
    sink_cls = SINKS.get(cell.sink)
    if executor_cls is None:
        return RunResult(name=name, target="", error=f"no executor for engine {cell.engine!r}")
    if sink_cls is None:
        return RunResult(name=name, target="", error=f"no sink for {cell.sink!r}")

    sink = sink_cls()
    try:
        # ATTACH this cell's sink and every upstream's sink so refs resolve
        sink.prepare(cell.config, ctx)
        for upstream in project.deps.get(name, ()):
            up_cell = project.cell(upstream)
            up_sink = SINKS.get(up_cell.sink)
            if up_sink is not None:
                up_sink().prepare(up_cell.config, ctx)

        for ext in cell.extensions:
            ctx.load_extension(ext)

        result = executor_cls().run(cell, ctx)
        return sink.write(cell, result, ctx)
    except (ExecutorError, SinkError) as exc:
        return RunResult(name=name, target="", error=str(exc))
    except Exception as exc:  # surface any backend error on the result, keep going
        return RunResult(name=name, target="", error=f"{type(exc).__name__}: {exc}")
