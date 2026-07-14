import sqlite3

import polars as pl
import pytest

from qsql_demo.compiler import compile_text
from qsql_demo.plugins.base import Plugin
from qsql_demo.registry import plugin
from qsql_demo.runner import RunSession, run_project


def test_run_lands_parquet_and_previews(tmp_path) -> None:
    project = compile_text(
        "-- @cell users\nSELECT * FROM range(3) t(user_id);\n"
        "-- @cell active\nSELECT * FROM {{ ref('users') }} WHERE user_id > 0;",
        root=tmp_path,
    )
    results = project.run()
    assert [r.cell for r in results] == ["users", "active"]
    assert all(r.ok for r in results), [r.error for r in results]
    assert (tmp_path / "data" / "users.parquet").exists()
    assert (tmp_path / "data" / "active.parquet").exists()
    assert results[0].rows == 3 and results[1].rows == 2
    assert isinstance(results[1].preview, pl.DataFrame)
    assert results[1].elapsed > 0


def test_cross_engine_sqlite_duckdb_join(tmp_path) -> None:
    con = sqlite3.connect(tmp_path / "legacy.sqlite")
    con.execute("CREATE TABLE users (user_id INTEGER, name TEXT)")
    con.executemany("INSERT INTO users VALUES (?, ?)", [(1, "ada"), (2, "bob")])
    con.commit()
    con.close()

    project = compile_text(
        "-- @cell legacy_users\n"
        "/*@ input: { sqlite: legacy.sqlite } */\n"
        "SELECT user_id, name FROM users;\n"
        "-- @cell events\n"
        "SELECT 1 AS user_id, 'click' AS event UNION ALL SELECT 2, 'view';\n"
        "-- @cell joined\n"
        "SELECT u.name, e.event FROM {{ ref('legacy_users') }} u\n"
        "JOIN {{ ref('events') }} e USING (user_id);",
        root=tmp_path,
    )
    results = project.run()
    assert all(r.ok for r in results), [r.error for r in results]
    joined = pl.read_parquet(tmp_path / "data" / "joined.parquet")
    assert joined.height == 2
    assert set(joined["name"]) == {"ada", "bob"}


def test_duckdb_sink_cell_readable_downstream(tmp_path) -> None:
    project = compile_text(
        "-- @cell landed\n-- @output: { type: duckdb, path: wh.db }\n"
        "SELECT 1 AS id UNION ALL SELECT 2;\n"
        "-- @cell reader\nSELECT * FROM {{ ref('landed') }};",
        root=tmp_path,
    )
    results = project.run()
    assert all(r.ok for r in results), [r.error for r in results]
    assert (tmp_path / "wh.db").exists()
    assert pl.read_parquet(tmp_path / "data" / "reader.parquet").height == 2


def test_select_runs_upstream_closure_only(tmp_path) -> None:
    project = compile_text(
        "-- @cell users\nSELECT 1 AS id;\n"
        "-- @cell unrelated\nSELECT 2 AS id;\n"
        "-- @cell active\nSELECT * FROM {{ ref('users') }};",
        root=tmp_path,
    )
    results = project.run(select=["active"])
    assert [r.cell for r in results] == ["users", "active"]


def test_failed_cell_reports_error_and_run_continues(tmp_path) -> None:
    project = compile_text(
        "-- @cell bad\nSELECT * FROM no_such_table;\n"
        "-- @cell good\nSELECT 1 AS x;",
        root=tmp_path,
    )
    results = {r.cell: r for r in project.run()}
    assert results["bad"].ok is False
    assert "no_such_table" in results["bad"].error
    assert results["good"].ok is True


def test_extensions_directive_is_loaded_by_runner(tmp_path) -> None:
    project = compile_text(
        "-- @cell a\n-- @extensions: [json]\nSELECT 1 AS x;", root=tmp_path
    )
    results = project.run()
    assert results[0].ok, results[0].error


