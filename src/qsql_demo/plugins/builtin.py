"""Builtin plugins: each bundles one config directive and its validation.

Each plugin's ``Config`` contributes its field to the ``GlobalConfig``/
``CellConfig`` models assembled by ``config.build_models``; ``scope`` controls
where the directive may appear and the ``qfield`` metadata how a cell value
merges with the inherited global one.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator

from ..models import Merge, Scope
from ..registry import plugin
from .base import Plugin, qfield


@plugin
class Engine(Plugin):
    name = "engine"
    scope = Scope.BOTH

    class Config(BaseModel):
        engine: str | None = None


@plugin
class Input(Plugin):
    name = "input"
    scope = Scope.BOTH

    class Config(BaseModel):
        input: dict[str, Any] = qfield({}, merge=Merge.DEEP)


@plugin
class Sources(Plugin):
    name = "sources"
    scope = Scope.BOTH

    class Config(BaseModel):
        sources: dict[str, Any] = qfield({}, merge=Merge.DEEP)


@plugin
class Extensions(Plugin):
    name = "extensions"
    scope = Scope.BOTH

    class Config(BaseModel):
        extensions: list[str] = qfield([], merge=Merge.EXTEND)


@plugin
class Output(Plugin):
    name = "output"
    scope = Scope.BOTH

    class Config(BaseModel):
        output: dict[str, Any] = qfield({"type": "parquet", "dir": "data/"}, merge=Merge.DEEP)

        @field_validator("output")
        @classmethod
        def _known_sink_type(cls, value: dict[str, Any]) -> dict[str, Any]:
            from .. import sinks as _sinks  # noqa: F401  (registers the builtin sinks)
            from ..registry import SINKS

            sink_type = (value or {}).get("type", "parquet")
            if sink_type not in SINKS:
                raise ValueError(f"unknown sink type: {sink_type!r}")
            return value


@plugin
class Autorun(Plugin):
    name = "autorun"
    scope = Scope.BOTH

    class Config(BaseModel):
        autorun: bool = True


@plugin
class Vars(Plugin):
    name = "vars"
    scope = Scope.BOTH

    class Config(BaseModel):
        vars: dict[str, Any] = qfield({}, merge=Merge.DEEP)


@plugin
class DependsOn(Plugin):
    name = "depends_on"
    scope = Scope.CELL

    class Config(BaseModel):
        depends_on: list[str] = qfield([], merge=Merge.EXTEND)


@plugin
class Tags(Plugin):
    name = "tags"
    scope = Scope.CELL

    class Config(BaseModel):
        tags: list[str] = qfield([], merge=Merge.EXTEND)
