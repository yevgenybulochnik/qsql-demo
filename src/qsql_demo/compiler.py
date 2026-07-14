"""Compile pipeline: parse -> resolve config -> render -> graph => Project."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bootstrap import load_builtins
from .config import resolve_cell, resolve_engine, resolve_global, resolve_sink_type
from .errors import CellError, ConfigError, ConfigErrorGroup
from .graph import topo_sort
from .models import RawBlock, RenderedCell, RunResult
from .parser import body_hash, parse_text
from .registry import PLUGINS
from .render import render_sql
from .sinks import make_sink


def _cell_error(blk: RawBlock, exc: ConfigError) -> CellError:
    """Strip the cell-name prefix/suffix our own messages carry — the group
    line already names the cell and its line."""
    msg = str(exc)
    for prefix in (f"invalid config for cell {blk.name!r}: ", f"cell {blk.name!r}: "):
        if msg.startswith(prefix):
            msg = msg[len(prefix) :]
            break
    return CellError(cell=blk.name or "<header>", line=blk.line, message=msg.replace(f" (cell {blk.name!r})", ""))


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
    where = str(path) if path else "<text>"
    blocks = parse_text(text)
    header, cell_blocks = blocks[0], blocks[1:]
    global_cfg = resolve_global(header.directives, overrides)

    # stage 1: resolve every cell's config, reporting all failures together
    configs: dict[str, Any] = {}
    errors: list[CellError] = []
    for blk in cell_blocks:
        try:
            configs[blk.name] = resolve_cell(
                header.directives, blk.directives, overrides, name=blk.name
            )
        except ConfigError as exc:
            errors.append(_cell_error(blk, exc))
    if errors:
        raise ConfigErrorGroup(where, errors)
    sinks = {name: make_sink(cfg, root) for name, cfg in configs.items()}

    # stage 2: render + wire every cell, again reporting all failures together
    cells: dict[str, RenderedCell] = {}
    for blk in cell_blocks:
        cfg = configs[blk.name]
        try:
            sql, rec = render_sql(blk.name, blk.sql, cfg, sinks, root)
            deps: list[str] = []
            for plug in PLUGINS.overriding("collect_edges"):
                for dep in plug.collect_edges(blk.name, cfg) or []:
                    if dep not in deps:
                        deps.append(dep)
            for dep in deps:
                if dep not in configs:
                    raise ConfigError(f"unknown cell {dep!r} in depends_on")
            for edge in rec.edges:
                if edge not in deps:
                    deps.append(edge)
            extensions = list(dict.fromkeys([*cfg.extensions, *rec.extensions]))
            engine = resolve_engine(cfg)
            if engine != "duckdb" and (deps or rec.used_source or extensions):
                raise ConfigError(
                    f"uses ref()/source()/@extensions and must run on duckdb, "
                    f"not {engine!r} (duckdb is the cross-cell conduit)"
                )
        except ConfigError as exc:
            errors.append(_cell_error(blk, exc))
            continue
        cells[blk.name] = RenderedCell(
            name=blk.name,
            config=cfg,
            sql_raw=blk.sql,
            sql=sql,
            hash=body_hash(blk.sql),
            engine=engine,
            sink_type=resolve_sink_type(cfg),
            depends_on=deps,
            extensions=extensions,
            uses_sources=rec.used_source,
            line=blk.line,
            line_end=blk.line_end,
            source=blk.source,
        )
    if errors:
        raise ConfigErrorGroup(where, errors)

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
    for plug in PLUGINS.overriding("after_compile"):
        plug.after_compile(project)  # a validation seam: raising rejects the compile
    return project


def compile_file(path: Path | str, overrides: dict[str, Any] | None = None) -> Project:
    p = Path(path)
    return compile_text(p.read_text(), root=p.parent, path=p, overrides=overrides)
