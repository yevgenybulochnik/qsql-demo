"""A VisiData-style sheet model over a Polars frame.

Pure, UI-agnostic state + operations (cursor, sort, select, hide, frequency,
describe, search) that the TUI's Data panel renders and drives with vim keys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import polars as pl


@dataclass
class Sheet:
    frame: pl.DataFrame
    row: int = 0
    col: int = 0
    hidden: set[str] = field(default_factory=set)
    selected: set[int] = field(default_factory=set)
    sort_col: str | None = None
    sort_desc: bool = False

    # -- views ---------------------------------------------------------------

    def visible_columns(self) -> list[str]:
        return [c for c in self.frame.columns if c not in self.hidden]

    def view(self) -> pl.DataFrame:
        """The displayed frame: sorted, with hidden columns dropped."""
        frame = self.frame
        if self.sort_col and self.sort_col in frame.columns:
            frame = frame.sort(self.sort_col, descending=self.sort_desc)
        return frame.select(self.visible_columns())

    def height(self) -> int:
        return self.frame.height

    def width(self) -> int:
        return len(self.visible_columns())

    # -- cursor --------------------------------------------------------------

    def _clamp(self) -> None:
        self.row = 0 if self.height() == 0 else max(0, min(self.row, self.height() - 1))
        self.col = 0 if self.width() == 0 else max(0, min(self.col, self.width() - 1))

    def move(self, d_row: int, d_col: int) -> None:
        self.row += d_row
        self.col += d_col
        self._clamp()

    def goto_top(self) -> None:
        self.row = 0

    def goto_bottom(self) -> None:
        self.row = max(0, self.height() - 1)

    def cursor_column(self) -> str | None:
        columns = self.visible_columns()
        if not columns:
            return None
        self.col = max(0, min(self.col, len(columns) - 1))
        return columns[self.col]

    # -- operations ----------------------------------------------------------

    def sort_by_cursor(self, descending: bool) -> None:
        column = self.cursor_column()
        if column is not None:
            self.sort_col = column
            self.sort_desc = descending
            self._clamp()

    def hide_cursor_column(self) -> None:
        column = self.cursor_column()
        if column is not None:
            self.hidden.add(column)
            self._clamp()

    def unhide_all(self) -> None:
        self.hidden.clear()

    def toggle_select_row(self) -> None:
        self.selected.symmetric_difference_update({self.row})

    def select_all(self) -> None:
        self.selected = set(range(self.height()))

    def unselect_all(self) -> None:
        self.selected.clear()

    def frequency(self) -> "Sheet":
        """A new sheet: value counts of the cursor column."""
        column = self.cursor_column()
        if column is None:
            return Sheet(pl.DataFrame())
        return Sheet(self.view().get_column(column).value_counts(sort=True))

    def describe(self) -> "Sheet":
        """A new sheet: summary statistics of the underlying frame."""
        return Sheet(self.frame.describe())

    def search(self, pattern: str) -> bool:
        """Move the cursor to the next row whose cursor-column value matches ``pattern``."""
        column = self.cursor_column()
        if column is None or self.height() == 0:
            return False
        values = self.view().get_column(column).cast(pl.Utf8, strict=False).to_list()
        regex = re.compile(pattern)
        count = len(values)
        for offset in range(1, count + 1):
            index = (self.row + offset) % count
            value = values[index]
            if value is not None and regex.search(value):
                self.row = index
                return True
        return False
