"""Compile pipeline: parse -> resolve config -> render -> graph => Project."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bootstrap import load_builtins
from .config import resolve_cell, resolve_engine, resolve_global, resolve_sink_type
from .errors import ConfigError
from .graph import topo_sort
from .models import RenderedCell, RunResult
from .parser import body_hash, parse_text
from .render import render_sql
from .sinks import make_sink


@dataclass
class Project:
    root: Path
    path: Path | None
    config: Any
    global_raw: dict[str, Any]
    cells: dict[str, RenderedCell]
    order: list[str]
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def edges(self) -> dict[str, list[str]]:
        return {name: cell.depends_on for name, cell in self.cells.items()}

    def run(self, select: list[str] | None = None) -> list[RunResult]:
        from .runner import run_project

        return run_project(self, select=select)


def compile_text(
    text: str,
    root: Path | str = ".",
    path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> Project:
    load_builtins()
    root = Path(root)
    overrides = overrides or {}
    blocks = parse_text(text)
    header, cell_blocks = blocks[0], blocks[1:]
    global_cfg = resolve_global(header.directives, overrides)
    configs = {
        blk.name: resolve_cell(header.directives, blk.directives, overrides, name=blk.name)
        for blk in cell_blocks
    }
    sinks = {name: make_sink(cfg, root) for name, cfg in configs.items()}

    cells: dict[str, RenderedCell] = {}
    for blk in cell_blocks:
        cfg = configs[blk.name]
        sql, rec = render_sql(blk.name, blk.sql, cfg, sinks, root)
        deps = list(cfg.depends_on)
        for dep in deps:
            if dep not in configs:
                raise ConfigError(f"cell {blk.name!r}: unknown cell {dep!r} in depends_on")
        for edge in rec.edges:
            if edge not in deps:
                deps.append(edge)
        extensions = list(dict.fromkeys([*cfg.extensions, *rec.extensions]))
        cells[blk.name] = RenderedCell(
            name=blk.name,
            config=cfg,
            sql_raw=blk.sql,
            sql=sql,
            hash=body_hash(blk.sql),
            engine=resolve_engine(cfg),
            sink_type=resolve_sink_type(cfg),
            depends_on=deps,
            extensions=extensions,
            uses_sources=rec.used_source,
            line=blk.line,
        )

    for cell in cells.values():
        if cell.engine != "duckdb" and (cell.depends_on or cell.uses_sources or cell.extensions):
            raise ConfigError(
                f"cell {cell.name!r} uses ref()/source()/@extensions and must run on duckdb, "
                f"not {cell.engine!r} (duckdb is the cross-cell conduit)"
            )

    order = topo_sort(list(cells), {n: c.depends_on for n, c in cells.items()})
    project = Project(
        root=root,
        path=path,
        config=global_cfg,
        global_raw=header.directives,
        cells=cells,
        order=order,
        overrides=overrides,
    )
    from .registry import PLUGINS

    for plug in PLUGINS.overriding("after_compile"):
        plug.after_compile(project)  # a validation seam: raising rejects the compile
    return project


def compile_file(path: Path | str, overrides: dict[str, Any] | None = None) -> Project:
    p = Path(path)
    return compile_text(p.read_text(), root=p.parent, path=p, overrides=overrides)
