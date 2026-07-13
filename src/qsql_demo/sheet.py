"""VisiData-style sheet operations: pure functions over a Polars frame.

The TUI's Data pane is a stack of these; every operation returns a new Sheet,
so they unit-test without any terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import polars as pl


@dataclass(frozen=True)
class Sheet:
    frame: pl.DataFrame
    title: str = "data"
    cursor: tuple[int, int] = (0, 0)
    hidden: tuple[str, ...] = ()
    selected: frozenset[int] = field(default_factory=frozenset)

    @property
    def columns(self) -> list[str]:
        return [c for c in self.frame.columns if c not in self.hidden]

    def visible(self) -> pl.DataFrame:
        return self.frame.select(self.columns)

    @property
    def current_column(self) -> str:
        return self.columns[self.cursor[1]]

    def _clamp(self, row: int, col: int) -> tuple[int, int]:
        max_row = max(self.frame.height - 1, 0)
        max_col = max(len(self.columns) - 1, 0)
        return (min(max(row, 0), max_row), min(max(col, 0), max_col))

    def move(self, d_row: int, d_col: int) -> Sheet:
        return replace(self, cursor=self._clamp(self.cursor[0] + d_row, self.cursor[1] + d_col))

    def top(self) -> Sheet:
        return replace(self, cursor=(0, self.cursor[1]))

    def bottom(self) -> Sheet:
        return replace(self, cursor=self._clamp(self.frame.height - 1, self.cursor[1]))

    def sort(self, desc: bool = False) -> Sheet:
        return replace(self, frame=self.frame.sort(self.current_column, descending=desc))

    def hide_current(self) -> Sheet:
        if len(self.columns) <= 1:
            return self
        hidden = (*self.hidden, self.current_column)
        out = replace(self, hidden=hidden)
        return replace(out, cursor=out._clamp(*out.cursor))

    def toggle_select(self) -> Sheet:
        row = self.cursor[0]
        selected = set(self.selected)
        selected.symmetric_difference_update({row})
        return replace(self, selected=frozenset(selected))

    def select_all(self) -> Sheet:
        if len(self.selected) == self.frame.height:
            return replace(self, selected=frozenset())
        return replace(self, selected=frozenset(range(self.frame.height)))

    def freq(self) -> Sheet:
        col = self.current_column
        frame = (
            self.frame.group_by(col)
            .len(name="count")
            .with_columns((pl.col("count") / self.frame.height).alias("share"))
            .sort("count", descending=True)
        )
        return Sheet(frame=frame, title=f"freq({col})")

    def describe(self) -> Sheet:
        return Sheet(frame=self.frame.describe(), title=f"describe({self.title})")

    def search(self, needle: str, reverse: bool = False) -> Sheet:
        if not needle or self.frame.height == 0:
            return self
        needle = needle.lower()
        rows = self.visible().rows()
        n = len(rows)
        step = -1 if reverse else 1
        for offset in range(1, n + 1):
            idx = (self.cursor[0] + step * offset) % n
            if any(needle in str(value).lower() for value in rows[idx]):
                return replace(self, cursor=(idx, self.cursor[1]))
        return self
