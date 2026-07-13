"""The builtin directive vocabulary, expressed as config plugins."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator

from ..models import Merge, Scope
from ..registry import EXECUTORS, SINKS, plugin
from .base import Plugin, qfield


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
    class Config(BaseModel):
        vars: dict[str, Any] = qfield({}, merge=Merge.DEEP)


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
