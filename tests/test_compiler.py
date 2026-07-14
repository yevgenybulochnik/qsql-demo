import pytest

from qsql_demo.compiler import compile_text
from qsql_demo.errors import ConfigError

PIPELINE = """\
-- @engine: duckdb
-- @vars: { n: 3 }

-- @cell users
SELECT * FROM range({{ var('n') }}) t(user_id);

-- @cell events
SELECT range AS user_id, 'click' AS event FROM range(2);

-- @cell active
-- @depends_on: [events]
SELECT u.user_id FROM {{ ref('users') }} u;
"""


def test_project_topo_order_and_edges(tmp_path) -> None:
    project = compile_text(PIPELINE, root=tmp_path)
    assert project.order == ["users", "events", "active"]
    assert project.cells["active"].depends_on == ["events", "users"]


def test_engine_resolution_explicit_and_inferred(tmp_path) -> None:
    project = compile_text(
        "-- @cell a\n-- @engine: sqlite\nSELECT 1 AS x;\n"
        "-- @cell b\n/*@ input: { sqlite: db.db } */\nSELECT 2 AS x;\n"
        "-- @cell c\nSELECT 3 AS x;",
        root=tmp_path,
    )
    assert project.cells["a"].engine == "sqlite"
    assert project.cells["b"].engine == "sqlite"
    assert project.cells["c"].engine == "duckdb"


def test_depends_on_unknown_cell_raises(tmp_path) -> None:
    with pytest.raises(ConfigError, match="unknown cell"):
        compile_text("-- @cell a\n-- @depends_on: [ghost]\nSELECT 1;", root=tmp_path)


def test_non_duckdb_cell_with_ref_trips_guardrail(tmp_path) -> None:
    with pytest.raises(ConfigError, match="must run on duckdb"):
        compile_text(
            "-- @cell a\nSELECT 1 AS x;\n"
            "-- @cell b\n-- @engine: sqlite\nSELECT * FROM {{ ref('a') }};",
            root=tmp_path,
        )


def test_non_duckdb_cell_with_source_trips_guardrail(tmp_path) -> None:
    with pytest.raises(ConfigError, match="must run on duckdb"):
        compile_text(
            "-- @cell a\n-- @engine: sqlite\nSELECT * FROM {{ source('x.csv') }};",
            root=tmp_path,
        )


def test_extensions_directive_trips_guardrail_on_non_duckdb_cell(tmp_path) -> None:
    with pytest.raises(ConfigError, match="must run on duckdb"):
        compile_text(
            "-- @cell a\n-- @engine: sqlite\n-- @extensions: [excel]\nSELECT 1;",
            root=tmp_path,
        )


def test_extensions_union_config_and_render_collected(tmp_path) -> None:
    project = compile_text(
        "-- @cell a\n-- @extensions: [spatial]\nSELECT * FROM {{ source('s.xlsx') }};",
        root=tmp_path,
    )
    assert set(project.cells["a"].extensions) == {"spatial", "excel"}


def test_all_config_errors_reported_together_with_lines(tmp_path) -> None:
    from qsql_demo.errors import ConfigErrorGroup

    text = (
        "-- @cell good\nSELECT 1;\n"
        "-- @cell bad_directive\n-- @bogus: 1\nSELECT 2;\n"
        "-- @cell bad_sink\n-- @output: { type: carrier_pigeon }\nSELECT 3;\n"
    )
    with pytest.raises(ConfigErrorGroup) as exc:
        compile_text(text, root=tmp_path)
    msg = str(exc.value)
    assert "cell 'bad_directive' (line 3)" in msg
    assert "@bogus" in msg
    assert "cell 'bad_sink' (line 6)" in msg
    assert "carrier_pigeon" in msg
    assert [e.cell for e in exc.value.errors] == ["bad_directive", "bad_sink"]


def test_all_render_errors_reported_together(tmp_path) -> None:
    from qsql_demo.errors import ConfigErrorGroup

    text = (
        "-- @cell a\nSELECT * FROM {{ ref('ghost') }};\n"
        "-- @cell b\nSELECT {{ var('nope') }};\n"
    )
    with pytest.raises(ConfigErrorGroup) as exc:
        compile_text(text, root=tmp_path)
    msg = str(exc.value)
    assert "cell 'a' (line 1)" in msg and "ghost" in msg
    assert "cell 'b' (line 3)" in msg and "undefined var" in msg


def test_single_error_still_matches_substring(tmp_path) -> None:
    with pytest.raises(ConfigError, match="unknown directive: @bogus"):
        compile_text("-- @cell a\n-- @bogus: 1\nSELECT 1;", root=tmp_path)


def test_cycle_reported(tmp_path) -> None:
    from qsql_demo.errors import CycleError

    with pytest.raises(CycleError):
        compile_text(
            "-- @cell a\nSELECT * FROM {{ ref('b') }};\n"
            "-- @cell b\nSELECT * FROM {{ ref('a') }};",
            root=tmp_path,
        )


def test_global_config_reaches_cells_and_overrides_apply(tmp_path) -> None:
    project = compile_text(
        "-- @autorun: false\n-- @cell a\nSELECT 1;",
        root=tmp_path,
        overrides={"autorun": True},
    )
    assert project.cells["a"].config.autorun is True
    assert project.config.autorun is True
