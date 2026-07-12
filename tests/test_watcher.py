"""Tests for the watch rebuild-planning logic."""

from __future__ import annotations

import time
from pathlib import Path

import polars as pl

from qsql_demo import Project
from qsql_demo.watcher import changed_cells, plan_rebuild, watch_file

V1 = """\
-- @output: { type: parquet, dir: data/ }

-- @cell a
SELECT 1 AS n;

-- @cell b
-- @depends_on: [a]
SELECT n + 1 AS n FROM {{ ref('a') }};

-- @cell c
-- @depends_on: [b]
SELECT n + 1 AS n FROM {{ ref('b') }};
"""


def _proj(dir: Path, text: str) -> Project:
    (dir / "base.sql").write_text(text)
    return Project.from_file(dir / "base.sql")


def test_changed_cells_detects_body_change(project_dir: Path) -> None:
    p1 = _proj(project_dir, V1)
    p2 = _proj(project_dir, V1.replace("SELECT 1 AS n;", "SELECT 100 AS n;"))
    assert changed_cells(p1, p2) == ["a"]


def test_plan_rebuild_includes_downstream(project_dir: Path) -> None:
    p1 = _proj(project_dir, V1)
    p2 = _proj(project_dir, V1.replace("SELECT 1 AS n;", "SELECT 100 AS n;"))
    assert plan_rebuild(p1, p2) == ["a", "b", "c"]


def test_plan_rebuild_no_change_is_empty(project_dir: Path) -> None:
    p1 = _proj(project_dir, V1)
    p2 = _proj(project_dir, V1)
    assert plan_rebuild(p1, p2) == []


def test_autorun_false_cell_is_skipped(project_dir: Path) -> None:
    text = V1.replace("-- @cell b\n", "-- @cell b\n-- @autorun: false\n")
    p1 = _proj(project_dir, text)
    p2 = _proj(project_dir, text.replace("SELECT 1 AS n;", "SELECT 100 AS n;"))
    plan = plan_rebuild(p1, p2)
    assert "b" not in plan
    assert plan == ["a", "c"]


def test_rebuild_only_touches_downstream_parquet(project_dir: Path) -> None:
    p1 = _proj(project_dir, V1)
    p1.run()
    a_mtime = (project_dir / "data" / "a.parquet").stat().st_mtime_ns
    c_mtime = (project_dir / "data" / "c.parquet").stat().st_mtime_ns

    time.sleep(0.02)
    changed = V1.replace(
        "SELECT n + 1 AS n FROM {{ ref('b') }};", "SELECT n + 10 AS n FROM {{ ref('b') }};"
    )
    p2 = _proj(project_dir, changed)
    plan = plan_rebuild(p1, p2)
    assert plan == ["c"]

    p2.run(select=plan)
    assert (project_dir / "data" / "a.parquet").stat().st_mtime_ns == a_mtime  # untouched
    assert (project_dir / "data" / "c.parquet").stat().st_mtime_ns > c_mtime  # rebuilt
    assert pl.read_parquet(project_dir / "data" / "c.parquet")["n"].to_list() == [12]


def test_watch_file_runs_initial_then_rebuilds_on_change(project_dir: Path, monkeypatch) -> None:
    (project_dir / "base.sql").write_text(V1)
    events: list[tuple[str, list[str]]] = []

    def fake_watch(path):
        # simulate a save that changes cell `a`
        Path(path).write_text(V1.replace("SELECT 1 AS n;", "SELECT 100 AS n;"))
        yield {("modified", path)}

    monkeypatch.setattr("qsql_demo.watcher._watch", fake_watch)
    watch_file(
        project_dir / "base.sql",
        on_event=lambda kind, names, payload: events.append((kind, names)),
    )

    assert events[0] == ("initial", ["a", "b", "c"])
    assert events[1] == ("rebuild", ["a", "b", "c"])
    # the change (a := 100) propagated through the DAG: c == 100 + 1 + 1
    assert pl.read_parquet(project_dir / "data" / "c.parquet")["n"].to_list() == [102]
