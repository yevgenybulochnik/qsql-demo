"""VisiData-style Textual TUI: master-detail over a qsql project, reflect-only.

Top: the cell list (engine -> sink, autorun, status, rows). Below: tabs for
SQL (t toggles raw/rendered), Data (a stack of Polars Sheets with vim keys),
Config, and Log. The file is edited in your own editor; a background watcher
recompiles on save and reruns autorun cells. The TUI never writes the file.

Keys: j/k/h/l move . gg/G top/bottom . Enter dive . [ ] sort . - hide col .
s/gs select . F frequency . I describe . / search, n/N next/prev . t raw/rendered .
a/A cell/global autorun . r/R run cell/all . V open in real VisiData . q pop/quit
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
    #detail { border: solid $secondary; }
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
        sql = cell.sql if self.show_rendered else cell.sql_raw
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

    def _refresh_data(self) -> None:
        table = self.query_one("#data", DataTable)
        table.clear(columns=True)
        if not self.sheet_stack:
            return
        sheet = self.sheet_stack[-1]
        frame = sheet.visible().head(200)
        table.add_columns(*(str(c) for c in frame.columns))
        for idx, row in enumerate(frame.rows()):
            marker = "▸" if idx in sheet.selected else ""
            table.add_row(*(f"{marker}{v}" if col == 0 else str(v) for col, v in enumerate(row)))
        if frame.height:
            table.move_cursor(row=min(sheet.cursor[0], frame.height - 1), column=sheet.cursor[1])
        picked = f" · {len(sheet.selected)} selected" if sheet.selected else ""
        self.sub_title = f"{sheet.title} · {sheet.frame.height}x{len(sheet.columns)}{picked}"

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

    def _preview_frame(self, name: str) -> pl.DataFrame:
        result = self.results.get(name)
        if result is not None and isinstance(result.preview, pl.DataFrame):
            return result.preview
        if result is not None and result.ok and result.target and result.target.endswith(".parquet"):
            return pl.read_parquet(result.target)
        target = self.project.root / "data" / f"{name}.parquet" if self.project else None
        if target and target.exists():
            return pl.read_parquet(target)
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

    def _move(self, d_row: int = 0, d_col: int = 0, top: bool = False, bottom: bool = False) -> None:
        if self.mode == "data":
            if top:
                self._mutate_sheet(lambda s: s.top())
            elif bottom:
                self._mutate_sheet(lambda s: s.bottom())
            else:
                self._mutate_sheet(lambda s: s.move(d_row, d_col))
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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "cells":
            return
        name = self.current_cell
        if not name:
            return
        self.sheet_stack = []
        self._push_sheet(Sheet(self._preview_frame(name), title=name))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "cells" and self.mode == "cells":
            self._refresh_detail()

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

        async for _ in watchfiles.awatch(self.path):
            try:
                project = compile_file(self.path, self.overrides)
            except QsqlError as exc:
                self.log_line(f"compile error: {exc}")
                continue
            to_run = [n for n in plan_rerun(self.hashes, project) if self.cell_autorun(n)]
            self.project = project
            self.hashes = hashes_of(project)
            self._refresh_cells()
            self._refresh_detail()
            if to_run:
                self.log_line(f"changed -> rerunning: {', '.join(to_run)}")
                self._run_worker(to_run, closure=False)
