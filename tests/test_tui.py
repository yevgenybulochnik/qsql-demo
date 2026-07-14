import polars as pl
import pytest
from textual.widgets import DataTable, TabbedContent

from qsql_demo.compiler import compile_file
from qsql_demo.scaffold import write_scaffold
from qsql_demo.tui import QsqlApp


@pytest.fixture
def notebook(tmp_path):
    return write_scaffold(tmp_path / "base.sql")


async def test_boots_lists_cells_and_navigates(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test() as pilot:
        table = app.query_one("#cells", DataTable)
        assert table.row_count == 3
        assert app.current_cell == "users"
        await pilot.press("j")
        assert app.current_cell == "events"
        await pilot.press("k")
        assert app.current_cell == "users"


async def test_toggle_raw_rendered_and_autorun(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test() as pilot:
        assert app.show_rendered is True
        await pilot.press("t")
        assert app.show_rendered is False
        await pilot.press("a")
        assert "users" in app.autorun_off
        await pilot.press("a")
        assert "users" not in app.autorun_off
        await pilot.press("A")
        assert app.autorun_global is False


async def test_activating_data_tab_loads_current_cell_sheet(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        tabs = app.query_one(TabbedContent)
        tabs.active = "tab_data"  # click the tab instead of pressing Enter
        await pilot.pause()
        assert app.mode == "cells"  # browsing a tab is not a dive
        assert app.sheet_stack and app.sheet_stack[-1].title == "users"
        assert app.query_one("#data", DataTable).row_count > 0
        tabs.active = "tab_sql"
        await pilot.pause()
        assert app.mode == "cells"
        assert not app.sheet_stack


async def test_h_l_cycle_tabs_and_data_follows_selection(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        tabs = app.query_one(TabbedContent)
        assert tabs.active == "tab_sql"
        await pilot.press("l")
        assert tabs.active == "tab_data"
        assert app.sheet_stack[-1].title == "users"
        await pilot.press("j")  # j/k still move the cell selection
        assert app.current_cell == "events"
        assert app.sheet_stack[-1].title == "events"  # Data pane follows
        await pilot.press("l", "l")
        assert tabs.active == "tab_log"
        await pilot.press("l")  # wraps around
        assert tabs.active == "tab_sql"
        await pilot.press("h")
        assert tabs.active == "tab_log"


async def test_detail_pane_fills_remaining_height(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#detail")
        cells = app.query_one("#cells")
        assert cells.region.height <= 12
        assert detail.region.height >= 20  # fills the rest, never collapses


async def test_watch_recompile_with_new_cell_runs_it(notebook) -> None:
    # regression: filtering the rerun plan against the *old* project raised
    # KeyError for a freshly added cell and crashed the watch worker
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test() as pilot:
        notebook.write_text(notebook.read_text() + "\n-- @cell fresh\nSELECT 1 AS z;\n")
        to_run = app._on_recompiled(compile_file(notebook))
        assert "fresh" in to_run
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.results["fresh"].ok


def test_preview_frame_survives_interval_parquet(tmp_path) -> None:
    # duckdb round-trips INTERVAL parquet, but polars' reader panics on it;
    # the cold-start preview must go through duckdb instead
    import duckdb

    f = write_scaffold(tmp_path / "base.sql")
    app = QsqlApp(path=f, watch=False, auto_run=False)
    app.project = compile_file(f)
    (tmp_path / "data").mkdir()
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT INTERVAL 3 DAY AS iv, 1 AS n) TO '{tmp_path}/data/users.parquet' (FORMAT PARQUET)"
    )
    con.close()
    frame = app._preview_frame("users")
    assert frame.height == 1
    assert frame["iv"].dtype == pl.Duration("us")


def test_preview_frame_reads_head_only(tmp_path) -> None:
    # landed files can be huge; the fallback must never load them fully
    f = write_scaffold(tmp_path / "base.sql")
    app = QsqlApp(path=f, watch=False, auto_run=False)
    app.project = compile_file(f)
    (tmp_path / "data").mkdir()
    pl.DataFrame({"n": range(50_000)}).write_parquet(tmp_path / "data" / "users.parquet")
    frame = app._preview_frame("users")
    assert frame.height <= app.PREVIEW_ROWS


async def test_data_table_not_rebuilt_on_cursor_moves(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("enter")  # dive
        table = app.query_one("#data", DataTable)
        rebuilds: list[int] = []
        original = table.clear
        table.clear = lambda *a, **kw: (rebuilds.append(1), original(*a, **kw))[1]
        await pilot.press("j", "l", "j", "k", "h")
        assert not rebuilds  # cursor-only moves reuse the rendered table
        await pilot.press("]")  # sort changes content
        assert rebuilds


async def test_wide_frames_render_a_column_window(tmp_path) -> None:
    cols = ", ".join(f"{i} AS c{i}" for i in range(60))
    f = tmp_path / "wide.sql"
    f.write_text(f"-- @cell wide\nSELECT {cols};\n")
    app = QsqlApp(path=f, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("enter")
        table = app.query_one("#data", DataTable)
        assert len(table.columns) == app.MAX_DATA_COLS
        assert f"cols 1-{app.MAX_DATA_COLS}/60" in app.sub_title
        app.sheet_stack[-1] = app.sheet_stack[-1].move(0, 59)  # jump to last column
        app._refresh_data()
        assert f"cols {60 - app.MAX_DATA_COLS + 1}-60/60" in app.sub_title


async def test_run_all_populates_results_and_dive(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test() as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.results["users"].ok
        assert app.results["active_user_events"].rows == 7
        await pilot.press("enter")  # dive into Data sheet
        assert app.mode == "data"
        assert app.sheet_stack
        await pilot.press("F")  # frequency pushes a sheet
        assert len(app.sheet_stack) == 2
        await pilot.press("q")  # pop back
        assert len(app.sheet_stack) == 1
        await pilot.press("q")  # leave data mode
        assert app.mode == "cells"
