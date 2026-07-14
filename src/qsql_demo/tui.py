"""VisiData-style Textual TUI: master-detail over a qsql project, reflect-only.

Top: the cell list (engine -> sink, autorun, status, rows). Below: tabs for
SQL (t toggles raw/rendered), Data (a stack of Polars Sheets with vim keys),
Config, and Log. The file is edited in your own editor; a background watcher
recompiles on save and reruns autorun cells. The TUI never writes the file.

Keys: j/k cell rows . h/l cycle detail tabs . gg/G top/bottom . Enter dive into
the Data sheet (then j/k/h/l move its cursor; q climbs back out) . [ ] sort .
- hide col . s/gs select . F frequency . I describe . / search, n/N next/prev .
t raw/rendered . a/A cell/global autorun . r/R run cell/all . V real VisiData .
q pop/quit
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import polars as pl
import yaml
from rich.syntax import Syntax
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Input, RichLog, Static, TabbedContent, TabPane

from .compiler import Project, compile_file
from .errors import QsqlError
from .models import RunResult
from .runner import run_project
from .sheet import Sheet
from .watcher import hashes_of, plan_rerun


class QsqlApp(App):
    TITLE = "qsql"

    CSS = """
    #cells { height: 40%; max-height: 12; border: solid $primary; }
    #detail { height: 1fr; border: solid $secondary; }
    #search { dock: bottom; display: none; }
    #sql_view, #config_view { padding: 1; }
    """

    BINDINGS = [
        Binding("q", "pop_or_quit", "pop/quit"),
        Binding("r", "run_cell", "run"),
        Binding("R", "run_all", "run all"),
        Binding("t", "toggle_sql", "raw/rendered"),
        Binding("a", "toggle_autorun", "autorun"),
        Binding("A", "toggle_autorun_global", "autorun*"),
        Binding("F", "frequency", "freq"),
        Binding("I", "describe", "describe"),
        Binding("V", "visidata", "vd"),
        Binding("slash", "search", "search", key_display="/"),
        Binding("ctrl+d", "page(1)", "page down", show=False),
        Binding("ctrl+u", "page(-1)", "page up", show=False),
    ]

    def __init__(
        self,
        path: Path | str,
        overrides: dict[str, Any] | None = None,
        watch: bool = True,
        auto_run: bool = True,
    ) -> None:
        super().__init__()
        self.path = Path(path)
        self.overrides = overrides or {}
        self.watch = watch
        self.auto_run = auto_run
        self.project: Project | None = None
        self.results: dict[str, RunResult] = {}
        self.running: set[str] = set()
        self.autorun_off: set[str] = set()
        self.autorun_global = True
        self.show_rendered = True
        self.mode = "cells"  # or "data"
        self.sheet_stack: list[Sheet] = []
        self.hashes: dict[str, str] = {}
        self._row_names: list[str] = []
        self._pending_g = False
        self._last_search = ""
        # what the #data table currently displays; holding the frame reference
        # keeps identity comparison sound (ids can't be recycled)
        self._data_shown: tuple[Any, tuple[str, ...], frozenset[int]] | None = None

    # ---------- layout ----------

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield DataTable(id="cells", cursor_type="row")
            with TabbedContent(id="detail"):
                with TabPane("SQL", id="tab_sql"):
                    yield Static(id="sql_view")
                with TabPane("Data", id="tab_data"):
                    yield DataTable(id="data", cursor_type="cell")
                with TabPane("Config", id="tab_config"):
                    yield Static(id="config_view")
                with TabPane("Log", id="tab_log"):
                    yield RichLog(id="log", markup=False, wrap=True)
        yield Input(placeholder="search...", id="search")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#cells", DataTable)
        table.add_columns("cell", "engine → sink", "auto", "status", "rows", "ms")
        self.query_one("#data", DataTable).can_focus = False
        table.focus()
        try:
            self.project = compile_file(self.path, self.overrides)
        except QsqlError as exc:
            self.log_line(f"compile error: {exc}")
            return
        self.hashes = hashes_of(self.project)
        self._refresh_cells()
        self._refresh_detail()
        if self.auto_run:
            self.action_run_all()
        if self.watch:
            self._watch_worker()

    # ---------- state helpers ----------

    @property
    def current_cell(self) -> str | None:
        table = self.query_one("#cells", DataTable)
        if not self._row_names or table.cursor_row is None:
            return None
        return self._row_names[min(table.cursor_row, len(self._row_names) - 1)]

    def cell_autorun(self, name: str) -> bool:
        if not self.project:
            return False
        configured = self.project.cells[name].config.autorun
        return self.autorun_global and configured and name not in self.autorun_off

    def log_line(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)

    def _status(self, name: str) -> str:
        if name in self.running:
            return "…"
        result = self.results.get(name)
        if result is None:
            return "·"
        return "✔" if result.ok else "✗"

    def _refresh_cells(self) -> None:
        table = self.query_one("#cells", DataTable)
        previous = table.cursor_row or 0
        table.clear()
        self._row_names = list(self.project.order) if self.project else []
        for name in self._row_names:
            cell = self.project.cells[name]
            result = self.results.get(name)
            table.add_row(
                name,
                f"{cell.engine} → {cell.sink_type}",
                "☑" if self.cell_autorun(name) else "☐",
                self._status(name),
                "" if result is None or result.rows is None else str(result.rows),
                "" if result is None else f"{result.elapsed * 1000:.0f}",
            )
        if self._row_names:
            table.move_cursor(row=min(previous, len(self._row_names) - 1))

    def _refresh_detail(self) -> None:
        name = self.current_cell
        if not name or not self.project:
            return
        cell = self.project.cells[name]
        sql = cell.sql if self.show_rendered else (cell.source or cell.sql_raw)
        label = "rendered" if self.show_rendered else "source"
        self.query_one("#sql_view", Static).update(
            Syntax(sql, "sql", line_numbers=True, word_wrap=True)
        )
        self.query_one("#config_view", Static).update(
            yaml.safe_dump(cell.config.model_dump(mode="json"), sort_keys=True)
        )
        stack = f" · sheets:{len(self.sheet_stack)}" if self.sheet_stack else ""
        self.sub_title = f"{name} · sql:{label}{stack}"
        result = self.results.get(name)
        if result and not result.ok and result.error:
            self.log_line(f"{name} failed:\n{result.error}")

    MAX_DATA_ROWS = 200
    MAX_DATA_COLS = 40  # window rendered around the cursor; re-windows at the edges

    def _refresh_data(self) -> None:
        table = self.query_one("#data", DataTable)
        if not self.sheet_stack:
            table.clear(columns=True)
            self._data_shown = None
            return
        sheet = self.sheet_stack[-1]
        cols = sheet.columns
        cursor_col = min(sheet.cursor[1], max(len(cols) - 1, 0))
        start = 0
        if len(cols) > self.MAX_DATA_COLS:
            start = max(0, min(cursor_col - self.MAX_DATA_COLS // 2, len(cols) - self.MAX_DATA_COLS))
        window = cols[start : start + self.MAX_DATA_COLS]
        shown = (sheet.frame, sheet.hidden, sheet.selected, start)
        if (
            self._data_shown is None
            or self._data_shown[0] is not shown[0]
            or self._data_shown[1:] != shown[1:]
        ):
            # rebuild only when content or the column window changed; wide
            # frames make rebuilds expensive and cursor moves happen per keypress
            self._data_shown = shown
            frame = sheet.frame.select(window).head(self.MAX_DATA_ROWS)
            table.clear(columns=True)
            table.add_columns(*(str(c) for c in frame.columns))
            table.add_rows(
                (("▸" if idx in sheet.selected else "") + str(row[0]), *map(str, row[1:]))
                for idx, row in enumerate(frame.rows())
            )
        height = min(sheet.frame.height, self.MAX_DATA_ROWS)
        if height:
            table.move_cursor(row=min(sheet.cursor[0], height - 1), column=cursor_col - start)
        picked = f" · {len(sheet.selected)} selected" if sheet.selected else ""
        span = ""
        if len(cols) > self.MAX_DATA_COLS:
            span = f" · cols {start + 1}-{start + len(window)}/{len(cols)}"
        self.sub_title = f"{sheet.title} · {sheet.frame.height}x{len(cols)}{picked}{span}"

    def _mutate_sheet(self, fn) -> None:
        if self.mode != "data" or not self.sheet_stack:
            return
        self.sheet_stack[-1] = fn(self.sheet_stack[-1])
        self._refresh_data()

    def _push_sheet(self, sheet: Sheet) -> None:
        self.sheet_stack.append(sheet)
        self.mode = "data"
        self.query_one(TabbedContent).active = "tab_data"
        self._refresh_data()

    PREVIEW_ROWS = 100

    def _preview_frame(self, name: str) -> pl.DataFrame:
        result = self.results.get(name)
        if result is not None and isinstance(result.preview, pl.DataFrame):
            return result.preview
        # lazy head, never a full read: landed files can be huge
        if result is not None and result.ok and result.target and result.target.endswith(".parquet"):
            return pl.scan_parquet(result.target).head(self.PREVIEW_ROWS).collect()
        target = self.project.root / "data" / f"{name}.parquet" if self.project else None
        if target and target.exists():
            return pl.scan_parquet(target).head(self.PREVIEW_ROWS).collect()
        return pl.DataFrame({"info": [f"no output for {name!r} yet — press r to run"]})

    # ---------- actions (footer bindings) ----------

    def action_pop_or_quit(self) -> None:
        if self.mode == "data" and self.sheet_stack:
            self.sheet_stack.pop()
            if self.sheet_stack:
                self._refresh_data()
                return
            self.mode = "cells"
            self.query_one(TabbedContent).active = "tab_sql"
            self._refresh_detail()
            return
        self.exit()

    def action_toggle_sql(self) -> None:
        self.show_rendered = not self.show_rendered
        self._refresh_detail()

    def action_toggle_autorun(self) -> None:
        name = self.current_cell
        if name:
            self.autorun_off.symmetric_difference_update({name})
            self._refresh_cells()

    def action_toggle_autorun_global(self) -> None:
        self.autorun_global = not self.autorun_global
        self._refresh_cells()

    def action_run_cell(self) -> None:
        if self.current_cell:
            self._run_worker([self.current_cell], closure=True)

    def action_run_all(self) -> None:
        self._run_worker(None, closure=True)

    def action_frequency(self) -> None:
        if self.mode == "data" and self.sheet_stack:
            self._push_sheet(self.sheet_stack[-1].freq())

    def action_describe(self) -> None:
        if self.mode == "data" and self.sheet_stack:
            self._push_sheet(self.sheet_stack[-1].describe())

    def action_search(self) -> None:
        search = self.query_one("#search", Input)
        search.styles.display = "block"
        search.focus()

    def action_page(self, direction: int) -> None:
        if self.mode == "data":
            self._mutate_sheet(lambda s: s.move(direction * 20, 0))
        else:
            self.query_one("#cells", DataTable).move_cursor(
                row=(self.query_one("#cells", DataTable).cursor_row or 0) + direction * 10
            )

    def action_visidata(self) -> None:
        name = self.current_cell
        result = self.results.get(name) if name else None
        target = result.target if result and result.ok else None
        vd = shutil.which("vd")
        if not vd:
            self.notify("visidata (vd) is not installed", severity="warning")
            return
        if not target or not Path(target).exists():
            self.notify(f"no landed file for {name!r} — run it first", severity="warning")
            return
        with self.suspend():
            subprocess.call([vd, target])

    # ---------- raw keys (vim/VisiData movement + sheet ops) ----------

    def on_key(self, event: events.Key) -> None:
        if self.query_one("#search", Input).has_focus:
            if event.key == "escape":
                self._hide_search()
            return
        ch = event.character
        if self._pending_g:
            self._pending_g = False
            if ch == "g":
                self._move(top=True)
            elif ch == "s":
                self._mutate_sheet(lambda s: s.select_all())
            return
        if ch == "g":
            self._pending_g = True
        elif ch == "G":
            self._move(bottom=True)
        elif ch == "j":
            self._move(1, 0)
        elif ch == "k":
            self._move(-1, 0)
        elif ch == "h":
            self._move(0, -1)
        elif ch == "l":
            self._move(0, 1)
        elif ch == "[":
            self._mutate_sheet(lambda s: s.sort(desc=False))
        elif ch == "]":
            self._mutate_sheet(lambda s: s.sort(desc=True))
        elif ch == "-":
            self._mutate_sheet(lambda s: s.hide_current())
        elif ch == "s":
            self._mutate_sheet(lambda s: s.toggle_select())
        elif ch == "n":
            self._repeat_search(reverse=False)
        elif ch == "N":
            self._repeat_search(reverse=True)

    TAB_ORDER = ["tab_sql", "tab_data", "tab_config", "tab_log"]

    def _cycle_tab(self, delta: int) -> None:
        tabs = self.query_one(TabbedContent)
        idx = self.TAB_ORDER.index(tabs.active) if tabs.active in self.TAB_ORDER else 0
        tabs.active = self.TAB_ORDER[(idx + delta) % len(self.TAB_ORDER)]

    def _move(self, d_row: int = 0, d_col: int = 0, top: bool = False, bottom: bool = False) -> None:
        if self.mode == "data":
            if top:
                self._mutate_sheet(lambda s: s.top())
            elif bottom:
                self._mutate_sheet(lambda s: s.bottom())
            else:
                self._mutate_sheet(lambda s: s.move(d_row, d_col))
            return
        if d_col:
            self._cycle_tab(d_col)
            return
        table = self.query_one("#cells", DataTable)
        if top:
            table.move_cursor(row=0)
        elif bottom:
            table.move_cursor(row=max(table.row_count - 1, 0))
        elif d_row:
            table.move_cursor(row=(table.cursor_row or 0) + d_row)
        self._refresh_detail()

    def _hide_search(self) -> None:
        search = self.query_one("#search", Input)
        search.styles.display = "none"
        self.query_one("#cells", DataTable).focus()

    def _repeat_search(self, reverse: bool) -> None:
        if self._last_search:
            self._mutate_sheet(lambda s: s.search(self._last_search, reverse=reverse))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        needle = event.value.strip()
        self._last_search = needle
        event.input.value = ""
        self._hide_search()
        if not needle:
            return
        if self.mode == "data":
            self._mutate_sheet(lambda s: s.search(needle))
        else:  # jump to the next cell whose name matches
            names = self._row_names
            table = self.query_one("#cells", DataTable)
            start = (table.cursor_row or 0) + 1
            for offset in range(len(names)):
                idx = (start + offset) % len(names)
                if needle.lower() in names[idx].lower():
                    table.move_cursor(row=idx)
                    break
            self._refresh_detail()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Browsing onto a tab (click or h/l) shows content but stays in cells
        mode, so j/k keep moving the cell selection; Enter is what dives."""
        active = self.query_one(TabbedContent).active
        if active == "tab_data":
            if not self.sheet_stack:
                self._show_current_data()
        else:
            self.mode = "cells"
            self.sheet_stack = []
            self._refresh_detail()

    def _show_current_data(self) -> None:
        name = self.current_cell
        if name:
            self.sheet_stack = [Sheet(self._preview_frame(name), title=name)]
            self._refresh_data()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "cells":
            return
        name = self.current_cell
        if not name:
            return
        self.sheet_stack = []
        self._push_sheet(Sheet(self._preview_frame(name), title=name))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "cells" or self.mode != "cells":
            return
        self._refresh_detail()
        if self.query_one(TabbedContent).active == "tab_data":
            self._show_current_data()  # the Data sheet follows the selection

    # ---------- workers ----------

    @work(thread=True, exclusive=True, group="run")
    def _run_worker(self, select: Optional[list[str]], closure: bool = True) -> None:
        try:
            project = compile_file(self.path, self.overrides)
        except QsqlError as exc:
            self.call_from_thread(self.log_line, f"compile error: {exc}")
            return
        names = select if select is not None else list(project.order)
        self.call_from_thread(self._mark_running, project, names)
        results = run_project(project, select=select, closure=closure)
        self.call_from_thread(self._apply_results, results)

    def _mark_running(self, project: Project, names: list[str]) -> None:
        self.project = project
        self.hashes = hashes_of(project)
        self.running.update(names)
        self._refresh_cells()

    def _apply_results(self, results: list[RunResult]) -> None:
        for result in results:
            self.running.discard(result.cell)
            self.results[result.cell] = result
            status = "ok" if result.ok else "FAILED"
            self.log_line(
                f"{status} {result.cell} rows={result.rows} {result.elapsed * 1000:.0f}ms -> {result.target}"
            )
        self.running.clear()
        self._refresh_cells()
        self._refresh_detail()

    @work(exclusive=True, group="watch")
    async def _watch_worker(self) -> None:
        import watchfiles

        from .watcher import touches

        # watch the directory: atomic editor saves (nvim) replace the inode,
        # which silently kills a watch on the file path itself
        async for changes in watchfiles.awatch(self.path.parent):
            if not touches(changes, self.path):
                continue
            try:
                project = compile_file(self.path, self.overrides)
            except QsqlError as exc:
                self.log_line(f"compile error: {exc}")
                continue
            self._on_recompiled(project)

    def _on_recompiled(self, project: Project) -> list[str]:
        planned = plan_rerun(self.hashes, project)
        # adopt the new project before consulting autorun overlays: a freshly
        # added cell only exists in the new one (KeyError otherwise)
        self.project = project
        self.hashes = hashes_of(project)
        self._refresh_cells()
        self._refresh_detail()
        to_run = [n for n in planned if self.cell_autorun(n)]
        if to_run:
            self.log_line(f"changed -> rerunning: {', '.join(to_run)}")
            self._run_worker(to_run, closure=False)
        return to_run
