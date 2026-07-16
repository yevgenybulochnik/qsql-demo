import sqlite3
from types import SimpleNamespace

import duckdb
import polars as pl
import pytest

from qsql_demo.catalog import (
    CatalogNode,
    bigquery_context_node,
    bq_field_paths,
    duckdb_context_node,
    duckdb_field_paths,
    postgres_context_node,
    project_root_node,
    sink_output_node,
    sqlite_context_node,
)
from qsql_demo.compiler import compile_text
from qsql_demo.config import resolve_cell
from qsql_demo.executors.bigquery_exec import BigQueryExecutor
from qsql_demo.executors.postgres_exec import PostgresExecutor
from qsql_demo.sinks import make_sink

FIELD_PATH_COLUMNS = ["column", "field_path", "type", "mode"]


def _sf(name, field_type, mode="NULLABLE", fields=()):
    """Stands in for a bigquery SchemaField: name/field_type/mode/fields."""
    return SimpleNamespace(name=name, field_type=field_type, mode=mode, fields=list(fields))


def test_bq_field_paths_one_row_per_path_level() -> None:
    schema = [
        _sf("id", "INTEGER", "REQUIRED"),
        _sf(
            "event",
            "RECORD",
            "NULLABLE",
            [
                _sf("name", "STRING"),
                _sf(
                    "params",
                    "RECORD",
                    "REPEATED",
                    [_sf("key", "STRING"), _sf("value", "INTEGER")],
                ),
            ],
        ),
    ]
    frame = bq_field_paths(schema)
    assert frame.columns == FIELD_PATH_COLUMNS
    # depth-first, document order, intermediate RECORDs included
    assert frame.rows() == [
        ("id", "id", "INTEGER", "REQUIRED"),
        ("event", "event", "RECORD", "NULLABLE"),
        ("event", "event.name", "STRING", "NULLABLE"),
        ("event", "event.params", "RECORD", "REPEATED"),
        ("event", "event.params.key", "STRING", "NULLABLE"),
        ("event", "event.params.value", "INTEGER", "NULLABLE"),
    ]


def test_bq_field_paths_empty_schema() -> None:
    frame = bq_field_paths([])
    assert frame.columns == FIELD_PATH_COLUMNS
    assert frame.height == 0


@pytest.fixture
def con():
    con = duckdb.connect()
    yield con
    con.close()


def test_duckdb_field_paths_flattens_structs_and_lists(con) -> None:
    rel = con.sql(
        "SELECT 1 AS n, {'name': 'x', 'params': [{'key': 'k', 'value': 1}]} AS event LIMIT 0"
    )
    frame = duckdb_field_paths(rel.columns, rel.types)
    assert frame.columns == FIELD_PATH_COLUMNS
    paths = {path: (type_, mode) for _, path, type_, mode in frame.rows()}
    # a LIST wrapper adds no path segment: params -> params.key, not params.child.key
    assert set(paths) == {
        "n",
        "event",
        "event.name",
        "event.params",
        "event.params.key",
        "event.params.value",
    }
    assert paths["n"] == ("INTEGER", "")
    assert paths["event"][0].startswith("STRUCT")
    assert paths["event.name"] == ("VARCHAR", "")
    assert paths["event.params"][0].endswith("[]")  # the full nested type string
    assert paths["event.params"][1] == "REPEATED"
    assert paths["event.params.key"] == ("VARCHAR", "")
    # column ties every path back to its top-level column, depth-first order
    assert [row[0] for row in frame.rows()] == ["n"] + ["event"] * 5


def test_duckdb_field_paths_survives_map_and_fixed_arrays(con) -> None:
    # exotic nested types must not crash the walker (fixed arrays carry a
    # non-type child; .children raises on scalars)
    rel = con.sql("SELECT MAP {'a': 1} AS m, CAST([1, 2, 3] AS INT[3]) AS fixed LIMIT 0")
    frame = duckdb_field_paths(rel.columns, rel.types)
    paths = {path for _, path, _, _ in frame.rows()}
    assert "m" in paths
    assert "fixed" in paths


def test_duckdb_field_paths_empty() -> None:
    frame = duckdb_field_paths([], [])
    assert frame.columns == FIELD_PATH_COLUMNS
    assert frame.height == 0


# ---------- drillable nodes ----------


def test_project_root_node_lists_contexts_and_outputs(tmp_path) -> None:
    project = compile_text(
        "-- @cell a\nSELECT 1 AS x;\n"
        "-- @cell b\n/*@ input: { sqlite: nums.db } */\nSELECT 2 AS y;\n"
        "-- @cell c\n/*@ input: { sqlite: nums.db } */\nSELECT 3 AS z;\n",
        root=tmp_path,
    )
    node = project_root_node(project)
    frame = node.load()
    assert frame.columns == ["kind", "name", "engine", "detail"]
    contexts = frame.filter(pl.col("kind") == "context")
    # b and c share one sqlite context (deduped by context_key); a is duckdb
    assert contexts["engine"].to_list() == ["duckdb", "sqlite"]
    outputs = frame.filter(pl.col("kind") == "output")
    assert outputs["name"].to_list() == ["a", "b", "c"]
    assert outputs["detail"].to_list() == ["duckdb → parquet"] + ["sqlite → parquet"] * 2

    out_child = node.child(outputs.row(0, named=True))
    assert isinstance(out_child, CatalogNode) and out_child.child is None  # leaf
    ctx_child = node.child(contexts.row(1, named=True))
    assert isinstance(ctx_child, CatalogNode)


