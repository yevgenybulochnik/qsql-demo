"""Exception hierarchy for qsql."""

from __future__ import annotations


class QsqlError(Exception):
    """Base class for every qsql error."""


class ParseError(QsqlError):
    """Raised when a .qsql file cannot be parsed."""


class ConfigError(QsqlError):
    """Raised when global/cell configuration is invalid or inconsistent."""


class RenderError(QsqlError):
    """Raised when a cell's SQL body fails to render (Jinja error, undefined var)."""


class CycleError(QsqlError):
    """Raised when the cell dependency graph contains a cycle."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = list(cycle)
        super().__init__("dependency cycle: " + " -> ".join(self.cycle))


class ExecutorError(QsqlError):
    """Raised when an engine/executor fails to run a cell."""


class SinkError(QsqlError):
    """Raised when a sink fails to land a cell's output."""
