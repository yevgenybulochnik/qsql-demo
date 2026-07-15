import sqlite3
from types import SimpleNamespace

import duckdb
import polars as pl
import pytest

from qsql_demo.config import resolve_cell
from qsql_demo.errors import ExecutorError
from qsql_demo.executors.bigquery_exec import BigQueryExecutor
from qsql_demo.executors.postgres_exec import PostgresExecutor
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
    events: list[str] = []  # submit/wait interleaving: sessions forbid concurrency

    class FakeJob:
        def __init__(self, sql: str, first: bool) -> None:
            self._sql = sql
            self.session_info = SimpleNamespace(session_id="sess-1") if first else None

        def result(self):
            events.append("wait")
            return self

        def to_arrow(self):
            return pl.DataFrame({"n": [1, 2, 3]})

    class FakeClient:
        def query(self, sql, job_config=None):
            events.append("submit")
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
    # regression: real sessions reject concurrent jobs — every submit must be
    # waited on before the next one goes in
    assert events == ["submit", "wait"] * len(calls)
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


class FakePgCursor:
    """Stands in for a psycopg cursor: .description (objects with .name) + rows."""

    def __init__(self, sql: str) -> None:
        head = sql.lstrip().split(None, 1)[0].upper()
        if head in ("DROP", "CREATE"):  # statements: no result set
            self.description = None
            self._rows: list[tuple] = []
        else:
            self.description = [SimpleNamespace(name="n")]
            self._rows = [(1,), (2,), (3,)]

    def fetchall(self) -> list[tuple]:
        return self._rows


class FakePgConnection:
    def __init__(self) -> None:
        self.sqls: list[str] = []
        self.closed = False

    def execute(self, sql: str) -> FakePgCursor:
        self.sqls.append(sql)
        if "boom" in sql:
            raise RuntimeError("relation missing")
        return FakePgCursor(sql)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_pg(monkeypatch):
    """Route make_connection to fakes; yields the list of connections created."""
    created: list[FakePgConnection] = []

    def make(self, dsn):
        created.append(FakePgConnection())
        return created[-1]

    monkeypatch.setattr(PostgresExecutor, "make_connection", make)
    return created


def test_postgres_executor_registers_result(ctx, fake_pg) -> None:
    cell = _cell("pg", "SELECT n FROM nums;", {"input": {"postgres": {"dsn": "postgresql://x"}}})
    view = EXECUTORS.get("postgres").execute(cell, ctx)
    assert ctx.conn.sql(f'SELECT * FROM "{view}"').fetchall() == [(1,), (2,), (3,)]
    # trailing semicolon stripped; no session -> the ephemeral connection is closed
    assert fake_pg[0].sqls == ["SELECT n FROM nums"]
    assert fake_pg[0].closed


def test_postgres_executor_string_shorthand_and_env_dsn(monkeypatch) -> None:
    monkeypatch.setenv("PG_DSN", "postgresql://qsql@localhost/qsql")
    cfg = resolve_cell({}, {"input": {"postgres": "$PG_DSN"}})
    key = EXECUTORS.get("postgres").context_key(cfg)
    assert key == "postgres:postgresql://qsql@localhost/qsql"


def test_postgres_executor_missing_dsn_raises(ctx, fake_pg) -> None:
    cell = _cell("pg", "SELECT 1", {"engine": "postgres"})
    with pytest.raises(ExecutorError, match="dsn"):
        EXECUTORS.get("postgres").execute(cell, ctx)


def test_postgres_executor_wraps_driver_errors(ctx, fake_pg) -> None:
    cell = _cell("pg", "SELECT boom", {"input": {"postgres": {"dsn": "postgresql://x"}}})
    with pytest.raises(ExecutorError, match="postgres.*relation missing"):
        EXECUTORS.get("postgres").execute(cell, ctx)


def test_postgres_same_context_cells_share_a_connection(tmp_path, fake_pg) -> None:
    from qsql_demo.compiler import compile_text

    project = compile_text(
        "/*@ input: { postgres: { dsn: 'postgresql://x' } } */\n"
        "-- @cell parent\nSELECT n FROM src;\n"
        "-- @cell child\nSELECT count(*) AS c FROM {{ ref('parent') }};",
        root=tmp_path,
    )
    assert project.cells["child"].engine == "postgres"  # legal: same context
    results = {r.cell: r for r in project.run()}
    assert all(r.ok for r in results.values()), [r.error for r in results.values()]

    assert len(fake_pg) == 1  # one shared session connection for the context
    sqls = fake_pg[0].sqls
    # the reffed parent materializes once as a session temp, then extracts from it
    assert 'CREATE TEMP TABLE "parent" AS SELECT n FROM src' in sqls
    assert 'SELECT * FROM "parent"' in sqls
    assert sum("FROM src" in s for s in sqls) == 1
    # the child consumes the temp by bare name, in postgres
    assert any("count(*)" in s and "FROM parent" in s for s in sqls)
    # landing-by-default: both cells still inspectable as parquet
    assert (tmp_path / "data" / "parent.parquet").exists()
    assert (tmp_path / "data" / "child.parquet").exists()
