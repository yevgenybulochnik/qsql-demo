"""The builtin directive vocabulary — plugins bundling config with behavior.

Vars/Sources own their directive *and* the template global that consumes it;
Refs/Env are behavior-only contributors of the remaining core globals.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, field_validator

from ..errors import ConfigError
from ..models import Merge, Scope
from ..registry import EXECUTORS, SINKS, plugin
from .base import Plugin, qfield

_MISSING = object()


@plugin
class Engine(Plugin):
    class Config(BaseModel):
        engine: str | None = qfield(None)

        @field_validator("engine")
        @classmethod
        def _registered(cls, v: str | None) -> str | None:
            if v is not None and v not in EXECUTORS:
                raise ValueError(
                    f"engine {v!r} is not a registered executor (have: {', '.join(EXECUTORS.names())})"
                )
            return v


@plugin
class Input(Plugin):
    class Config(BaseModel):
        input: dict[str, Any] = qfield({}, merge=Merge.DEEP)


@plugin
class Sources(Plugin):
    """The sources: directive plus the source() template global that reads it."""

    class Config(BaseModel):
        sources: dict[str, Any] = qfield({}, merge=Merge.DEEP)

        @field_validator("sources")
        @classmethod
        def _shape(cls, v: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for name, spec in v.items():
                if isinstance(spec, str):
                    spec = {"path": spec}
                if not isinstance(spec, dict) or "path" not in spec:
                    raise ValueError(f"source {name!r} needs a path (got {spec!r})")
                out[name] = spec
            return out

    def render_context(self, rctx: Any) -> dict[str, Any]:
        from ..sources import reader_for

        def source(name_or_path: str, **opts: Any) -> str:
            sources_cfg = rctx.config.sources or {}
            if name_or_path in sources_cfg:
                spec = dict(sources_cfg[name_or_path])
                path = spec.pop("path")
                type_ = spec.pop("type", None)
                opts = {**spec, **opts}
            else:
                path, type_ = name_or_path, opts.pop("type", None)
            reader = reader_for(path, type_)
            rctx.require_extensions(reader.requires)
            rctx.mark_source_used()
            return reader.expr(rctx.resolve_path(path), **opts)

        return {"source": source}


@plugin
class Extensions(Plugin):
    class Config(BaseModel):
        extensions: list[str] = qfield([], merge=Merge.EXTEND)


@plugin
class Output(Plugin):
    class Config(BaseModel):
        output: dict[str, Any] = qfield({"type": "parquet", "dir": "data/"}, merge=Merge.DEEP)

        @field_validator("output")
        @classmethod
        def _sink_registered(cls, v: dict[str, Any]) -> dict[str, Any]:
            sink_type = v.get("type", "parquet")
            if sink_type not in SINKS:
                raise ValueError(
                    f"output.type {sink_type!r} is not a registered sink (have: {', '.join(SINKS.names())})"
                )
            return v


@plugin
class Autorun(Plugin):
    class Config(BaseModel):
        autorun: bool = qfield(True)


@plugin
class Vars(Plugin):
    """The vars: directive plus the var() template global that reads it."""

    class Config(BaseModel):
        vars: dict[str, Any] = qfield({}, merge=Merge.DEEP)

    def render_context(self, rctx: Any) -> dict[str, Any]:
        values = rctx.config.vars or {}

        def var(key: str, default: Any = _MISSING) -> Any:
            if key in values:
                return values[key]
            if default is not _MISSING:
                return default
            raise ConfigError(f"cell {rctx.name!r}: undefined var {key!r}")

        return {"var": var, "vars": values}


@plugin
class Refs(Plugin):
    """Behavior-only: the ref() global — producer read-back + edge recording."""

    def render_context(self, rctx: Any) -> dict[str, Any]:
        def ref(cell_name: str) -> str:
            rctx.add_edge(cell_name)
            return rctx.producer_expr(cell_name)

        return {"ref": ref}


@plugin
class Env(Plugin):
    """Behavior-only: the env() global."""

    def render_context(self, rctx: Any) -> dict[str, Any]:
        def env(key: str, default: str = "") -> str:
            return os.environ.get(key, default)

        return {"env": env}


@plugin
class DependsOn(Plugin):
    scope = Scope.CELL

    class Config(BaseModel):
        depends_on: list[str] = qfield([], merge=Merge.EXTEND)


@plugin
class Schema(Plugin):
    class Config(BaseModel):
        schema_: str | None = qfield(None, alias="schema")


@plugin
class Tags(Plugin):
    class Config(BaseModel):
        tags: list[str] = qfield([], merge=Merge.EXTEND)
