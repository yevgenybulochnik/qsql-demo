import pytest
from textual.widgets import DataTable, TabbedContent

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
