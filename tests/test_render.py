"""Tests for Jinja rendering of SQL bodies: var/env/ref/source globals."""

from __future__ import annotations

import pytest

from qsql_demo.config import resolve_cell
from qsql_demo.errors import RenderError
from qsql_demo.render import render_cell


def _cfg(cell: dict) -> object:
    return resolve_cell({}, cell, {})


def _render(sql: str, cell: dict | None = None, ref_resolver=lambda n: n):
    return render_cell(
        name="c", sql_raw=sql, config=_cfg(cell or {}), ref_resolver=ref_resolver
    )


def test_var_substitution() -> None:
    r = _render("SELECT '{{ var(\"region\") }}'", {"vars": {"region": "us"}})
    assert r.sql == "SELECT 'us'"


def test_vars_attribute_access() -> None:
    r = _render("{{ vars.region }}", {"vars": {"region": "eu"}})
    assert r.sql == "eu"


def test_ref_records_edge_and_uses_resolver() -> None:
    r = _render(
        "SELECT * FROM {{ ref('users') }}",
        ref_resolver=lambda n: f"read_parquet('data/{n}.parquet')",
    )
    assert r.refs == ["users"]
    assert r.sql == "SELECT * FROM read_parquet('data/users.parquet')"


def test_source_expands_and_records_extensions() -> None:
    cell = {"sources": {"sales": {"type": "excel", "path": "./s.xlsx", "sheet": "Q1"}}}
    r = _render("SELECT * FROM {{ source('sales') }}", cell)
    assert "read_xlsx('./s.xlsx', sheet = 'Q1')" in r.sql
    assert r.extensions == ["excel"]


def test_env_function(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QSQL_TEST_ENVVAR", "hello")
    assert _render("{{ env('QSQL_TEST_ENVVAR') }}").sql == "hello"


def test_missing_var_without_default_raises() -> None:
    with pytest.raises(RenderError):
        _render("{{ var('nope') }}")


def test_missing_var_attribute_access_raises() -> None:
    with pytest.raises(RenderError):
        _render("{{ vars.nope }}")
