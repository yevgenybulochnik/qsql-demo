"""Compile a .qsql file into a ``Project``.

Pipeline: parse -> resolve global + per-cell config -> render SQL bodies (with a
ref resolver that reads each producer back through its sink) -> build the
dependency DAG. The result is an immutable ``Project`` the CLI/runner/TUI drive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .config import resolve_cell, resolve_engine, resolve_global, resolve_sink
from .errors import ConfigError
from .graph import downstream, topo_sort
from .models import RenderedCell
from .parser import parse
from .plugins import builtin as _builtin  # noqa: F401  (ensure directives registered)
from . import executors as _executors  # noqa: F401  (ensure executors registered)
from . import sinks as _sinks  # noqa: F401  (ensure sinks registered)
from . import sources as _sources  # noqa: F401  (ensure source readers registered)
from .registry import EXECUTORS, PLUGINS, SINKS, PluginRegistry
from .render import render_cell


def _ref_expr_for(cfg: Any, name: str) -> str:
    """How a downstream DuckDB cell reads cell ``name`` back, delegated to its sink."""
    sink_type = resolve_sink(cfg)
    sink_cls = SINKS.get(sink_type)
    if sink_cls is None:
        raise ConfigError(f"unknown sink type: {sink_type!r}")
    return sink_cls().ref_expr(name, cfg)


def _check_engine_guardrail(cells: dict[str, RenderedCell], deps: dict[str, set[str]]) -> None:
    """Cells that read local parquet (ref/depends_on/source) must run on DuckDB.

    Only enforced when the engine's executor is registered and cannot read parquet;
    an unregistered engine is left to fail at run time (keeps compile/list working
    without optional engines installed).
    """
    for name, cell in cells.items():
        executor_cls = EXECUTORS.get(cell.engine)
        if executor_cls is None or executor_cls.reads_parquet:
            continue
        if deps.get(name) or cell.extensions:
            raise ConfigError(
                f"cell {name!r} runs on {cell.engine!r} but uses ref()/depends_on/source(); "
                "cells that read local outputs must run on duckdb"
            )


class Project:
    """A compiled qsql project: resolved global config + rendered cells + DAG."""

    def __init__(
        self,
        *,
        global_config: Any,
        cells: dict[str, RenderedCell],
        deps: dict[str, set[str]],
        order: list[str],
        names: list[str],
        project_dir: str | Path | None = None,
    ) -> None:
        self.global_config = global_config
        self.cells = cells
        self._deps = deps
        self._order = order
        self._names = names
        self.project_dir = Path(project_dir) if project_dir is not None else Path.cwd()

    # -- construction --------------------------------------------------------

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        overrides: dict[str, Any] | None = None,
        registry: PluginRegistry = PLUGINS,
        project_dir: str | Path | None = None,
    ) -> "Project":
        overrides = overrides or {}
        blocks = parse(text)
        header = blocks[0]
        cell_blocks = [b for b in blocks if not b.is_header]

        global_config = resolve_global(header.directives, overrides, registry)
        configs = {
            b.name: resolve_cell(header.directives, b.directives, overrides, registry)
            for b in cell_blocks
        }

        def ref_resolver(target: str) -> str:
            if target not in configs:
                raise ConfigError(f"cell references unknown cell {target!r}")
            return _ref_expr_for(configs[target], target)

        cells: dict[str, RenderedCell] = {}
        deps: dict[str, set[str]] = {}
        for block in cell_blocks:
            cfg = configs[block.name]
            result = render_cell(
                name=block.name, sql_raw=block.sql, config=cfg, ref_resolver=ref_resolver
            )
            config_exts = list(getattr(cfg, "extensions", []) or [])
            extensions = config_exts + [e for e in result.extensions if e not in config_exts]
            cells[block.name] = RenderedCell(
                name=block.name,
                config=cfg,
                sql=result.sql,
                sql_raw=block.sql,
                engine=resolve_engine(cfg),
                sink=resolve_sink(cfg),
                refs=result.refs,
                extensions=extensions,
                hash=block.hash,
            )
            deps[block.name] = set(result.refs) | set(getattr(cfg, "depends_on", []) or [])

        _check_engine_guardrail(cells, deps)
        order = topo_sort(deps)  # validates unknown deps + cycles
        names = [b.name for b in cell_blocks]
        return cls(
            global_config=global_config,
            cells=cells,
            deps=deps,
            order=order,
            names=names,
            project_dir=project_dir,
        )

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        overrides: dict[str, Any] | None = None,
        registry: PluginRegistry = PLUGINS,
    ) -> "Project":
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        return cls.from_text(
            text, overrides=overrides, registry=registry, project_dir=path.parent
        )

    # -- execution -----------------------------------------------------------

    def run(self, select: Iterable[str] | None = None) -> list:
        """Run the selected cells (default all) and return their RunResults."""
        from .runner import run_project

        return run_project(self, self.project_dir, select=list(select) if select else None)

    # -- queries -------------------------------------------------------------

    @property
    def deps(self) -> dict[str, set[str]]:
        return self._deps

    def order(self) -> list[str]:
        """Cell names in dependency (topological) order."""
        return list(self._order)

    def names(self) -> list[str]:
        """Cell names in declaration order."""
        return list(self._names)

    def cell(self, name: str) -> RenderedCell:
        if name not in self.cells:
            raise KeyError(name)
        return self.cells[name]

    def compiled(self, name: str) -> str:
        """The rendered SQL for a cell."""
        return self.cell(name).sql

    def _ancestors(self, name: str) -> set[str]:
        seen: set[str] = set()
        stack = [name]
        while stack:
            node = stack.pop()
            for upstream in self._deps.get(node, ()):
                if upstream not in seen:
                    seen.add(upstream)
                    stack.append(upstream)
        return seen

    def select(self, patterns: Iterable[str] | None) -> list[str]:
        """Resolve a selection: ``name``, ``+name`` (with upstream), ``name+`` (with downstream)."""
        if not patterns:
            return self.order()
        chosen: set[str] = set()
        for pattern in patterns:
            if pattern.startswith("+"):
                name = pattern[1:]
                chosen |= self._ancestors(name) | {name}
            elif pattern.endswith("+"):
                name = pattern[:-1]
                chosen |= set(downstream(self._deps, [name]))
            else:
                chosen.add(pattern)
        for name in chosen:
            if name not in self.cells:
                raise ConfigError(f"unknown cell in selection: {name!r}")
        return [n for n in self.order() if n in chosen]
