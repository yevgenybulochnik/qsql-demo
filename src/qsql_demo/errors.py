class QsqlError(Exception):
    """Base class for all qsql errors."""


class ParseError(QsqlError):
    """The .qsql/.sql file could not be parsed into blocks."""


class ConfigError(QsqlError):
    """A directive is unknown, out of scope, or fails validation."""


class CycleError(QsqlError):
    """The cell dependency graph contains a cycle."""


class ExecutorError(QsqlError):
    """A cell's engine failed to execute its SQL."""


class SinkError(QsqlError):
    """A cell's output could not be materialized at its destination."""
