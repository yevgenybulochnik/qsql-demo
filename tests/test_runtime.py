"""Tests for runtime helpers."""

from __future__ import annotations

from qsql_demo.runtime import as_subquery


def test_as_subquery_strips_trailing_semicolon() -> None:
    assert as_subquery("SELECT 1;") == "SELECT 1"


def test_as_subquery_drops_trailing_comments_and_blanks() -> None:
    sql = "SELECT 1;\n\n-- a trailing note\n-- another\n"
    assert as_subquery(sql) == "SELECT 1"


def test_as_subquery_preserves_inner_content() -> None:
    assert as_subquery("SELECT a\nFROM t\nWHERE a > 0") == "SELECT a\nFROM t\nWHERE a > 0"
