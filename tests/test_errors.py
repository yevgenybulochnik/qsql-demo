"""Tests for the qsql error hierarchy."""

from __future__ import annotations

import pytest

from qsql_demo.errors import (
    ConfigError,
    CycleError,
    ExecutorError,
    ParseError,
    QsqlError,
    SinkError,
)


@pytest.mark.parametrize(
    "exc", [ParseError, ConfigError, CycleError, ExecutorError, SinkError]
)
def test_errors_subclass_qsqlerror(exc: type[Exception]) -> None:
    assert issubclass(exc, QsqlError)


def test_cycle_error_reports_the_cycle_path() -> None:
    err = CycleError(["a", "b", "a"])
    assert err.cycle == ["a", "b", "a"]
    assert "a -> b -> a" in str(err)