def test_session_reuses_conduit_across_runs(tmp_path) -> None:
    project = compile_text("-- @cell a\nSELECT 1 AS x;", root=tmp_path)
    session = RunSession()
    try:
        assert run_project(project, session=session)[0].ok
        first_conn = session.conn
        assert first_conn is not None
        assert run_project(project, session=session)[0].ok
        assert session.conn is first_conn  # no reconnect between runs
    finally:
        session.close()
    assert session.conn is None


def test_session_reconnects_when_conduit_target_changes(tmp_path) -> None:
    in_memory = compile_text("-- @cell a\nSELECT 1 AS x;", root=tmp_path)
    on_disk = compile_text(
        "/*@ input: { duckdb: wh.db } */\n-- @cell a\nSELECT 1 AS x;", root=tmp_path
    )
    session = RunSession()
    try:
        run_project(in_memory, session=session)
        first_conn = session.conn
        run_project(on_disk, session=session)
        assert session.conn is not first_conn
        assert (tmp_path / "wh.db").exists()
    finally:
        session.close()


def test_session_caches_extension_loads(tmp_path, monkeypatch) -> None:
    import qsql_demo.runner as runner_mod

    loads: list[str] = []
    original = runner_mod._load_extension
    monkeypatch.setattr(
        runner_mod, "_load_extension",
        lambda conn, ext: (loads.append(ext), original(conn, ext))[1],
    )
    project = compile_text("-- @cell a\n-- @extensions: [json]\nSELECT 1;", root=tmp_path)
    session = RunSession()
    try:
        assert run_project(project, session=session)[0].ok
        assert run_project(project, session=session)[0].ok
    finally:
        session.close()
    assert loads.count("json") == 1  # second run hits the session cache


def test_without_session_each_run_owns_its_connection(tmp_path) -> None:
    project = compile_text("-- @cell a\nSELECT 1 AS x;", root=tmp_path)
    assert project.run()[0].ok
    assert project.run()[0].ok  # independent runs still work


def test_chain_wraps_outermost_first(tmp_path) -> None:
    calls: list[str] = []

    @plugin
    class InnerMost(Plugin):
        priority = 10

        def run(self, cell, ctx, inner):
            calls.append("in:start")
            result = inner(cell, ctx)
            calls.append("in:end")
            return result

    @plugin
    class OuterMost(Plugin):
        priority = -10

        def run(self, cell, ctx, inner):
            calls.append("out:start")
            result = inner(cell, ctx)
            calls.append("out:end")
            return result

    project = compile_text("-- @cell a\nSELECT 1 AS x;", root=tmp_path)
    assert project.run()[0].ok
    assert calls == ["out:start", "in:start", "in:end", "out:end"]


def test_retries_plugin_reinvokes_inner_on_error_result(tmp_path) -> None:
    attempts: list[int] = []

    @plugin
    class Retries(Plugin):
        def run(self, cell, ctx, inner):
            result = inner(cell, ctx)
            attempts.append(1)
            if not result.ok:
                result = inner(cell, ctx)
                attempts.append(2)
            return result

    project = compile_text("-- @cell bad\nSELECT * FROM nope;", root=tmp_path)
    results = project.run()
    assert results[0].ok is False
    assert attempts == [1, 2]


def test_buggy_plugin_degrades_to_error_result(tmp_path) -> None:
    @plugin
    class Buggy(Plugin):
        def run(self, cell, ctx, inner):
            raise RuntimeError("plugin exploded")

    project = compile_text(
        "-- @cell a\nSELECT 1 AS x;\n-- @cell b\nSELECT 2 AS y;", root=tmp_path
    )
    results = project.run()
    assert all(r.ok is False for r in results)
    assert "plugin exploded" in results[0].error


def test_emit_sql_plugin_writes_rendered_sql(tmp_path) -> None:
    project = compile_text(
        "-- @cell a\nSELECT 1 AS x;",
        root=tmp_path,
        overrides={"render_dir": "build/sql"},
    )
    assert project.run()[0].ok
    assert (tmp_path / "build" / "sql" / "a.sql").read_text().strip() == "SELECT 1 AS x;"
