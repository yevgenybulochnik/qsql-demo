"""Watch a qsql file: recompile on save, rerun changed cells + their dependents.

Change detection hashes SQL bodies only, so config-only edits don't trigger
reruns (known limitation). Cells with autorun:false are skipped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from .compiler import Project, compile_file
from .errors import QsqlError
from .graph import downstream
from .models import RunResult
from .runner import run_project


def hashes_of(project: Project) -> dict[str, str]:
    return {name: cell.hash for name, cell in project.cells.items()}


def plan_rerun(old_hashes: dict[str, str], project: Project) -> list[str]:
    """Changed cells (new ones count) plus downstream, autorun:false filtered out."""
    changed = {n for n, c in project.cells.items() if old_hashes.get(n) != c.hash}
    targets = downstream(list(project.cells), project.edges, changed)
    return [n for n in targets if project.cells[n].config.autorun]


def run_changed(
    path: Path | str,
    old_hashes: dict[str, str],
    overrides: dict[str, Any] | None = None,
) -> tuple[Project, list[RunResult]]:
    project = compile_file(path, overrides)
    to_run = plan_rerun(old_hashes, project)
    results = run_project(project, select=to_run, closure=False) if to_run else []
    return project, results


def watch_events(
    path: Path | str, overrides: dict[str, Any] | None = None
) -> Iterator[tuple[Project | None, list[RunResult] | QsqlError]]:
    """Initial full autorun pass, then one event per file save.

    Yields (project, results); on compile failure yields (None, error) and
    keeps watching.
    """
    import watchfiles

    path = Path(path)
    project = compile_file(path, overrides)
    autorun = [n for n in project.order if project.cells[n].config.autorun]
    results = run_project(project, select=autorun, closure=False) if autorun else []
    yield project, results
    hashes = hashes_of(project)
    for _ in watchfiles.watch(path):
        try:
            project, results = run_changed(path, hashes, overrides)
        except QsqlError as exc:
            yield None, exc
            continue
        hashes = hashes_of(project)
        yield project, results
