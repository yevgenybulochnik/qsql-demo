"""The qsql Textual TUI — master-detail, reflect-only, VisiData/vim keys.

Left: a cell list. Right: tabbed SQL / Data / Config / Log for the selected cell.
The Data panel is an in-app VisiData-style Polars sheet (sort/hide/freq/describe);
``V`` opens the cell's output in real VisiData. Reflect-only: a background watch
task recompiles on save and re-runs autorun cells (+ downstream).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

import polars as pl
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Static, TabbedContent, TabPane

from .compiler import Project
from .errors import QsqlError
from .sheet import Sheet
from .watcher import plan_rebuild


def _fill(table: DataTable, frame: pl.DataFrame) -> None:
    table.clear(columns=True)
    if frame.width == 0:
        return
    table.add_columns(*frame.columns)
    for row in frame.iter_rows():
        table.add_row(*["" if v is None else str(v) for v in row])


class QsqlApp(App):
    CSS = """
    #cells { width: 45%; border-right: solid $accent; }
    #detail { width: 55%; }
    """

    BINDINGS = [
        Binding("q", "quit", "quit"),
        Binding("t", "toggle_sql", "raw/rendered"),
        Binding("a", "toggle_autorun", "autorun"),
        Binding("A", "toggle_all_autorun", "autorun*"),
        Binding("r", "run_selected", "run"),
        Binding("R", "run_all", "run all"),
        Binding("V", "open_visidata", "visidata"),
        Binding("left_square_bracket", "sort('asc')", "sort+"),
        Binding("right_square_bracket", "sort('desc')", "sort-"),
        Binding("minus", "hide_col", "hide"),
        Binding("u", "unhide", "unhide"),
        Binding("f", "frequency", "freq"),
        Binding("i", "describe", "describe"),
        Binding("j", "cell_move(1)", "down"),
        Binding("k", "cell_move(-1)", "up"),
        Binding("g", "cell_top", "top"),
        Binding("G", "cell_bottom", "bottom"),
    ]

    def __init__(
        self,
        project: Project,
        *,
        file: str | Path | None = None,
        overrides: dict[str, Any] | None = None,
        enable_watch: bool = True,
    ) -> None:
        super().__init__()
        self.project = project
        # resolve now: a run() chdir-ing in a worker thread must not re-point a
        # relative path between watch events
        self.file = Path(file).resolve() if file else None
        self.overrides = overrides or {}
        self.enable_watch = enable_watch and self.file is not None
        self.current: str | None = None
        self.sql_mode = "rendered"  # or "source"
        self.results: dict[str, Any] = {}
        self._sheet: Sheet | None = None

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield DataTable(id="cells", cursor_type="row")
            with TabbedContent(id="detail"):
                with TabPane("SQL", id="tab-sql"):
                    yield Static(id="sql")
                with TabPane("Data", id="tab-data"):
                    yield DataTable(id="data")
                with TabPane("Config", id="tab-config"):
                    yield Static(id="config")
                with TabPane("Log", id="tab-log"):
                    yield Static(id="log")
        yield Footer()

    def on_mount(self) -> None:
        cells = self.query_one("#cells", DataTable)
        cells.add_columns("cell", "engine→sink", "auto", "rows")
        self._repopulate_cells()
        self.current = self.project.order()[0] if self.project.order() else None
        self._refresh_detail()
        if self.enable_watch:
            self.run_worker(self._watch_worker(), exclusive=False)

    # -- population ----------------------------------------------------------

    def _repopulate_cells(self) -> None:
        table = self.query_one("#cells", DataTable)
        table.clear()
        order = self.project.order()
        for name in order:
            cell = self.project.cell(name)
            result = self.results.get(name)
            rows = str(result.rows) if result and result.rows is not None else ""
            table.add_row(
                name,
                f"{cell.engine}→{cell.sink}",
                "✓" if getattr(cell.config, "autorun", True) else "✗",
                rows,
                key=name,
            )
        # clear() resets the cursor to row 0; without this the highlight event
        # would silently re-select the first cell after every rebuild
        if self.current in order:
            table.move_cursor(row=order.index(self.current))

    def _reconcile_current(self) -> None:
        """Keep ``current`` valid after a recompile that may add/remove cells."""
        if self.current not in self.project.cells:
            order = self.project.order()
            self.current = order[0] if order else None

    def _refresh_detail(self) -> None:
        self._reconcile_current()
        if self.current is None:
            for pane in ("#sql", "#config", "#log"):
                self.query_one(pane, Static).update("")
            self._sheet = None
            self._render_sheet()
            return
        cell = self.project.cell(self.current)
        sql = cell.sql if self.sql_mode == "rendered" else cell.sql_raw
        self.query_one("#sql", Static).update(f"[{self.sql_mode}]\n\n{sql}")

        config = cell.config.model_dump()
        self.query_one("#config", Static).update(
            "\n".join(f"{k}: {v}" for k, v in config.items())
        )

        result = self.results.get(self.current)
        if result is None:
            log = "not run yet"
        elif result.ok:
            log = f"target: {result.target}\nrows: {result.rows}\nelapsed: {result.elapsed:.3f}s"
        else:
            log = f"[error]\n{result.error}"
        self.query_one("#log", Static).update(log)

        self._sheet = self._load_sheet(cell)
        self._render_sheet()

    def _parquet_path(self, cell: Any) -> Path | None:
        out = getattr(cell.config, "output", {}) or {}
        if out.get("type", "parquet") != "parquet":
            return None
        base = self.project.project_dir / out.get("dir", "data/")
        return base / f"{cell.name}.parquet"

    def _load_sheet(self, cell: Any) -> Sheet | None:
        path = self._parquet_path(cell)
        if path and path.exists():
            return Sheet(pl.read_parquet(path))
        return None

    def _render_sheet(self) -> None:
        table = self.query_one("#data", DataTable)
        if self._sheet is None:
            table.clear(columns=True)
            return
        _fill(table, self._sheet.view())

    # -- events --------------------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "cells":
            return
        key = event.row_key.value
        if key and key != self.current:
            self.current = key
            self._refresh_detail()

    # -- actions -------------------------------------------------------------

    def action_toggle_sql(self) -> None:
        self.sql_mode = "source" if self.sql_mode == "rendered" else "rendered"
        self._refresh_detail()

    def action_toggle_autorun(self) -> None:
        if self.current is None:
            return
        cfg = self.project.cell(self.current).config
        cfg.autorun = not getattr(cfg, "autorun", True)
        self._repopulate_cells()

    def action_toggle_all_autorun(self) -> None:
        names = self.project.order()
        target = not all(getattr(self.project.cell(n).config, "autorun", True) for n in names)
        for name in names:
            self.project.cell(name).config.autorun = target
        self._repopulate_cells()

    def action_run_selected(self) -> None:
        if self.current is not None:
            self._run([self.current])

    def action_run_all(self) -> None:
        self._run(None)

    def _run(self, select: list[str] | None) -> None:
        for result in self.project.run(select=select):
            self.results[result.name] = result
        self._repopulate_cells()
        self._refresh_detail()

    def action_open_visidata(self) -> None:
        if self.current is None:
            return
        path = self._parquet_path(self.project.cell(self.current))
        if not path or not path.exists():
            self.notify("no parquet output — run the cell first")
            return
        try:
            with self.suspend():
                subprocess.run(["vd", str(path)])
        except FileNotFoundError:
            self.notify("VisiData (vd) is not installed")

    def action_sort(self, direction: str) -> None:
        if self._sheet is not None:
            self._sheet.sort_by_cursor(descending=direction == "desc")
            self._render_sheet()

    def action_hide_col(self) -> None:
        if self._sheet is not None:
            self._sheet.hide_cursor_column()
            self._render_sheet()

    def action_unhide(self) -> None:
        if self._sheet is not None:
            self._sheet.unhide_all()
            self._render_sheet()

    def action_frequency(self) -> None:
        if self._sheet is not None:
            self._sheet = self._sheet.frequency()
            self._render_sheet()

    def action_describe(self) -> None:
        if self._sheet is not None:
            self._sheet = self._sheet.describe()
            self._render_sheet()

    def action_cell_move(self, delta: int) -> None:
        table = self.query_one("#cells", DataTable)
        table.move_cursor(row=table.cursor_row + delta)

    def action_cell_top(self) -> None:
        self.query_one("#cells", DataTable).move_cursor(row=0)

    def action_cell_bottom(self) -> None:
        table = self.query_one("#cells", DataTable)
        table.move_cursor(row=table.row_count - 1)

    # -- watch worker --------------------------------------------------------

    async def _watch_worker(self) -> None:
        from watchfiles import awatch

        # Watch the parent directory, not the file: editors that save via
        # rename (vim/nvim backup writes) replace the inode, which kills a
        # watch placed on the file itself after the first save.
        async for changes in awatch(str(self.file.parent)):
            if any(Path(path) == self.file for _, path in changes):
                await self._apply_file_change()

    async def _apply_file_change(self) -> None:
        try:
            new = Project.from_file(self.file, overrides=self.overrides)
        except (QsqlError, OSError):
            # invalid intermediate state or mid-save rename race; keep last good
            return
        names = plan_rebuild(self.project, new)
        if names:
            results = await asyncio.to_thread(new.run, names)
            for result in results:
                self.results[result.name] = result
        self.project = new
        self._reconcile_current()
        self._repopulate_cells()
        self._refresh_detail()
