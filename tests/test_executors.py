import sqlite3

import duckdb
import polars as pl
import pytest

from qsql_demo.config import resolve_cell
from qsql_demo.errors import ExecutorError
from qsql_demo.executors.bigquery_exec import BigQueryExecutor
from qsql_demo.models import RenderedCell, RunContext
from qsql_demo.registry import EXECUTORS


def _cell(name: str, sql: str, cell_raw: dict | None = None) -> RenderedCell:
    cfg = resolve_cell({}, cell_raw or {})
    return RenderedCell(
        name=name, config=cfg, sql_raw=sql, sql=sql, hash="",
        engine="duckdb", sink_type="parquet",
    )


@pytest.fixture
def ctx(tmp_path):
    conn = duckdb.connect()
    yield RunContext(conn=conn, root=tmp_path)
    conn.close()


def test_duckdb_executor_creates_view(ctx) -> None:
    view = EXECUTORS.get("duckdb").execute(_cell("a", "SELECT 42 AS x;"), ctx)
    assert ctx.conn.sql(f'SELECT * FROM "{view}"').fetchall() == [(42,)]


def test_sqlite_executor_registers_result(ctx, tmp_path) -> None:
    db = tmp_path / "nums.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE nums (n INTEGER)")
    con.executemany("INSERT INTO nums VALUES (?)", [(1,), (2,), (3,)])
    con.commit()
    con.close()

    cell = _cell("sq", "SELECT n FROM nums ORDER BY n", {"input": {"sqlite": "nums.sqlite"}})
    view = EXECUTORS.get("sqlite").execute(cell, ctx)
    assert ctx.conn.sql(f'SELECT * FROM "{view}"').fetchall() == [(1,), (2,), (3,)]


def test_sqlite_executor_bad_sql_raises(ctx) -> None:
    cell = _cell("sq", "SELECT * FROM missing", {"input": {"sqlite": ":memory:"}})
    with pytest.raises(ExecutorError, match="sqlite"):
        EXECUTORS.get("sqlite").execute(cell, ctx)


def test_bigquery_same_context_cells_share_a_session(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from qsql_demo.compiler import compile_text

    calls: list[tuple[str, object]] = []

    class FakeJob:
        def __init__(self, sql: str, first: bool) -> None:
            self._sql = sql
            self.session_info = SimpleNamespace(session_id="sess-1") if first else None

        def to_arrow(self):
            return pl.DataFrame({"n": [1, 2, 3]})

    class FakeClient:
        def query(self, sql, job_config=None):
            calls.append((sql, job_config))
            return FakeJob(sql, first=len(calls) == 1)

    monkeypatch.setattr(BigQueryExecutor, "make_client", lambda self, spec: FakeClient())
    monkeypatch.setattr(
        BigQueryExecutor, "_job_config", lambda self, state: {"session": state["session_id"]}
    )
    project = compile_text(
        "/*@ input: { bigquery: { project: p } } */\n"
        "-- @cell parent\nSELECT * FROM src;\n"
        "-- @cell child\nSELECT count(*) AS c FROM {{ ref('parent') }};",
        root=tmp_path,
    )
    assert project.cells["child"].engine == "bigquery"  # legal: same context
    results = {r.cell: r for r in project.run()}
    assert all(r.ok for r in results.values()), [r.error for r in results.values()]

    sqls = [sql for sql, _ in calls]
    assert any(s.startswith("CREATE OR REPLACE TEMP TABLE parent AS") for s in sqls)
    assert "SELECT * FROM parent" in sqls          # extraction reads the temp once
    assert sum("FROM src" in s for s in sqls) == 1  # the parent query ran exactly once
    assert any("count(*)" in s and "FROM parent" in s for s in sqls)  # child in-engine
    # every job after the first rides the captured session id
    assert calls[0][1] == {"session": None}
    assert all(cfg == {"session": "sess-1"} for _, cfg in calls[1:])
    # landing-by-default: the parent stays inspectable as parquet
    assert (tmp_path / "data" / "parent.parquet").exists()
    assert (tmp_path / "data" / "child.parquet").exists()


def test_bigquery_executor_with_fake_client(ctx, monkeypatch) -> None:
    frame = pl.DataFrame({"user_id": [1, 2], "event": ["click", "view"]})

    class FakeJob:
        def to_arrow(self):
            # stands in for a pyarrow.Table; duckdb registers either the same way
            return frame

    class FakeClient:
        def query(self, sql):
            assert "events" in sql
            return FakeJob()

    monkeypatch.setattr(BigQueryExecutor, "make_client", lambda self, spec: FakeClient())
    cell = _cell("bq", "SELECT * FROM events", {"input": {"bigquery": {"project": "p"}}})
    view = EXECUTORS.get("bigquery").execute(cell, ctx)
    assert ctx.conn.sql(f'SELECT count(*) FROM "{view}"').fetchone() == (2,)