def test_sqlite_catalog_chain(tmp_path) -> None:
    db = sqlite3.connect(tmp_path / "nums.db")
    db.execute("CREATE TABLE nums (n INTEGER NOT NULL, label TEXT)")
    db.commit()
    db.close()

    node = sqlite_context_node("nums.db", tmp_path)
    tables = node.load()
    assert tables["table"].to_list() == ["nums"]
    leaf = node.child(tables.row(0, named=True))
    cols = leaf.load()
    assert cols.columns == FIELD_PATH_COLUMNS
    assert cols.rows() == [
        ("n", "n", "INTEGER", "REQUIRED"),
        ("label", "label", "TEXT", ""),
    ]
    assert leaf.child is None


def test_sqlite_memory_context_not_browsable(tmp_path) -> None:
    node = sqlite_context_node(":memory:", tmp_path)
    assert node.child is None
    assert "memory" in node.load()["info"][0]


def test_duckdb_catalog_chain(tmp_path) -> None:
    con = duckdb.connect(str(tmp_path / "wh.db"))
    con.execute("CREATE TABLE t AS SELECT {'a': 1} AS s")
    con.close()

    node = duckdb_context_node({"path": "wh.db"}, tmp_path)
    tables = node.load()
    assert tables.columns == ["schema", "table"]
    assert tables.rows() == [("main", "t")]
    leaf = node.child(tables.row(0, named=True))
    assert leaf.load()["field_path"].to_list() == ["s", "s.a"]
    assert leaf.child is None


def test_duckdb_memory_context_not_browsable(tmp_path) -> None:
    node = duckdb_context_node(None, tmp_path)
    assert node.child is None
    assert "memory" in node.load()["info"][0]


def test_bigquery_catalog_chain(monkeypatch) -> None:
    created: list[dict] = []

    class FakeClient:
        def list_datasets(self):
            return [SimpleNamespace(dataset_id="analytics"), SimpleNamespace(dataset_id="raw")]

        def list_tables(self, dataset_id):
            assert dataset_id == "analytics"
            return [SimpleNamespace(table_id="events", table_type="TABLE")]

        def get_table(self, ref):
            assert ref == "analytics.events"
            return SimpleNamespace(
                schema=[
                    _sf("id", "INTEGER", "REQUIRED"),
                    _sf("event", "RECORD", "REPEATED", [_sf("name", "STRING")]),
                ]
            )

    def make(self, spec):
        created.append(spec)
        return FakeClient()

    monkeypatch.setattr(BigQueryExecutor, "make_client", make)
    node = bigquery_context_node({"project": "p"})
    datasets = node.load()
    assert datasets["dataset"].to_list() == ["analytics", "raw"]
    tables_node = node.child(datasets.row(0, named=True))
    tables = tables_node.load()
    assert tables["table"].to_list() == ["events"]
    leaf = tables_node.child(tables.row(0, named=True))
    paths = leaf.load()
    assert "event.name" in paths["field_path"].to_list()
    assert leaf.child is None
    assert len(created) == 1  # one client, memoized across the whole drill chain


class FakeCatalogPgCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class FakeCatalogPg:
    def __init__(self):
        self.closed = False

    def execute(self, sql, params=None):
        if "schemata" in sql:
            return FakeCatalogPgCursor([("public",), ("analytics",)])
        if "information_schema.tables" in sql:
            return FakeCatalogPgCursor([("users",)])
        if "information_schema.columns" in sql:
            return FakeCatalogPgCursor([("id", "integer", "NO"), ("email", "text", "YES")])
        raise AssertionError(f"unexpected catalog sql: {sql}")

    def close(self):
        self.closed = True


def test_postgres_catalog_chain(monkeypatch) -> None:
    created: list[FakeCatalogPg] = []

    def make(self, dsn):
        assert dsn == "postgresql://x"
        created.append(FakeCatalogPg())
        return created[-1]

    monkeypatch.setattr(PostgresExecutor, "make_connection", make)
    node = postgres_context_node("postgresql://x")
    schemas = node.load()
    assert schemas["schema"].to_list() == ["public", "analytics"]
    tables_node = node.child(schemas.row(0, named=True))
    tables = tables_node.load()
    assert tables["table"].to_list() == ["users"]
    leaf = tables_node.child(tables.row(0, named=True))
    cols = leaf.load()
    assert cols.rows() == [
        ("id", "id", "integer", "REQUIRED"),
        ("email", "email", "text", ""),
    ]
    assert leaf.child is None
    # throwaway connection per load, closed every time
    assert len(created) == 3 and all(c.closed for c in created)


def test_sink_output_node_reads_parquet_struct(tmp_path, con) -> None:
    (tmp_path / "data").mkdir()
    con.execute(
        f"COPY (SELECT 1 AS id, {{'name': 'x'}} AS event)"
        f" TO '{tmp_path}/data/c.parquet' (FORMAT PARQUET)"
    )
    node = sink_output_node("c", resolve_cell({}, {}), tmp_path)
    frame = node.load()
    assert frame["field_path"].to_list() == ["id", "event", "event.name"]
    assert node.child is None


def test_sink_output_node_duckdb_sink_needs_the_conduit_cursor(tmp_path) -> None:
    cfg = resolve_cell({"output": {"type": "duckdb", "path": "warehouse.db"}}, {})
    conduit = duckdb.connect()
    try:
        sink = make_sink(cfg, tmp_path)
        sink.prepare(conduit)
        conduit.execute(f"CREATE TABLE {sink.ref_expr('c')} AS SELECT {{'a': 1}} AS s")
        # a throwaway connection cannot re-ATTACH the conduit-held file...
        with pytest.raises(duckdb.Error, match="[Uu]nique file handle"):
            sink_output_node("c", cfg, tmp_path).load()
        # ...but a cursor of the conduit sees the existing ATTACH
        node = sink_output_node("c", cfg, tmp_path, connect=conduit.cursor)
        assert node.load()["field_path"].to_list() == ["s", "s.a"]
    finally:
        conduit.close()
