"""Tests for the VisiData-style Sheet model."""

from __future__ import annotations

import polars as pl

from qsql_demo.sheet import Sheet


def _df() -> pl.DataFrame:
    return pl.DataFrame({"name": ["Ana", "Ben", "Cara", "Ana"], "age": [30, 20, 40, 25]})


def test_view_defaults_to_all_columns() -> None:
    assert Sheet(_df()).view().columns == ["name", "age"]


def test_sort_by_cursor_ascending_then_descending() -> None:
    s = Sheet(_df())
    s.col = 1  # age
    s.sort_by_cursor(descending=False)
    assert s.view().get_column("age").to_list() == [20, 25, 30, 40]
    s.sort_by_cursor(descending=True)
    assert s.view().get_column("age").to_list() == [40, 30, 25, 20]


def test_hide_column() -> None:
    s = Sheet(_df())
    s.col = 0
    s.hide_cursor_column()
    assert s.view().columns == ["age"]
    s.unhide_all()
    assert s.view().columns == ["name", "age"]


def test_cursor_movement_clamps() -> None:
    s = Sheet(_df())
    s.move(100, 100)
    assert (s.row, s.col) == (3, 1)
    s.goto_top()
    assert s.row == 0
    s.goto_bottom()
    assert s.row == 3


def test_select_rows() -> None:
    s = Sheet(_df())
    s.toggle_select_row()
    s.row = 2
    s.toggle_select_row()
    assert s.selected == {0, 2}
    s.unselect_all()
    assert s.selected == set()
    s.select_all()
    assert s.selected == {0, 1, 2, 3}


def test_frequency_counts_cursor_column() -> None:
    s = Sheet(_df())
    s.col = 0
    freq = s.frequency().frame
    ana = freq.filter(pl.col("name") == "Ana")
    assert ana.row(0)[1] == 2  # count column, name-agnostic


def test_describe_returns_stats() -> None:
    assert Sheet(_df()).describe().frame.height > 0


def test_search_moves_cursor_and_reports_miss() -> None:
    s = Sheet(_df())
    s.col = 0
    assert s.search("Cara") is True
    assert s.row == 2
    assert s.search("zzz") is False
