"""Render a cell's SQL body with Jinja2.

Only SQL bodies are rendered (config values are literal). The template context
exposes ``ref``/``source``/``var``/``env`` globals plus ``vars``/``config``:

- ``ref(name)`` records a dependency edge and returns the producer cell's
  read-back expression (supplied by ``ref_resolver``).
- ``source(name_or_path, **opts)`` returns a DuckDB reader expression and records
  any DuckDB extensions the reader needs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from jinja2 import Environment, StrictUndefined

from .errors import RenderError
from .registry import SOURCE_READERS, SourceReaderRegistry
from .sources import resolve_source

_MISSING = object()


@dataclass
class RenderResult:
    sql: str
    refs: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)


def render_cell(
    *,
    name: str,
    sql_raw: str,
    config: Any,
    ref_resolver: Callable[[str], str],
    source_registry: SourceReaderRegistry = SOURCE_READERS,
) -> RenderResult:
    """Render one cell's SQL, collecting ref edges and required extensions."""
    refs: list[str] = []
    extensions: list[str] = []
    cell_vars = getattr(config, "vars", {}) or {}
    cell_sources = getattr(config, "sources", {}) or {}

    def _ref(target: str) -> str:
        if target not in refs:
            refs.append(target)
        return ref_resolver(target)

    def _source(arg: str, **opts: Any) -> str:
        expr, requires = resolve_source(arg, cell_sources, opts, source_registry)
        for ext in requires:
            if ext not in extensions:
                extensions.append(ext)
        return expr

    def _var(key: str, default: Any = _MISSING) -> Any:
        if key in cell_vars:
            return cell_vars[key]
        if default is _MISSING:
            raise RenderError(f"undefined var {key!r} in cell {name!r}")
        return default

    def _env(key: str, default: Any = None) -> Any:
        return os.environ.get(key, default)

    env = Environment(autoescape=False, undefined=StrictUndefined, keep_trailing_newline=True)
    context = {
        "ref": _ref,
        "source": _source,
        "var": _var,
        "env": _env,
        "vars": cell_vars,
        "config": config,
    }
    try:
        sql = env.from_string(sql_raw).render(**context)
    except RenderError:
        raise
    except Exception as exc:  # jinja UndefinedError, TemplateSyntaxError, ...
        raise RenderError(f"failed to render cell {name!r}: {exc}") from exc

    return RenderResult(sql=sql, refs=refs, extensions=extensions)
