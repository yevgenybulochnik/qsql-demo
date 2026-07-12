"""Tests for the .qsql parser: header + named cells, line and block directives."""

from __future__ import annotations

import pytest

from qsql_demo.errors import ParseError
from qsql_demo.models import RawBlock, body_hash
from qsql_demo.parser import parse


def _cells(blocks: list[RawBlock]) -> dict[str, RawBlock]:
    return {b.name: b for b in blocks if b.name is not None}


def test_empty_file_yields_just_an_empty_header() -> None:
    blocks = parse("")
    assert len(blocks) == 1
    assert blocks[0].is_header
    assert blocks[0].directives == {}
    assert blocks[0].sql == ""


def test_first_block_is_always_the_header() -> None:
    blocks = parse("-- @cell users\nSELECT 1;\n")
    assert blocks[0].is_header
    assert [b.name for b in blocks] == [None, "users"]


def test_line_directives_parse_as_yaml() -> None:
    blocks = parse("-- @engine: duckdb\n-- @autorun: true\n")
    assert blocks[0].directives == {"engine": "duckdb", "autorun": True}


def test_nested_multiline_line_directive() -> None:
    text = "-- @vars:\n--   region: us-east\n--   tier: gold\n"
    blocks = parse(text)
    assert blocks[0].directives == {"vars": {"region": "us-east", "tier": "gold"}}


def test_block_directive_multiline() -> None:
    text = "/*@\ninput:\n  duckdb: ./warehouse.db\n*/\n"
    blocks = parse(text)
    assert blocks[0].directives == {"input": {"duckdb": "./warehouse.db"}}


def test_block_directive_single_line() -> None:
    text = "/*@ input: { duckdb: ./warehouse.db } */\n"
    blocks = parse(text)
    assert blocks[0].directives == {"input": {"duckdb": "./warehouse.db"}}


def test_line_and_block_directives_merge_into_one_dict() -> None:
    text = (
        "-- @engine: duckdb\n"
        "-- @autorun: true\n"
        "\n"
        "/*@\ninput: { duckdb: ./w.db }\nvars: { data_dir: ./seeds }\n*/\n"
    )
    d = parse(text)[0].directives
    assert d == {
        "engine": "duckdb",
        "autorun": True,
        "input": {"duckdb": "./w.db"},
        "vars": {"data_dir": "./seeds"},
    }


def test_cell_captures_name_body_and_hash() -> None:
    text = "-- @cell users\nSELECT * FROM t;\n"
    users = _cells(parse(text))["users"]
    assert users.sql == "SELECT * FROM t;"
    assert users.directives == {}
    assert users.hash == body_hash("SELECT * FROM t;")


def test_cell_local_directives_override_scope() -> None:
    text = "-- @cell active\n-- @autorun: false\nSELECT 1;\n"
    active = _cells(parse(text))["active"]
    assert active.directives == {"autorun": False}
    assert active.sql == "SELECT 1;"


def test_plain_comments_pass_through_into_body() -> None:
    text = "-- @cell c\n-- a plain SQL note\nSELECT 1 /* inline note */;\n"
    c = _cells(parse(text))["c"]
    assert "-- a plain SQL note" in c.sql
    assert "/* inline note */" in c.sql
    assert c.directives == {}


def test_directive_after_sql_is_still_captured() -> None:
    text = "-- @cell c\nSELECT 1;\n-- @tags: [x, y]\n"
    c = _cells(parse(text))["c"]
    assert c.directives == {"tags": ["x", "y"]}
    assert c.sql == "SELECT 1;"


def test_two_cells_are_separated() -> None:
    text = "-- @cell a\nSELECT 1;\n-- @cell b\nSELECT 2;\n"
    cells = _cells(parse(text))
    assert cells["a"].sql == "SELECT 1;"
    assert cells["b"].sql == "SELECT 2;"


def test_duplicate_cell_name_raises() -> None:
    with pytest.raises(ParseError):
        parse("-- @cell a\nSELECT 1;\n-- @cell a\nSELECT 2;\n")


def test_unterminated_block_raises() -> None:
    with pytest.raises(ParseError):
        parse("/*@\ninput: { duckdb: x }\n")


def test_malformed_directive_yaml_raises() -> None:
    with pytest.raises(ParseError):
        parse("/*@\n: : : not valid : :\n*/\n")


def test_cell_marker_without_name_raises() -> None:
    with pytest.raises(ParseError):
        parse("-- @cell\nSELECT 1;\n")
