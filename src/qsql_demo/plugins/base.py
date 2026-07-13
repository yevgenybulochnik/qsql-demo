"""The Plugin base: config fields + validation, and optional run-time behavior.

A plugin bundles up to two capabilities:

* ``Config`` — a pydantic model whose fields become directives; validators run
  on the merged config. Field merge strategy rides on the field via ``qfield``.
* ``run`` — a decorator around cell execution: call ``inner`` zero or more
  times, do work before/after. Lower ``priority`` wraps outermore.
"""

from __future__ import annotations

from typing import Any, Callable, ClassVar

from pydantic import BaseModel, Field

from ..models import Merge, RenderedCell, RunContext, RunResult, Scope

Inner = Callable[[RenderedCell, RunContext], RunResult]


class EmptyConfig(BaseModel):
    """Default Config for behavior-only plugins: contributes no directives."""


def qfield(default: Any = None, *, merge: Merge = Merge.OVERRIDE, **kwargs: Any) -> Any:
    """A pydantic Field carrying qsql's per-field merge strategy."""
    extra = dict(kwargs.pop("json_schema_extra", None) or {})
    extra["qsql_merge"] = merge.value
    return Field(default, json_schema_extra=extra, **kwargs)


class Plugin:
    name: ClassVar[str] = ""
    scope: ClassVar[Scope] = Scope.BOTH
    priority: ClassVar[int] = 0
    Config: ClassVar[type[BaseModel]] = EmptyConfig

    def run(self, cell: RenderedCell, ctx: RunContext, inner: Inner) -> RunResult:
        return inner(cell, ctx)
