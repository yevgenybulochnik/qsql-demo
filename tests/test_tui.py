import polars as pl
import pytest
from textual.widgets import DataTable, TabbedContent

from qsql_demo.compiler import compile_file
from qsql_demo.scaffold import write_scaffold
from qsql_demo.tui import QsqlApp


@pytest.fixture
def notebook(tmp_path):
    return write_scaffold(tmp_path / "base.qsql")


async def test_missing_file_shows_picker_and_template_creates(tmp_path) -> None:
    from qsql_demo.tui import NotebookPicker

    target = tmp_path / "base.qsql"
    app = QsqlApp(path=target, watch=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, NotebookPicker)
        await pilot.press("enter")  # sole option: create base.qsql from the template
        await pilot.pause()
        assert target.exists()
        assert app.project and "users" in app.project.cells
        assert app.results == {}  # picker never runs anything


async def test_missing_file_picker_lists_existing_notebooks(tmp_path) -> None:
    from qsql_demo.tui import NotebookPicker

    write_scaffold(tmp_path / "other.qsql")
    app = QsqlApp(path=tmp_path / "base.qsql", watch=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, NotebookPicker)
        await pilot.press("enter")  # first option: open other.qsql
        await pilot.pause()
        assert app.path.name == "other.qsql"
        assert app.project
        assert not (tmp_path / "base.qsql").exists()  # nothing was scaffolded


async def test_picker_lists_qsql_and_qsql_sql_but_ignores_plain_sql(tmp_path) -> None:
    from textual.widgets import OptionList

    from qsql_demo.tui import NotebookPicker

    (tmp_path / "pipeline.qsql").write_text("-- @cell a\nSELECT 1;\n")
    (tmp_path / "legacy.qsql.sql").write_text("-- @cell b\nSELECT 2;\n")
    (tmp_path / "schema_dump.sql").write_text("CREATE TABLE noise (id INT);\n")
    app = QsqlApp(path=tmp_path / "base.qsql", watch=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, NotebookPicker)
        ol = app.screen.query_one(OptionList)
        prompts = [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
        assert any("pipeline.qsql" in p for p in prompts)
        assert any("legacy.qsql.sql" in p for p in prompts)
        assert not any("schema_dump.sql" in p for p in prompts)


async def test_user_templates_offered_and_seed_the_requested_file(tmp_path, monkeypatch) -> None:
    from textual.widgets import OptionList

    home = tmp_path / "home"
    (home / ".qsql" / "templates").mkdir(parents=True)
    (home / ".qsql" / "templates" / "metrics.qsql").write_text(
        "-- @cell tpl\nSELECT 7 AS seven;\n"
    )
    monkeypatch.setenv("HOME", str(home))
    workdir = tmp_path / "proj"
    workdir.mkdir()
    app = QsqlApp(path=workdir / "base.qsql", watch=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        ol = app.screen.query_one(OptionList)
        prompts = [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
        assert any("template 'base'" in p for p in prompts)
        assert any("template 'metrics'" in p for p in prompts)
        await pilot.press("down", "enter")  # base first, metrics second
        await pilot.pause()
        # the user template seeded the *requested* filename
        assert (workdir / "base.qsql").read_text().startswith("-- @cell tpl")
        assert list(app.project.cells) == ["tpl"]


async def test_o_switches_between_notebooks_and_resets_state(tmp_path) -> None:
    from qsql_demo.tui import NotebookPicker

    alpha = write_scaffold(tmp_path / "alpha.qsql")
    beta = tmp_path / "beta.qsql"
    beta.write_text("-- @cell solo\nSELECT 1 AS x;\n")
    app = QsqlApp(path=alpha, watch=False)
    async with app.run_test() as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.results and app.armed
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(app.screen, NotebookPicker)
        await pilot.press("down", "enter")  # alpha, [beta], create base.qsql
        await pilot.pause()
        assert app.path == beta
        assert list(app.project.cells) == ["solo"]
        assert app.results == {}      # fresh notebook, fresh state
        assert app.armed is False     # arming is per-notebook


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
        await pilot.press("R")  # arm autorun
        await app.workers.wait_for_complete()
        await pilot.pause()
        notebook.write_text(notebook.read_text() + "\n-- @cell fresh\nSELECT 1 AS z;\n")
        to_run = app._on_recompiled(compile_file(notebook))
        assert "fresh" in to_run
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.results["fresh"].ok


async def test_no_initial_run_until_run_all(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False)  # defaults: nothing runs on start
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.results == {}
        assert app.armed is False
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.armed is True
        assert app.results["users"].ok


async def test_watch_reruns_gated_until_armed(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False)
    async with app.run_test() as pilot:
        notebook.write_text(notebook.read_text().replace("range(10)", "range(5)"))
        assert app._on_recompiled(compile_file(notebook)) == []  # adopt, don't run
        assert app.results == {}
        assert app.project.cells["events"].sql_raw.count("range(5)")  # view refreshed
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        notebook.write_text(notebook.read_text().replace("range(5)", "range(7)"))
        to_run = app._on_recompiled(compile_file(notebook))
        assert "events" in to_run  # armed: changes rerun again
        await app.workers.wait_for_complete()


async def test_single_cell_run_does_not_arm_autorun(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False)
    async with app.run_test() as pilot:
        await pilot.press("r")  # run just the selected cell
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.results["users"].ok
        assert app.armed is False  # run-all is the explicit gate


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


async def test_catalog_browser_opens_drills_and_pops(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("S")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.mode == "data"
        top = app.sheet_stack[-1]
        assert top.title == "catalog"
        assert top.drill is not None
        kinds = top.frame["kind"].to_list()
        assert kinds.count("output") == 3  # one per scaffold cell
        await pilot.press("j")  # onto the first output row (one duckdb context)
        assert app.sheet_stack[-1].frame.row(1, named=True)["kind"] == "output"
        await pilot.press("enter")  # drill into the cell's field paths
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.sheet_stack) == 2
        leaf = app.sheet_stack[-1]
        assert leaf.frame.columns == ["column", "field_path", "type", "mode"]
        assert leaf.frame.height > 0
        await pilot.press("enter")  # leaves don't drill further
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.sheet_stack) == 2
        await pilot.press("q")  # pop back to the catalog
        assert len(app.sheet_stack) == 1
        assert app.sheet_stack[-1].title == "catalog"
        await pilot.press("q")
        assert app.mode == "cells"


async def test_catalog_cache_serves_redrills_and_ctrl_r_refetches(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("S")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("j", "enter")  # field paths of users, now cached
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.sheet_stack) == 2
        (notebook.parent / "data" / "users.parquet").unlink()
        await pilot.press("q", "enter")  # re-drill: cache serves despite the missing file
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.sheet_stack) == 2
        assert app.sheet_stack[-1].frame.columns == ["column", "field_path", "type", "mode"]
        await pilot.press("ctrl+r")  # invalidate + refetch: the reload now fails
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.sheet_stack) == 2  # the stale sheet stays visible
        await pilot.press("q", "enter")  # entry really gone: fresh drill fails too
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.sheet_stack) == 1


