"""The Plugin base: a config model (with validators) plus optional run decoration.

A plugin bundles (1) a pydantic ``Config`` whose fields are composed into the
``GlobalConfig``/``CellConfig`` models by ``config.build_models`` and (2) an
optional ``run`` hook that wraps cell execution in the runner's decorator chain
(ordered by ``priority``, lower = outermore). Compile-time behavior (rendering,
edges, engine/sink resolution) stays in core.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field

from ..models import Merge, Scope


class EmptyConfig(BaseModel):
    """The Config for plugins that contribute no config fields."""


def qfield(default: Any = None, *, merge: Merge = Merge.OVERRIDE, **kwargs: Any) -> Any:
    """A pydantic ``Field`` carrying qsql's per-field merge strategy as metadata."""
    return Field(default, json_schema_extra={"qsql_merge": merge.value}, **kwargs)


class Plugin:
    """Base for a qsql plugin.

    Subclasses set ``name`` (required), a ``Config`` pydantic model whose fields
    (declared with ``qfield`` for non-default merge) become config directives at
    ``scope``, and may override ``run`` to decorate cell execution.
    """

    name: str = ""
    Config: type[BaseModel] = EmptyConfig
    scope: Scope = Scope.BOTH
    priority: int = 0

    def run(self, cell: Any, ctx: Any, inner: Callable[[Any, Any], Any]) -> Any:
        """Decorate cell execution; the default passes through to ``inner``."""
        return inner(cell, ctx)
