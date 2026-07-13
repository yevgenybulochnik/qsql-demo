"""Executor: run a cell's SQL on a backend, land the result as a view DuckDB can read."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..models import RenderedCell, RunContext


def strip_trailing_semicolon(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def result_view(cell_name: str) -> str:
    return f"__qsql_{cell_name}"


class Executor(ABC):
    name: ClassVar[str] = ""

    @abstractmethod
    def execute(self, cell: RenderedCell, ctx: RunContext) -> str:
        """Materialize the cell's result on ctx.conn; return the view name."""
