"""Tests for the plugin registries and decorators."""

from __future__ import annotations

import pytest

from qsql_demo.models import Directive, Scope
from qsql_demo.registry import DIRECTIVES, DirectiveRegistry, directive


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
