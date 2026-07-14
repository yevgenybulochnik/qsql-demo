class QsqlError(Exception):
    """Base class for all qsql errors."""


class ParseError(QsqlError):
    """The .qsql/.sql file could not be parsed into blocks."""


class ConfigError(QsqlError):
    """A directive is unknown, out of scope, or fails validation."""


class CellError:
    """One cell-level compile error with its file location."""

    def __init__(self, cell: str, line: int, message: str) -> None:
        self.cell = cell
        self.line = line
        self.message = message


class ConfigErrorGroup(ConfigError):
    """Every cell's compile errors, reported together with line context."""

    def __init__(self, where: str, errors: list[CellError]) -> None:
        self.errors = errors
        listing = "\n".join(
            f"  cell {e.cell!r} (line {e.line}): {e.message}" for e in errors
        )
        super().__init__(f"{len(errors)} config error(s) in {where}:\n{listing}")


class CycleError(QsqlError):
    """The cell dependency graph contains a cycle."""


class ExecutorError(QsqlError):
    """A cell's engine failed to execute its SQL."""


class SinkError(QsqlError):
    """A cell's output could not be materialized at its destination."""
