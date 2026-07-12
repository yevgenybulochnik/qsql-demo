"""Tests for the compiler: parse -> resolve -> render -> graph => Project."""

from __future__ import annotations

import pytest

from qsql_demo import Project
from qsql_demo.errors import ConfigError, CycleError

SAMPLE = """\
-- @engine: duckdb
-- @output: { type: parquet, dir: data/ }

-- @cell users
SELECT * FROM read_csv_auto('users.csv');

-- @cell active
-- @depends_on: [users]
SELECT * FROM {{ ref('users') }} WHERE active;
"""


def test_compile_orders_and_renders() -> None:
    proj = Project.from_text(SAMPLE)
    assert proj.order() == ["users", "active"]
    assert "read_parquet('data/users.parquet')" in proj.compiled("active")


def test_deps_from_ref_and_depends_on() -> None:
    proj = Project.from_text(SAMPLE)
    assert proj.deps["active"] == {"users"}
    assert proj.deps["users"] == set()


def test_engine_and_sink_resolved_per_cell() -> None:
    proj = Project.from_text(SAMPLE)
    assert proj.cell("users").engine == "duckdb"
    assert proj.cell("active").sink == "parquet"


def test_cell_keeps_raw_and_rendered_sql() -> None:
    active = Project.from_text(SAMPLE).cell("active")
    assert "{{ ref('users') }}" in active.sql_raw
    assert "read_parquet" in active.sql


def test_ref_to_unknown_cell_raises_configerror() -> None:
    with pytest.raises(ConfigError):
        Project.from_text("-- @cell a\nSELECT * FROM {{ ref('ghost') }};")


def test_cycle_detected() -> None:
    text = "-- @cell a\nSELECT {{ ref('b') }};\n-- @cell b\nSELECT {{ ref('a') }};\n"
    with pytest.raises(CycleError):
        Project.from_text(text)


def test_select_upstream_and_plain() -> None:
    proj = Project.from_text(SAMPLE)
    assert proj.select(["+active"]) == ["users", "active"]
    assert proj.select(["users"]) == ["users"]
    assert proj.select(["users+"]) == ["users", "active"]


def test_from_file(tmp_path) -> None:
    path = tmp_path / "base.sql"
    path.write_text(SAMPLE)
    proj = Project.from_file(path)
    assert proj.order() == ["users", "active"]
