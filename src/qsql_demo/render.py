"""Jinja rendering of SQL bodies only — config values stay literal.

Template globals: ``ref(cell)`` emits the producer's sink read-back expression
and records a dependency edge; ``source(name_or_path, **opts)`` resolves a file
reader and records required DuckDB extensions; ``var(key, default)`` reads
config vars; ``env(key, default)`` reads the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from jinja2 import Environment, StrictUndefined, TemplateError

from .errors import ConfigError
from .registry import PLUGINS
from .sinks.base import Sink
from .sources import reader_for

_MISSING = object()


@dataclass
class Recorder:
    """Side-channel state collected while rendering one cell."""

    edges: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    used_source: bool = False

    def add_edge(self, name: str) -> None:
        if name not in self.edges:
            self.edges.append(name)

    def add_extensions(self, exts: list[str]) -> None:
        for ext in exts:
            if ext not in self.extensions:
                self.extensions.append(ext)


def render_sql(
    name: str,
    sql_raw: str,
    config: Any,
    producers: Mapping[str, Sink],
    root: Path,
) -> tuple[str, Recorder]:
    rec = Recorder()

    def ref(other: str) -> str:
        if other not in producers:
            raise ConfigError(f"cell {name!r}: unknown cell {other!r} in ref()")
        rec.add_edge(other)
        return producers[other].ref_expr(other)

    def source(name_or_path: str, **opts: Any) -> str:
        sources_cfg = config.sources or {}
        if name_or_path in sources_cfg:
            spec = dict(sources_cfg[name_or_path])
            path = spec.pop("path")
            type_ = spec.pop("type", None)
            opts = {**spec, **opts}
        else:
            path, type_ = name_or_path, opts.pop("type", None)
        reader = reader_for(path, type_)
        rec.add_extensions(reader.requires)
        rec.used_source = True
        abs_path = path if os.path.isabs(path) else str(root / path)
        return reader.expr(abs_path, **opts)

    def var(key: str, default: Any = _MISSING) -> Any:
        vars_ = config.vars or {}
        if key in vars_:
            return vars_[key]
        if default is not _MISSING:
            return default
        raise ConfigError(f"cell {name!r}: undefined var {key!r}")

    def env(key: str, default: str = "") -> str:
        return os.environ.get(key, default)

    context: dict[str, Any] = {"vars": config.vars, "config": config}
    for plug in PLUGINS.overriding("render_context"):
        updated = plug.render_context(name, config, context)
        if updated is not None:
            context = updated
    # core globals apply last: plugins may add, never shadow (ref/source carry
    # side-channel state a replacement could not)
    context.update(ref=ref, source=source, var=var, env=env)

    jinja = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    try:
        sql = jinja.from_string(sql_raw).render(**context)
    except TemplateError as exc:
        raise ConfigError(f"cell {name!r}: template error: {exc}") from exc

    for plug in PLUGINS.overriding("after_render"):
        out = plug.after_render(name, config, sql)
        if out is not None:
            sql = out
    return sql, rec
