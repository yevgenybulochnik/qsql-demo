from qsql_demo.compiler import compile_file
from qsql_demo.watcher import hashes_of, plan_rerun, run_changed

V1 = """\
-- @cell a
SELECT 1 AS x;
-- @cell b
SELECT * FROM {{ ref('a') }};
-- @cell c
SELECT 9 AS z;
-- @cell d
-- @autorun: false
SELECT * FROM {{ ref('a') }};
"""

V2 = V1.replace("SELECT 1 AS x;", "SELECT 2 AS x;")


def test_only_changed_and_downstream_rerun_autorun_respected(tmp_path) -> None:
    f = tmp_path / "base.sql"
    f.write_text(V1)
    hashes = hashes_of(compile_file(f))

    f.write_text(V2)
    project, results = run_changed(f, hashes)
    assert [r.cell for r in results] == ["a", "b"]  # c unchanged, d autorun:false
    assert all(r.ok for r in results), [r.error for r in results]
    assert (tmp_path / "data" / "b.parquet").exists()
    assert not (tmp_path / "data" / "c.parquet").exists()


def test_no_change_means_no_rerun(tmp_path) -> None:
    f = tmp_path / "base.sql"
    f.write_text(V1)
    hashes = hashes_of(compile_file(f))
    _, results = run_changed(f, hashes)
    assert results == []


def test_new_cell_counts_as_changed(tmp_path) -> None:
    f = tmp_path / "base.sql"
    f.write_text(V1)
    project = compile_file(f)
    hashes = hashes_of(project)
    f.write_text(V1 + "-- @cell e\nSELECT 5 AS w;\n")
    assert plan_rerun(hashes, compile_file(f)) == ["e"]


def test_config_only_edits_do_not_trigger(tmp_path) -> None:
    # change detection hashes SQL bodies only — a known limitation
    f = tmp_path / "base.sql"
    f.write_text(V1)
    hashes = hashes_of(compile_file(f))
    f.write_text(V1.replace("-- @autorun: false", "-- @autorun: true"))
    project, results = run_changed(f, hashes)
    assert results == []
