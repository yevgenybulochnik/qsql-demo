import duckdb
import pytest

from qsql_demo.errors import SinkError
from qsql_demo.models import RenderedCell
from qsql_demo.registry import SINKS


def _cell(name: str) -> RenderedCell:
    return RenderedCell(
        name=name, config=None, sql_raw="", sql="", hash="",
        engine="duckdb", sink_type="parquet",
    )


@pytest.fixture
def conn():
    c = duckdb.connect()
    c.execute("CREATE TEMP VIEW v AS SELECT 1 AS x UNION ALL SELECT 2")
    yield c
    c.close()


def test_parquet_sink_lands_file_named_after_cell(conn, tmp_path) -> None:
    sink = SINKS.get("parquet")({}, tmp_path)
    rows, target = sink.write(_cell("users"), "v", conn)
    assert rows == 2
    assert target == str(tmp_path / "data" / "users.parquet")
    assert (tmp_path / "data" / "users.parquet").exists()
    assert sink.ref_expr("users") == f"read_parquet('{tmp_path}/data/users.parquet')"


def test_parquet_sink_honors_dir(conn, tmp_path) -> None:
    sink = SINKS.get("parquet")({"dir": "out/"}, tmp_path)
    _, target = sink.write(_cell("u"), "v", conn)
    assert target == str(tmp_path / "out" / "u.parquet")


def test_duckdb_sink_writes_table_readable_via_ref_expr(conn, tmp_path) -> None:
    sink = SINKS.get("duckdb")({"path": "wh.db"}, tmp_path)
    sink.prepare(conn)
    rows, target = sink.write(_cell("landed"), "v", conn)
    assert rows == 2
    assert target.endswith("::main.landed")
    assert conn.sql(f"SELECT count(*) FROM {sink.ref_expr('landed')}").fetchone() == (2,)
    assert (tmp_path / "wh.db").exists()


def test_duckdb_sink_append_mode_accumulates(conn, tmp_path) -> None:
    sink = SINKS.get("duckdb")({"path": "wh.db", "mode": "append"}, tmp_path)
    sink.prepare(conn)
    sink.write(_cell("acc"), "v", conn)
    rows, _ = sink.write(_cell("acc"), "v", conn)
    assert rows == 4


def test_duckdb_sink_custom_schema(conn, tmp_path) -> None:
    sink = SINKS.get("duckdb")({"path": "wh.db", "schema": "analytics"}, tmp_path)
    sink.prepare(conn)
    _, target = sink.write(_cell("t"), "v", conn)
    assert target.endswith("::analytics.t")
    assert '."analytics"."t"' in sink.ref_expr("t")


def test_postgres_sink_dsn_expands_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PG_DSN", "host=db user=me")
    sink = SINKS.get("postgres")({"dsn": "$PG_DSN", "table": "analytics.active"}, tmp_path)
    assert sink.dsn == "host=db user=me"
    assert sink.ref_expr("active") .endswith('."analytics"."active"')
    assert sink.requires == ["postgres"]


def test_postgres_sink_missing_dsn_raises(tmp_path) -> None:
    sink = SINKS.get("postgres")({}, tmp_path)
    with pytest.raises(SinkError, match="dsn"):
        sink.dsn
