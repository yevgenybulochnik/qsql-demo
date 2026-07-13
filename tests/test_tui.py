"""Pilot smoke test for the Textual TUI."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.widgets import DataTable

from qsql_demo import Project
from qsql_demo.tui import QsqlApp

PIPELINE = """\
-- @output: { type: parquet, dir: data/ }

-- @cell users
SELECT * FROM (VALUES (1,'Ana',true),(2,'Ben',false)) AS t(id,name,active);

-- @cell active_users
-- @depends_on: [users]
SELECT id, name FROM {{ ref('users') }} WHERE active;
"""


def _project(project_dir: Path) -> Project:
    (project_dir / "base.sql").write_text(PIPELINE)
    proj = Project.from_file(project_dir / "base.sql")
    proj.run()
    return proj


def test_tui_mounts_and_reacts_to_keys(project_dir: Path) -> None:
    app = QsqlApp(_project(project_dir), enable_watch=False)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            cells = app.query_one("#cells", DataTable)
            assert cells.row_count == 2
            assert app.current == "users"

            # SQL panel toggles source/rendered
            assert app.sql_mode == "rendered"
            await pilot.press("t")
            assert app.sql_mode == "source"

            # navigate to the next cell
            await pilot.press("j")
            await pilot.pause()
            assert app.current == "active_users"

            # rendered SQL of the join cell reads its upstream's parquet
            await pilot.press("t")  # back to rendered
            assert app.sql_mode == "rendered"
            assert "read_parquet" in app.project.cell("active_users").sql

            await pilot.press("q")

    asyncio.run(scenario())


def test_tui_layout_stacks_cells_above_detail(project_dir: Path) -> None:
    app = QsqlApp(_project(project_dir), enable_watch=False)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            cells = app.query_one("#cells")
            detail = app.query_one("#detail")
            assert cells.region.x == detail.region.x  # both span from the left edge
            assert detail.region.y >= cells.region.bottom  # detail sits below the cell list

    asyncio.run(scenario())


def test_tui_survives_removed_current_cell(project_dir: Path) -> None:
    # regression: deleting the selected cell then recompiling must not crash the UI
    (project_dir / "base.sql").write_text(PIPELINE)
    app = QsqlApp(Project.from_file(project_dir / "base.sql"), enable_watch=False)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.current = "active_users"
            reduced = "-- @output: { type: parquet, dir: data/ }\n\n-- @cell users\nSELECT 1 AS id;\n"
            app.project = Project.from_text(reduced, project_dir=project_dir)
            app._refresh_detail()  # must not raise KeyError on the removed cell
            assert app.current == "users"

    asyncio.run(scenario())


def test_tui_file_change_adds_new_cell_and_runs_it(project_dir: Path) -> None:
    # regression: a saved file with a brand-new cell must show up in the cell
    # list and be run (landing its parquet), without resetting the selection
    file = project_dir / "base.sql"
    file.write_text(PIPELINE)
    app = QsqlApp(Project.from_file(file), file=file, enable_watch=False)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("j")  # select active_users
            await pilot.pause()
            assert app.current == "active_users"

            file.write_text(PIPELINE + "\n-- @cell hello\nSELECT 'hi' AS greeting;\n")
            await app._apply_file_change()
            await pilot.pause()

            cells = app.query_one("#cells", DataTable)
            assert cells.row_count == 3
            assert app.results["hello"].ok
            assert (project_dir / "data" / "hello.parquet").exists()
            assert app.current == "active_users"  # selection survives the rebuild

    asyncio.run(scenario())


def test_tui_run_all_populates_results(project_dir: Path) -> None:
    (project_dir / "base.sql").write_text(PIPELINE)
    app = QsqlApp(Project.from_file(project_dir / "base.sql"), enable_watch=False)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("R")  # run all
            await pilot.pause()
            assert app.results["active_users"].ok
            assert app.results["users"].rows == 2

    asyncio.run(scenario())
