"""Integration tests for running compiled projects (offline)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import polars as pl
import pytest

from qsql_demo import Project
from qsql_demo.errors import ConfigError


def _run(project_dir: Path, text: str, select=None):
    (project_dir / "base.sql").write_text(text)
    proj = Project.from_file(project_dir / "base.sql")
    return proj, proj.run(select=select)


def test_parquet_pipeline(project_dir: Path) -> None:
    text = """\
-- @output: { type: parquet, dir: data/ }

-- @cell nums
SELECT * FROM (VALUES (1),(2),(3)) AS t(n);

-- @cell doubled
-- @depends_on: [nums]
SELECT n * 2 AS n FROM {{ ref('nums') }};
"""
    _, results = _run(project_dir, text)
    assert all(r.ok for r in results), [r.error for r in results]
    out = pl.read_parquet(project_dir / "data" / "doubled.parquet")
    assert sorted(out["n"].to_list()) == [2, 4, 6]


def test_cross_engine_sqlite_and_duckdb(project_dir: Path) -> None:
    db = project_dir / "src.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE nums(n INTEGER)")
    con.executemany("INSERT INTO nums VALUES (?)", [(1,), (2,), (3,)])
    con.commit()
    con.close()

    text = """\
-- @output: { type: parquet, dir: data/ }

-- @cell s
-- @engine: sqlite
/*@ input: { sqlite: src.sqlite } */
SELECT n FROM nums;

-- @cell d
SELECT 10 AS n;

-- @cell joined
-- @depends_on: [s, d]
SELECT s.n AS a, d.n AS b FROM {{ ref('s') }} s CROSS JOIN {{ ref('d') }} d;
"""
    _, results = _run(project_dir, text)
    assert all(r.ok for r in results), [r.error for r in results]
    out = pl.read_parquet(project_dir / "data" / "joined.parquet")
    assert out.height == 3
    assert set(out["b"].to_list()) == {10}
    assert sorted(out["a"].to_list()) == [1, 2, 3]


def test_duckdb_sink_and_readback(project_dir: Path) -> None:
    text = """\
-- @output: { type: parquet, dir: data/ }

-- @cell base
SELECT * FROM (VALUES (1),(2)) AS t(x);

-- @cell stored
-- @depends_on: [base]
-- @output: { type: duckdb, path: wh.db }
SELECT x * 10 AS y FROM {{ ref('base') }};

-- @cell reader
-- @depends_on: [stored]
SELECT sum(y) AS total FROM {{ ref('stored') }};
"""
    _, results = _run(project_dir, text)
    assert all(r.ok for r in results), [r.error for r in results]
    assert (project_dir / "wh.db").exists()
    out = pl.read_parquet(project_dir / "data" / "reader.parquet")
    assert out["total"].to_list() == [30]


def test_select_runs_subset(project_dir: Path) -> None:
    text = """\
-- @output: { type: parquet, dir: data/ }

-- @cell a
SELECT 1 AS n;

-- @cell b
-- @depends_on: [a]
SELECT n + 1 AS n FROM {{ ref('a') }};
"""
    _, results = _run(project_dir, text, select=["a"])
    assert [r.name for r in results] == ["a"]


def test_non_duckdb_cell_with_ref_raises(project_dir: Path) -> None:
    text = """\
-- @cell up
SELECT 1 AS n;

-- @cell bad
-- @engine: sqlite
-- @depends_on: [up]
SELECT * FROM {{ ref('up') }};
"""
    (project_dir / "base.sql").write_text(text)
    with pytest.raises(ConfigError):
        Project.from_file(project_dir / "base.sql")
