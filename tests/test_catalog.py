from types import SimpleNamespace

import duckdb
import pytest

from qsql_demo.catalog import bq_field_paths, duckdb_field_paths

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
