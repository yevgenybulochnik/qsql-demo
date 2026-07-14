"""DevLimit: demonstrator after_render transformer.

Set ``dev_limit`` globally (or ``--set dev_limit=100``) to cap every cell's
rows while iterating; a cell opts out with ``-- @dev_limit: null``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator

from ..registry import plugin
from .base import Plugin, qfield


@plugin
class DevLimit(Plugin):
    class Config(BaseModel):
        dev_limit: int | None = qfield(None)

        @field_validator("dev_limit")
        @classmethod
        def _positive(cls, v: int | None) -> int | None:
            if v is not None and v <= 0:
                raise ValueError("dev_limit must be positive")
            return v

    def after_render(self, rctx: Any, sql: str) -> str | None:
        limit = getattr(rctx.config, "dev_limit", None)
        if not limit:
            return None
        body = sql.strip().rstrip(";")
        return f"SELECT * FROM (\n{body}\n) AS __qsql_dev_limit LIMIT {limit};"
