import pytest
from textual.widgets import DataTable

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
