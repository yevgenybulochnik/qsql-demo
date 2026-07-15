"""Integration tests against the compose Postgres (docker compose up -d --wait).

Run with: uv run --extra postgres pytest -m postgres
Each test drops/recreates its own tables in qsql_test, so runs are idempotent.
"""

import duckdb
import pytest

from qsql_demo.compiler import compile_text
from qsql_demo.errors import ExecutorError
from qsql_demo.models import RunContext
from qsql_demo.registry import EXECUTORS

pytestmark = pytest.mark.postgres


@pytest.fixture
def seeded(pg_dsn):
    """A small nums table in qsql_test; yields the dsn."""
    import psycopg

    with psycopg.connect(pg_dsn, autocommit=True) as con:
        con.execute("DROP TABLE IF EXISTS nums")
        con.execute("CREATE TABLE nums (n int)")
        con.execute("INSERT INTO nums SELECT generate_series(1, 5)")
    return pg_dsn


def _cell_config(dsn: str) -> str:
    return f"/*@ input: {{ postgres: {{ dsn: '{dsn}' }} }} */\n"


def test_executor_runs_real_sql(seeded, tmp_path) -> None:
    from qsql_demo.config import resolve_cell
    from qsql_demo.models import RenderedCell

    cfg = resolve_cell({}, {"input": {"postgres": {"dsn": seeded}}})
    cell = RenderedCell(
        name="pg", config=cfg, sql_raw="", hash="",
        sql="SELECT n, n * n AS sq FROM nums ORDER BY n",
        engine="postgres", sink_type="parquet",
    )
    conn = duckdb.connect()
    try:
        view = EXECUTORS.get("postgres").execute(cell, RunContext(conn=conn, root=tmp_path))
        assert conn.sql(f'SELECT * FROM "{view}"').fetchall() == [
            (1, 1), (2, 4), (3, 9), (4, 16), (5, 25)
        ]
    finally:
        conn.close()


def test_real_driver_errors_wrap_as_executor_error(seeded, tmp_path) -> None:
    """The offline test fakes the driver; only a real psycopg error proves the wrap."""
    from qsql_demo.config import resolve_cell
    from qsql_demo.models import RenderedCell

    cfg = resolve_cell({}, {"input": {"postgres": {"dsn": seeded}}})
    cell = RenderedCell(
        name="pg", config=cfg, sql_raw="", hash="", sql="SELECT * FROM no_such_table",
        engine="postgres", sink_type="parquet",
    )
    conn = duckdb.connect()
    try:
        with pytest.raises(ExecutorError, match="postgres.*no_such_table"):
            EXECUTORS.get("postgres").execute(cell, RunContext(conn=conn, root=tmp_path))
    finally:
        conn.close()


def test_same_context_cells_share_session_temps(seeded, tmp_path) -> None:
    project = compile_text(
        _cell_config(seeded)
        + "-- @cell parent\nSELECT n FROM nums WHERE n <= 3;\n"
        + "-- @cell child\nSELECT count(*) AS c, sum(n) AS s FROM {{ ref('parent') }};",
        root=tmp_path,
    )
    assert project.cells["child"].engine == "postgres"  # legal: same context
    results = {r.cell: r for r in project.run()}
    assert all(r.ok for r in results.values()), [r.error for r in results.values()]
    con = duckdb.connect()
    try:
        assert con.sql(
            f"SELECT c, s FROM read_parquet('{tmp_path / 'data' / 'child.parquet'}')"
        ).fetchall() == [(3, 6)]
    finally:
        con.close()


def test_failed_cell_does_not_poison_the_session(seeded, tmp_path) -> None:
    """watch/TUI keep one session across reruns: without autocommit a failed
    statement would leave it aborted and every later cell would fail too."""
    from qsql_demo.runner import RunSession, run_project

    session = RunSession()
    try:
        broken = compile_text(
            _cell_config(seeded) + "-- @cell broken\nSELECT * FROM no_such_table;",
            root=tmp_path,
        )
        assert not {r.cell: r for r in run_project(broken, session=session)}["broken"].ok

        # same session, same connection: a healthy cell must still run
        healthy = compile_text(
            _cell_config(seeded) + "-- @cell healthy\nSELECT count(*) AS c FROM nums;",
            root=tmp_path,
        )
        result = {r.cell: r for r in run_project(healthy, session=session)}["healthy"]
        assert result.ok, result.error
    finally:
        session.close()


def test_cross_engine_duckdb_reads_postgres_cell(seeded, tmp_path) -> None:
    project = compile_text(
        _cell_config(seeded)
        + "-- @cell extract\nSELECT n FROM nums;\n"
        + "-- @cell crunch\n-- @engine: duckdb\n"
        + "SELECT max(n) AS top FROM {{ ref('extract') }};",
        root=tmp_path,
    )
    results = {r.cell: r for r in project.run()}
    assert all(r.ok for r in results.values()), [r.error for r in results.values()]
    con = duckdb.connect()
    try:
        assert con.sql(
            f"SELECT top FROM read_parquet('{tmp_path / 'data' / 'crunch.parquet'}')"
        ).fetchall() == [(5,)]
    finally:
        con.close()


def test_round_trip_through_postgres_sink(seeded, tmp_path) -> None:
    """postgres engine cell lands back into Postgres via the existing sink
    (needs duckdb's postgres extension: network once, to install it)."""
    import psycopg

    project = compile_text(
        _cell_config(seeded)
        + f"-- @cell doubled\n/*@ output: {{ type: postgres, dsn: '{seeded}' }} */\n"
        + "SELECT n, n * 2 AS twice FROM nums ORDER BY n;",
        root=tmp_path,
    )
    results = {r.cell: r for r in project.run()}
    assert all(r.ok for r in results.values()), [r.error for r in results.values()]
    with psycopg.connect(seeded) as con:
        rows = con.execute("SELECT n, twice FROM public.doubled ORDER BY n").fetchall()
    assert rows == [(1, 2), (2, 4), (3, 6), (4, 8), (5, 10)]
