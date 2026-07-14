"""Behavior-hook seams: execute sugar, render seams, lifecycle notifications."""

from dataclasses import replace

from qsql_demo.compiler import compile_text
from qsql_demo.plugins.base import Plugin
from qsql_demo.registry import PLUGINS, plugin

# ---------- before_execute / after_execute sugar ----------


def test_before_and_after_execute_called_around_cell(tmp_path) -> None:
    calls: list[str] = []

    @plugin
    class Timing(Plugin):
        def before_execute(self, cell, ctx):
            calls.append(f"before:{cell.name}")

        def after_execute(self, cell, ctx, result):
            calls.append(f"after:{cell.name}:{result.ok}")

    project = compile_text("-- @cell a\nSELECT 1 AS x;", root=tmp_path)
    assert project.run()[0].ok
    assert calls == ["before:a", "after:a:True"]


def test_after_execute_can_replace_the_result(tmp_path) -> None:
    @plugin
    class Censor(Plugin):
        def after_execute(self, cell, ctx, result):
            return replace(result, target="[redacted]")

    project = compile_text("-- @cell a\nSELECT 1 AS x;", root=tmp_path)
    assert project.run()[0].target == "[redacted]"


def test_after_execute_returning_none_keeps_result(tmp_path) -> None:
    @plugin
    class Observer(Plugin):
        def after_execute(self, cell, ctx, result):
            return None

    project = compile_text("-- @cell a\nSELECT 1 AS x;", root=tmp_path)
    result = project.run()[0]
    assert result.ok and result.rows == 1


def test_sugar_only_plugin_joins_the_run_chain() -> None:
    @plugin
    class OnlyBefore(Plugin):
        def before_execute(self, cell, ctx):
            pass

    assert "only_before" in [p.name for p in PLUGINS.chain()]


def test_render_context_plugin_adds_jinja_globals(tmp_path) -> None:
    @plugin
    class Macros(Plugin):
        def render_context(self, name, config, context):
            context["greeting"] = "hello"
            return context

    project = compile_text("-- @cell a\nSELECT '{{ greeting }}' AS g;", root=tmp_path)
    assert "'hello' AS g" in project.cells["a"].sql


def test_render_context_cannot_shadow_core_globals(tmp_path) -> None:
    @plugin
    class Hijack(Plugin):
        def render_context(self, name, config, context):
            context["ref"] = lambda n: "HACKED"
            return context

    project = compile_text(
        "-- @cell a\nSELECT 1 AS x;\n-- @cell b\nSELECT * FROM {{ ref('a') }};",
        root=tmp_path,
    )
    sql = project.cells["b"].sql
    assert "HACKED" not in sql
    assert "read_parquet" in sql
    assert project.cells["b"].depends_on == ["a"]  # edge recording survived


def test_after_render_transformers_compose_in_priority_order(tmp_path) -> None:
    @plugin
    class Footer(Plugin):
        priority = 10

        def after_render(self, name, config, sql):
            return sql + "\n-- footer"

    @plugin
    class Header(Plugin):
        priority = -10

        def after_render(self, name, config, sql):
            return "-- header\n" + sql

    sql = compile_text("-- @cell a\nSELECT 1;", root=tmp_path).cells["a"].sql
    assert sql == "-- header\nSELECT 1;\n-- footer"


def test_dev_limit_wraps_rendered_sql_and_limits_rows(tmp_path) -> None:
    project = compile_text(
        "-- @cell many\nSELECT * FROM range(10);",
        root=tmp_path,
        overrides={"dev_limit": 4},
    )
    assert "LIMIT 4" in project.cells["many"].sql
    result = project.run()[0]
    assert result.ok, result.error
    assert result.rows == 4


def test_dev_limit_cell_null_disables_it(tmp_path) -> None:
    project = compile_text(
        "-- @dev_limit: 4\n"
        "-- @cell capped\nSELECT * FROM range(10);\n"
        "-- @cell full\n-- @dev_limit: null\nSELECT * FROM range(10);",
        root=tmp_path,
    )
    assert "LIMIT 4" in project.cells["capped"].sql
    assert "LIMIT" not in project.cells["full"].sql


def test_dev_limit_rejects_nonpositive(tmp_path) -> None:
    import pytest

    from qsql_demo.errors import ConfigError

    with pytest.raises(ConfigError, match="dev_limit"):
        compile_text("-- @dev_limit: 0\n-- @cell a\nSELECT 1;", root=tmp_path)


def test_sugar_respects_chain_priority(tmp_path) -> None:
    calls: list[str] = []

    @plugin
    class Inner(Plugin):
        priority = 10

        def before_execute(self, cell, ctx):
            calls.append("inner")

    @plugin
    class Outer(Plugin):
        priority = -10

        def before_execute(self, cell, ctx):
            calls.append("outer")

    project = compile_text("-- @cell a\nSELECT 1 AS x;", root=tmp_path)
    project.run()
    assert calls == ["outer", "inner"]
