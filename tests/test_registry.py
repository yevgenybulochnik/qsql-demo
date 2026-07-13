"""Tests for the plugin registries and decorators."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from qsql_demo.models import Directive, Merge, Scope
from qsql_demo.plugins.base import Plugin, qfield
from qsql_demo.registry import DIRECTIVES, PLUGINS, DirectiveRegistry, PluginRegistry, directive, plugin


def test_registry_register_and_get() -> None:
    reg = DirectiveRegistry()

    class Foo(Directive):
        key = "foo"

    reg.register(Foo)
    assert reg.get("foo") is Foo
    assert "foo" in reg


def test_registry_by_scope_filters() -> None:
    reg = DirectiveRegistry()

    class G(Directive):
        key = "g"
        scope = Scope.GLOBAL

    class C(Directive):
        key = "c"
        scope = Scope.CELL

    class B(Directive):
        key = "b"
        scope = Scope.BOTH

    for cls in (G, C, B):
        reg.register(cls)

    assert {d.key for d in reg.by_scope(Scope.GLOBAL, Scope.BOTH)} == {"g", "b"}
    assert {d.key for d in reg.by_scope(Scope.CELL, Scope.BOTH)} == {"c", "b"}


def test_register_requires_key() -> None:
    reg = DirectiveRegistry()

    class NoKey(Directive):
        pass

    with pytest.raises(ValueError):
        reg.register(NoKey)


def test_global_directive_decorator(registries) -> None:
    @directive
    class XTest(Directive):
        key = "xtest"
        scope = Scope.CELL

    assert DIRECTIVES.get("xtest") is XTest


def test_builtins_are_registered(registries) -> None:
    for key in ("engine", "input", "sources", "extensions", "output", "autorun", "vars", "depends_on"):
        assert key in DIRECTIVES


# --- Plugin registry ---------------------------------------------------------


def test_plugin_register_and_get() -> None:
    reg = PluginRegistry()

    class Foo(Plugin):
        name = "foo"

    reg.register(Foo)
    assert reg.get("foo") is Foo
    assert "foo" in reg


def test_plugin_register_requires_name() -> None:
    reg = PluginRegistry()

    class NoName(Plugin):
        pass

    with pytest.raises(ValueError):
        reg.register(NoName)


def test_plugin_by_scope_filters() -> None:
    reg = PluginRegistry()

    class G(Plugin):
        name = "g"
        scope = Scope.GLOBAL

    class C(Plugin):
        name = "c"
        scope = Scope.CELL

    class B(Plugin):
        name = "b"
        scope = Scope.BOTH

    for cls in (G, C, B):
        reg.register(cls)

    assert {p.name for p in reg.by_scope(Scope.GLOBAL, Scope.BOTH)} == {"g", "b"}
    assert {p.name for p in reg.by_scope(Scope.CELL, Scope.BOTH)} == {"c", "b"}


def test_plugin_field_map_and_merge_metadata() -> None:
    reg = PluginRegistry()

    class Foo(Plugin):
        name = "foo"

        class Config(BaseModel):
            alpha: dict = qfield({}, merge=Merge.DEEP)
            beta: int = 0

    reg.register(Foo)
    assert reg.field_owner("alpha") is Foo
    assert reg.field_owner("beta") is Foo
    assert reg.field_owner("nope") is None
    assert reg.field_merge("alpha") is Merge.DEEP
    assert reg.field_merge("beta") is Merge.OVERRIDE
    assert reg.field_merge("nope") is Merge.OVERRIDE


def test_plugin_field_collision_raises() -> None:
    reg = PluginRegistry()

    class A(Plugin):
        name = "a"

        class Config(BaseModel):
            alpha: int = 0

    class B(Plugin):
        name = "b"

        class Config(BaseModel):
            alpha: str = ""

    reg.register(A)
    with pytest.raises(ValueError, match="alpha"):
        reg.register(B)


def test_plugin_reregister_same_name_replaces_fields() -> None:
    reg = PluginRegistry()

    class A1(Plugin):
        name = "a"

        class Config(BaseModel):
            alpha: int = 0

    class A2(Plugin):
        name = "a"

        class Config(BaseModel):
            gamma: int = 0

    reg.register(A1)
    reg.register(A2)
    assert reg.field_owner("alpha") is None
    assert reg.field_owner("gamma") is A2


def test_plugin_snapshot_restore() -> None:
    reg = PluginRegistry()

    class A(Plugin):
        name = "a"

        class Config(BaseModel):
            alpha: int = 0

    snap = reg.snapshot()
    reg.register(A)
    reg.restore(snap)
    assert reg.get("a") is None
    assert reg.field_owner("alpha") is None


def test_global_plugin_decorator(registries) -> None:
    @plugin
    class XPlugin(Plugin):
        name = "xplugin"

    assert PLUGINS.get("xplugin") is XPlugin
