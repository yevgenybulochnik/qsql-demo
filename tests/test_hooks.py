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
