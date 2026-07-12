"""Tests for the source-reader registry and source() resolution."""

from __future__ import annotations

import pytest

from qsql_demo.errors import ConfigError
from qsql_demo.sources import resolve_source


def test_csv_inline_infers_by_extension() -> None:
    expr, requires = resolve_source("./data/regions.csv", {})
    assert expr == "read_csv_auto('./data/regions.csv')"
    assert requires == []


def test_parquet_and_json_inline() -> None:
    assert resolve_source("a.parquet", {})[0] == "read_parquet('a.parquet')"
    assert resolve_source("a.json", {})[0] == "read_json_auto('a.json')"


def test_excel_declared_with_options_and_requires() -> None:
    sources = {"sales": {"type": "excel", "path": "./s.xlsx", "sheet": "Q1"}}
    expr, requires = resolve_source("sales", sources)
    assert expr == "read_xlsx('./s.xlsx', sheet = 'Q1')"
    assert requires == ["excel"]


def test_inline_opts_override_declared() -> None:
    sources = {"sales": {"type": "excel", "path": "./s.xlsx", "sheet": "Q1"}}
    expr, _ = resolve_source("sales", sources, {"sheet": "Q2"})
    assert "sheet = 'Q2'" in expr


def test_declared_type_inferred_from_extension() -> None:
    sources = {"regions": {"path": "./regions.csv"}}
    expr, _ = resolve_source("regions", sources)
    assert expr == "read_csv_auto('./regions.csv')"


def test_unknown_extension_raises() -> None:
    with pytest.raises(ConfigError):
        resolve_source("mystery.dat", {})