async def test_run_and_notebook_switch_clear_the_catalog_cache(notebook) -> None:
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("S")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app._catalog_cache) > 0
        await pilot.press("q", "R")  # back to cells, rerun: outputs changed
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app._catalog_cache) == 0
        await pilot.press("S")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app._catalog_cache) > 0
        app._load_notebook(notebook)  # switching notebooks resets everything
        assert len(app._catalog_cache) == 0


async def test_catalog_load_error_clears_loading_subtitle(notebook) -> None:
    # drilling into an output that never ran fails (no parquet yet); the
    # "loading …" subtitle must not stick around after the error toast
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("S")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("j", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(app.sheet_stack) == 1  # nothing was pushed
        assert not app.sub_title.startswith("loading")


async def test_enter_on_plain_data_sheet_still_resets_preview(notebook) -> None:
    # regression guard for the drill interception: sheets without a drill
    # payload keep the old Enter behavior (reset to the cell's preview)
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("enter")  # dive
        await pilot.press("F")  # freq sheet on top (drill-less)
        assert len(app.sheet_stack) == 2
        await pilot.press("enter")
        assert len(app.sheet_stack) == 1
        assert app.sheet_stack[-1].title == "users"


async def test_f_live_filters_commits_on_enter_cancels_on_escape(notebook) -> None:
    from textual.widgets import Input

    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("S")
        await app.workers.wait_for_complete()
        await pilot.pause()
        full_height = app.sheet_stack[-1].frame.height
        await pilot.press("f")
        assert app.query_one("#search", Input).has_focus
        await pilot.press("u", "s", "e", "r", "s")
        top = app.sheet_stack[-1]  # live: already narrowed while typing
        assert top.title == "filter(users)"
        assert top.frame.height == 1
        assert top.drill is not None  # a filtered catalog still drills
        await pilot.press("escape")  # cancel: unfiltered sheet restored
        assert app.sheet_stack[-1].frame.height == full_height
        assert len(app.sheet_stack) == 1
        await pilot.press("f")
        await pilot.press("e", "v", "e", "n", "t")
        await pilot.press("enter")  # commit: filtered pushed above the base
        assert len(app.sheet_stack) == 2
        assert app.sheet_stack[-1].title == "filter(event)"
        assert app.sheet_stack[-1].frame.height == 2  # events, active_user_events
        await pilot.press("q")
        assert app.sheet_stack[-1].frame.height == full_height


async def test_y_yanks_current_cell_or_selected_column_values(notebook, monkeypatch) -> None:
    copied: list[str] = []
    monkeypatch.setattr(QsqlApp, "copy_to_clipboard", lambda self, text: copied.append(text))
    app = QsqlApp(path=notebook, watch=False, auto_run=False)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("R")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("S")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("j", "enter")  # drill into the users field paths
        await app.workers.wait_for_complete()
        await pilot.pause()
        sheet = app.sheet_stack[-1]
        assert sheet.frame.columns == ["column", "field_path", "type", "mode"]
        await pilot.press("l")  # cursor onto field_path
        await pilot.press("y")  # no selection: the current cell
        assert copied == [sheet.frame["field_path"][0]]
        await pilot.press("s", "j", "s")  # select rows 0 and 1
        await pilot.press("y")
        expected = ",\n".join(sheet.frame["field_path"][:2].to_list())
        assert copied[-1] == expected  # SQL-ready select-list snippet


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
