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
