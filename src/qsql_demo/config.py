"""Build the dynamic pydantic config models and resolve per-cell config.

``build_models`` assembles ``GlobalConfig``/``CellConfig`` from the registered
directives via ``pydantic.create_model`` (the plugin centerpiece). Resolution
merges global -> cell -> run-overrides using each directive's merge strategy,
validates against the model, and derives the resolved engine + sink.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import ConfigDict, Field, ValidationError, create_model

from .errors import ConfigError
from .models import Merge, Scope
from .plugins import builtin as _builtin  # noqa: F401  (ensures builtins registered)
from .registry import DIRECTIVES, DirectiveRegistry
from .util import deep_merge

_MODEL_CONFIG = ConfigDict(extra="forbid")


def _field_spec(directive: type) -> tuple[Any, Any]:
    default = directive.default
    if isinstance(default, (dict, list)):
        return (directive.annotation, Field(default_factory=lambda d=default: copy.deepcopy(d)))
    return (directive.annotation, default)


def build_models(registry: DirectiveRegistry = DIRECTIVES):
    """Return ``(GlobalConfig, CellConfig)`` built from the registered directives."""
    global_fields = {d.key: _field_spec(d) for d in registry.by_scope(Scope.GLOBAL, Scope.BOTH)}
    cell_fields = {d.key: _field_spec(d) for d in registry.by_scope(Scope.CELL, Scope.BOTH)}
    GlobalConfig = create_model("GlobalConfig", __config__=_MODEL_CONFIG, **global_fields)
    CellConfig = create_model("CellConfig", __config__=_MODEL_CONFIG, **cell_fields)
    return GlobalConfig, CellConfig


def _merge_value(existing: Any, value: Any, strategy: Merge) -> Any:
    if strategy is Merge.DEEP and isinstance(existing, dict) and isinstance(value, dict):
        return deep_merge(existing, value)
    if strategy is Merge.EXTEND and isinstance(existing, list) and isinstance(value, list):
        return existing + value
    return value


def _combine(sources: list[dict[str, Any]], registry: DirectiveRegistry) -> dict[str, Any]:
    acc: dict[str, Any] = {}
    for src in sources:
        for key, value in src.items():
            directive = registry.get(key)
            strategy = directive.merge if directive else Merge.OVERRIDE
            acc[key] = _merge_value(acc[key], value, strategy) if key in acc else value
    return acc


def _check_scope(directives: dict[str, Any], allowed: tuple[Scope, ...], where: str, registry: DirectiveRegistry) -> None:
    for key in directives:
        d = registry.get(key)
        if d is None:
            raise ConfigError(f"unknown directive: @{key}")
        if d.scope not in allowed:
            raise ConfigError(f"@{key} is not allowed {where}")


def resolve_global(
    header: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    registry: DirectiveRegistry = DIRECTIVES,
    model: Any = None,
):
    """Resolve the global (header) config."""
    overrides = overrides or {}
    model = model or build_models(registry)[0]
    scopes = (Scope.GLOBAL, Scope.BOTH)
    _check_scope(header, scopes, "in the global header", registry)
    ov = {k: v for k, v in overrides.items() if (d := registry.get(k)) and d.scope in scopes}
    merged = _combine([header, ov], registry)
    try:
        return model(**merged)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def resolve_cell(
    header: dict[str, Any],
    cell: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    registry: DirectiveRegistry = DIRECTIVES,
    model: Any = None,
):
    """Resolve one cell's config: inherit BOTH-scoped header keys, then cell, then overrides."""
    overrides = overrides or {}
    model = model or build_models(registry)[1]
    cell_scopes = (Scope.CELL, Scope.BOTH)

    _check_scope(header, (Scope.GLOBAL, Scope.BOTH), "in the global header", registry)
    _check_scope(cell, cell_scopes, "on a cell", registry)

    inherited = {k: v for k, v in header.items() if registry.get(k).scope is Scope.BOTH}
    ov = {k: v for k, v in overrides.items() if (d := registry.get(k)) and d.scope in cell_scopes}
    merged = _combine([inherited, cell, ov], registry)
    try:
        return model(**merged)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc


def resolve_engine(cfg: Any, default: str = "duckdb") -> str:
    """The cell's engine: explicit ``@engine``, else inferred from a sole ``input`` key, else default."""
    engine = getattr(cfg, "engine", None)
    if engine:
        return engine
    inp = getattr(cfg, "input", None) or {}
    if len(inp) == 1:
        return next(iter(inp))
    if len(inp) > 1:
        raise ConfigError("cannot infer @engine from multiple input keys; set @engine explicitly")
    return default


def resolve_sink(cfg: Any, default: str = "parquet") -> str:
    """The cell's sink type from ``@output.type`` (default parquet)."""
    out = getattr(cfg, "output", None) or {}
    return out.get("type", default)
