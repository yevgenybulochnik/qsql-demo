"""Unit test for the BigQuery executor using a mocked client (runs offline)."""

from __future__ import annotations

import qsql_demo.executors  # noqa: F401  (register executors)
from qsql_demo.config import resolve_cell
from qsql_demo.models import RenderedCell
from qsql_demo.registry import EXECUTORS


class _Job:
    def __init__(self, rows):
        self._rows = rows

    def result(self):
        return self._rows


class _Client:
    def __init__(self, rows):
        self._rows = rows

    def query(self, sql):
        return _Job(self._rows)


def _cell() -> RenderedCell:
    cfg = resolve_cell({}, {"engine": "bigquery"}, {})
    return RenderedCell(
        name="events",
        config=cfg,
        sql="SELECT user_id, event FROM t",
        sql_raw="",
        engine="bigquery",
        sink="parquet",
    )


def test_bigquery_executor_builds_frame(monkeypatch) -> None:
    ex = EXECUTORS.get("bigquery")()
    rows = [{"user_id": 1, "event": "login"}, {"user_id": 2, "event": "signup"}]
    monkeypatch.setattr(ex, "_client", lambda config, ctx: _Client(rows))

    result = ex.run(_cell(), ctx=None)
    assert result.sql is None
    assert result.frame["user_id"].to_list() == [1, 2]
    assert result.frame["event"].to_list() == ["login", "signup"]


def test_bigquery_executor_does_not_read_parquet() -> None:
    assert EXECUTORS.get("bigquery").reads_parquet is False
