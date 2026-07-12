"""Watch a .qsql file and rebuild changed cells (and their downstream) on save.

The rebuild-planning logic is pure and unit-tested; the watchfiles loop is a thin
driver around it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from watchfiles import watch as _watch

from .compiler import Project
from .errors import QsqlError
from .graph import downstream


def _autorun(cell: Any) -> bool:
    return bool(getattr(cell.config, "autorun", True))


def changed_cells(old: Project | None, new: Project) -> list[str]:
    """Cells whose SQL body changed (or are new) between two compiles, in declaration order."""
    if old is None:
        return list(new.names())
    old_hashes = {name: old.cell(name).hash for name in old.names()}
    return [
        name
        for name in new.names()
        if name not in old_hashes or new.cell(name).hash != old_hashes[name]
    ]


def plan_rebuild(old: Project | None, new: Project) -> list[str]:
    """Changed cells plus their downstream, restricted to autorun cells, in topo order."""
    changed = changed_cells(old, new)
    if not changed:
        return []
    affected = downstream(new.deps, changed)
    return [name for name in affected if _autorun(new.cell(name))]


def watch_file(
    file: str | Path,
    *,
    overrides: dict[str, Any] | None = None,
    on_event: Callable[[str, list[str], Any], None] | None = None,
) -> None:
    """Run autorun cells once, then rebuild changed cells + downstream on each save.

    ``on_event(kind, names, payload)`` is called with kind in
    {``initial``, ``rebuild``, ``error``}.
    """
    file = Path(file)
    project = Project.from_file(file, overrides=overrides)
    initial = [name for name in project.order() if _autorun(project.cell(name))]
    results = project.run(select=initial) if initial else []
    if on_event:
        on_event("initial", initial, results)

    for _changes in _watch(str(file)):
        try:
            new = Project.from_file(file, overrides=overrides)
        except QsqlError as exc:
            if on_event:
                on_event("error", [], exc)
            continue
        names = plan_rebuild(project, new)
        results = new.run(select=names) if names else []
        if on_event:
            on_event("rebuild", names, results)
        project = new
