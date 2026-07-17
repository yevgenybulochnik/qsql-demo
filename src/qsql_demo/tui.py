"""VisiData-style Textual TUI: master-detail over a qsql project, reflect-only.

Top: the cell list (engine -> sink, autorun, status, rows). Below: tabs for
SQL (t toggles raw/rendered), Data (a stack of Polars Sheets with vim keys),
Config, and Log. Nothing runs on startup: the first R (run all) arms autorun,
after which a background watcher recompiles on save and reruns autorun cells.
The file is edited in your own editor; the TUI never writes it.

Keys: j/k cell rows . h/l cycle detail tabs . gg/G top/bottom . Enter dive into
the Data sheet (then j/k/h/l move its cursor; q climbs back out) . [ ] sort .
- hide col . s/gs select . F frequency . I describe . / search, n/N next/prev .
f filter rows by regex (live; Enter commits, Esc cancels) . y yank the cell
(or selected rows' column, ",\n"-joined) to the clipboard .
S catalog browser (Enter drills context/dataset/table down to field paths,
q pops; levels are cached — ctrl+r refetches the current one) .
t raw/rendered . a/A cell/global autorun . r/R run cell/all .
V real VisiData . o open/switch notebook (auto-opens as a picker when the
file doesn't exist) . ? help overlay (all keys) . q pop/quit
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
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, OptionList, RichLog, Static, TabbedContent, TabPane
from textual.widgets.option_list import Option

from .catalog import CatalogCache, CatalogNode, project_root_node
from .compiler import Project, compile_file
from .errors import QsqlError
from .models import RunResult
from .runner import RunSession, run_project
from .sheet import Sheet
from .watcher import hashes_of, plan_rerun


class NotebookPicker(ModalScreen):
    """Choose a notebook in the directory, or create one from a starting
    template (builtin, plus any under ~/.qsql/templates)."""

    BINDINGS = [Binding("escape", "cancel", "cancel")]

    CSS = """
    NotebookPicker { align: center middle; }
    #picker { width: 64; max-height: 20; border: solid $primary; padding: 1; }
    """

    def __init__(self, directory: Path, creates: list[tuple[str, str]]) -> None:
        super().__init__()
        self.directory = directory
        self.creates = creates  # (target filename, template name) pairs

    def compose(self) -> ComposeResult:
        # notebooks only: .qsql, or .qsql.sql for editors that want SQL
        # highlighting — plain .sql files (dumps, migrations) are noise here
        notebooks = sorted(self.directory.glob("*.qsql")) + sorted(
            self.directory.glob("*.qsql.sql")
        )
        options = [Option(f"open    {f.name}", id=f"open:{f}") for f in notebooks]
        options += [
            Option(f"create  {target} — template {name!r}", id=f"template:{i}")
            for i, (target, name) in enumerate(self.creates)
        ]
        with Vertical(id="picker"):
            yield Static("select a notebook — Enter opens, Esc cancels")
            yield OptionList(*options)

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        if event.character == "j":
            self.query_one(OptionList).action_cursor_down()
        elif event.character == "k":
            self.query_one(OptionList).action_cursor_up()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        kind, _, value = (event.option.id or "").partition(":")
        if kind == "template":
            self.dismiss(("template", self.creates[int(value)]))
        else:
            self.dismiss(("open", value))

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen):
    """`?` overlay: every key, grouped. Most sheet/vim keys live only in
    on_key and show in no footer binding, so this is the single place they
    are all documented. ``?`` / Esc / q dismiss."""

    BINDINGS = [
        Binding("question_mark", "close", "close", key_display="?"),
        Binding("escape", "close", "close"),
        Binding("q", "close", "close"),
    ]

    CSS = """
    HelpScreen { align: center middle; }
    #help { width: 76; height: 80%; max-height: 34; border: round $primary; background: $surface; }
    #help_title { padding: 0 2; text-style: bold; }
    #help_body { height: 1fr; padding: 1 2; }
    """

    # (section, [(keys, what), ...]); alternatives are "/"-joined so the keys
    # flatten back to the individual bindings documented (see the TUI test)
    SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
        ("Cells", [
            ("j/k", "move the cell selection"),
            ("gg/G", "first / last cell"),
            ("h/l", "cycle detail tabs (SQL / Data / Config / Log)"),
            ("enter", "dive into the Data sheet"),
            ("/", "search cell names"),
            ("r/R", "run cell / run all (arms watch reruns)"),
            ("a/A", "toggle autorun for the cell / globally"),
            ("t", "SQL raw ↔ rendered"),
            ("S", "catalog browser"),
            ("V", "open the cell's output in VisiData"),
            ("o", "open / switch notebook"),
        ]),
        ("Data sheet", [
            ("j/k/h/l", "move the cursor"),
            ("gg/G", "top / bottom row"),
            ("ctrl+u/ctrl+d", "page up / down"),
            ("[/]", "sort ascending / descending"),
            ("-", "hide the current column"),
            ("s/gs", "select row / select all"),
            ("f", "filter rows by regex (live; Enter commits)"),
            ("n/N", "next / previous search match"),
            ("F", "frequency table of the column"),
            ("I", "describe (summary stats)"),
            ("y", "yank cell / selected column to clipboard"),
            ("q", "pop the sheet (back a level)"),
        ]),
        ("Catalog (S)", [
            ("enter", "drill: context → dataset → table → fields"),
            ("ctrl+r", "refetch the current level"),
            ("q", "pop back a level"),
        ]),
        ("General", [
            ("?", "this help"),
            ("q", "pop / quit"),
        ]),
    ]

    def compose(self) -> ComposeResult:
        from rich.console import Group
        from rich.table import Table
        from rich.text import Text

        blocks: list[Any] = []
        for i, (title, rows) in enumerate(self.SECTIONS):
            if i:
                blocks.append(Text())
            blocks.append(Text(title, style="bold"))
            grid = Table.grid(padding=(0, 3))
            grid.add_column(justify="right", style="cyan", no_wrap=True)
            grid.add_column(overflow="fold")
            for keys, what in rows:  # Text() so "[/]" et al. aren't read as markup
                grid.add_row(Text(keys), Text(what))
            blocks.append(grid)
        with Vertical(id="help"):
            yield Static("qsql keys — ? or Esc to close", id="help_title")
            with VerticalScroll(id="help_body"):
                yield Static(Group(*blocks))

    def action_close(self) -> None:
        self.dismiss(None)


class QsqlApp(App):
    TITLE = "qsql"

    CSS = """
    #cells { height: 40%; max-height: 12; border: solid $primary; }
    #detail { height: 1fr; border: solid $secondary; }
    #search { dock: bottom; display: none; }
    #sql_view, #config_view { padding: 1; }
    /* too short for both sections: drop the detail tabs, let the cell list fill */
    #body.-compact #detail { display: none; }
    #body.-compact #cells { height: 1fr; max-height: 100%; }
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
        Binding("S", "catalog", "catalog"),
        Binding("V", "visidata", "vd"),
        Binding("o", "open_notebook", "open"),
        Binding("slash", "search", "search", key_display="/"),
        Binding("question_mark", "help", "help", key_display="?"),
        Binding("ctrl+r", "refetch", "refetch", show=False),
        Binding("ctrl+d", "page(1)", "page down", show=False),
        Binding("ctrl+u", "page(-1)", "page up", show=False),
    ]

    def __init__(
        self,
        path: Path | str,
        overrides: dict[str, Any] | None = None,
        watch: bool = True,
        auto_run: bool = False,
    ) -> None:
        super().__init__()
        self.path = Path(path)
        self.overrides = overrides or {}
        self.watch = watch
        self.auto_run = auto_run
        self.armed = False  # watch reruns stay dormant until the first run-all
        self.project: Project | None = None
        self.session = RunSession()  # reused across reruns; run worker is exclusive
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
        self._input_mode = "search"  # what the bottom input edits: search | filter
        self._filter_base: Sheet | None = None  # sheet being live-filtered
        self._catalog_cache = CatalogCache()  # cleared on run/recompile/switch
        # what the #data table currently displays; holding the frame reference
        # keeps identity comparison sound (ids can't be recycled)
        self._data_shown: tuple[Any, tuple[str, ...], frozenset[int]] | None = None

    # ---------- layout ----------

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
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
        if self.path.exists():
            self._load_notebook(self.path)
        else:
            self._show_picker(startup=True)

    def _load_notebook(self, path: Path | str) -> None:
        """Open a notebook (fresh state), arming and watching per-notebook."""
        self.path = Path(path)
        self.title = f"qsql · {self.path.name}"
        self.results = {}
        self.running = set()
        self.sheet_stack = []
        self._catalog_cache.invalidate()
        self._data_shown = None
        self.mode = "cells"
        self.armed = False
        self.project = None
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
        else:
            self.log_line("autorun paused — press R to run all cells and arm watch reruns")
        if self.watch:
            self._watch_worker()  # exclusive group: replaces any previous watcher

    def _show_picker(self, startup: bool) -> None:
        from .scaffold import template_names

        directory = self.path.parent if str(self.path.parent) else Path(".")
        creates: list[tuple[str, str]] = []
        if not self.path.exists():
            # the requested file is missing: any template may seed it
            creates = [(self.path.name, name) for name in template_names()]
        else:  # switching: offer each template under its own filename
            for name in template_names():
                target = "base.qsql" if name == "base" else f"{name}.qsql"
                if not (directory / target).exists():
                    creates.append((target, name))

        def chosen(result: tuple[str, Any] | None) -> None:
            if result is None:
                if startup:
                    self.exit()
                return
            kind, value = result
            if kind == "template":
                from .scaffold import write_scaffold

                target, name = value
                self._load_notebook(write_scaffold(directory / target, template=name))
            else:
                self._load_notebook(Path(value))

        self.push_screen(NotebookPicker(directory, creates), chosen)

    def action_open_notebook(self) -> None:
        self._show_picker(startup=False)

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen())

    # rows of terminal below which the detail tabs are dropped and the cell
    # list fills the screen (header + a usable detail pane don't both fit)
    COMPACT_HEIGHT = 16

    def on_resize(self, event: events.Resize) -> None:
        try:
            body = self.query_one("#body", Vertical)
        except NoMatches:
            return  # resize before the body mounted; on_mount lays out fresh
        body.set_class(event.size.height < self.COMPACT_HEIGHT, "-compact")

    def on_unmount(self) -> None:
        self.session.close()

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
        from .watcher import should_rerun

        configured = should_rerun(self.project.cells[name])
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

    def _row_cap(self, sheet: Sheet) -> int | None:
        # catalog sheets list one row per column/table/dataset — never truncate
        # them, or a wide table would hide fields. data previews stay capped so
        # rebuilding a wide frame stays cheap on every cursor keypress.
        return None if sheet.drill is not None else self.MAX_DATA_ROWS

    def _refresh_data(self) -> None:
        table = self.query_one("#data", DataTable)
        if not self.sheet_stack:
            table.clear(columns=True)
            self._data_shown = None
            return
        sheet = self.sheet_stack[-1]
        cap = self._row_cap(sheet)
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
            frame = sheet.frame.select(window)
            if cap is not None:
                frame = frame.head(cap)
            rows = [
                (("▸" if idx in sheet.selected else "") + str(row[0]), *map(str, row[1:]))
                for idx, row in enumerate(frame.rows())
            ]
            table.clear(columns=True)
            for name, width in zip(window, self._column_widths(window, rows)):
                table.add_column(str(name), width=width)
            table.add_rows(rows)
        height = sheet.frame.height if cap is None else min(sheet.frame.height, cap)
        if height:
            table.move_cursor(row=min(sheet.cursor[0], height - 1), column=cursor_col - start)
        picked = f" · {len(sheet.selected)} selected" if sheet.selected else ""
        span = ""
        if len(cols) > self.MAX_DATA_COLS:
            span = f" · cols {start + 1}-{start + len(window)}/{len(cols)}"
        self.sub_title = f"{sheet.title} · {sheet.frame.height}x{len(cols)}{picked}{span}"

    def _column_widths(self, window: list[str], rows: list[tuple[str, ...]]) -> list[int]:
        """Explicit column widths for the data table. While a filter is being
        typed the shown rows are a shrinking subset — measure the captured
        base sheet instead, so widths hold still keystroke to keystroke."""
        base = self._filter_base
        if base is not None and all(c in base.frame.columns for c in window):
            source = base.frame.select(window)
            cap = self._row_cap(base)
            if cap is not None:
                source = source.head(cap)
            rows = [tuple(map(str, row)) for row in source.rows()]
        widths = [len(str(name)) for name in window]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))
        return widths

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

    def _read_parquet_head(self, target: str) -> pl.DataFrame:
        """Preview through duckdb's parquet reader, never polars' — the polars
        reader panics on duckdb-written INTERVAL columns, and duckdb only reads
        the head row groups for a LIMIT."""
        import duckdb

        from .runner import _preview

        con = duckdb.connect()
        try:
            return _preview(con, f"read_parquet('{target}')", self.PREVIEW_ROWS)
        finally:
            con.close()

    def _preview_frame(self, name: str) -> pl.DataFrame:
        result = self.results.get(name)
        if result is not None and isinstance(result.preview, pl.DataFrame):
            return result.preview
        if result is not None and result.ok and result.target and result.target.endswith(".parquet"):
            return self._read_parquet_head(result.target)
        target = self.project.root / "data" / f"{name}.parquet" if self.project else None
        if target and target.exists():
            return self._read_parquet_head(str(target))
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
        self.armed = True
        self._run_worker(None, closure=True)

    def action_frequency(self) -> None:
        if self.mode == "data" and self.sheet_stack:
            self._push_sheet(self.sheet_stack[-1].freq())

    def action_describe(self) -> None:
        if self.mode == "data" and self.sheet_stack:
            self._push_sheet(self.sheet_stack[-1].describe())

    def action_catalog(self) -> None:
        if self.project:
            self._catalog_worker(project_root_node(self.project, connect=self._catalog_connect))

    def action_refetch(self) -> None:
        """ctrl+r: drop the current catalog sheet's cached frame and reload it."""
        if self.mode != "data" or not self.sheet_stack:
            return
        node: CatalogNode | None = self.sheet_stack[-1].drill
        if node is None:
            return
        self._catalog_cache.invalidate(node)
        self._catalog_worker(node, replace=True)

    def _catalog_connect(self):
        """DuckDB handle for catalog reads: a cursor of the live conduit (it
        may already hold sink ATTACHes, and cursors are per-thread-safe), or
        a throwaway connection before the first run."""
        if self.session.conn is not None:
            return self.session.conn.cursor()
        import duckdb

        return duckdb.connect()

    def _restore_subtitle(self) -> None:
        if self.mode == "data" and self.sheet_stack:
            self._refresh_data()
        else:
            self._refresh_detail()

    def _drill_current(self) -> None:
        sheet = self.sheet_stack[-1]
        node: CatalogNode = sheet.drill
        if node.child is None or sheet.frame.height == 0:
            return  # a leaf (field-path sheet): nowhere further down
        child = node.child(sheet.frame.row(sheet.cursor[0], named=True))
        if child is not None:
            self._catalog_worker(child)

    def action_search(self) -> None:
        self._input_mode = "search"
        self._show_input("search...")

    def _show_input(self, placeholder: str) -> None:
        search = self.query_one("#search", Input)
        search.value = ""  # a cancelled filter/search must not leave stale text
        search.placeholder = placeholder
        search.styles.display = "block"
        search.focus()

    def _show_filter(self) -> None:
        if self.mode != "data" or not self.sheet_stack:
            return
        self._input_mode = "filter"
        self._filter_base = self.sheet_stack[-1]
        self._show_input("filter rows by regex...")

    def _cancel_filter(self) -> None:
        if self._filter_base is not None and self.sheet_stack:
            self.sheet_stack[-1] = self._filter_base
            self._refresh_data()
        self._filter_base = None
        self._input_mode = "search"

    def _yank(self) -> None:
        if self.mode != "data" or not self.sheet_stack:
            return
        sheet = self.sheet_stack[-1]
        if sheet.frame.height == 0:
            return
        col = sheet.current_column
        if sheet.selected:
            values = [str(sheet.frame[col][i]) for i in sorted(sheet.selected)]
            text = ",\n".join(values)  # paste-ready as a SQL select list
        else:
            values = [str(sheet.frame[col][sheet.cursor[0]])]
            text = values[0]
        self.copy_to_clipboard(text)
        self.notify(f"copied {len(values)} value(s) from {col!r}")

    def action_page(self, direction: int) -> None:
        if self.mode == "data":
            self._mutate_sheet(lambda s: self._reconcile_to_viewport(s).move(direction * 20, 0))
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
        if len(self.screen_stack) > 1:  # a modal (the picker) owns the keys
            return
        if self.query_one("#search", Input).has_focus:
            if event.key == "escape":
                if self._input_mode == "filter":
                    self._cancel_filter()
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
        elif ch == "f":
            self._show_filter()
        elif ch == "y":
            self._yank()
        elif ch == "n":
            self._repeat_search(reverse=False)
        elif ch == "N":
            self._repeat_search(reverse=True)

    TAB_ORDER = ["tab_sql", "tab_data", "tab_config", "tab_log"]

    def _cycle_tab(self, delta: int) -> None:
        tabs = self.query_one(TabbedContent)
        idx = self.TAB_ORDER.index(tabs.active) if tabs.active in self.TAB_ORDER else 0
        tabs.active = self.TAB_ORDER[(idx + delta) % len(self.TAB_ORDER)]

    def _reconcile_to_viewport(self, sheet: Sheet) -> Sheet:
        """Snap the cursor row into the data table's visible window. The mouse
        wheel scrolls the viewport but not the Sheet cursor, so without this a
        keyboard move would resume from the stale (often top) cursor and snap
        the view away from what the user is looking at. A no-op during normal
        keyboard navigation, where the cursor is always already on screen."""
        table = self.query_one("#data", DataTable)
        height = table.scrollable_content_region.height
        if not height:
            return sheet
        first = int(table.scroll_y)
        last = min(first + height - 1, sheet.frame.height - 1)
        row = min(max(sheet.cursor[0], first), last)
        return sheet if row == sheet.cursor[0] else sheet.move(row - sheet.cursor[0], 0)

    def _move(self, d_row: int = 0, d_col: int = 0, top: bool = False, bottom: bool = False) -> None:
        if self.mode == "data":
            if top:
                self._mutate_sheet(lambda s: s.top())
            elif bottom:
                self._mutate_sheet(lambda s: s.bottom())
            else:
                self._mutate_sheet(lambda s: self._reconcile_to_viewport(s).move(d_row, d_col))
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

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._input_mode != "filter" or self._filter_base is None or not self.sheet_stack:
            return
        # live: re-filter the captured base on every keystroke
        self.sheet_stack[-1] = self._filter_base.filtered(event.value.strip())
        self._refresh_data()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._input_mode == "filter":
            event.input.value = ""
            self._hide_search()
            base, self._filter_base = self._filter_base, None
            self._input_mode = "search"
            if base is not None and self.sheet_stack and self.sheet_stack[-1] is not base:
                # commit: keep the filtered sheet on top, base beneath (q restores)
                self.sheet_stack.insert(len(self.sheet_stack) - 1, base)
                self._refresh_data()
            return
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
        if self.mode == "data" and self.sheet_stack and self.sheet_stack[-1].drill is not None:
            self._drill_current()  # Enter on a catalog sheet goes deeper
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

    @work(thread=True, exclusive=True, group="catalog")
    def _catalog_worker(self, node: CatalogNode, replace: bool = False) -> None:
        self.call_from_thread(setattr, self, "sub_title", f"loading {node.title}…")
        try:
            frame, _ = self._catalog_cache.load(node)
        except Exception as exc:
            self.call_from_thread(self.log_line, f"catalog {node.title}: {exc}")
            self.call_from_thread(self.notify, f"catalog: {exc}", severity="error")
            self.call_from_thread(self._restore_subtitle)  # drop the loading… note
            return
        sheet = Sheet(frame, title=node.title, drill=node)
        if replace:  # refetch: swap the current sheet, keep the stack shape
            self.call_from_thread(self._replace_top_sheet, sheet)
        else:
            self.call_from_thread(self._push_sheet, sheet)

    def _replace_top_sheet(self, sheet: Sheet) -> None:
        if self.sheet_stack:
            self.sheet_stack[-1] = sheet
            self._refresh_data()
        else:
            self._push_sheet(sheet)

    @work(thread=True, exclusive=True, group="run")
    def _run_worker(self, select: Optional[list[str]], closure: bool = True) -> None:
        try:
            project = compile_file(self.path, self.overrides)
        except QsqlError as exc:
            self.call_from_thread(self.log_line, f"compile error: {exc}")
            return
        names = select if select is not None else list(project.order)
        self.call_from_thread(self._mark_running, project, names)
        results = run_project(project, select=select, closure=closure, session=self.session)
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
        self._catalog_cache.invalidate()  # outputs and warehouses just changed
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
        self._catalog_cache.invalidate()  # cells/contexts may have changed
        self._refresh_cells()
        self._refresh_detail()
        if not self.armed:
            if planned:
                self.log_line(
                    f"changed: {', '.join(planned)} (autorun paused — press R to run all)"
                )
            return []
        to_run = [n for n in planned if self.cell_autorun(n)]
        if to_run:
            self.log_line(f"changed -> rerunning: {', '.join(to_run)}")
            self._run_worker(to_run, closure=False)
        return to_run
