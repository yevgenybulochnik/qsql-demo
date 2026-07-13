"""The shipped example files stay compilable (and the kitchen sink runnable)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from qsql_demo import Project

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.mark.parametrize("name", ["pipeline.qsql", "bigquery.qsql", "kitchen-sink.qsql"])
def test_example_compiles(name: str) -> None:
    proj = Project.from_file(EXAMPLES / name)
    assert proj.order()


def test_kitchen_sink_runs_offline(tmp_path: Path) -> None:
    shutil.copytree(EXAMPLES, tmp_path / "ex")
    proj = Project.from_file(tmp_path / "ex" / "kitchen-sink.qsql")
    results = proj.run()
    assert all(r.ok for r in results), [(r.name, r.error) for r in results]
    assert (tmp_path / "ex" / "build" / "sql" / "summary.sql").exists()  # @render_dir emitted
    assert (tmp_path / "ex" / "kitchen.db").exists()  # the duckdb-sink cell landed
