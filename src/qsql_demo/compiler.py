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
from .registry import DIRECTIVES, DirectiveRegistry
from .render import render_cell


def _ref_expr_for(cfg: Any, name: str) -> str:
    """How a downstream DuckDB cell reads cell ``name`` back, given its sink.

    Step 5 supports the default parquet sink; other sinks are wired via
    ``Sink.ref_expr`` when sinks land (step 6).
    """
    sink = resolve_sink(cfg)
    if sink != "parquet":
        raise ConfigError(f"ref to a {sink!r}-sink cell is not supported yet")
    out_dir = (getattr(cfg, "output", {}) or {}).get("dir", "data/")
    return f"read_parquet('{out_dir.rstrip('/')}/{name}.parquet')"


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
    ) -> None:
        self.global_config = global_config
        self.cells = cells
        self._deps = deps
        self._order = order
        self._names = names

    # -- construction --------------------------------------------------------

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        overrides: dict[str, Any] | None = None,
        registry: DirectiveRegistry = DIRECTIVES,
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
            cells[block.name] = RenderedCell(
                name=block.name,
                config=cfg,
                sql=result.sql,
                sql_raw=block.sql,
                engine=resolve_engine(cfg),
                sink=resolve_sink(cfg),
                refs=result.refs,
                extensions=result.extensions,
                hash=block.hash,
            )
            deps[block.name] = set(result.refs) | set(getattr(cfg, "depends_on", []) or [])

        order = topo_sort(deps)  # validates unknown deps + cycles
        names = [b.name for b in cell_blocks]
        return cls(global_config=global_config, cells=cells, deps=deps, order=order, names=names)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        overrides: dict[str, Any] | None = None,
        registry: DirectiveRegistry = DIRECTIVES,
    ) -> "Project":
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_text(text, overrides=overrides, registry=registry)

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
